from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque


@dataclass
class AgentActivity:
    ts: float
    kind: str
    detail: str


class AgentMonitor:
    def __init__(self, data_dir: Path, *, history_size: int = 32) -> None:
        self._path = data_dir / "agent_profile.json"
        self._activity: Deque[AgentActivity] = deque(maxlen=history_size)
        self._tool_runs = 0
        self._tool_failures = 0
        self._status = "idle"
        self._last_active = 0.0
        self._sessions_started = 0
        self._sessions_resumed = 0

    def profile(self) -> dict[str, Any]:
        custom = self._load()
        capability = self._capability()
        return {
            "name": custom.get("name") or "Augment",
            "role": custom.get("role") or "Single-loop coding assistant",
            "description": custom.get("description") or "",
            "persona": custom.get("persona") or "Direct, evidence-driven engineer who keeps state inside one session.",
            "soul_enabled": bool(custom.get("soul_enabled", True)),
            "status": self._status,
            "last_active": self._last_active,
            "capability": capability,
            "stats": {
                "tool_runs": self._tool_runs,
                "tool_failures": self._tool_failures,
                "sessions_started": self._sessions_started,
                "sessions_resumed": self._sessions_resumed,
            },
            "recent_activity": [activity.__dict__ for activity in list(self._activity)[-12:]],
        }

    def update_profile(self, values: dict[str, Any]) -> dict[str, Any]:
        data = self._load()
        for key in ("name", "role", "description", "persona"):
            if key in values and isinstance(values[key], str):
                data[key] = values[key].strip()
        if "soul_enabled" in values:
            data["soul_enabled"] = bool(values["soul_enabled"])
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return self.profile()

    def mark_status(self, status: str, *, detail: str = "") -> None:
        self._status = status
        self._last_active = time.time()
        self._record("status", f"{status}{(': ' + detail) if detail else ''}")

    def record_tool_run(self, name: str, *, success: bool, duration_ms: float = 0.0) -> None:
        self._tool_runs += 1
        if not success:
            self._tool_failures += 1
        self._record("tool", f"{name} {'ok' if success else 'fail'} {duration_ms:.0f}ms")

    def record_session(self, *, resumed: bool) -> None:
        if resumed:
            self._sessions_resumed += 1
            self._record("session", "resumed")
        else:
            self._sessions_started += 1
            self._record("session", "started")

    def _capability(self) -> dict[str, Any]:
        runs = self._tool_runs
        successes = max(0, runs - self._tool_failures)
        rate = (successes / runs) if runs else 1.0
        score = int(round(rate * 100))
        return {"tool_runs": runs, "success_rate": round(rate, 4), "score": score}

    def _record(self, kind: str, detail: str) -> None:
        self._activity.append(AgentActivity(time.time(), kind, detail))

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
