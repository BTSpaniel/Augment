"""Cross-platform command compatibility shims (alias-style interception).

Ported and extended from FAIL's ``server/tools/compat.py``. A weak model
freely emits POSIX shell commands (``mkdir -p``, ``touch``, ``rm -rf``,
``ls``, ``cat``) that silently fail on Windows ``cmd``/``pwsh``. Rather than
let those errors trigger retry loops, :func:`try_compat_command` recognizes
the common verbs and routes them to deterministic, cross-platform Python
handlers — the model writes a normal command string and gets a clean result
that works on every OS.

Design:
  * Pure interception layer — ``run_command`` calls :func:`try_compat_command`
    first; a non-``None`` return means "handled, do not touch the shell".
    ``None`` means "not a compat command, fall through to the real shell".
  * Commands containing shell composition (``|`` ``;`` ``&&`` ``||``) fall
    through untouched — except the ``echo ... > file`` redirect form.
  * Destructive ``rm`` is guarded by :class:`PathGuard` (no secrets) and
    refuses drive/system roots.
  * ``node --check`` / ``python -m py_compile`` reuse the host probe to decide
    between a real run and an internal syntax shim.

Sections (in order):
  1. Tokenizer + path helpers.
  2. Per-verb handlers (mkdir / touch / rm / ls / cat / echo>).
  3. Verification shims (node --check / py_compile).
  4. try_compat_command dispatcher.
"""
from __future__ import annotations

import py_compile
import shlex
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from augment.context.environment import detect_environment
from augment.security.path_guard import PathGuard
from augment.tools.registry import ToolRegistry

_MAX_CAT_CHARS = 20_000
_COMPOSITION_TOKENS = {"|", ";", "&&", "||", "&", "`"}
_GUARD = PathGuard()


# ── 1. Tokenizer + path helpers ─────────────────────────────────────


def _tokenize(command: str) -> List[str]:
    """Split a command line while preserving Windows backslash paths.

    ``posix=False`` keeps backslashes intact (so ``C:\\cake`` survives) and
    respects quoting; surrounding quotes are then stripped per token.
    """
    try:
        raw = shlex.split(command, posix=False)
    except ValueError:
        raw = command.split()
    out: List[str] = []
    for tok in raw:
        if len(tok) >= 2 and tok[0] in "'\"" and tok[-1] == tok[0]:
            tok = tok[1:-1]
        out.append(tok)
    return out


def _resolve_cwd(cwd: str, context: Dict[str, Any] | None) -> Path:
    root_value = str((context or {}).get("workspace_root") or "") if isinstance(context, dict) else ""
    root = Path(root_value).expanduser().resolve() if root_value else Path.cwd()
    path = Path(str(cwd or ".")).expanduser()
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def _resolve(path_value: str, cwd_path: Path) -> Path:
    p = Path(str(path_value)).expanduser()
    return (cwd_path / p).resolve() if not p.is_absolute() else p.resolve()


def _args_without_flags(tokens: List[str]) -> List[str]:
    """Positional args only (drop tokens starting with '-' or '/')."""
    return [t for t in tokens if not (t.startswith("-") or (len(t) == 2 and t.startswith("/")))]


def _has_flag(tokens: List[str], *names: str) -> bool:
    flat = "".join(t[1:] for t in tokens if t.startswith("-"))
    return any(n in flat for n in names) or any(t in {f"--{n}" for n in names} for t in tokens)


def _result(ok: bool, summary: str) -> str:
    return f"exit code: {0 if ok else 1}\n[compat] {summary}"


# ── 2. Per-verb handlers ────────────────────────────────────────────


def _do_mkdir(tokens: List[str], cwd: Path) -> str:
    dirs = _args_without_flags(tokens[1:])
    if not dirs:
        return _result(False, "mkdir: missing directory operand")
    made: List[str] = []
    for d in dirs:
        target = _resolve(d, cwd)
        target.mkdir(parents=True, exist_ok=True)
        made.append(str(target))
    return _result(True, "created directory(ies): " + ", ".join(made))


