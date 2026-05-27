from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from augment.tools.files import resolve_under
from augment.tools.registry import ToolRegistry

_MAX_RESULTS = 80
_MAX_OUTPUT_CHARS = 30000


def _ripgrep_path() -> str:
    found = shutil.which("rg")
    if found:
        return found
    candidates: list[Path] = []
    if sys.platform.startswith("win"):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.extend(Path(local_app_data).glob("Microsoft/WinGet/Packages/BurntSushi.ripgrep*/**/rg.exe"))
            candidates.extend(Path(local_app_data).glob("Microsoft/WinGet/Links/rg.exe"))
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            candidates.extend(Path(user_profile).glob("scoop/apps/ripgrep/current/rg.exe"))
            candidates.extend(Path(user_profile).glob(".cargo/bin/rg.exe"))
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def _workspace_root(_context: dict[str, Any] | None) -> Path:
    return Path(str((_context or {}).get("workspace_root") or ".")).expanduser().resolve()


def search_files(query: str, path: str = ".", extensions: str = "", _context: dict[str, Any] | None = None) -> str:
    root = _workspace_root(_context)
    base = resolve_under(root, path)
    needle = str(query or "").strip().lower()
    if not needle:
        return "Error: empty query"
    ext_list = [item.strip().lstrip(".") for item in str(extensions or "").split(",") if item.strip()]
    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", "__pycache__", ".pytest_cache", "venv"} and not d.startswith(".")]
        for filename in filenames:
            if filename.startswith("."):
                continue
            if needle not in filename.lower():
                continue
            if ext_list and not any(filename.endswith(f".{ext}") for ext in ext_list):
                continue
            file_path = Path(dirpath) / filename
            results.append(f"{file_path.relative_to(root).as_posix()} ({file_path.stat().st_size} bytes)")
            if len(results) >= _MAX_RESULTS:
                break
        if len(results) >= _MAX_RESULTS:
            break
    return "\n".join(results) if results else f"No files matching: {query}"


def search_code(query: str, path: str = ".", include: str = "", case_sensitive: bool = False, _context: dict[str, Any] | None = None) -> str:
    root = _workspace_root(_context)
    base = resolve_under(root, path)
    needle = str(query or "").strip()
    if not needle:
        return "Error: empty query"
    rg = _ripgrep_path()
    if rg:
        cmd = [rg, "--no-heading", "--line-number", "--color=never"]
        if not case_sensitive:
            cmd.append("--ignore-case")
        if include:
            cmd.extend(["--glob", include])
        cmd.extend([needle, str(base)])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(base if base.is_dir() else base.parent))
            output = result.stdout.strip()
            body = (output[:_MAX_OUTPUT_CHARS] + "\n... [truncated]" if len(output) > _MAX_OUTPUT_CHARS else output) or f"No matches found for: {query}"
            return f"[search_code: ripgrep]\n{body}"
        except Exception as exc:
            fallback = _python_search(needle, root, base, include, case_sensitive)
            return f"[search_code: ripgrep failed: {exc}; python fallback]\n{fallback}"
    return f"[search_code: python fallback; ripgrep not found in PATH or common install locations]\n{_python_search(needle, root, base, include, case_sensitive)}"


def _python_search(query: str, root: Path, base: Path, include: str, case_sensitive: bool) -> str:
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(query, flags)
    except re.error:
        pattern = re.compile(re.escape(query), flags)
    results: list[str] = []
    if base.is_file():
        if include and not base.match(include):
            return f"No matches found for: {query}"
        try:
            text = base.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return f"No matches found for: {query}"
        for line_number, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                results.append(f"{base.relative_to(root).as_posix()}:{line_number}: {line.strip()[:200]}")
                if len(results) >= _MAX_RESULTS:
                    return "\n".join(results)
        return "\n".join(results) if results else f"No matches found for: {query}"
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", "__pycache__", ".pytest_cache", "venv"} and not d.startswith(".")]
        for filename in filenames:
            if include and not Path(filename).match(include):
                continue
            file_path = Path(dirpath) / filename
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for line_number, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    results.append(f"{file_path.relative_to(root).as_posix()}:{line_number}: {line.strip()[:200]}")
                    if len(results) >= _MAX_RESULTS:
                        return "\n".join(results)
    return "\n".join(results) if results else f"No matches found for: {query}"


def register_search_tools(registry: ToolRegistry) -> None:
    registry.register_fn("search_files", "Find files by name under the workspace root.", {"type": "object", "properties": {"query": {"type": "string"}, "path": {"type": "string"}, "extensions": {"type": "string"}}, "required": ["query"]}, search_files, read_only=True, tags=["search"])
    registry.register_fn("search_code", "Search text or regex in files under the workspace root using ripgrep when available, with Python fallback.", {"type": "object", "properties": {"query": {"type": "string"}, "path": {"type": "string"}, "include": {"type": "string"}, "case_sensitive": {"type": "boolean"}}, "required": ["query"]}, search_code, read_only=True, tags=["search"])
