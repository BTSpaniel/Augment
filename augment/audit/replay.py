"""Audit replay — build structured replay views from ledger events.

Sections: build_audit_replay (main entry point), _summarize,
_causal_chains, _timeline_groups.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from augment.audit.ledger import AuditLedger


def build_audit_replay(
    data_root: str | Path,
    *,
    session_id: str = "",
    correlation_id: str = "",
    limit: int = 200,
) -> Dict[str, Any]:
    """Return a structured replay dict for a session or correlation chain."""
    ledger = AuditLedger(data_root)
    events = (
        ledger.trace(correlation_id, session_id=session_id, limit=limit)
        if correlation_id
        else ledger.tail(session_id=session_id, limit=limit)
    )
    ordered = sorted(events, key=lambda ev: ev.ts)
    return {
        "session_id": session_id,
        "correlation_id": correlation_id,
        "event_count": len(ordered),
        "events": [ev.to_dict() for ev in ordered],
        "causal_chains": _causal_chains(ordered),
        "timeline_groups": _timeline_groups(ordered),
        "summary": _summarize(ordered),
    }


# ── Internal helpers ──────────────────────────────────────────────────

def _summarize(events: list) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    statuses: Dict[str, int] = {}
    for ev in events:
        counts[ev.event_type] = counts.get(ev.event_type, 0) + 1
        if ev.status:
            statuses[ev.status] = statuses.get(ev.status, 0) + 1
    return {"types": counts, "statuses": statuses}


def _causal_chains(events: list) -> List[Dict[str, Any]]:
    children: Dict[str, List[Any]] = {}
    for ev in events:
        parent = getattr(ev, "parent_correlation_id", "")
        if parent:
            children.setdefault(parent, []).append(ev)
    roots = [ev for ev in events if ev.correlation_id and not getattr(ev, "parent_correlation_id", "")]
    if not roots:
        roots = [ev for ev in events if ev.correlation_id]
    chains = []
    for root in roots[:40]:
        chain: List[Dict[str, Any]] = []
        stack = [root]
        seen: set = set()
        while stack:
            current = stack.pop(0)
            cid = current.correlation_id
            if cid in seen:
                continue
            seen.add(cid)
            chain.append({
                "event_id": current.event_id,
                "correlation_id": cid,
                "type": current.event_type,
                "status": current.status,
                "source": current.source,
            })
            stack.extend(children.get(cid, []))
        chains.append({"root": root.correlation_id, "events": chain})
    return chains


def _timeline_groups(events: list) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for ev in events:
        key = ev.correlation_id or "uncorrelated"
        groups.setdefault(key, []).append({
            "ts": ev.ts,
            "event_id": ev.event_id,
            "type": ev.event_type,
            "source": ev.source,
            "status": ev.status,
            "parent_correlation_id": getattr(ev, "parent_correlation_id", ""),
        })
    return groups
