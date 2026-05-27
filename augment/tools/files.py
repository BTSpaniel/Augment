from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from augment.security.path_guard import PathGuard
from augment.tools.registry import ToolRegistry

_MAX_READ_CHARS = 60000
_MAX_LIST_ENTRIES = 200
_STYLE_CHECK_EXTENSIONS = {".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".py"}


def resolve_under(root: Path, path: str) -> Path:
    base = root.expanduser().resolve()
    value = Path(str(path or ".")).expanduser()
    candidate = value.resolve() if value.is_absolute() else (base / value).resolve()
    candidate.relative_to(base)
    return candidate


def _workspace_root(_context: dict[str, Any] | None) -> Path:
    root = (_context or {}).get("workspace_root") or "."
    return Path(str(root)).expanduser().resolve()


def _scratch_root(_context: dict[str, Any] | None) -> Path:
    """Default sandbox dir for new files when no explicit output_dir is set."""
    ctx = _context or {}
    explicit = ctx.get("scratch_root")
    if explicit:
        return Path(str(explicit)).expanduser().resolve()
    return _workspace_root(ctx) / "temp"


def _output_dir_override(_context: dict[str, Any] | None) -> Path | None:
    """User-directed override (e.g. ``set_output_dir('C:/cake')``)."""
    value = (_context or {}).get("output_dir")
    if not value:
        return None
    return Path(str(value)).expanduser().resolve()


def _resolve_write_target(path: str, _context: dict[str, Any] | None) -> tuple[Path, Path, str]:
    """Resolve where a `write_file` call lands.

    Resolution priority:
      1. Absolute ``path`` → use literally (still subject to PathGuard).
      2. Session has an ``output_dir`` override → place under that dir.
      3. Otherwise → place under ``<scratch_root>/<session_id>/`` so new
         files don't litter the workspace unless explicitly asked.

    Returns ``(target_path, base_dir, kind)`` where ``kind`` is one of
    ``absolute`` / ``override`` / ``scratch``.
    """
    ctx = _context or {}
    sid = str(ctx.get("session_id") or "default")
    candidate = Path(str(path or "")).expanduser()

    if candidate.is_absolute():
        target = candidate.resolve()
        return target, target.parent, "absolute"

    override = _output_dir_override(ctx)
    if override is not None:
        override.mkdir(parents=True, exist_ok=True)
        target = (override / candidate).resolve()
        target.relative_to(override)  # prevent ../ escape
        return target, override, "override"

    base = _scratch_root(ctx) / sid
    base.mkdir(parents=True, exist_ok=True)
    target = (base / candidate).resolve()
    target.relative_to(base)
    return target, base, "scratch"


def _display(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix() or "."
    except Exception:
        return str(path)


def _first_meaningful_line(lines: list[str]) -> tuple[int, str]:
    """Return the first non-empty line with its zero-based index."""
    for index, line in enumerate(lines):
        if line.strip():
            return index, line.strip()
    return 0, ""


def _has_required_header(path: Path, text: str) -> bool:
    """Check whether a code file starts with the required audit header."""
    lines = text.splitlines()
    index, first = _first_meaningful_line(lines)
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        if first.lower().startswith("<!doctype"):
            _, first = _first_meaningful_line(lines[index + 1:])
        return first.startswith("<!--")
    if suffix == ".py":
        return first.startswith('"""') or first.startswith("'''")
    if suffix in {".css", ".js", ".mjs", ".cjs"}:
        return first.startswith("/**") or first.startswith("/*")
    return True


def _has_section_markers(path: Path, text: str) -> bool:
    """Check whether long code files are split into visible sections."""
    if len(text.splitlines()) <= 100:
        return True
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return text.count("<!--") >= 2 or "/* --" in text or "// ===" in text
    if suffix == ".py":
        return "# --" in text or "# ──" in text or "# ==" in text
    if suffix in {".css", ".js", ".mjs", ".cjs"}:
        return "/* --" in text or "/* ==" in text or "// --" in text or "// ===" in text
    return True


def _has_js_doc_before(lines: list[str], index: int) -> bool:
    """Return True when a JS function/class has a nearby doc block."""
    window = "\n".join(lines[max(0, index - 5):index]).strip()
    return window.endswith("*/") and "/**" in window


def _missing_js_docs(text: str) -> list[str]:
    """List public JS functions/classes that are missing JSDoc blocks."""
    missing: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        name = ""
        if stripped.startswith("function "):
            name = stripped.removeprefix("function ").split("(", 1)[0].strip()
        elif stripped.startswith("async function "):
            name = stripped.removeprefix("async function ").split("(", 1)[0].strip()
        elif stripped.startswith("class "):
            name = stripped.removeprefix("class ").split("{", 1)[0].split(" ", 1)[0].strip()
        if name and not name.startswith("_") and not _has_js_doc_before(lines, index):
            missing.append(name)
    return missing[:5]


def _missing_python_docs(text: str) -> list[str]:
    """List public Python functions/classes missing immediate docstrings."""
    missing: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not (stripped.startswith("def ") or stripped.startswith("async def ") or stripped.startswith("class ")):
            continue
        name = stripped.split(" ", 2)[1].split("(", 1)[0].split(":", 1)[0].strip()
        if not name or name.startswith("_"):
            continue
        next_lines = [item.strip() for item in lines[index + 1:index + 4] if item.strip()]
        if not next_lines or not (next_lines[0].startswith('"""') or next_lines[0].startswith("'''")):
            missing.append(name)
    return missing[:5]


def _coding_style_errors(path: Path, content: str) -> list[str]:
    """Return blocking style errors for generated code files."""
    if path.suffix.lower() not in _STYLE_CHECK_EXTENSIONS:
        return []
    text = str(content or "")
    errors: list[str] = []
    if not _has_required_header(path, text):
        errors.append("missing required 4-12 line file-header banner")
    if not _has_section_markers(path, text):
        errors.append("missing required section comments for a file over 100 lines")
    if path.suffix.lower() == ".py":
        missing = _missing_python_docs(text)
        if missing:
            errors.append(f"missing public docstrings: {', '.join(missing)}")
    if path.suffix.lower() in {".html", ".htm", ".js", ".mjs", ".cjs"}:
        missing = _missing_js_docs(text)
        if missing:
            errors.append(f"missing JSDoc blocks: {', '.join(missing)}")
    return errors


def list_dir(path: str = ".", _context: dict[str, Any] | None = None) -> str:
    root = _workspace_root(_context)
    target = resolve_under(root, path)
    if not target.exists():
        return f"Error: directory not found: {path}"
    if not target.is_dir():
        return f"Error: not a directory: {path}"
    entries: list[str] = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            try:
                count = sum(1 for _ in item.iterdir())
            except Exception:
                count = 0
            entries.append(f"{item.name}/ ({count} items)")
        else:
            entries.append(f"{item.name} ({item.stat().st_size} bytes)")
        if len(entries) >= _MAX_LIST_ENTRIES:
            entries.append("... [truncated]")
            break
    return f"{_display(root, target)}/\n" + ("\n".join(entries) if entries else "(empty)")


def _resolve_existing_file(path: str, _context: dict[str, Any] | None) -> Path | None:
    """Find an existing file by probing workspace → override → scratch dirs.

    Used by ``read_file`` and ``edit_file`` so a file created via
    ``write_file`` is reachable by the same relative path without forcing
    the agent to remember the scratch sub-directory.
    """
    raw = Path(str(path or "")).expanduser()
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw.resolve())
    else:
        try:
            candidates.append(resolve_under(_workspace_root(_context), str(path)))
        except Exception:
            pass
        override = _output_dir_override(_context)
        if override is not None:
            try:
                candidates.append((override / raw).resolve())
            except Exception:
                pass
        sid = str((_context or {}).get("session_id") or "default")
        try:
            candidates.append((_scratch_root(_context) / sid / raw).resolve())
        except Exception:
            pass
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def read_file(path: str, start_line: int = 0, end_line: int = 0, _context: dict[str, Any] | None = None) -> str:
    target = _resolve_existing_file(path, _context)
    if target is None:
        return f"Error: file not found: {path}"
    root = _workspace_root(_context)
    text = target.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    total = len(lines)
    start = max(1, int(start_line or 1))
    end = int(end_line or total or 1)
    selected = lines[start - 1:end] if start_line or end_line else lines
    offset = start if (start_line or end_line) else 1
    display = _display(root, target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    header = f"[FILE CONTEXT] path={display} lines={offset}-{offset + len(selected) - 1} total_lines={total} sha256={digest}"
    body = "\n".join(f"{offset + index:>5}\t{line}" for index, line in enumerate(selected))
    output = header + ("\n" + body if body else "")
    return output[:_MAX_READ_CHARS] + ("\n... [truncated]" if len(output) > _MAX_READ_CHARS else "")


_WRITE_PATH_GUARD = PathGuard()  # blocks .env, ~/.ssh, *.pem, credentials, etc.


def write_file(path: str, content: str, _context: dict[str, Any] | None = None) -> str:
    """Write ``content`` to a file.

    By default new files land in ``<scratch_root>/<session_id>/`` so the
    agent never litters the workspace. If the session has an explicit
    ``output_dir`` override (set via ``set_output_dir`` or the
    ``PUT /api/sessions/{id}/output_dir`` endpoint) writes go there
    instead. Absolute paths are honored but guarded against sensitive
    locations (``.env``, SSH keys, system creds, etc).
    """
    if not str(path or "").strip():
        return "Error: path is required"
    try:
        target, base, kind = _resolve_write_target(path, _context)
    except ValueError as exc:
        return f"Error: refused unsafe write target ({exc})"
    if kind == "absolute" and not _WRITE_PATH_GUARD.is_safe(str(target)):
        return f"Error: refused to write to sensitive path: {target}"
    style_errors = _coding_style_errors(target, str(content or ""))
    if style_errors:
        return (
            "Error: coding style gate blocked write_file for "
            f"{target.name}: " + "; ".join(style_errors)
            + ". Rewrite the complete file content with the required header, sections, and docs."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(content or ""), encoding="utf-8")
    size = target.stat().st_size
    display = _display(base, target) if kind != "absolute" else str(target)
    if kind == "scratch":
        suffix = f" (scratch — set_output_dir to redirect)"
    elif kind == "override":
        suffix = f" (output_dir override: {base})"
    else:
        suffix = " (absolute path)"
    return f"Written {size} bytes to {display}{suffix}"


def edit_file(path: str, old_string: str, new_string: str, _context: dict[str, Any] | None = None) -> str:
    """Replace exactly one occurrence of ``old_string`` in a file.

    Resolves the target by trying, in order:
      1. The literal absolute path.
      2. ``<workspace_root>/<path>`` (existing behavior).
      3. ``<output_dir>/<path>`` if the session has an override.
      4. ``<scratch_root>/<session_id>/<path>`` for files just written.
    """
    target = _resolve_existing_file(path, _context)
    if target is None:
        return f"Error: file not found: {path}"
    if not _WRITE_PATH_GUARD.is_safe(str(target)):
        return f"Error: refused to edit sensitive path: {target}"
    text = target.read_text(encoding="utf-8")
    if old_string not in text:
        return "Error: old_string not found. Re-read the file and use an exact unique snippet."
    count = text.count(old_string)
    if count != 1:
        return f"Error: old_string appears {count} times. Provide a unique snippet."
    target.write_text(text.replace(old_string, new_string, 1), encoding="utf-8")
    return f"Edited {target}: replaced 1 occurrence"


def set_output_dir(path: str, _context: dict[str, Any] | None = None) -> str:
    """Record where new files should land for this session.

    Use this only when the user has *explicitly* directed where to place
    files — e.g. ``"put everything in C:\\cake"``. Pass an empty string to
    clear the override and revert to the default scratch directory.
    """
    ctx = _context or {}
    sid = str(ctx.get("session_id") or "")
    sessions = ctx.get("sessions_store")
    if sessions is None:
        return "Error: session store unavailable"
    clean = str(path or "").strip()
    if not clean:
        sessions.set_meta(sid, output_dir="")
        return "Cleared output_dir override; new files will go to the default scratch directory."
    resolved = Path(clean).expanduser().resolve()
    if not _WRITE_PATH_GUARD.is_safe(str(resolved)):
        return f"Error: refused to set sensitive path as output_dir: {resolved}"
    resolved.mkdir(parents=True, exist_ok=True)
    sessions.set_meta(sid, output_dir=str(resolved))
    return f"Output directory set to {resolved}. Subsequent write_file calls (with relative paths) will land here."


def register_file_tools(registry: ToolRegistry) -> None:
    registry.register_fn("list_dir", "List files and directories under the workspace root.", {"type": "object", "properties": {"path": {"type": "string"}}}, list_dir, read_only=True, tags=["filesystem"])
    registry.register_fn("read_file", "Read a UTF-8 text file under the workspace root with line numbers.", {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, "required": ["path"]}, read_file, read_only=True, tags=["filesystem"])
    registry.register_fn(
        "write_file",
        "Write a UTF-8 text file. Code files must include the required file-header banner, section comments for files over 100 lines, and public function/class docs; non-compliant code writes are rejected. By default new files land in <scratch_root>/<session_id>/ (a temp sandbox). Use set_output_dir(path) ONCE PER SESSION when the user explicitly directs files to a specific location.",
        {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
        write_file, read_only=False, tags=["filesystem"],
    )
    registry.register_fn("edit_file", "Replace one exact unique string in a file. Resolves under workspace_root, then the session output_dir, then the scratch directory.", {"type": "object", "properties": {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}}, "required": ["path", "old_string", "new_string"]}, edit_file, read_only=False, tags=["filesystem"])
    registry.register_fn(
        "set_output_dir",
        "Set the directory where subsequent write_file calls will place files. Use ONLY when the user explicitly says 'put files in <path>' or 'place this in <directory>'. Pass an empty string to clear the override.",
        {"type": "object", "properties": {"path": {"type": "string", "description": "Absolute directory path (e.g. C:/cake)."}}, "required": ["path"]},
        set_output_dir, read_only=False, tags=["filesystem", "session"],
    )
