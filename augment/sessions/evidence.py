"""Evidence context — build a [EVIDENCE / BELIEF STATE] prompt block from audit events.

Reads recent tool events from the AuditLedger and categorises them as
VERIFIED (ok), mutation evidence, or FAILED.  Surfaces the ranked list to
the model so it can ground assertions in actual tool observations rather
than assumptions.

Sections: build_evidence_context (main entry), internal helpers.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

from augment.audit.ledger import AuditLedger

# ── Constants ─────────────────────────────────────────────────────────

_READ_EVIDENCE_TOOLS = {
    "read_file", "list_dir", "search_files", "search_code",
    "git_status", "git_diff", "git_log", "tool_status", "get_current_datetime",
}
_MUTATION_HINTS = {
    "write", "edit", "patch", "delete", "remove", "create",
    "run", "execute", "apply", "register", "update",
}
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "what", "how",
    "can", "you", "are", "was", "were", "have", "has", "from",
    "into", "about", "then", "than",
}


# ── Public entry point ────────────────────────────────────────────────

def build_evidence_context(
    data_root: str | Path,
    *,
    session_id: str = "",
    query: str = "",
    max_chars: int = 2600,
) -> str:
    """Return a [EVIDENCE / BELIEF STATE] block for the system prompt, or '' if empty."""
    try:
        events = AuditLedger(data_root).tail(session_id=session_id, limit=120)
    except Exception:
        return ""
    tool_events = [ev for ev in events if ev.event_type == "tool"]
    if not tool_events:
        return ""

    query_terms = _semantic_terms(query)
    verified: List[tuple[int, int, str]] = []
    failed: List[tuple[int, int, str]] = []
    mutation_evidence: List[tuple[int, int, str]] = []
    assumptions: List[str] = []
    seen: set = set()

    for recency, event in enumerate(tool_events[-40:]):
        payload: Dict[str, Any] = event.payload or {}
        tool = str(payload.get("tool") or "tool")
        status = str(event.status or "unknown")
        output = _compact(payload.get("output") or "")
        error = _compact(payload.get("error") or "")
        age = _age_label(float(event.ts or 0))
        key = (tool, status, output[:120], error[:120])
        if key in seen:
            continue
        seen.add(key)
        score = _semantic_score(f"{tool} {status} {output} {error}", query_terms)
        if status == "ok":
            line = f"- VERIFIED via {tool} ({age}): {output or 'tool completed successfully'}"
            if _looks_mutating(tool):
                mutation_evidence.append((score, recency, line))
            else:
                verified.append((score, recency, line))
        else:
            failed.append((
                score, recency,
                f"- FAILED via {tool} ({age}): {error or output or 'no error text recorded'}",
            ))

    if failed and mutation_evidence:
        assumptions.append(
            "- Some mutation-adjacent actions have nearby failures; "
            "verify final state before claiming completion."
        )
    if not verified and not mutation_evidence and not failed:
        return ""

    lines = [
        "[EVIDENCE / BELIEF STATE]",
        "Trust policy: tool-backed observations are stronger than assumptions; "
        "failed tools are evidence of non-completion, not success.",
    ]
    if query_terms:
        lines.append("Semantic focus: " + ", ".join(query_terms[:8]))
    if verified:
        lines.append("Verified observations:")
        lines.extend(_ranked_lines(verified, limit=8))
    if mutation_evidence:
        lines.append("Mutation/action evidence:")
        lines.extend(_ranked_lines(mutation_evidence, limit=6))
    if failed:
        lines.append("Known failed/uncertain observations:")
        lines.extend(_ranked_lines(failed, limit=6))
    if assumptions:
        lines.append("Assumption warnings:")
        lines.extend(assumptions)
    lines.append(
        "Guidance: when asked whether work is done, cite the relevant verified evidence "
        "or say what still needs verification."
    )

    value = "\n".join(lines)
    if len(value) <= max_chars:
        return value
    return value[: max(1, max_chars - 35)].rstrip() + "\n[...truncated evidence context]"


# ── Internal helpers ──────────────────────────────────────────────────

def _compact(value: Any, *, limit: int = 260) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: max(1, limit - 3)].rstrip() + "..."


def _semantic_terms(query: str) -> List[str]:
    terms: List[str] = []
    for raw in str(query or "").lower().replace("_", " ").replace("-", " ").split():
        term = "".join(ch for ch in raw if ch.isalnum())
        if len(term) >= 3 and term not in _STOPWORDS and term not in terms:
            terms.append(term)
    return terms


def _semantic_score(text: str, query_terms: List[str]) -> int:
    if not query_terms:
        return 0
    lowered = str(text or "").lower()
    score = 0
    for term in query_terms:
        if term in lowered:
            score += 3
        if any(
            part.startswith(term[:5])
            for part in lowered.replace("/", " ").replace("\\", " ").split()
            if len(term) >= 5
        ):
            score += 1
    return score


def _ranked_lines(items: List[tuple[int, int, str]], *, limit: int) -> List[str]:
    ranked = sorted(items, key=lambda item: (item[0], item[1]), reverse=True)
    return [line for _, _, line in ranked[:limit]]


def _looks_mutating(tool: str) -> bool:
    lowered = tool.lower()
    if lowered in _READ_EVIDENCE_TOOLS:
        return False
    return any(hint in lowered for hint in _MUTATION_HINTS)


def _age_label(ts: float) -> str:
    if ts <= 0:
        return "unknown age"
    seconds = max(0, int(time.time() - ts))
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"
