from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Any

import uvicorn

from augment.config import load_config
from augment.service import AugmentApp

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"

# Controlled by --color flag; set once in main() before any output.
_color_enabled: bool = True


def _c(text: str, *codes: str) -> str:
    if not _color_enabled:
        return text
    return "".join(codes) + text + _RESET


def _jsonl(obj: dict[str, Any]) -> None:
    """Emit one JSON object to stdout followed by a newline (JSONL)."""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _err(msg: str, *, json_mode: bool = False) -> None:
    """Write a progress/warning message. JSON mode → stderr only."""
    if json_mode:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()
    else:
        print(msg)


def _add_provider_model_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("-p", "--provider", default="", metavar="PROFILE",
                   help="Profile ID to use (see: augment providers)")
    p.add_argument("-m", "--model", default="", metavar="MODEL",
                   help="Override model for this session only")
    p.add_argument("-s", "--session", default="", dest="session_id", metavar="SESSION_ID",
                   help="Resume an existing session by ID")
    p.add_argument("-j", "--json", action="store_true", dest="json_mode",
                   help="JSONL output: emit one JSON event per line (stdout=API, stderr=progress)")
    p.add_argument("--no-stream", action="store_true", dest="no_stream",
                   help="Suppress live step indicators; wait for full reply")
    p.add_argument("--no-tools", action="store_true", dest="no_tools",
                   help="Disable all tool calls for this session")


