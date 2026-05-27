"""User model — agent-learned preferences, observations, and explicit style.

Sibling of :class:`augment.sessions.user_model.UserModelStore`; the sessions
version auto-infers from message style/intent, this one captures *explicit*
learnings the agent records via tools or reflection. Labelled
``[USER PROFILE — Learned]`` to distinguish in the system prompt.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List

from augment.kernel.atomic_files import write_text_atomically


logger = logging.getLogger("augment.mind.user_model")

_MAX_PREFERENCES = 50
_MAX_OBSERVATIONS = 100


class UserModel:
    """Tracks explicit user preferences, behavioural observations, and style."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._data_dir / "user_model.json"
        self._preferences: Dict[str, Any] = {}
        self._observations: List[Dict[str, Any]] = []
        self._style: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("user_model load failed: %s", exc)
            return
        if not isinstance(data, dict):
            return
        self._preferences = dict(data.get("preferences") or {})
        self._observations = list(data.get("observations") or [])[-_MAX_OBSERVATIONS:]
        self._style = {str(k): str(v) for k, v in (data.get("style") or {}).items()}

    def save(self) -> None:
        try:
            write_text_atomically(
                self._path,
                json.dumps(
                    {
                        "preferences": self._preferences,
                        "observations": self._observations[-_MAX_OBSERVATIONS:],
                        "style": self._style,
                        "updated_at": time.time(),
                    },
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                ),
            )
        except Exception as exc:
            logger.warning("user_model save failed: %s", exc)

    def set_preference(self, key: str, value: Any) -> None:
        clean = str(key).strip().lower()[:100]
        if not clean:
            return
        self._preferences[clean] = value
        if len(self._preferences) > _MAX_PREFERENCES:
            keep_keys = list(self._preferences.keys())[-_MAX_PREFERENCES:]
            self._preferences = {k: self._preferences[k] for k in keep_keys}
        self.save()

    def get_preference(self, key: str, default: Any = None) -> Any:
        return self._preferences.get(str(key).strip().lower(), default)

    def observe(self, observation: str, category: str = "general") -> None:
        text = str(observation).strip()[:500]
        if not text:
            return
        self._observations.append({
            "ts": time.time(),
            "text": text,
            "category": str(category)[:50],
        })
        if len(self._observations) > _MAX_OBSERVATIONS:
            self._observations = self._observations[-_MAX_OBSERVATIONS:]
        self.save()

    def set_style(self, aspect: str, value: str) -> None:
        clean = str(aspect).strip().lower()[:50]
        if not clean:
            return
        self._style[clean] = str(value).strip()[:200]
        self.save()

    def preferences(self) -> Dict[str, Any]:
        return dict(self._preferences)

    def observations(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        return list(self._observations[-max(1, limit):])

    def style(self) -> Dict[str, str]:
        return dict(self._style)

    def as_context_block(self) -> str:
        parts: List[str] = []
        if self._preferences:
            prefs = [f"  - {k}: {v}" for k, v in list(self._preferences.items())[:10]]
            parts.append("Preferences:\n" + "\n".join(prefs))
        if self._style:
            styles = [f"  - {k}: {v}" for k, v in self._style.items()]
            parts.append("Communication style:\n" + "\n".join(styles))
        if self._observations:
            recent = self._observations[-5:]
            obs = [f"  - {o.get('text', '')}" for o in recent]
            parts.append("Recent observations:\n" + "\n".join(obs))
        if not parts:
            return ""
        return "[USER PROFILE — Learned]\n" + "\n".join(parts)
