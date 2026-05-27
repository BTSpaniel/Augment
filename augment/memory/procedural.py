"""Procedural memory — learned step-by-step approaches that have worked."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


logger = logging.getLogger("augment.memory.procedural")

_MAX_PROCEDURES = 100


class ProceduralMemory:
    """Stores named procedures (step sequences) with running success scores."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir) / "memory"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._data_dir / "procedural.json"
        self._procedures: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("procedural load failed: %s", exc)
            return
        if isinstance(data, dict):
            procs = data.get("procedures") or {}
            if isinstance(procs, dict):
                self._procedures = {str(k): dict(v) for k, v in procs.items() if isinstance(v, dict)}

    def save(self) -> None:
        data = {
            "procedures": self._procedures,
            "updated_at": time.time(),
            "count": len(self._procedures),
        }
        try:
            self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.warning("procedural save failed: %s", exc)

    def learn(
        self,
        name: str,
        *,
        steps: List[str],
        trigger: str = "",
        success_rate: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        clean_name = str(name).strip().lower()[:100]
        clean_steps = [str(s)[:200] for s in (steps or [])[:20] if str(s or "").strip()]
        if not clean_name or not clean_steps:
            return
        existing = self._procedures.get(clean_name)
        if existing:
            old_rate = float(existing.get("success_rate", 0.5))
            existing["success_rate"] = (old_rate + max(0.0, min(1.0, float(success_rate)))) / 2
            existing["use_count"] = int(existing.get("use_count", 0)) + 1
            existing["updated_at"] = time.time()
        else:
            self._procedures[clean_name] = {
                "steps": clean_steps,
                "trigger": str(trigger)[:200],
                "success_rate": max(0.0, min(1.0, float(success_rate))),
                "use_count": 1,
                "created_at": time.time(),
                "updated_at": time.time(),
                "metadata": metadata or {},
            }
        if len(self._procedures) > _MAX_PROCEDURES:
            self._evict()
        self.save()

    def recall(self, name: str) -> Optional[Dict[str, Any]]:
        entry = self._procedures.get(str(name).strip().lower())
        if entry is None:
            return None
        entry["use_count"] = int(entry.get("use_count", 0)) + 1
        return dict(entry)

    def find_for_trigger(self, trigger: str) -> List[Dict[str, Any]]:
        needle = str(trigger or "").lower()
        if not needle:
            return []
        results: List[Dict[str, Any]] = []
        for name, proc in self._procedures.items():
            text = f"{name} {proc.get('trigger', '')}".lower()
            if needle in text:
                results.append({"name": name, **proc})
        results.sort(key=lambda x: -float(x.get("success_rate", 0)))
        return results[:5]

    def all_procedures(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        results = [{"name": k, **v} for k, v in self._procedures.items()]
        results.sort(key=lambda x: -int(x.get("use_count", 0)))
        return results[: max(1, limit)]

    def remove(self, name: str) -> bool:
        clean = str(name).strip().lower()
        if clean in self._procedures:
            del self._procedures[clean]
            self.save()
            return True
        return False

    def _evict(self) -> None:
        if len(self._procedures) <= _MAX_PROCEDURES:
            return
        scored = sorted(
            self._procedures.items(),
            key=lambda kv: float(kv[1].get("success_rate", 0)) * int(kv[1].get("use_count", 1)),
        )
        remove_count = len(self._procedures) - _MAX_PROCEDURES
        for key, _ in scored[:remove_count]:
            del self._procedures[key]

    def as_context_block(self, trigger: Optional[str] = None) -> str:
        if trigger:
            procs = self.find_for_trigger(trigger)
        else:
            procs = sorted(
                ({"name": k, **v} for k, v in self._procedures.items()),
                key=lambda x: -int(x.get("use_count", 0)),
            )[:5]
        if not procs:
            return ""
        lines = ["[PROCEDURAL MEMORY - Known Approaches]"]
        for proc in procs:
            steps_str = " → ".join((proc.get("steps") or [])[:5])
            lines.append(f"- {proc.get('name', '?')}: {steps_str}")
        return "\n".join(lines)
