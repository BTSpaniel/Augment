"""Self model — the agent's awareness of its own capabilities and limitations."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List

from augment.kernel.atomic_files import write_text_atomically


logger = logging.getLogger("augment.mind.self_model")

_MAX_LEARNED = 50
_MAX_LIMITATIONS = 20


class SelfModel:
    """Tracks what the agent can do, what it has learned, where it struggles."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._data_dir / "self_model.json"
        self._capabilities: Dict[str, float] = {}
        self._learned: List[Dict[str, Any]] = []
        self._limitations: List[str] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("self_model load failed: %s", exc)
            return
        if not isinstance(data, dict):
            return
        self._capabilities = {
            str(k): float(v) for k, v in (data.get("capabilities") or {}).items()
        }
        self._learned = list(data.get("learned") or [])[-_MAX_LEARNED:]
        self._limitations = list(data.get("limitations") or [])[-_MAX_LIMITATIONS:]

    def save(self) -> None:
        try:
            write_text_atomically(
                self._path,
                json.dumps(
                    {
                        "capabilities": self._capabilities,
                        "learned": self._learned[-_MAX_LEARNED:],
                        "limitations": self._limitations[-_MAX_LIMITATIONS:],
                        "updated_at": time.time(),
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
            )
        except Exception as exc:
            logger.warning("self_model save failed: %s", exc)

    def update_capability(self, skill: str, confidence: float) -> None:
        clean = str(skill).strip().lower()[:100]
        if not clean:
            return
        self._capabilities[clean] = max(0.0, min(1.0, float(confidence)))
        self.save()

    def record_learning(self, what: str, context: str = "") -> None:
        text = str(what).strip()[:300]
        if not text:
            return
        self._learned.append({
            "ts": time.time(),
            "what": text,
            "context": str(context).strip()[:200],
        })
        if len(self._learned) > _MAX_LEARNED:
            self._learned = self._learned[-_MAX_LEARNED:]
        self.save()

    def add_limitation(self, limitation: str) -> None:
        text = str(limitation).strip()[:200]
        if not text or text in self._limitations:
            return
        self._limitations.append(text)
        if len(self._limitations) > _MAX_LIMITATIONS:
            self._limitations = self._limitations[-_MAX_LIMITATIONS:]
        self.save()

    def confidence_for(self, skill: str) -> float:
        return float(self._capabilities.get(str(skill).strip().lower(), 0.5))

    def capabilities(self) -> Dict[str, float]:
        return dict(self._capabilities)

    def learned(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        return list(self._learned[-max(1, limit):])

    def limitations(self) -> List[str]:
        return list(self._limitations)

    def as_context_block(self) -> str:
        parts: List[str] = []
        if self._capabilities:
            strong = [k for k, v in self._capabilities.items() if v >= 0.8]
            weak = [k for k, v in self._capabilities.items() if v < 0.4]
            if strong:
                parts.append(f"Strong at: {', '.join(strong[:8])}")
            if weak:
                parts.append(f"Developing: {', '.join(weak[:5])}")
        if self._learned:
            recent = [item.get("what", "") for item in self._learned[-3:]]
            parts.append("Recently learned: " + "; ".join(recent))
        if self._limitations:
            parts.append(f"Known limits: {'; '.join(self._limitations[-3:])}")
        if not parts:
            return ""
        return "[SELF MODEL]\n" + "\n".join(parts)
