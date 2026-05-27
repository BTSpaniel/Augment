"""Metacognition — self-monitoring, strategy selection, performance tracking."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List

from augment.kernel.atomic_files import write_text_atomically


logger = logging.getLogger("augment.mind.metacognition")

_MAX_REFLECTIONS = 50


class Metacognition:
    """Self-monitoring and strategy awareness.

    Tracks the current cognitive strategy, per-strategy success/duration metrics,
    and a rolling buffer of self-reflections on what works.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._data_dir / "metacognition.json"
        self._strategy: str = "default"
        self._strategy_scores: Dict[str, Dict[str, float]] = {}
        self._reflections: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("metacognition load failed: %s", exc)
            return
        if not isinstance(data, dict):
            return
        self._strategy = str(data.get("strategy") or "default")
        self._strategy_scores = dict(data.get("strategy_scores") or {})
        self._reflections = list(data.get("reflections") or [])[-_MAX_REFLECTIONS:]

    def save(self) -> None:
        try:
            write_text_atomically(
                self._path,
                json.dumps(
                    {
                        "strategy": self._strategy,
                        "strategy_scores": self._strategy_scores,
                        "reflections": self._reflections[-_MAX_REFLECTIONS:],
                        "updated_at": time.time(),
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
            )
        except Exception as exc:
            logger.warning("metacognition save failed: %s", exc)

    @property
    def current_strategy(self) -> str:
        return self._strategy

    def set_strategy(self, strategy: str, reason: str = "") -> None:
        old = self._strategy
        self._strategy = str(strategy).strip()[:50] or "default"
        if old != self._strategy:
            self.reflect(f"Switched strategy from '{old}' to '{self._strategy}': {reason}")
        self.save()

    def record_outcome(self, strategy: str, success: bool, duration_s: float = 0.0) -> None:
        clean = str(strategy).strip().lower()[:50] or "default"
        scores = self._strategy_scores.setdefault(
            clean, {"attempts": 0, "successes": 0, "avg_duration": 0.0}
        )
        scores["attempts"] = int(scores.get("attempts", 0)) + 1
        if success:
            scores["successes"] = int(scores.get("successes", 0)) + 1
        if duration_s > 0:
            n = scores["attempts"]
            scores["avg_duration"] = (
                (float(scores.get("avg_duration", 0.0)) * (n - 1)) + float(duration_s)
            ) / n
        self.save()

    def success_rate(self, strategy: str) -> float:
        scores = self._strategy_scores.get(str(strategy).strip().lower(), {})
        attempts = int(scores.get("attempts", 0))
        if attempts == 0:
            return 0.5
        return float(scores.get("successes", 0)) / attempts

    def reflect(self, thought: str) -> None:
        text = str(thought).strip()[:500]
        if not text:
            return
        self._reflections.append({"ts": time.time(), "text": text})
        if len(self._reflections) > _MAX_REFLECTIONS:
            self._reflections = self._reflections[-_MAX_REFLECTIONS:]
        self.save()

    def best_strategy_for(self, _task_type: str = "") -> str:
        if not self._strategy_scores:
            return "default"
        best = "default"
        best_rate = 0.0
        for strat in self._strategy_scores:
            rate = self.success_rate(strat)
            if rate > best_rate:
                best_rate = rate
                best = strat
        return best

    def snapshot(self) -> Dict[str, Any]:
        return {
            "strategy": self._strategy,
            "strategy_scores": dict(self._strategy_scores),
            "reflections": list(self._reflections[-10:]),
        }

    def as_context_block(self) -> str:
        parts = [f"Strategy: {self._strategy}"]
        if self._strategy_scores:
            top = sorted(
                self._strategy_scores.items(),
                key=lambda x: int(x[1].get("successes", 0)),
                reverse=True,
            )[:3]
            strat_info = [
                f"  - {s}: {round(self.success_rate(s) * 100)}% ({int(d.get('attempts', 0))} uses)"
                for s, d in top
            ]
            parts.append("Known strategies:\n" + "\n".join(strat_info))
        if self._reflections:
            recent = [r.get("text", "") for r in self._reflections[-2:]]
            parts.append("Recent reflections: " + "; ".join(recent))
        return "[METACOGNITION]\n" + "\n".join(parts)
