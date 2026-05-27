"""Investigation tool — light multi-step search + read orchestration.

This is a simplified port of FAIL's Holmes investigation. It runs a small
fixed pipeline (workspace search + targeted reads + memory recall) rather than
spawning a full sub-loop, keeping latency bounded inside Augment's single
ReAct loop.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from augment.tools.files import _MAX_READ_CHARS, _workspace_root, resolve_under  # type: ignore
from augment.tools.registry import ToolRegistry
from augment.tools.search import search_code, search_files  # type: ignore


def _read_snippet(root: Path, path: Path, max_chars: int = 1200) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"(error reading {path}: {exc})"
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... [truncated]"
    try:
        rel = path.relative_to(root).as_posix()
    except Exception:
        rel = str(path)
    return f"### {rel}\n{text}"


def investigate(question: str, _context: Dict[str, Any] | None = None) -> str:
    question = str(question or "").strip()
    if not question:
        return "Error: empty question"
    root = _workspace_root(_context)
    sections: list[str] = [f"# Investigation: {question}", ""]

    # Step 1 — workspace code search
    code_hits = search_code(question, _context=_context)
    sections.append("## Code matches")
    sections.append(code_hits or "(none)")

    # Step 2 — file-name matches
    file_hits = search_files(question, _context=_context)
    sections.append("\n## File matches")
    sections.append(file_hits or "(none)")

    # Step 3 — read top files mentioned in the search output
    candidates: list[Path] = []
    seen: set[str] = set()
    for line in (code_hits or "").splitlines():
        parts = line.split(":", 1)
        if not parts:
            continue
        rel = parts[0].strip()
        if not rel or rel in seen:
            continue
        seen.add(rel)
        try:
            candidate = resolve_under(root, rel)
        except Exception:
            continue
        if candidate.is_file():
            candidates.append(candidate)
        if len(candidates) >= 3:
            break

    if candidates:
        sections.append("\n## Read excerpts")
        for path in candidates:
            sections.append(_read_snippet(root, path))

    # Step 4 — memory recall
    store = (_context or {}).get("memory") if isinstance(_context, dict) else None
    if store is not None:
        hits = store.search(question, limit=5)
        if hits:
            sections.append("\n## Memory")
            for item in hits:
                key = item.get("key") or item.get("category") or "fact"
                sections.append(f"- [{key}] {str(item.get('fact') or '')[:240]}")

    output = "\n".join(sections)
    if len(output) > _MAX_READ_CHARS:
        output = output[:_MAX_READ_CHARS] + "\n... [truncated]"
    return output


def register_investigation_tools(registry: ToolRegistry) -> None:
    registry.register_fn(
        "investigate",
        "Run a quick multi-step investigation of a question against the workspace: search code, search filenames, read top matches, and recall related memory.",
        {"type": "object", "properties": {
            "question": {"type": "string", "description": "The question or problem to investigate"},
        }, "required": ["question"]},
        investigate, read_only=True, tags=["investigation"], timeout_seconds=60,
    )
