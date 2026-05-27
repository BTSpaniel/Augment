"""Unified mind orchestrator — personality, drives, thinking, plus extensions.

Distilled from FAIL's ``server/mind/mind.py``. Extensions ported in Pass 3:
inner monologue, beliefs / world-model, self-model, metacognition, learned
user profile. All persist as small JSON / JSONL files under ``<data>/mind``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from augment.mind.beliefs import Beliefs
from augment.mind.drives import DriveSystem
from augment.mind.metacognition import Metacognition
from augment.mind.monologue import InnerMonologue
from augment.mind.personality import Personality
from augment.mind.self_model import SelfModel
from augment.mind.thinking import BackgroundThinking
from augment.mind.user_model import UserModel


logger = logging.getLogger("augment.mind")


class Mind:
    """Aggregates personality + drives + extensions + thinking."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        mind_dir = self._data_dir / "mind"
        mind_dir.mkdir(parents=True, exist_ok=True)

        self.personality = Personality(mind_dir)
        self.drives = DriveSystem(mind_dir)
        self.thinking = BackgroundThinking()
        # Pass-3 extensions.
        self.monologue = InnerMonologue(mind_dir)
        self.beliefs = Beliefs(mind_dir)
        self.self_model = SelfModel(mind_dir)
        self.metacognition = Metacognition(mind_dir)
        self.user_profile = UserModel(mind_dir)

    # ── Events ───────────────────────────────────────────────────────
    def on_event(self, event_type: str, detail: str = "") -> None:
        """Propagate an event to personality + drive responses."""
        self.personality.on_event(event_type, detail)
        if event_type == "task_success":
            self.drives.satisfy("completion", 0.3)
            self.drives.satisfy("helpfulness", 0.2)
        elif event_type == "task_failure":
            self.drives.boost("accuracy", 0.15)
        elif event_type == "creative_output":
            self.drives.satisfy("creativity", 0.3)
        elif event_type == "new_session":
            self.drives.boost("curiosity", 0.1)
        elif event_type == "user_frustration":
            self.drives.boost("helpfulness", 0.15)

    # ── Context injection ────────────────────────────────────────────
    def context_block(self, *, max_chars: int = 1200) -> str:
        """Combined personality + drives block suitable for system-prompt injection."""
        parts = []
        for block in (
            self.personality.as_context_block(),
            self.drives.as_context_block(),
            self.metacognition.as_context_block(),
            self.self_model.as_context_block(),
            self.beliefs.as_context_block(),
            self.user_profile.as_context_block(),
            self.monologue.as_context_block(),
        ):
            if block:
                parts.append(block)
        value = "\n\n".join(parts)
        if len(value) <= max_chars:
            return value
        return value[: max(0, max_chars - 24)].rstrip() + "\n[...truncated mind block]"

    # ── Status / API surface ─────────────────────────────────────────
    def snapshot(self) -> Dict[str, Any]:
        return {
            "personality": self.personality.snapshot(),
            "drives": self.drives.snapshot(),
            "thinking": self.thinking.status(),
            "monologue": {"recent": self.monologue.recent(limit=5)},
            "beliefs": {
                "beliefs": self.beliefs.all_beliefs(),
                "world": self.beliefs.world_facts(limit=10),
            },
            "self_model": {
                "capabilities": self.self_model.capabilities(),
                "learned": self.self_model.learned(limit=10),
                "limitations": self.self_model.limitations(),
            },
            "metacognition": self.metacognition.snapshot(),
            "user_profile": {
                "preferences": self.user_profile.preferences(),
                "style": self.user_profile.style(),
                "observations": self.user_profile.observations(limit=10),
            },
        }

    def decay(self) -> None:
        """Gentle decay step — useful to wire to a timer or to call between sessions."""
        self.personality.mood.decay()
        self.personality.save()
        self.drives.decay_all()


# ── Module-level singleton (optional helpers) ────────────────────────
_MIND: Optional[Mind] = None


def init_mind(data_dir: Path) -> Mind:
    global _MIND
    _MIND = Mind(data_dir)
    return _MIND


def get_mind() -> Mind:
    if _MIND is None:
        raise RuntimeError("Mind not initialised — call init_mind() first")
    return _MIND