def _do_touch(tokens: List[str], cwd: Path) -> str:
    files = _args_without_flags(tokens[1:])
    if not files:
        return _result(False, "touch: missing file operand")
    touched: List[str] = []
    for f in files:
        target = _resolve(f, cwd)
        if not _GUARD.is_safe(str(target)):
            return _result(False, f"touch: refused sensitive path: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch(exist_ok=True)
        touched.append(str(target))
    return _result(True, "touched: " + ", ".join(touched))


def _do_rm(tokens: List[str], cwd: Path) -> str:
    recursive = _has_flag(tokens, "r", "R", "recursive")
    paths = _args_without_flags(tokens[1:])
    if not paths:
        return _result(False, "rm: missing operand")
    removed: List[str] = []
    for p in paths:
        target = _resolve(p, cwd)
        # Refuse drive/system roots and anything PathGuard flags sensitive.
        if target == Path(target.anchor) or len(target.parts) <= 2:
            return _result(False, f"rm: refused dangerous path: {target}")
        if not _GUARD.is_safe(str(target)):
            return _result(False, f"rm: refused sensitive path: {target}")
        if not target.exists():
            continue
        if target.is_dir():
            if not recursive:
                return _result(False, f"rm: {target} is a directory (use -r)")
            shutil.rmtree(target)
        else:
            target.unlink()
        removed.append(str(target))
    return _result(True, "removed: " + (", ".join(removed) or "(nothing existed)"))


def _do_ls(tokens: List[str], cwd: Path) -> str:
    args = _args_without_flags(tokens[1:])
    target = _resolve(args[0], cwd) if args else cwd
    if not target.exists():
        return _result(False, f"ls: path not found: {target}")
    if target.is_file():
        return _result(True, f"{target.name}")
    entries = sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    listing = "\n".join(f"{'d' if e.is_dir() else '-'} {e.name}" for e in entries)
    return _result(True, f"{target}:\n{listing}" if listing else f"{target}: (empty)")


def _do_cat(tokens: List[str], cwd: Path) -> str:
    args = _args_without_flags(tokens[1:])
    if not args:
        return _result(False, "cat: missing file operand")
    target = _resolve(args[0], cwd)
    if not _GUARD.is_safe(str(target)):
        return _result(False, f"cat: refused sensitive path: {target}")
    if not target.is_file():
        return _result(False, f"cat: file not found: {target}")
    text = target.read_text(encoding="utf-8", errors="replace")
    truncated = len(text) > _MAX_CAT_CHARS
    body = text[:_MAX_CAT_CHARS] + ("\n... [truncated]" if truncated else "")
    return f"exit code: 0\n{body}"


def _do_echo_redirect(tokens: List[str], cwd: Path) -> Optional[str]:
    """Handle ``echo <text> > file`` / ``>> file``; else return None."""
    redirect = next((i for i, t in enumerate(tokens) if t in (">", ">>")), -1)
    if redirect == -1 or redirect == len(tokens) - 1:
        return None
    append = tokens[redirect] == ">>"
    text = " ".join(tokens[1:redirect])
    target = _resolve(tokens[redirect + 1], cwd)
    if not _GUARD.is_safe(str(target)):
        return _result(False, f"echo: refused sensitive path: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with target.open(mode, encoding="utf-8") as fh:
        fh.write(text + "\n")
    return _result(True, f"wrote {len(text) + 1} bytes to {target}")


# ── 3. Verification shims ───────────────────────────────────────────


def _do_py_compile(tokens: List[str], cwd: Path) -> str:
    args = [t for t in tokens if t not in ("python", "python3", "-m", "py_compile")]
    if not args:
        return _result(False, "py_compile: missing file operand")
    target = _resolve(args[0], cwd)
    if not target.is_file():
        return _result(False, f"py_compile: file not found: {target}")
    try:
        py_compile.compile(str(target), doraise=True)
    except py_compile.PyCompileError as exc:
        return _result(False, f"py_compile failed: {exc}")
    return _result(True, f"py_compile passed: {target.name}")


# ── 4. Dispatcher ───────────────────────────────────────────────────


def try_compat_command(
    command: str,
    cwd: str = ".",
    context: Dict[str, Any] | None = None,
) -> Optional[str]:
    """Intercept a known cross-platform command, or return ``None``.

    A non-``None`` return is the final tool output (the caller must NOT also
    run the shell). ``None`` means the command is not a recognized compat
    verb and should fall through to the real shell.
    """
    text = str(command or "").strip()
    if not text:
        return None
    tokens = _tokenize(text)
    if not tokens:
        return None

    verb = tokens[0].lower()
    is_echo = verb == "echo"
    # Shell composition changes semantics — let the real shell handle it,
    # except the simple ``echo ... > file`` redirect we explicitly support.
    if not is_echo and any(t in _COMPOSITION_TOKENS for t in tokens):
        return None

    cwd_path = _resolve_cwd(cwd, context)
    try:
        if verb == "mkdir":
            return _do_mkdir(tokens, cwd_path)
        if verb == "touch":
            return _do_touch(tokens, cwd_path)
        if verb in ("rm", "del", "erase"):
            return _do_rm(tokens, cwd_path)
        if verb in ("ls", "dir"):
            return _do_ls(tokens, cwd_path)
        if verb in ("cat", "type"):
            return _do_cat(tokens, cwd_path)
        if is_echo:
            return _do_echo_redirect(tokens, cwd_path)
        if verb in ("python", "python3") and "py_compile" in tokens:
            return _do_py_compile(tokens, cwd_path)
        if verb in ("node", "node.exe") and "--check" in tokens:
            # Only shim when real Node is absent; otherwise let it run for real.
            if "node" in (detect_environment().get("available_tools") or []):
                return None
            return _result(
                False,
                "node --check: Node.js is not installed on this host. Skip the "
                "syntax check or install Node; do not retry this command.",
            )
    except Exception as exc:  # pragma: no cover - defensive
        return _result(False, f"{verb}: compat handler error: {exc}")
    return None


def register_compat_tools(registry: ToolRegistry) -> None:
    """Register a standalone ``compat_shell`` tool (interception is also wired
    into ``run_command``; this exposes it directly for explicit calls)."""
    def _compat_shell(command: str, cwd: str = ".", _context: Dict[str, Any] | None = None) -> str:
        handled = try_compat_command(command, cwd, _context)
        if handled is None:
            return (
                "exit code: 1\n[compat] Unsupported compat command. Handled verbs: "
                "mkdir, touch, rm, ls, cat, echo>redirect, python -m py_compile, node --check."
            )
        return handled

    registry.register_fn(
        "compat_shell",
        "Cross-platform shim for common shell verbs (mkdir/touch/rm/ls/cat/echo redirect, "
        "python -m py_compile, node --check). Runs them via internal handlers that work on "
        "any OS. run_command already routes through this automatically.",
        {"type": "object", "properties": {
            "command": {"type": "string", "description": "The shell-style command to run."},
            "cwd": {"type": "string", "description": "Optional working directory."},
        }, "required": ["command"]},
        _compat_shell, tags=["commands", "compat"], read_only=False,
    )
