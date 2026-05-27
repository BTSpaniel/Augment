"""Shell command tool — sandboxed subprocess execution (FAIL port)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict

from augment.tools.registry import ToolRegistry

_MAX_OUTPUT_CHARS = 30_000
_DEFAULT_TIMEOUT = 60


def _resolve_cwd(cwd: str, context: Dict[str, Any] | None) -> str:
    root_value = ""
    if isinstance(context, dict):
        root_value = str(context.get("workspace_root") or "")
    root = Path(root_value).expanduser().resolve() if root_value else None
    path = Path(str(cwd or ".")).expanduser()
    if root and not path.is_absolute():
        path = root / path
    return str(path.resolve())


_SEARCH_REDIRECT_CMDS = ("rg ", "grep ", "grep -", "find ", "fd ")


def run_command(command: str, cwd: str = ".", timeout: int = _DEFAULT_TIMEOUT, _context: Dict[str, Any] | None = None) -> str:
    if not str(command or "").strip():
        return "Error: empty command"
    cmd_stripped = str(command or "").strip()
    if any(cmd_stripped.startswith(prefix) for prefix in _SEARCH_REDIRECT_CMDS):
        return (
            "Error: rg/grep/find is not available as a shell command here. "
            "Use the 'search_code' tool for text/regex search (it has a built-in Python fallback) "
            "or 'search_files' to find files by name. Do not retry with run_command."
        )
    try:
        timeout = min(max(1, int(timeout or _DEFAULT_TIMEOUT)), 300)
    except Exception:
        timeout = _DEFAULT_TIMEOUT
    resolved_cwd = _resolve_cwd(cwd, _context)
    if not Path(resolved_cwd).exists():
        return f"Error: cwd not found: {cwd}"
    if not Path(resolved_cwd).is_dir():
        return f"Error: cwd is not a directory: {cwd}"
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=resolved_cwd,
            env=dict(os.environ),
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except Exception as exc:
        return f"Error running command: {exc}"
    parts: list[str] = []
    if (result.stdout or "").strip():
        parts.append(result.stdout.strip())
    if (result.stderr or "").strip():
        parts.append(f"[stderr]\n{result.stderr.strip()}")
    body = "\n".join(parts) or f"(exit code {result.returncode}, no output)"
    output = f"exit code: {result.returncode}\n{body}"
    if len(output) > _MAX_OUTPUT_CHARS:
        output = output[:_MAX_OUTPUT_CHARS] + "\n... [truncated]"
    return output


def register_command_tools(registry: ToolRegistry) -> None:
    registry.register_fn(
        "run_command",
        "Run a shell command (cmd/bash) inside the workspace and return exit code, stdout, and stderr.",
        {"type": "object", "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "cwd": {"type": "string", "description": "Working directory relative to the workspace root"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (max 300)"},
        }, "required": ["command"]},
        run_command, tags=["commands"], timeout_seconds=305,
    )
