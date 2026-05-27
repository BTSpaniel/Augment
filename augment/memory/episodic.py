"""Episodic memory — records of past sessions and experiences."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


logger = logging.getLogger("augment.memory.episodic")

_MAX_EPISODES = 200


class EpisodicMemory:
    """Stores per-session episodes for later recall.

    Each entry captures what happened, the outcome, the tools used, and any
    lessons distilled. Truncated to the most recent ``_MAX_EPISODES``.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir) / "memory"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._data_dir / "episodic.jsonl"

    def record(
        self,
        *,
        session_id: str = "",
        summary: str = "",
        outcome: str = "success",
        tools_used: Optional[List[str]] = None,
        lessons: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry = {
            "ts": time.time(),
            "session_id": session_id,
            "summary": str(summary).strip()[:500],
            "outcome": outcome,
            "tools_used": (tools_used or [])[:20],
            "lessons": (lessons or [])[:5],
            "metadata": metadata or {},
        }
        try:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._compact()
        except Exception as exc:
            logger.warning("episodic write failed: %s", exc)

    def recall(self, *, limit: int = 10, outcome: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            lines = self._path.read_text(encoding="utf-8").strip().splitlines()
        except Exception:
            return []
        entries: List[Dict[str, Any]] = []
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if outcome and entry.get("outcome") != outcome:
                continue
            entries.append(entry)
            if len(entries) >= limit:
                break
        return entries

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        needle = str(query or "").lower()
        if not needle:
            return []
        results: List[Dict[str, Any]] = []
        for episode in self.recall(limit=50):
            text = f"{episode.get('summary', '')} {' '.join(episode.get('lessons', []))}".lower()
            if needle in text:
                results.append(episode)
        return results[:limit]

    def _compact(self) -> None:
        if not self._path.exists():
            return
        try:
            lines = self._path.read_text(encoding="utf-8").strip().splitlines()
            if len(lines) > _MAX_EPISODES:
                self._path.write_text("\n".join(lines[-_MAX_EPISODES:]) + "\n", encoding="utf-8")
        except Exception:
            pass

    def as_context_block(self, limit: int = 3) -> str:
        episodes = self.recall(limit=limit)
        if not episodes:
            return ""
        lines = ["[EPISODIC MEMORY - Recent Sessions]"]
        for episode in episodes:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(episode.get("ts", 0)))
            summary = (episode.get("summary") or "")[:150]
            outcome = episode.get("outcome") or ""
            lines.append(f"- [{ts}] ({outcome}) {summary}")
            for lesson in (episode.get("lessons") or [])[:2]:
                lines.append(f"    → {lesson}")
        return "\n".join(lines)
