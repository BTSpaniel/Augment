"""Drives — motivation, urgency, and goal-directed energy signals.

Distilled from FAIL's ``server/mind/drives.py``.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


logger = logging.getLogger("augment.mind.drives")


@dataclass
class Drive:
    name: str
    urgency: float = 0.5
    last_satisfied: float = 0.0
    description: str = ""

    def decay(self, rate: float = 0.01) -> None:
        elapsed = time.time() - self.last_satisfied if self.last_satisfied else 0
        if elapsed > 300:
            self.urgency = min(1.0, self.urgency + rate)

    def satisfy(self, amount: float = 0.3) -> None:
        self.urgency = max(0.0, self.urgency - amount)
        self.last_satisfied = time.time()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "urgency": round(self.urgency, 3),
            "last_satisfied": self.last_satisfied,
            "description": self.description,
        }


class DriveSystem:
    """Manages the agent's motivational drives with file-backed persistence."""

    _DEFAULTS = (
        Drive("curiosity", urgency=0.6, description="desire to explore and learn"),
        Drive("helpfulness", urgency=0.7, description="desire to assist the user effectively"),
        Drive("accuracy", urgency=0.5, description="desire to be correct and precise"),
        Drive("creativity", urgency=0.4, description="desire to produce novel solutions"),
        Drive("completion", urgency=0.5, description="desire to finish tasks fully"),
        Drive("efficiency", urgency=0.4, description="desire to minimize waste and round-trips"),
    )

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._data_dir / "drives.json"
        self._drives: Dict[str, Drive] = {
            d.name: Drive(d.name, d.urgency, d.last_satisfied, d.description) for d in self._DEFAULTS
        }
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("drives load failed: %s", exc)
            return
        for entry in (data or {}).get("drives", []):
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "")
            if name in self._drives:
                self._drives[name].urgency = float(entry.get("urgency", 0.5))
                self._drives[name].last_satisfied = float(entry.get("last_satisfied", 0))

    def save(self) -> None:
        data = {
            "drives": [d.as_dict() for d in self._drives.values()],
            "updated_at": time.time(),
        }
        try:
            self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.warning("drives save failed: %s", exc)

    def get(self, name: str) -> Optional[Drive]:
        return self._drives.get(name)

    def satisfy(self, name: str, amount: float = 0.3) -> None:
        drive = self._drives.get(name)
        if drive:
            drive.satisfy(amount)
            self.save()

    def boost(self, name: str, amount: float = 0.2) -> None:
        drive = self._drives.get(name)
        if drive:
            drive.urgency = min(1.0, drive.urgency + amount)
            self.save()

    def decay_all(self) -> None:
        for drive in self._drives.values():
            drive.decay()
        self.save()

    def most_urgent(self) -> Optional[Drive]:
        if not self._drives:
            return None
        return max(self._drives.values(), key=lambda d: d.urgency)

    def as_context_block(self) -> str:
        urgent = sorted(self._drives.values(), key=lambda d: -d.urgency)[:3]
        if not urgent:
            return ""
        lines = ["[DRIVES]"]
        for drive in urgent:
            filled = max(0, min(5, int(round(drive.urgency * 5))))
            bar = "█" * filled + "░" * (5 - filled)
            lines.append(f"  {drive.name}: [{bar}] {drive.description}")
        return "\n".join(lines)

    def snapshot(self) -> Dict[str, Any]:
        return {"drives": [d.as_dict() for d in self._drives.values()]}
