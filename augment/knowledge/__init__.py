"""Knowledge layer — durable structured knowledge base (wiki) and
memory-to-knowledge consolidation.

* :class:`WikiManager` — Markdown wiki with frontmatter, search,
  context_block, health, and index.
* :func:`consolidate_memory_to_wiki` — promotes episodic / semantic /
  procedural memory tiers into wiki pages at session end.
"""
from __future__ import annotations

from augment.knowledge.consolidation import consolidate_memory_to_wiki
from augment.knowledge.wiki import WikiManager, WikiPage

__all__ = [
    "WikiManager",
    "WikiPage",
    "consolidate_memory_to_wiki",
]
