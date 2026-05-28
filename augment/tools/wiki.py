"""Wiki tools — persistent Markdown knowledge base.

Delegates to :class:`augment.knowledge.wiki.WikiManager` when a
``memory_system`` is present in the tool context (i.e. inside a live
chat loop). Falls back to the original flat-file JSON implementation
so the tools work in standalone / test environments.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List

from augment.tools.registry import ToolRegistry

_MAX_CONTENT = 10_000


# ── Context helpers ───────────────────────────────────────────────────

def _get_wiki(context: Dict[str, Any] | None):
    """Return the WikiManager from memory_system if available."""
    if isinstance(context, dict):
        ms = context.get("memory_system")
        if ms is not None:
            return getattr(ms, "wiki", None)
    return None


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


# ── Tool functions ────────────────────────────────────────────────────

def wiki_write(title: str, content: str, category: str = "general", _context: Dict[str, Any] | None = None) -> str:
    title = str(title or "").strip()[:200]
    content = str(content or "").strip()[:_MAX_CONTENT]
    if not title:
        return "Error: title required"
    if not content:
        return "Error: content required"

    wiki = _get_wiki(_context)
    if wiki:
        try:
            page = wiki.write_page(title, content, source=f"tool:wiki_write")
            existed = page.content.count("version:") > 0
            return f"{'Updated' if existed else 'Created'} wiki page: {title}"
        except Exception as exc:
            return f"Error writing wiki page: {exc}"

    # ── JSON fallback ──────────────────────────────────────────────
    path = _page_path(_context, title)
    existing = None
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = None
    page_data = {
        "title": title,
        "slug": _slug(title),
        "content": content,
        "category": (category or "general").strip()[:50] or "general",
        "created_at": existing.get("created_at", time.time()) if existing else time.time(),
        "updated_at": time.time(),
        "version": (existing.get("version", 0) if existing else 0) + 1,
    }
    path.write_text(json.dumps(page_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"{'Updated' if existing else 'Created'} wiki page: {title} (v{page_data['version']})"


def wiki_read(title: str, _context: Dict[str, Any] | None = None) -> str:
    title = str(title or "").strip()
    if not title:
        return "Error: title required"

    wiki = _get_wiki(_context)
    if wiki:
        content = wiki.read_page(title)
        if content:
            return content
        hits = wiki.search(title, max_results=3)
        if hits:
            names = ", ".join(h.name for h in hits)
            return f"Page '{title}' not found. Similar pages: {names}"
        return f"Wiki page not found: {title}"

    # ── JSON fallback ──────────────────────────────────────────────
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

    wiki = _get_wiki(_context)
    if wiki:
        hits = wiki.search(needle, max_results=10)
        if not hits:
            return f"No wiki pages matching: {query}"
        lines = [f"Found {len(hits)} pages:"]
        for page in hits:
            lines.append(f"  - [[{page.name}]] — {page.summary_line[:120]}")
        return "\n".join(lines)

    # ── JSON fallback ──────────────────────────────────────────────
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
    wiki = _get_wiki(_context)
    if wiki:
        pages = wiki.list_pages()
        if not pages:
            return "No wiki pages found."
        lines = [f"Wiki pages ({len(pages)}):"]
        for page in pages[:50]:
            lines.append(f"  - [[{page.name}]] — {page.summary_line[:100]}")
        return "\n".join(lines)

    # ── JSON fallback ──────────────────────────────────────────────
    page_list: List[Dict[str, Any]] = []
    for path in sorted(_wiki_dir(_context).glob("*.json")):
        try:
            page = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if category and str(page.get("category", "")).lower() != category.lower():
            continue
        page_list.append(page)
    if not page_list:
        suffix = f" (category={category})" if category else ""
        return "No wiki pages found." + suffix
    lines = [f"Wiki pages ({len(page_list)}):"]
    for page in page_list[:50]:
        lines.append(f"  - [{page.get('category', 'general')}] {page.get('title', '?')}")
    return "\n".join(lines)


def wiki_delete(title: str, _context: Dict[str, Any] | None = None) -> str:
    title = str(title or "").strip()
    if not title:
        return "Error: title required"

    wiki = _get_wiki(_context)
    if wiki:
        ok = wiki.delete_page(title)
        return f"Deleted wiki page: {title}" if ok else f"Wiki page not found: {title}"

    # ── JSON fallback ──────────────────────────────────────────────
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
