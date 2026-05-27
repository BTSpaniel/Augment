"""Memory tiers — working, episodic, semantic, procedural + retrieval / consolidation.

Ported from FAIL's ``server/memory`` package. The existing legacy
:class:`augment.context.memory.MemoryStore` continues to back the memory tools
for backward compatibility; this package adds the deeper tiered system.
"""
from __future__ import annotations

from augment.memory.consolidation import MemoryConsolidator
from augment.memory.episodic import EpisodicMemory
from augment.memory.procedural import ProceduralMemory
from augment.memory.retrieval import MemoryRetriever
from augment.memory.semantic import SemanticMemory
from augment.memory.system import MemorySystem, get_memory_system, init_memory_system
from augment.memory.working import WorkingMemory

__all__ = [
    "EpisodicMemory",
    "MemoryConsolidator",
    "MemoryRetriever",
    "MemorySystem",
    "ProceduralMemory",
    "SemanticMemory",
    "WorkingMemory",
    "get_memory_system",
    "init_memory_system",
]
