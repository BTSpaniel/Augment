"""Sandbox tools — run code in an isolated subprocess (FAIL port)."""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

from augment.tools.registry import ToolRegistry

_MAX_OUTPUT = 20_000
_MAX_CODE_CHARS = 100_000
_DEFAULT_TIMEOUT = 30
_ALLOWED_LANGUAGES = {"python", "javascript", "bash", "shell"}


async def run_code(code: str, language: str = "python", timeout: int = _DEFAULT_TIMEOUT, _context: Dict[str, Any] | None = None) -> str:
    code = str(code or "")
    if not code.strip():
        return "Error: empty code"
    if len(code) > _MAX_CODE_CHARS:
        return f"Error: code is too long (max {_MAX_CODE_CHARS} chars)"
    language = str(language or "python").lower().strip()
    if language not in _ALLOWED_LANGUAGES:
        return f"Error: unsupported language '{language}'. Supported: {', '.join(sorted(_ALLOWED_LANGUAGES))}"
    try:
        timeout = min(max(5, int(timeout or _DEFAULT_TIMEOUT)), 60)
    except Exception:
        timeout = _DEFAULT_TIMEOUT
    suffix = {"python": ".py", "javascript": ".js", "bash": ".sh", "shell": ".sh"}.get(language, ".txt")
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8") as handle:
            handle.write(code)
            temp_path = handle.name
        if language == "python":
            cmd = [sys.executable, temp_path]
        elif language == "javascript":
            cmd = ["node", temp_path]
        else:
            cmd = (["cmd", "/c", temp_path] if sys.platform == "win32" else ["bash", temp_path])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tempfile.gettempdir(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return f"Error: execution timed out after {timeout}s"
        parts: list[str] = []
        if stdout:
            parts.append(stdout.decode("utf-8", errors="replace"))
        if stderr:
            parts.append(f"[stderr]\n{stderr.decode('utf-8', errors='replace')}")
        body = "\n".join(parts).strip() or f"(exit code {proc.returncode}, no output)"
        output = f"exit code: {proc.returncode}\n{body}"
        if len(output) > _MAX_OUTPUT:
            output = output[:_MAX_OUTPUT] + "\n... [truncated]"
        return output
    except Exception as exc:
        return f"Error running code: {exc}"
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass


async def eval_python(expression: str, _context: Dict[str, Any] | None = None) -> str:
    expression = str(expression or "").strip()
    if not expression:
        return "Error: empty expression"
    if len(expression) > 10_000:
        return "Error: expression is too long"
    code = f"print(repr({expression}))"
    return await run_code(code, language="python", timeout=10)


def register_sandbox_tools(registry: ToolRegistry) -> None:
    registry.register_fn(
        "run_code",
        "Execute code in an isolated sandbox. Supports python, javascript, bash. Files are written to a tempdir, not the workspace.",
        {"type": "object", "properties": {
            "code": {"type": "string", "description": "Code to execute"},
            "language": {"type": "string", "description": "Language: python, javascript, bash"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (max 60)"},
        }, "required": ["code"]},
        run_code, tags=["sandbox"], timeout_seconds=65,
    )
    registry.register_fn(
        "eval_python",
        "Evaluate a single Python expression in a sandboxed subprocess and return repr().",
        {"type": "object", "properties": {
            "expression": {"type": "string", "description": "Python expression to evaluate"},
        }, "required": ["expression"]},
        eval_python, read_only=True, tags=["sandbox"], timeout_seconds=15,
    )
