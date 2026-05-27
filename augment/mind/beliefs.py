"""Beliefs + World Model — what the agent believes about the world."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List

from augment.kernel.atomic_files import write_text_atomically


logger = logging.getLogger("augment.mind.beliefs")

_MAX_BELIEFS = 60
_MAX_WORLD_FACTS = 40


class Beliefs:
    """Tracks current beliefs and world model facts."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._data_dir / "beliefs.json"
        self._beliefs: Dict[str, Dict[str, Any]] = {}
        self._world: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("beliefs load failed: %s", exc)
            return
        if not isinstance(data, dict):
            return
        self._beliefs = dict(data.get("beliefs") or {})
        self._world = list(data.get("world") or [])[-_MAX_WORLD_FACTS:]

    def save(self) -> None:
        try:
            write_text_atomically(
                self._path,
                json.dumps(
                    {
                        "beliefs": self._beliefs,
                        "world": self._world[-_MAX_WORLD_FACTS:],
                        "updated_at": time.time(),
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
            )
        except Exception as exc:
            logger.warning("beliefs save failed: %s", exc)

    def believe(self, key: str, value: Any, confidence: float = 0.8) -> None:
        clean_key = str(key).strip().lower()[:100]
        if not clean_key:
            return
        self._beliefs[clean_key] = {
            "value": value,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "updated_at": time.time(),
        }
        if len(self._beliefs) > _MAX_BELIEFS:
            sorted_keys = sorted(
                self._beliefs, key=lambda k: float(self._beliefs[k].get("confidence", 0))
            )
            for k in sorted_keys[: len(self._beliefs) - _MAX_BELIEFS]:
                del self._beliefs[k]
        self.save()

    def get_belief(self, key: str) -> Any:
        entry = self._beliefs.get(str(key).strip().lower())
        return entry.get("value") if entry else None

    def belief_confidence(self, key: str) -> float:
        entry = self._beliefs.get(str(key).strip().lower())
        return float(entry.get("confidence", 0.0)) if entry else 0.0

    def add_world_fact(self, fact: str, source: str = "") -> None:
        text = str(fact or "").strip()[:300]
        if not text:
            return
        self._world.append({
            "fact": text,
            "source": str(source)[:100],
            "ts": time.time(),
        })
        if len(self._world) > _MAX_WORLD_FACTS:
            self._world = self._world[-_MAX_WORLD_FACTS:]
        self.save()

    def all_beliefs(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._beliefs)

    def world_facts(self, *, limit: int = 40) -> List[Dict[str, Any]]:
        return list(self._world[-max(1, limit):])

    def as_context_block(self) -> str:
        parts: List[str] = []
        if self._beliefs:
            high_conf = [
                (k, v) for k, v in self._beliefs.items() if float(v.get("confidence", 0)) >= 0.7
            ]
            if high_conf:
                belief_lines = [f"  - {k}: {v['value']}" for k, v in high_conf[:8]]
                parts.append("Beliefs:\n" + "\n".join(belief_lines))
        if self._world:
            recent_facts = [f"  - {w['fact']}" for w in self._world[-5:]]
            parts.append("World facts:\n" + "\n".join(recent_facts))
        if not parts:
            return ""
        return "[BELIEFS & WORLD MODEL]\n" + "\n".join(parts)
