"""Audit ledger — structured JSONL event log with per-session and global files.

Sections: AuditEvent dataclass, AuditLedger (append/tail/trace),
module-level helpers, internal correlation_id generator.

Events are written to:
  data/audit/<session_id>.jsonl  — per-session stream
  data/audit/global.jsonl        — global stream (all events)

Secret payloads are sanitized before writing via _sanitize_payload.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from augment.security.redaction import redact

# ── Module-level write lock ────────────────────────────────────────────
_LOCK = threading.RLock()

# Keys that indicate a value should be redacted before writing to audit
_SECRET_KEYS = ("key", "secret", "token", "password", "authorization", "cookie", "credential")


# ── Dataclasses ───────────────────────────────────────────────────────

@dataclass
class AuditEvent:
    """Single audit event written as one JSON line."""

    event_id: str
    event_type: str
    actor: str = "system"
    session_id: str = ""
    correlation_id: str = ""
    parent_correlation_id: str = ""
    source: str = ""
    status: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict suitable for JSON encoding."""
        return asdict(self)


# ── AuditLedger ───────────────────────────────────────────────────────

class AuditLedger:
    """Append-only JSONL ledger.  One file per session + one global file."""

    def __init__(self, data_root: str | Path) -> None:
        self._root = Path(data_root) / "audit"
        self._root.mkdir(parents=True, exist_ok=True)

    # -- Write -----------------------------------------------------------

    def append(
        self,
        event_type: str,
        *,
        actor: str = "system",
        session_id: str = "",
        correlation_id: str = "",
        parent_correlation_id: str = "",
        source: str = "",
        status: str = "",
        payload: Dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Write one event and return it.  Thread-safe."""
        safe_payload = _sanitize_payload(payload or {})
        cid = _build_correlation_id(
            event_type,
            source=source,
            session_id=session_id,
            correlation_id=correlation_id,
            payload=safe_payload,
        )
        event = AuditEvent(
            event_id=f"audit_{uuid.uuid4().hex[:12]}",
            event_type=str(event_type or "event"),
            actor=str(actor or "system"),
            session_id=str(session_id or ""),
            correlation_id=cid,
            parent_correlation_id=str(
                parent_correlation_id
                or safe_payload.get("parent_correlation_id")
                or safe_payload.get("parent_cid")
                or ""
            ),
            source=str(source or ""),
            status=str(status or ""),
            payload={**safe_payload, "correlation_id": cid},
            ts=time.time(),
        )
        line = json.dumps(event.to_dict(), ensure_ascii=False, default=str)
        with _LOCK:
            with self._path(session_id).open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            with self._path("global").open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return event

    # -- Read ------------------------------------------------------------

    def tail(self, *, session_id: str = "", limit: int = 100) -> List[AuditEvent]:
        """Return the last *limit* events for session_id (or global)."""
        path = self._path(session_id or "global")
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-max(1, int(limit)):]
        events: List[AuditEvent] = []
        for line in lines:
            try:
                data = json.loads(line)
                events.append(_event_from_dict(data))
            except Exception:
                continue
        return events

    def trace(self, correlation_id: str, *, session_id: str = "", limit: int = 200) -> List[AuditEvent]:
        """Return all events matching correlation_id or having it as parent."""
        target = str(correlation_id or "")
        if not target:
            return []
        return [
            ev for ev in self.tail(session_id=session_id, limit=limit)
            if ev.correlation_id == target or ev.parent_correlation_id == target
        ]

    # -- Internals -------------------------------------------------------

    def _path(self, session_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(session_id or "global")) or "global"
        return self._root / f"{safe}.jsonl"


# ── Module helpers ────────────────────────────────────────────────────

def append_audit_event(
    data_root: str | Path,
    event_type: str,
    **kwargs: Any,
) -> AuditEvent:
    """Convenience: create a ledger and append one event."""
    return AuditLedger(data_root).append(event_type, **kwargs)


# ── Internal helpers ──────────────────────────────────────────────────

def _event_from_dict(data: Dict[str, Any]) -> AuditEvent:
    return AuditEvent(
        event_id=str(data.get("event_id") or ""),
        event_type=str(data.get("event_type") or "event"),
        actor=str(data.get("actor") or "system"),
        session_id=str(data.get("session_id") or ""),
        correlation_id=str(data.get("correlation_id") or ""),
        parent_correlation_id=str(
            data.get("parent_correlation_id")
            or (data.get("payload") or {}).get("parent_correlation_id")
            or ""
        ),
        source=str(data.get("source") or ""),
        status=str(data.get("status") or ""),
        payload=dict(data.get("payload") or {}),
        ts=float(data.get("ts") or 0.0),
    )


def _build_correlation_id(
    event_type: str,
    *,
    source: str = "",
    session_id: str = "",
    correlation_id: str = "",
    payload: Dict[str, Any] | None = None,
) -> str:
    payload = payload or {}
    explicit = (
        correlation_id
        or payload.get("correlation_id")
        or payload.get("request_id")
        or payload.get("run_id")
    )
    if explicit:
        return str(explicit)
    prefix = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(source or event_type or "audit")).strip("_") or "audit"
    session = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(session_id or "global")).strip("_") or "global"
    return f"{prefix}_{session}_{uuid.uuid4().hex[:8]}"


def _sanitize_payload(value: Any, *, max_string: int = 4000) -> Any:
    """Recursively redact secrets and truncate long strings."""
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            lowered = str(k).lower()
            if any(term in lowered for term in _SECRET_KEYS):
                out[str(k)] = "[redacted]"
            else:
                out[str(k)] = _sanitize_payload(v, max_string=max_string)
        return out
    if isinstance(value, list):
        return [_sanitize_payload(item, max_string=max_string) for item in value[:100]]
    if isinstance(value, tuple):
        return [_sanitize_payload(item, max_string=max_string) for item in list(value)[:100]]
    if isinstance(value, str):
        return redact(value[:max_string], redact_ips=True)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact(str(value)[:max_string], redact_ips=True)
