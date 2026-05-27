"""Codex tools — thin shell over the already-installed Codex bridge."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict

from augment.codex.bridge import codex_status as _codex_status_payload, _resolve_codex_bin, _probe_codex_cli
from augment.tools.registry import ToolRegistry


_MAX_OUTPUT_CHARS = 30_000
_MAX_PROMPT_CHARS = 24_000
_MAX_CONTEXT_CHARS = 24_000
_DEFAULT_TIMEOUT = 300


def _resolve_cwd(cwd: str, context: Dict[str, Any] | None) -> str:
    root_value = ""
    if isinstance(context, dict):
        root_value = str(context.get("workspace_root") or "")
    root = Path(root_value).expanduser().resolve() if root_value else None
    path = Path(str(cwd or ".")).expanduser()
    if root and not path.is_absolute():
        path = root / path
    return str(path.resolve())


def codex_status(codex_bin: str = "", _context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return _codex_status_payload(codex_bin=codex_bin)


def codex_run(
    prompt: str,
    stdin_context: str = "",
    cwd: str = ".",
    timeout: int = _DEFAULT_TIMEOUT,
    codex_bin: str = "",
    sandbox: str = "read-only",
    _context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    prompt = str(prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "empty prompt"}
    if len(prompt) > _MAX_PROMPT_CHARS:
        return {"ok": False, "error": f"prompt is too long (max {_MAX_PROMPT_CHARS} chars)"}
    if len(str(stdin_context or "")) > _MAX_CONTEXT_CHARS:
        return {"ok": False, "error": f"stdin_context is too long (max {_MAX_CONTEXT_CHARS} chars)"}
    sandbox_value = str(sandbox or "read-only").strip().lower()
    if sandbox_value not in {"read-only", "workspace-write"}:
        sandbox_value = "read-only"
    resolved = _resolve_codex_bin(codex_bin)
    if not resolved:
        return {"ok": False, "error": "Codex CLI runtime not found. Set CODEX_BIN or sign in via Settings → ChatGPT / Codex."}
    probe = _probe_codex_cli(resolved)
    if not probe.get("supports_exec"):
        return {
            "ok": False,
            "error": probe.get("error") or "Codex executable found but `codex exec` is not supported by this binary.",
            "codex_bin": resolved,
        }
    try:
        timeout_value = min(max(5, int(timeout or _DEFAULT_TIMEOUT)), 900)
    except Exception:
        timeout_value = _DEFAULT_TIMEOUT
    workdir = _resolve_cwd(cwd, _context)
    if not Path(workdir).exists() or not Path(workdir).is_dir():
        return {"ok": False, "error": f"cwd not found or not a directory: {cwd}"}
    cmd = [resolved, "exec", "--sandbox", sandbox_value, "--ephemeral", prompt]
    try:
        result = subprocess.run(
            cmd,
            cwd=workdir,
            input=str(stdin_context or "") or None,
            capture_output=True,
            text=True,
            timeout=timeout_value,
            env=dict(os.environ),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"codex exec timed out after {timeout_value}s", "codex_bin": resolved}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "codex_bin": resolved}
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    truncated = False
    if len(stdout) > _MAX_OUTPUT_CHARS:
        stdout = stdout[:_MAX_OUTPUT_CHARS] + "\n... [truncated]"
        truncated = True
    if len(stderr) > _MAX_OUTPUT_CHARS:
        stderr = stderr[:_MAX_OUTPUT_CHARS] + "\n... [truncated]"
        truncated = True
    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "output": stdout,
        "stderr": stderr,
        "truncated": truncated,
        "codex_bin": resolved,
        "sandbox": sandbox_value,
        "cwd": workdir,
    }


def register_codex_tools(registry: ToolRegistry) -> None:
    registry.register_fn(
        "codex_status",
        "Check whether a local Codex CLI/app server is available for the optional Codex bridge.",
        {"type": "object", "properties": {
            "codex_bin": {"type": "string", "description": "Optional path to the codex executable. Defaults to CODEX_BIN or PATH."},
        }},
        codex_status, read_only=True, tags=["codex"],
    )
    registry.register_fn(
        "codex_run",
        "Run a bounded non-interactive Codex task via local `codex exec`. Default sandbox is read-only; use for reviews, summaries, and second opinions.",
        {"type": "object", "properties": {
            "prompt": {"type": "string", "description": "Task prompt for Codex."},
            "stdin_context": {"type": "string", "description": "Optional extra context passed on stdin."},
            "cwd": {"type": "string", "description": "Working directory relative to the workspace root."},
            "timeout": {"type": "integer", "description": "Timeout in seconds, clamped to 5..900."},
            "codex_bin": {"type": "string", "description": "Optional path to the codex executable."},
            "sandbox": {"type": "string", "description": "Codex sandbox mode: read-only or workspace-write."},
        }, "required": ["prompt"]},
        codex_run, read_only=True, tags=["codex", "commands"], timeout_seconds=920,
    )
