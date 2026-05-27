"""Memory tools — store, recall, search, take notes (FAIL port).

These wrap the in-process :class:`augment.context.memory.MemoryStore`, which is
exposed via the ReAct ``_context["memory"]`` injection.
"""
from __future__ import annotations

from typing import Any, Dict

from augment.tools.registry import ToolRegistry


def _store(context: Dict[str, Any] | None):
    if not isinstance(context, dict):
        return None
    return context.get("memory")


def _session_id(context: Dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    return str(context.get("session_id") or "")


def store_fact(key: str, value: str, category: str = "general", _context: Dict[str, Any] | None = None) -> str:
    store = _store(_context)
    if store is None:
        return "Error: memory not available"
    record = store.set_fact(key, value, category=category, session_id=_session_id(_context))
    if not record:
        return "Error: key and value required"
    return f"Stored fact [{record.get('category', 'general')}] {record['key']}: {record['fact'][:200]}"


def recall_fact(key: str, _context: Dict[str, Any] | None = None) -> str:
    store = _store(_context)
    if store is None:
        return "Error: memory not available"
    record = store.get_fact(key)
    if not record:
        return f"No fact found for key: {key}"
    return f"[{record.get('category', 'general')}] {record.get('key')}: {record.get('fact', '')}"


def search_memory(query: str, limit: int = 8, _context: Dict[str, Any] | None = None) -> str:
    store = _store(_context)
    if store is None:
        return "Error: memory not available"
    hits = store.search(query, limit=max(1, min(int(limit or 8), 32)))
    if not hits:
        return f"No memories matching: {query}"
    lines = [f"Found {len(hits)} memories for: {query}"]
    for item in hits:
        key = item.get("key") or item.get("category") or "fact"
        lines.append(f"- [{key}] {str(item.get('fact') or '')[:280]}")
    return "\n".join(lines)


def add_note(content: str, category: str = "note", _context: Dict[str, Any] | None = None) -> str:
    store = _store(_context)
    if store is None:
        return "Error: memory not available"
    record = store.add_note(content, category=category, session_id=_session_id(_context))
    if not record:
        return "Error: empty note"
    return f"Note added [{record.get('category', 'note')}]: {record['fact'][:200]}"


def register_memory_tools(registry: ToolRegistry) -> None:
    registry.register_fn(
        "store_fact",
        "Store a fact in durable memory under a key for future recall. Use for user preferences, project decisions, and reusable knowledge.",
        {"type": "object", "properties": {
            "key": {"type": "string", "description": "Short slug or label for the fact"},
            "value": {"type": "string", "description": "The fact content"},
            "category": {"type": "string", "description": "Category bucket: general, user, project, tool"},
        }, "required": ["key", "value"]},
        store_fact, tags=["memory"],
    )
    registry.register_fn(
        "recall_fact",
        "Recall a previously stored fact from memory by exact key match.",
        {"type": "object", "properties": {
            "key": {"type": "string", "description": "Key to look up"},
        }, "required": ["key"]},
        recall_fact, read_only=True, tags=["memory"],
    )
    registry.register_fn(
        "search_memory",
        "Search across stored memories (facts and notes) for a substring match.",
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "description": "Max results (default 8, max 32)"},
        }, "required": ["query"]},
        search_memory, read_only=True, tags=["memory"],
    )
    registry.register_fn(
        "add_note",
        "Append a short note to durable memory. Use for in-progress observations during multi-step tasks.",
        {"type": "object", "properties": {
            "content": {"type": "string", "description": "Note content"},
            "category": {"type": "string", "description": "Category bucket (default: note)"},
        }, "required": ["content"]},
        add_note, tags=["memory"],
    )
