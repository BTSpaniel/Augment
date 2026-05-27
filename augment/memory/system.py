"""Memory system — unified access to all memory tiers."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from augment.memory.consolidation import MemoryConsolidator
from augment.memory.episodic import EpisodicMemory
from augment.memory.procedural import ProceduralMemory
from augment.memory.retrieval import MemoryRetriever
from augment.memory.semantic import SemanticMemory
from augment.memory.working import WorkingMemory


logger = logging.getLogger("augment.memory.system")


class MemorySystem:
    """Aggregates the four memory tiers plus retrieval + consolidation."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)

        self.working = WorkingMemory()
        self.episodic = EpisodicMemory(self._data_dir)
        self.semantic = SemanticMemory(self._data_dir)
        self.procedural = ProceduralMemory(self._data_dir)

        self.consolidator = MemoryConsolidator(
            self.working, self.episodic, self.semantic, self.procedural,
        )
        self.retriever = MemoryRetriever(
            self.working, self.episodic, self.semantic, self.procedural,
        )

        logger.debug(
            "memory system initialised (semantic=%d procedural=%d)",
            len(self.semantic._facts),  # noqa: SLF001
            len(self.procedural._procedures),  # noqa: SLF001
        )

    def context_block(self, query: str = "", *, max_chars: int = 2000) -> str:
        """Combined memory block for prompt injection."""
        parts = []
        wm_block = self.working.as_context_block()
        if wm_block:
            parts.append(wm_block)
        if query:
            remaining = max(0, max_chars - len(wm_block))
            if remaining > 0:
                relevant = self.retriever.context_block_for(query, max_chars=remaining)
                if relevant:
                    parts.append(relevant)
        else:
            ep_block = self.episodic.as_context_block(limit=2)
            if ep_block:
                parts.append(ep_block)
        return "\n\n".join(parts) if parts else ""

    def snapshot(self) -> Dict[str, Any]:
        return {
            "working": {
                "count": len(self.working.all_items()),
                "items": self.working.all_items()[:10],
            },
            "episodic": {
                "count": len(self.episodic.recall(limit=10_000)),
                "recent": self.episodic.recall(limit=10),
            },
            "semantic": {
                "count": len(self.semantic._facts),  # noqa: SLF001
                "facts": self.semantic.all_facts(limit=50),
            },
            "procedural": {
                "count": len(self.procedural._procedures),  # noqa: SLF001
                "procedures": self.procedural.all_procedures(limit=50),
            },
            "last_consolidation": self.consolidator.time_since_last,
        }


# ── Optional module-level singleton (for places that prefer it) ─────
_MEMORY_SYSTEM: Optional[MemorySystem] = None


def init_memory_system(data_dir: Path) -> MemorySystem:
    global _MEMORY_SYSTEM
    _MEMORY_SYSTEM = MemorySystem(data_dir)
    return _MEMORY_SYSTEM


def get_memory_system() -> MemorySystem:
    if _MEMORY_SYSTEM is None:
        raise RuntimeError("MemorySystem not initialised — call init_memory_system() first")
    return _MEMORY_SYSTEM