def main() -> None:
    global _color_enabled

    parser = argparse.ArgumentParser(
        prog="augment",
        description="Augment — AI agent with tools, memory, and context.",
    )
    parser.add_argument(
        "--color", choices=["auto", "always", "never"], default="auto",
        help="Control ANSI color output (default: auto)",
    )
    parser.add_argument(
        "-w", "--workspace", default="", metavar="PATH",
        help="Override workspace root for this invocation",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    chat_p = sub.add_parser("chat", help="Send a single message and print the reply")
    chat_p.add_argument("message", nargs="?", default="")
    _add_provider_model_args(chat_p)

    console_p = sub.add_parser("console", help="Interactive multi-turn REPL session")
    _add_provider_model_args(console_p)

    providers_p = sub.add_parser("providers", help="List all configured provider profiles")
    providers_p.add_argument("-j", "--json", action="store_true", dest="json_mode",
                             help="Output as JSON array")

    tools_p = sub.add_parser("tools", help="List available tools")
    tools_p.add_argument("--filter", default="", dest="filter", metavar="TEXT",
                         help="Filter tools by name substring")
    tools_p.add_argument("-j", "--json", action="store_true", dest="json_mode",
                         help="Output as JSON array")

    serve_p = sub.add_parser("serve", help="Start the HTTP server")
    serve_p.add_argument("--host", default=None)
    serve_p.add_argument("--port", type=int, default=None)
    serve_p.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")

    args = parser.parse_args()

    # Resolve --color flag before any _c() calls.
    if args.color == "always":
        _color_enabled = True
    elif args.color == "never":
        _color_enabled = False
    else:
        _color_enabled = sys.stdout.isatty()

    # Workspace override: inject via env so load_config() picks it up.
    if getattr(args, "workspace", ""):
        import os
        os.environ["AUGMENT_WORKSPACE_ROOT"] = args.workspace

    if args.command == "chat":
        msg = args.message or sys.stdin.read().strip()
        if not msg:
            parser.error("Provide a message argument or pipe text via stdin.")
        rc = asyncio.run(_chat(
            msg,
            provider=args.provider, model=args.model, session_id=args.session_id,
            json_mode=args.json_mode, no_stream=args.no_stream, no_tools=args.no_tools,
        ))
        sys.exit(rc)
    elif args.command == "console":
        asyncio.run(_console(
            provider=args.provider, model=args.model, session_id=args.session_id,
            json_mode=args.json_mode, no_stream=args.no_stream, no_tools=args.no_tools,
        ))
    elif args.command == "providers":
        asyncio.run(_providers(json_mode=args.json_mode))
    elif args.command == "tools":
        asyncio.run(_tools(args.filter, json_mode=args.json_mode))
    elif args.command == "serve":
        config = load_config()
        uvicorn.run(
            "augment.main:app",
            host=args.host or config.server.host,
            port=args.port or config.server.port,
            reload=args.reload,
        )


# ── Provider/model injection ──────────────────────────────────────────

def _apply_provider_override(app: AugmentApp, provider: str, model: str) -> str:
    """Switch to requested profile/model and return resolved model string."""
    from augment.providers.registry import ProviderRegistry, build_provider
    from dataclasses import replace

    if provider:
        state = app.settings._read_state()
        if provider not in state.get("profiles", {}):
            sys.stderr.write(f"Unknown profile '{provider}'. Available:\n")
            for pid in state.get("profiles", {}):
                marker = " (default)" if pid == state.get("default_id") else ""
                sys.stderr.write(f"  {pid}{marker}\n")
            sys.exit(2)
        cfg = app.settings.provider_config(provider)
    else:
        cfg = app.settings.provider_config()

    if model:
        cfg = replace(cfg, model=model)

    app.providers = ProviderRegistry.__new__(ProviderRegistry)
    app.providers._provider = build_provider(cfg)
    return str(cfg.model or model or "")


# ── Step callbacks ────────────────────────────────────────────────────

def _make_step_cb(*, quiet: bool = False, json_mode: bool = False) -> Any:
    """Return an async step callback.

    quiet=True  → silence all output (--no-stream, non-interactive JSON mode).
    json_mode   → emit JSONL events to stdout; progress/warnings to stderr.
    """
    async def _cb(event: dict[str, Any]) -> None:
        if quiet:
            return
        kind = str(event.get("kind") or "")
        if json_mode:
            _jsonl({"ts": time.time(), **event})
            return
        if kind == "action":
            tool = str(event.get("tool") or "tool")
            print(_c(f"  ◆ {tool}", _CYAN), end=" ", flush=True)
        elif kind == "observation":
            ok = bool(event.get("success", True))
            print(_c("✓", _GREEN) if ok else _c("✗", _RED), flush=True)
        elif kind == "thought":
            ms = float(event.get("duration_ms") or 0)
            if ms >= 1000:
                print(_c(f"  … thinking ({ms / 1000:.1f}s)", _DIM), flush=True)
        elif kind == "error":
            print(_c(f"  ✗ {event.get('content', '')}", _RED), flush=True)
    return _cb


# ── chat (single-shot) ────────────────────────────────────────────────

async def _chat(
    message: str, *,
    provider: str, model: str, session_id: str,
    json_mode: bool, no_stream: bool, no_tools: bool,
) -> int:
    """Returns exit code: 0=ok, 1=error."""
    app = AugmentApp(load_config())
    try:
        resolved_model = _apply_provider_override(app, provider, model)
        step_cb = _make_step_cb(quiet=no_stream or (json_mode and False), json_mode=json_mode)
        try:
            result = await app.chat(
                message, session_id=session_id, step_callback=step_cb,
                allowed_tools=None if not no_tools else [],
            )
        except Exception as exc:
            if json_mode:
                _jsonl({"kind": "error", "error": str(exc), "ts": time.time()})
            else:
                print(_c(f"\nError: {exc}", _RED), file=sys.stderr)
            return 1

        if json_mode:
            _jsonl({
                "kind": "done",
                "reply": result.reply,
                "session_id": result.session_id,
                "model": resolved_model or result.model,
                "tool_calls": result.tool_calls,
                "iterations": result.iterations,
                "status": result.stopped_reason,
                "ts": time.time(),
            })
        else:
            print(result.reply)
            print(_c(
                f"\n[session={result.session_id}  model={resolved_model or result.model}"
                f"  tools={result.tool_calls}  iters={result.iterations}  status={result.stopped_reason}]",
                _DIM,
            ))
        return 0
    finally:
        await app.close()


# ── console (interactive REPL) ────────────────────────────────────────

_CONSOLE_HELP = """\
Meta-commands (prefix with /):
  /help            Show this help
  /session         Print the current session ID
  /providers       List configured provider profiles
  /tools [filter]  List available tools
  /model MODEL     Switch model for the rest of this session
  /clear           Clear the screen
  /exit  /quit     Exit the console
"""


async def _console(
    *, provider: str, model: str, session_id: str,
    json_mode: bool, no_stream: bool, no_tools: bool,
) -> None:
    try:
        import readline  # noqa: F401  — enables arrow-key history on Unix
    except ImportError:
        pass

    app = AugmentApp(load_config())
    try:
        resolved_model = _apply_provider_override(app, provider, model)
        sid = session_id or app.sessions.new_session_id()

        if json_mode:
            _jsonl({"kind": "session_start", "session_id": sid, "model": resolved_model, "ts": time.time()})
        else:
            print(_c("Augment console", _BOLD) + _c(f"  •  {resolved_model or 'unknown model'}  •  session: {sid}", _DIM))
            print(_c("Type /help for meta-commands, Ctrl-D or /exit to quit.\n", _DIM))

        step_cb = _make_step_cb(quiet=no_stream, json_mode=json_mode)
        allowed: list[str] | None = [] if no_tools else None

        while True:
            try:
                if json_mode:
                    raw = sys.stdin.readline()
                    if not raw:
                        break
                    try:
                        payload = json.loads(raw.strip())
                        line = str(payload.get("message") or "").strip()
                    except json.JSONDecodeError:
                        line = raw.strip()
                else:
                    line = input(_c("you> ", _BOLD + _CYAN)).strip()
            except (EOFError, KeyboardInterrupt):
                if not json_mode:
                    print()
                break

            if not line:
                continue

            if not json_mode and line.startswith("/"):
                cmd, _, rest = line[1:].partition(" ")
                cmd = cmd.lower()
                if cmd in ("exit", "quit"):
                    break
                elif cmd == "help":
                    print(_CONSOLE_HELP)
                elif cmd == "session":
                    print(_c(f"  session: {sid}", _DIM))
                elif cmd == "providers":
                    await _providers()
                elif cmd == "tools":
                    await _tools(rest.strip())
                elif cmd == "model":
                    if rest.strip():
                        from dataclasses import replace
                        from augment.providers.registry import ProviderRegistry, build_provider
                        cfg = app.settings.provider_config(provider or None)
                        cfg = replace(cfg, model=rest.strip())
                        app.providers = ProviderRegistry.__new__(ProviderRegistry)
                        app.providers._provider = build_provider(cfg)
                        resolved_model = rest.strip()
                        print(_c(f"  Switched to model: {resolved_model}", _GREEN))
                    else:
                        print(_c(f"  Current model: {resolved_model}", _DIM))
                elif cmd == "clear":
                    print("\033[2J\033[H", end="")
                else:
                    print(_c(f"  Unknown command /{cmd}. Type /help.", _YELLOW))
                continue

            try:
                result = await app.chat(line, session_id=sid, step_callback=step_cb, allowed_tools=allowed)
            except Exception as exc:
                if json_mode:
                    _jsonl({"kind": "error", "error": str(exc), "ts": time.time()})
                else:
                    print(_c(f"\n  Error: {exc}\n", _RED))
                continue

            if json_mode:
                _jsonl({
                    "kind": "done",
                    "reply": result.reply,
                    "session_id": result.session_id,
                    "model": resolved_model or result.model,
                    "tool_calls": result.tool_calls,
                    "iterations": result.iterations,
                    "status": result.stopped_reason,
                    "ts": time.time(),
                })
            else:
                print()
                print(_c("augment> ", _BOLD + _BLUE) + result.reply)
                print(_c(
                    f"\n  [tools={result.tool_calls}  iters={result.iterations}  status={result.stopped_reason}]",
                    _DIM,
                ))
                print()
    finally:
        await app.close()


# ── providers ─────────────────────────────────────────────────────────

async def _providers(*, json_mode: bool = False) -> None:
    app = AugmentApp(load_config())
    try:
        state = app.settings._read_state()
        default_id = state.get("default_id") or ""
        profiles = state.get("profiles") or {}
        if not profiles:
            _err(_c("  No provider profiles configured. Use the web UI to add one.", _YELLOW), json_mode=json_mode)
            return
        if json_mode:
            out = []
            for pid, prof in profiles.items():
                out.append({
                    "id": pid,
                    "name": str(prof.get("name") or pid),
                    "model": str(prof.get("model") or ""),
                    "endpoint": str(prof.get("endpoint") or ""),
                    "default": pid == default_id,
                })
            _jsonl({"providers": out})
            return
        col_w = max(len(pid) for pid in profiles) + 2
        header = f"  {'PROFILE':<{col_w}}  {'NAME':<22}  {'MODEL':<30}  ENDPOINT"
        print(_c(header, _BOLD))
        print(_c("  " + "─" * (len(header) - 2), _DIM))
        for pid, prof in profiles.items():
            marker = _c(" ◀ default", _GREEN) if pid == default_id else ""
            name = str(prof.get("name") or pid)[:22]
            model = str(prof.get("model") or "")[:30]
            endpoint = str(prof.get("endpoint") or "")
            print(f"  {_c(pid, _CYAN):<{col_w + 9}}  {name:<22}  {model:<30}  {_c(endpoint, _DIM)}{marker}")
    finally:
        await app.close()


# ── tools ─────────────────────────────────────────────────────────────

async def _tools(filter_text: str = "", *, json_mode: bool = False) -> None:
    app = AugmentApp(load_config())
    try:
        names = sorted(app.tools.all_names())
        if filter_text:
            names = [n for n in names if filter_text.lower() in n.lower()]
        if not names:
            _err(_c(f"  No tools matching '{filter_text}'.", _YELLOW), json_mode=json_mode)
            return
        if json_mode:
            out = []
            for name in names:
                tool = app.tools.get(name)
                out.append({
                    "name": name,
                    "description": str(getattr(tool, "description", "") or "") if tool else "",
                    "read_only": bool(getattr(tool, "read_only", True)) if tool else True,
                    "tags": list(getattr(tool, "tags", None) or []) if tool else [],
                })
            _jsonl({"tools": out})
            return
        for name in names:
            tool = app.tools.get(name)
            desc = ""
            if tool:
                desc = _c("  " + (str(getattr(tool, "description", "") or "")[:72]), _DIM)
            print(f"  {_c(name, _CYAN)}{desc}")
    finally:
        await app.close()


if __name__ == "__main__":
    main()
