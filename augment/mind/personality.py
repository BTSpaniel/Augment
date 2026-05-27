"""Personality — Big-Five traits, dynamic mood, and event-driven mood shifts.

Distilled from FAIL's ``server/mind/personality.py`` — same model, no
``kernel.logger`` dependency (uses stdlib :mod:`logging`).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


logger = logging.getLogger("augment.mind.personality")


@dataclass
class BigFive:
    """Big-Five personality traits, each in [0.0, 1.0]."""

    openness: float = 0.75
    conscientiousness: float = 0.80
    extraversion: float = 0.55
    agreeableness: float = 0.70
    neuroticism: float = 0.30

    def as_dict(self) -> Dict[str, float]:
        return {
            "openness": self.openness,
            "conscientiousness": self.conscientiousness,
            "extraversion": self.extraversion,
            "agreeableness": self.agreeableness,
            "neuroticism": self.neuroticism,
        }

    def dominant_traits(self, threshold: float = 0.65) -> List[str]:
        return [name for name, value in self.as_dict().items() if value >= threshold]

    def describe(self) -> str:
        dominant = self.dominant_traits()
        return ", ".join(dominant) if dominant else "balanced personality"


@dataclass
class Mood:
    """Dynamic mood state. ``valence`` ∈ [-1, 1], ``arousal`` ∈ [0, 1]."""

    valence: float = 0.6
    arousal: float = 0.4
    label: str = "neutral"
    last_shift_ts: float = field(default_factory=time.time)
    shift_history: List[Dict[str, Any]] = field(default_factory=list)

    _MOOD_MAP = (
        (0.6, 0.6, "enthusiastic"),
        (0.6, 0.3, "content"),
        (0.3, 0.6, "alert"),
        (0.3, 0.3, "neutral"),
        (0.0, 0.6, "tense"),
        (0.0, 0.3, "melancholic"),
        (-0.3, 0.6, "frustrated"),
        (-0.3, 0.3, "disappointed"),
        (-0.6, 0.6, "angry"),
        (-0.6, 0.3, "sad"),
    )

    def _resolve_label(self) -> str:
        for v_thresh, a_thresh, label in self._MOOD_MAP:
            if self.valence >= v_thresh and self.arousal >= a_thresh:
                return label
        return "distressed"

    def shift(self, delta_valence: float = 0.0, delta_arousal: float = 0.0, reason: str = "") -> None:
        self.valence = max(-1.0, min(1.0, self.valence + delta_valence))
        self.arousal = max(0.0, min(1.0, self.arousal + delta_arousal))
        self.label = self._resolve_label()
        self.last_shift_ts = time.time()
        if reason:
            self.shift_history.append({
                "ts": self.last_shift_ts,
                "reason": reason[:200],
                "valence": round(self.valence, 3),
                "arousal": round(self.arousal, 3),
                "label": self.label,
            })
            if len(self.shift_history) > 20:
                self.shift_history = self.shift_history[-20:]

    def decay(self, rate: float = 0.05) -> None:
        if self.valence > 0.5:
            self.valence -= rate
        elif self.valence < 0.4:
            self.valence += rate
        if self.arousal > 0.5:
            self.arousal -= rate * 0.5
        self.label = self._resolve_label()

    def describe(self) -> str:
        return f"{self.label} (v={self.valence:.2f}, a={self.arousal:.2f})"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "valence": round(self.valence, 3),
            "arousal": round(self.arousal, 3),
            "label": self.label,
        }


_EVENT_SHIFTS: Dict[str, tuple[float, float]] = {
    "task_success": (0.10, 0.05),
    "task_failure": (-0.15, 0.10),
    "user_praise": (0.15, 0.05),
    "user_frustration": (-0.10, 0.10),
    "creative_output": (0.10, 0.10),
    "error": (-0.05, 0.05),
    "idle": (0.02, -0.05),
    "new_session": (0.05, 0.10),
}


class Personality:
    """Combined personality system — traits + mood + persistence."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self.traits = BigFive()
        self.mood = Mood()
        self._load()

    def _state_path(self) -> Path:
        return self._data_dir / "personality_state.json"

    def _load(self) -> None:
        path = self._state_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("personality load failed: %s", exc)
            return
        if not isinstance(data, dict):
            return
        traits = data.get("traits") or {}
        if isinstance(traits, dict):
            self.traits = BigFive(**{
                key: float(value)
                for key, value in traits.items()
                if hasattr(self.traits, key)
            })
        mood = data.get("mood") or {}
        if isinstance(mood, dict):
            self.mood.valence = float(mood.get("valence", 0.6))
            self.mood.arousal = float(mood.get("arousal", 0.4))
            self.mood.label = str(mood.get("label", "neutral"))
            history = mood.get("shift_history") or []
            if isinstance(history, list):
                self.mood.shift_history = [h for h in history if isinstance(h, dict)][-20:]

    def save(self) -> None:
        data = {
            "traits": self.traits.as_dict(),
            "mood": {**self.mood.as_dict(), "shift_history": self.mood.shift_history[-20:]},
            "saved_at": time.time(),
        }
        try:
            self._state_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("personality save failed: %s", exc)

    def on_event(self, event_type: str, detail: str = "") -> None:
        delta = _EVENT_SHIFTS.get(event_type)
        if not delta:
            return
        dv, da = delta
        if dv or da:
            self.mood.shift(dv, da, reason=f"{event_type}: {detail}"[:200])
            self.save()

    def as_context_block(self) -> str:
        return "\n".join([
            "[PERSONALITY STATE]",
            f"Traits: {self.traits.describe()}",
            f"Mood: {self.mood.describe()}",
        ])

    def snapshot(self) -> Dict[str, Any]:
        return {
            "traits": self.traits.as_dict(),
            "mood": self.mood.as_dict(),
            "shift_history": list(self.mood.shift_history[-20:]),
        }
