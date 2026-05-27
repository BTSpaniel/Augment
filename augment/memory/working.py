"""Working memory — short-lived, high-priority items for the current task."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List


logger = logging.getLogger("augment.memory.working")

_MAX_ITEMS = 20
_DEFAULT_TTL = 600  # 10 minutes


class WorkingMemory:
    """Short-term memory for current task context.

    Items expire after ``ttl`` seconds. Used to hold active context like the
    file being edited, recent observations, etc. Items above ``priority=8``
    are eligible for promotion to semantic memory during consolidation.
    """

    def __init__(self, max_items: int = _MAX_ITEMS) -> None:
        self._items: List[Dict[str, Any]] = []
        self._max = max(5, int(max_items))

    def put(self, key: str, value: Any, *, ttl: float = _DEFAULT_TTL, priority: int = 5) -> None:
        key = str(key).strip()[:100]
        if not key:
            return
        self._items = [i for i in self._items if i["key"] != key]
        self._items.append({
            "key": key,
            "value": value,
            "priority": max(1, min(10, int(priority))),
            "created_at": time.time(),
            "expires_at": time.time() + ttl,
        })
        self._prune()

    def get(self, key: str) -> Any:
        self._expire()
        for item in self._items:
            if item["key"] == key:
                return item["value"]
        return None

    def remove(self, key: str) -> None:
        self._items = [i for i in self._items if i["key"] != key]

    def all_items(self) -> List[Dict[str, Any]]:
        self._expire()
        return list(self._items)

    def clear(self) -> None:
        self._items.clear()

    def _expire(self) -> None:
        now = time.time()
        self._items = [i for i in self._items if i["expires_at"] > now]

    def _prune(self) -> None:
        self._expire()
        if len(self._items) > self._max:
            self._items.sort(key=lambda i: -i["priority"])
            self._items = self._items[: self._max]

    def as_context_block(self) -> str:
        items = self.all_items()
        if not items:
            return ""
        lines = ["[WORKING MEMORY]"]
        for item in sorted(items, key=lambda i: -i["priority"])[:10]:
            val = str(item["value"])[:200]
            lines.append(f"- [{item['key']}] {val}")
        return "\n".join(lines)
