"""Memory retrieval — relevance-ranked access across all memory tiers."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from augment.memory.episodic import EpisodicMemory
from augment.memory.procedural import ProceduralMemory
from augment.memory.semantic import SemanticMemory
from augment.memory.working import WorkingMemory


logger = logging.getLogger("augment.memory.retrieval")


class MemoryRetriever:
    """Unified retrieval across the working / episodic / semantic / procedural tiers.

    Returns relevance-ranked results with a ``tier`` discriminator so callers
    can render or weight them differently.
    """

    def __init__(
        self,
        working: WorkingMemory,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        procedural: ProceduralMemory,
    ) -> None:
        self._working = working
        self._episodic = episodic
        self._semantic = semantic
        self._procedural = procedural

    def retrieve(self, query: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        needle = str(query or "").lower()
        results: List[Dict[str, Any]] = []
        if not needle:
            return results

        for item in self._working.all_items():
            text = f"{item.get('key', '')} {item.get('value', '')}".lower()
            if needle in text:
                results.append({
                    "tier": "working",
                    "key": item["key"],
                    "content": str(item["value"])[:300],
                    "score": 1.0,
                })

        for fact in self._semantic.search(query, limit=limit):
            results.append({
                "tier": "semantic",
                "key": fact.get("key", ""),
                "content": str(fact.get("value", ""))[:300],
                "score": float(fact.get("confidence", 0.5)) * 0.8,
            })

        for episode in self._episodic.search(query, limit=5):
            results.append({
                "tier": "episodic",
                "key": str(episode.get("session_id", ""))[:12],
                "content": str(episode.get("summary", ""))[:300],
                "score": 0.6,
            })

        for proc in self._procedural.find_for_trigger(query):
            steps = " → ".join((proc.get("steps") or [])[:5])
            results.append({
                "tier": "procedural",
                "key": str(proc.get("name", "")),
                "content": steps[:300],
                "score": float(proc.get("success_rate", 0.5)) * 0.7,
            })

        results.sort(key=lambda r: -float(r.get("score", 0)))
        return results[: max(1, limit)]

    def context_block_for(self, query: str, *, max_chars: int = 2000) -> str:
        results = self.retrieve(query, limit=8)
        if not results:
            return ""
        lines = ["[RELEVANT MEMORIES]"]
        total = 0
        for r in results:
            entry = f"- [{r['tier']}:{r['key']}] {r['content']}"
            if total + len(entry) > max_chars:
                break
            lines.append(entry)
            total += len(entry)
        return "\n".join(lines)
