"""Memory consolidation — promotes items from working → episodic → semantic."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from augment.memory.episodic import EpisodicMemory
from augment.memory.procedural import ProceduralMemory
from augment.memory.semantic import SemanticMemory
from augment.memory.working import WorkingMemory


logger = logging.getLogger("augment.memory.consolidation")


class MemoryConsolidator:
    """Promotes short-term observations into durable storage.

    Call :meth:`consolidate_session` at the end of a chat to record an
    episode, store any newly-learned facts, and clear working memory.
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
        self._last_consolidation: float = 0.0

    def consolidate_session(
        self,
        *,
        session_id: str = "",
        summary: str = "",
        outcome: str = "success",
        tools_used: Optional[List[str]] = None,
        lessons: Optional[List[str]] = None,
        facts_learned: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        if summary:
            self._episodic.record(
                session_id=session_id,
                summary=summary,
                outcome=outcome,
                tools_used=tools_used,
                lessons=lessons,
            )

        if facts_learned:
            for fact in facts_learned[:10]:
                key = fact.get("key", "")
                value = fact.get("value", "")
                if key and value:
                    self._semantic.store(
                        key,
                        value,
                        category=fact.get("category", "learned"),
                        source=f"session:{session_id}",
                    )

        self._working.clear()
        self._last_consolidation = time.time()
        logger.debug(
            "session %s consolidated (outcome=%s, tools=%d)",
            (session_id or "")[:12],
            outcome,
            len(tools_used or []),
        )

    def consolidate_working(self, *, min_priority: int = 8) -> int:
        """Promote high-priority working items into semantic memory. Returns count."""
        promoted = 0
        for item in self._working.all_items():
            if int(item.get("priority", 0)) < min_priority:
                continue
            key = str(item.get("key", ""))
            value = str(item.get("value", ""))
            if key and value:
                self._semantic.store(
                    key,
                    value,
                    category="working_promoted",
                    confidence=0.6,
                )
                promoted += 1
        self._last_consolidation = time.time()
        return promoted

    @property
    def time_since_last(self) -> float:
        if not self._last_consolidation:
            return float("inf")
        return time.time() - self._last_consolidation
