"""Knowledge consolidation — promotes memory tiers → durable wiki pages.

Adapted from FAIL's ``server/knowledge/consolidation.py``. Called at
session end (or on demand) to materialise what the agent has learned
into human-readable, searchable wiki articles.

Three page types written:
- ``memory/semantic`` — top facts from semantic memory
- ``memory/procedures`` — learned procedures from procedural memory
- ``memory/episodes`` — recent episodic log entries
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from augment.memory.system import MemorySystem
    from augment.knowledge.wiki import WikiManager

logger = logging.getLogger("augment.knowledge.consolidation")

_MIN_INTERVAL_S = 300.0  # don't run more than once per 5 min


def consolidate_memory_to_wiki(
    memory_system: "MemorySystem",
    *,
    max_semantic_facts: int = 40,
    max_procedures: int = 20,
    max_episodes: int = 30,
) -> dict[str, Any]:
    """Write memory tier snapshots to the wiki.

    Returns a summary dict with counts of pages written.
    """
    wiki: WikiManager = memory_system.wiki
    written = 0

    # ── Semantic facts ────────────────────────────────────────────────
    facts = getattr(memory_system.semantic, "_facts", {}) or {}
    if facts:
        sorted_facts = sorted(
            facts.items(),
            key=lambda kv: (-float(kv[1].get("confidence", 0)), str(kv[0])),
        )[:max_semantic_facts]
        lines = ["# Learned Semantic Memory\n"]
        for key, fact in sorted_facts:
            conf = float(fact.get("confidence", 0))
            cat = fact.get("category", "general")
            val = str(fact.get("value", ""))[:350]
            src = fact.get("source", "")
            lines.append(f"- **{key}** (conf={conf:.2f} cat={cat} src={src}): {val}")
        try:
            wiki.write_page("memory/semantic", "\n".join(lines), source="consolidation")
            written += 1
            logger.debug("wiki: wrote memory/semantic (%d facts)", len(sorted_facts))
        except Exception as exc:
            logger.warning("wiki: semantic page failed: %s", exc)

    # ── Procedural memory ─────────────────────────────────────────────
    procs = getattr(memory_system.procedural, "_procedures", {}) or {}
    if procs:
        sorted_procs = sorted(
            procs.items(),
            key=lambda kv: (-int(kv[1].get("use_count", 0)), str(kv[0])),
        )[:max_procedures]
        parts = ["# Learned Procedures\n"]
        for name, proc in sorted_procs:
            steps = proc.get("steps") or []
            rate = float(proc.get("success_rate", 0))
            uses = int(proc.get("use_count", 0))
            trigger = str(proc.get("trigger", ""))[:200]
            parts.append(f"\n## {name}")
            parts.append(f"- success_rate: {rate:.2f}  use_count: {uses}")
            if trigger:
                parts.append(f"- trigger: {trigger}")
            if steps:
                parts.append("\n".join(f"{i + 1}. {str(s)[:200]}" for i, s in enumerate(steps[:10])))
        try:
            wiki.write_page("memory/procedures", "\n".join(parts), source="consolidation")
            written += 1
            logger.debug("wiki: wrote memory/procedures (%d procs)", len(sorted_procs))
        except Exception as exc:
            logger.warning("wiki: procedures page failed: %s", exc)

    # ── Episodic log ──────────────────────────────────────────────────
    try:
        episodes = memory_system.episodic.recall(limit=max_episodes)
    except Exception:
        episodes = []
    if episodes:
        lines_ep = ["# Episodic Learning Log\n"]
        for ep in episodes:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(ep.get("ts", 0)))
            outcome = ep.get("outcome", "")
            summary = str(ep.get("summary", ""))[:300]
            lines_ep.append(f"- [{ts}] ({outcome}) {summary}")
            for lesson in (ep.get("lessons") or [])[:2]:
                lines_ep.append(f"  → {lesson}")
        try:
            wiki.write_page("memory/episodes", "\n".join(lines_ep), source="consolidation")
            written += 1
            logger.debug("wiki: wrote memory/episodes (%d episodes)", len(episodes))
        except Exception as exc:
            logger.warning("wiki: episodes page failed: %s", exc)

    return {
        "pages_written": written,
        "semantic_facts": len(facts),
        "procedures": len(procs),
        "episodes": len(episodes),
    }
