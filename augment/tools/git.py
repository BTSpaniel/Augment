"""Git tools — status, diff, log (FAIL port)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict

from augment.tools.registry import ToolRegistry

_MAX_OUTPUT = 20_000


def _resolve_cwd(cwd: str, context: Dict[str, Any] | None) -> str:
    root_value = ""
    if isinstance(context, dict):
        root_value = str(context.get("workspace_root") or "")
    root = Path(root_value).expanduser().resolve() if root_value else None
    path = Path(str(cwd or ".")).expanduser()
    if root and not path.is_absolute():
        path = root / path
    return str(path.resolve())


def _git(args: list[str], cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=cwd or ".",
        )
    except FileNotFoundError:
        return "Error: git is not installed or not in PATH"
    except subprocess.TimeoutExpired:
        return "Error: git command timed out"
    except Exception as exc:
        return f"Error: {exc}"
    output = (result.stdout or "").strip()
    if result.returncode != 0 and result.stderr:
        output = f"{output}\n[stderr] {result.stderr.strip()}".strip()
    if not output:
        output = f"(exit code {result.returncode}, no output)"
    if len(output) > _MAX_OUTPUT:
        output = output[:_MAX_OUTPUT] + "\n... [truncated]"
    return output


def git_status(cwd: str = ".", _context: Dict[str, Any] | None = None) -> str:
    return _git(["status", "--short", "--branch"], _resolve_cwd(cwd, _context))


def git_diff(path: str = "", cwd: str = ".", staged: bool = False, _context: Dict[str, Any] | None = None) -> str:
    args = ["diff"]
    if staged:
        args.append("--staged")
    if path:
        args.extend(["--", str(path)])
    return _git(args, _resolve_cwd(cwd, _context))


def git_log(n: int = 10, cwd: str = ".", _context: Dict[str, Any] | None = None) -> str:
    try:
        count = min(max(1, int(n or 10)), 50)
    except Exception:
        count = 10
    return _git(["log", f"-{count}", "--oneline", "--no-decorate"], _resolve_cwd(cwd, _context))


def register_git_tools(registry: ToolRegistry) -> None:
    registry.register_fn(
        "git_status",
        "Show git status (short format with branch) for the workspace.",
        {"type": "object", "properties": {
            "cwd": {"type": "string", "description": "Repository directory relative to workspace root"},
        }},
        git_status, read_only=True, tags=["git"],
    )
    registry.register_fn(
        "git_diff",
        "Show git diff. Optionally restrict to a file, optionally show staged changes.",
        {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path to diff (optional)"},
            "cwd": {"type": "string", "description": "Repository directory relative to workspace root"},
            "staged": {"type": "boolean", "description": "Show staged changes"},
        }},
        git_diff, read_only=True, tags=["git"],
    )
    registry.register_fn(
        "git_log",
        "Show recent git commits in oneline format.",
        {"type": "object", "properties": {
            "n": {"type": "integer", "description": "Number of commits (default 10, max 50)"},
            "cwd": {"type": "string", "description": "Repository directory relative to workspace root"},
        }},
        git_log, read_only=True, tags=["git"],
    )
