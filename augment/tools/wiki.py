"""Wiki tools — persistent Markdown knowledge base (FAIL port)."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List

from augment.tools.registry import ToolRegistry

_MAX_CONTENT = 10_000


def _wiki_dir(context: Dict[str, Any] | None) -> Path:
    data_dir = ""
    if isinstance(context, dict):
        data_dir = str(context.get("data_dir") or "")
    root = Path(data_dir).expanduser().resolve() if data_dir else Path("data").resolve()
    directory = root / "wiki"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(title or "").lower().strip()).strip("-")
    return slug[:80] or "untitled"


def _page_path(context: Dict[str, Any] | None, title: str) -> Path:
    return _wiki_dir(context) / f"{_slug(title)}.json"


def wiki_write(title: str, content: str, category: str = "general", _context: Dict[str, Any] | None = None) -> str:
    title = str(title or "").strip()[:200]
    content = str(content or "").strip()[:_MAX_CONTENT]
    if not title:
        return "Error: title required"
    if not content:
        return "Error: content required"
    path = _page_path(_context, title)
    existing = None
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = None
    page = {
        "title": title,
        "slug": _slug(title),
        "content": content,
        "category": (category or "general").strip()[:50] or "general",
        "created_at": existing.get("created_at", time.time()) if existing else time.time(),
        "updated_at": time.time(),
        "version": (existing.get("version", 0) if existing else 0) + 1,
    }
    path.write_text(json.dumps(page, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"{'Updated' if existing else 'Created'} wiki page: {title} (v{page['version']})"


def wiki_read(title: str, _context: Dict[str, Any] | None = None) -> str:
    title = str(title or "").strip()
    if not title:
        return "Error: title required"
    path = _page_path(_context, title)
    if not path.exists():
        matches = wiki_search(title, _context=_context)
        if matches and not matches.startswith("No wiki pages"):
            return f"Page '{title}' not found. Closest matches:\n{matches}"
        return f"Wiki page not found: {title}"
    try:
        page = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"Error reading wiki page: {exc}"
    return f"# {page['title']}\nCategory: {page.get('category', 'general')} | v{page.get('version', 1)}\n\n{page['content']}"


def wiki_search(query: str, _context: Dict[str, Any] | None = None) -> str:
    needle = str(query or "").strip().lower()
    if not needle:
        return "Error: query required"
    results: List[str] = []
    for path in sorted(_wiki_dir(_context).glob("*.json")):
        try:
            page = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        haystack = f"{page.get('title', '')} {page.get('content', '')} {page.get('category', '')}".lower()
        if needle in haystack:
            results.append(f"- [{page.get('category', 'general')}] {page.get('title', path.stem)}: {str(page.get('content') or '')[:120]}")
        if len(results) >= 20:
            break
    if not results:
        return f"No wiki pages matching: {query}"
    return f"Found {len(results)} pages:\n" + "\n".join(results)


def wiki_list(category: str = "", _context: Dict[str, Any] | None = None) -> str:
    pages: List[Dict[str, Any]] = []
    for path in sorted(_wiki_dir(_context).glob("*.json")):
        try:
            page = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if category and str(page.get("category", "")).lower() != category.lower():
            continue
        pages.append(page)
    if not pages:
        suffix = f" (category={category})" if category else ""
        return "No wiki pages found." + suffix
    lines = [f"Wiki pages ({len(pages)}):"]
    for page in pages[:50]:
        lines.append(f"  - [{page.get('category', 'general')}] {page.get('title', '?')}")
    return "\n".join(lines)


def wiki_delete(title: str, _context: Dict[str, Any] | None = None) -> str:
    title = str(title or "").strip()
    if not title:
        return "Error: title required"
    path = _page_path(_context, title)
    if not path.exists():
        return f"Wiki page not found: {title}"
    try:
        path.unlink()
    except Exception as exc:
        return f"Error deleting wiki page: {exc}"
    return f"Deleted wiki page: {title}"


def register_wiki_tools(registry: ToolRegistry) -> None:
    registry.register_fn(
        "wiki_write",
        "Create or update a wiki page in the persistent knowledge base under data/wiki.",
        {"type": "object", "properties": {
            "title": {"type": "string", "description": "Page title"},
            "content": {"type": "string", "description": "Page content (Markdown)"},
            "category": {"type": "string", "description": "Category bucket (project, reference, notes, …)"},
        }, "required": ["title", "content"]},
        wiki_write, tags=["wiki"],
    )
    registry.register_fn(
        "wiki_read",
        "Read a wiki page by title.",
        {"type": "object", "properties": {
            "title": {"type": "string", "description": "Page title to read"},
        }, "required": ["title"]},
        wiki_read, read_only=True, tags=["wiki"],
    )
    registry.register_fn(
        "wiki_search",
        "Search wiki pages by keyword across title, content, and category.",
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "Search query"},
        }, "required": ["query"]},
        wiki_search, read_only=True, tags=["wiki"],
    )
    registry.register_fn(
        "wiki_list",
        "List all wiki pages, optionally filtered by category.",
        {"type": "object", "properties": {
            "category": {"type": "string", "description": "Filter by category (optional)"},
        }},
        wiki_list, read_only=True, tags=["wiki"],
    )
    registry.register_fn(
        "wiki_delete",
        "Delete a wiki page by title.",
        {"type": "object", "properties": {
            "title": {"type": "string", "description": "Page title to delete"},
        }, "required": ["title"]},
        wiki_delete, tags=["wiki"],
    )
