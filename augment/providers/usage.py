"""Provider-level usage tally — rolling per-profile token counts + per-tool stats.

Sections: ProviderUsage, ToolUsage dataclasses, UsageTracker (record/
snapshot/reset), module-level init_usage_tracker / get_usage_tracker.

Persisted to data/usage/stats.json.  Thread-safe.  No external deps beyond stdlib.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


# ── Dataclasses ───────────────────────────────────────────────────────

@dataclass
class ProviderUsage:
    """Per-provider-profile accumulated token and call counts."""

    profile_id: str
    role: str = ""
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    last_ts: float = 0.0
    last_model: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class ToolUsage:
    """Per-tool accumulated call and timing stats."""

    tool_name: str
    calls: int = 0
    success: int = 0
    failed: int = 0
    timeout: int = 0
    total_elapsed_ms: float = 0.0
    last_ts: float = 0.0


# ── UsageTracker ──────────────────────────────────────────────────────

class UsageTracker:
    """Thread-safe in-process usage accumulator with JSON persistence."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._lock = threading.RLock()
        self._by_profile: Dict[str, ProviderUsage] = {}
        self._by_tool: Dict[str, ToolUsage] = {}
        self._path = Path(path).resolve() if path else None
        self._load()

    # -- Persistence -----------------------------------------------------

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        providers = payload.get("providers") or {}
        tools = payload.get("tools") or {}
        if isinstance(providers, dict):
            for pid, raw in providers.items():
                item = dict(raw or {})
                self._by_profile[str(pid)] = ProviderUsage(
                    profile_id=str(item.get("profile_id") or pid),
                    role=str(item.get("role") or ""),
                    calls=int(item.get("calls") or 0),
                    prompt_tokens=int(item.get("prompt_tokens") or 0),
                    completion_tokens=int(item.get("completion_tokens") or 0),
                    last_ts=float(item.get("last_ts") or 0.0),
                    last_model=str(item.get("last_model") or ""),
                )
        if isinstance(tools, dict):
            for name, raw in tools.items():
                item = dict(raw or {})
                self._by_tool[str(name)] = ToolUsage(
                    tool_name=str(item.get("tool_name") or name),
                    calls=int(item.get("calls") or 0),
                    success=int(item.get("success") or 0),
                    failed=int(item.get("failed") or 0),
                    timeout=int(item.get("timeout") or 0),
                    total_elapsed_ms=float(item.get("total_elapsed_ms") or 0.0),
                    last_ts=float(item.get("last_ts") or 0.0),
                )

    def _save(self) -> None:
        if self._path is None:
            return
        snapshot = self.snapshot()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(snapshot, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception:
            pass

    # -- Record ----------------------------------------------------------

    def record(
        self,
        *,
        profile_id: str,
        role: str,
        prompt: int,
        completion: int,
        model: str = "",
    ) -> None:
        """Accumulate one provider call's token usage."""
        with self._lock:
            entry = self._by_profile.setdefault(profile_id, ProviderUsage(profile_id=profile_id))
            entry.role = role or entry.role
            entry.calls += 1
            entry.prompt_tokens += max(0, int(prompt or 0))
            entry.completion_tokens += max(0, int(completion or 0))
            entry.last_ts = time.time()
            entry.last_model = model or entry.last_model
        self._save()

    def record_tool_call(
        self,
        *,
        tool_name: str,
        success: bool,
        elapsed_ms: float = 0.0,
        timed_out: bool = False,
    ) -> None:
        """Accumulate one tool execution."""
        with self._lock:
            entry = self._by_tool.setdefault(tool_name, ToolUsage(tool_name=tool_name))
            entry.calls += 1
            entry.total_elapsed_ms += max(0.0, float(elapsed_ms or 0.0))
            entry.last_ts = time.time()
            if timed_out:
                entry.timeout += 1
            elif success:
                entry.success += 1
            else:
                entry.failed += 1
        self._save()

    # -- Read ------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a serialisable summary of all accumulated usage."""
        with self._lock:
            providers = {
                pid: {
                    "profile_id": e.profile_id,
                    "role": e.role,
                    "calls": e.calls,
                    "prompt_tokens": e.prompt_tokens,
                    "completion_tokens": e.completion_tokens,
                    "total_tokens": e.total_tokens,
                    "last_ts": e.last_ts,
                    "last_model": e.last_model,
                }
                for pid, e in self._by_profile.items()
            }
            tools = {
                name: {
                    "tool_name": e.tool_name,
                    "calls": e.calls,
                    "success": e.success,
                    "failed": e.failed,
                    "timeout": e.timeout,
                    "success_rate": round(e.success / max(1, e.calls), 3),
                    "total_elapsed_ms": round(e.total_elapsed_ms, 1),
                    "avg_elapsed_ms": round(e.total_elapsed_ms / max(1, e.calls), 1),
                    "last_ts": e.last_ts,
                }
                for name, e in self._by_tool.items()
            }
            total_calls = sum(int(v["calls"] or 0) for v in providers.values())
            total_prompt = sum(int(v["prompt_tokens"] or 0) for v in providers.values())
            total_comp = sum(int(v["completion_tokens"] or 0) for v in providers.values())
            total_tool = sum(int(v["calls"] or 0) for v in tools.values())
            return {
                "providers": providers,
                "tools": tools,
                "totals": {
                    "provider_profiles": len(providers),
                    "provider_calls": total_calls,
                    "prompt_tokens": total_prompt,
                    "completion_tokens": total_comp,
                    "total_tokens": total_prompt + total_comp,
                    "tool_calls": total_tool,
                },
            }

    def reset(self) -> None:
        """Clear all accumulated stats and persist the empty state."""
        with self._lock:
            self._by_profile.clear()
            self._by_tool.clear()
        self._save()


# ── Module-level singleton ────────────────────────────────────────────

_tracker: Optional[UsageTracker] = None


def init_usage_tracker(data_root: Path | str | None = None) -> UsageTracker:
    """Initialise (or re-initialise) the global tracker.  Call once at startup."""
    global _tracker
    path: Optional[Path] = None
    if data_root:
        path = Path(data_root).resolve() / "usage" / "stats.json"
    _tracker = UsageTracker(path=path)
    return _tracker


def get_usage_tracker() -> UsageTracker:
    """Return the global tracker, creating an in-memory one if not initialised."""
    global _tracker
    if _tracker is None:
        _tracker = UsageTracker()
    return _tracker
