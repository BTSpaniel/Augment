"""Semantic memory — long-term facts, knowledge, and learned information."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


logger = logging.getLogger("augment.memory.semantic")

_MAX_FACTS = 500


class SemanticMemory:
    """Long-term keyed fact storage with category + confidence scoring.

    Distinct from the legacy :class:`augment.context.memory.MemoryStore` so
    the new memory tools can write here without interfering with the existing
    behaviour exposed to the chat UI's Memory page.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir) / "memory"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._data_dir / "semantic.json"
        self._facts: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("semantic load failed: %s", exc)
            return
        if isinstance(data, dict):
            facts = data.get("facts") or {}
            if isinstance(facts, dict):
                self._facts = {str(k): dict(v) for k, v in facts.items() if isinstance(v, dict)}

    def save(self) -> None:
        data = {
            "facts": self._facts,
            "updated_at": time.time(),
            "count": len(self._facts),
        }
        try:
            self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.warning("semantic save failed: %s", exc)

    def store(
        self,
        key: str,
        value: str,
        *,
        category: str = "general",
        confidence: float = 0.8,
        source: str = "",
    ) -> None:
        clean_key = str(key).strip().lower()[:200]
        if not clean_key:
            return
        self._facts[clean_key] = {
            "value": str(value).strip()[:1000],
            "category": str(category or "general"),
            "confidence": max(0.0, min(1.0, float(confidence))),
            "source": str(source)[:100],
            "created_at": time.time(),
            "access_count": 0,
        }
        if len(self._facts) > _MAX_FACTS:
            self._evict()
        self.save()

    def recall(self, key: str) -> Optional[str]:
        entry = self._facts.get(str(key).strip().lower())
        if entry is None:
            return None
        entry["access_count"] = int(entry.get("access_count", 0)) + 1
        return entry.get("value")

    def search(
        self,
        query: str,
        *,
        category: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        needle = str(query or "").lower()
        results: List[Dict[str, Any]] = []
        for key, fact in self._facts.items():
            if category and fact.get("category") != category:
                continue
            text = f"{key} {fact.get('value', '')}".lower()
            if needle and needle not in text:
                continue
            results.append({"key": key, **fact})
        results.sort(
            key=lambda x: (
                -float(x.get("confidence", 0)),
                -int(x.get("access_count", 0)),
            )
        )
        return results[: max(1, limit)]

    def by_category(self, category: str, limit: int = 20) -> List[Dict[str, Any]]:
        results = [{"key": k, **v} for k, v in self._facts.items() if v.get("category") == category]
        results.sort(key=lambda x: -float(x.get("confidence", 0)))
        return results[: max(1, limit)]

    def all_facts(self, *, limit: int = 500) -> List[Dict[str, Any]]:
        results = [{"key": k, **v} for k, v in self._facts.items()]
        results.sort(key=lambda x: -float(x.get("confidence", 0)))
        return results[: max(1, limit)]

    def remove(self, key: str) -> bool:
        clean_key = str(key).strip().lower()
        if clean_key in self._facts:
            del self._facts[clean_key]
            self.save()
            return True
        return False

    def _evict(self) -> None:
        if len(self._facts) <= _MAX_FACTS:
            return
        scored = sorted(
            self._facts.items(),
            key=lambda kv: (
                float(kv[1].get("confidence", 0)) * 0.6
                + min(int(kv[1].get("access_count", 0)), 10) * 0.04
            ),
        )
        remove_count = len(self._facts) - _MAX_FACTS
        for key, _ in scored[:remove_count]:
            del self._facts[key]

    def as_context_block(self, *, category: Optional[str] = None, limit: int = 8) -> str:
        facts = self.by_category(category, limit=limit) if category else self.all_facts(limit=limit)
        if not facts:
            return ""
        lines = ["[SEMANTIC MEMORY]"]
        for fact in facts:
            lines.append(f"- {fact['key']}: {str(fact.get('value', ''))[:150]}")
        return "\n".join(lines)
