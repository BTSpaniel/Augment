"""Learning signals — surface corrections, praise and tool stats from audit events.

Reads recent message + tool events from AuditLedger and builds a
[LEARNING SIGNALS] prompt block that nudges the agent to adapt its
behaviour mid-session based on user feedback patterns.

Sections: build_learning_signals_context (main entry), internal helpers.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from augment.audit.ledger import AuditLedger

# ── Keyword lists ─────────────────────────────────────────────────────

_CORRECTION_TERMS = (
    "wrong", "incorrect", "not right", "actually", "instead",
    "i meant", "try again", "not mathing", "use your tools",
    "listen", "bruh",
)
_PRAISE_TERMS = (
    "thanks", "thank you", "great", "perfect", "awesome",
    "nice", "good job", "works", "exactly",
)
_URGENCY_TERMS = (
    "urgent", "asap", "quick", "now", "hurry", "immediately",
)
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "what", "how",
    "can", "you", "are", "was", "were", "have", "has", "from",
    "into", "about", "then", "than",
}


# ── Public entry point ────────────────────────────────────────────────

def build_learning_signals_context(
    data_root: str | Path,
    *,
    session_id: str = "",
    query: str = "",
    max_chars: int = 2200,
) -> str:
    """Return a [LEARNING SIGNALS] block for the system prompt, or '' if empty."""
    try:
        events = AuditLedger(data_root).tail(session_id=session_id, limit=140)
    except Exception:
        return ""
    if not events:
        return ""

    query_terms = _semantic_terms(query)
    corrections: List[tuple[int, int, str]] = []
    praise: List[tuple[int, int, str]] = []
    urgent: List[tuple[int, int, str]] = []
    tool_success: Dict[str, int] = {}
    tool_failure: Dict[str, int] = {}
    provider_errors = 0
    stopped_reasons: Dict[str, int] = {}

    for recency, event in enumerate(events):
        payload: Dict[str, Any] = event.payload or {}
        if event.event_type == "message" and event.actor == "user":
            text = str(payload.get("content") or "")
            lowered = text.lower()
            score = _semantic_score(text, query_terms)
            if any(term in lowered for term in _CORRECTION_TERMS):
                corrections.append((score, recency, _clip(text, 180)))
            if any(term in lowered for term in _PRAISE_TERMS):
                praise.append((score, recency, _clip(text, 180)))
            if any(term in lowered for term in _URGENCY_TERMS):
                urgent.append((score, recency, _clip(text, 180)))
        elif event.event_type == "tool":
            tool = str(payload.get("tool") or "tool")
            if event.status == "ok":
                tool_success[tool] = tool_success.get(tool, 0) + 1
            else:
                tool_failure[tool] = tool_failure.get(tool, 0) + 1
        elif event.event_type == "provider_error":
            provider_errors += 1
        elif event.event_type == "message" and event.actor == "assistant":
            reason = str(event.status or "")
            if reason:
                stopped_reasons[reason] = stopped_reasons.get(reason, 0) + 1

    if not any((corrections, praise, urgent, tool_success, tool_failure, provider_errors, stopped_reasons)):
        return ""

    lines = [
        "[LEARNING SIGNALS]",
        "Purpose: use recent outcomes to adapt behavior in this session; "
        "do not rewrite identity or claim permanent learning unless explicitly saved.",
    ]
    if query_terms:
        lines.append("Semantic focus: " + ", ".join(query_terms[:8]))
    if corrections:
        lines.append(f"Recent correction signals: {len(corrections)}")
        lines.extend(f"- {item}" for item in _ranked_text(corrections, limit=4))
        lines.append(
            "Adaptation: slow down, verify with tools where applicable, "
            "and explicitly avoid repeating the corrected mistake."
        )
    if praise:
        lines.append(f"Recent positive feedback signals: {len(praise)}")
        lines.extend(f"- {item}" for item in _ranked_text(praise, limit=3))
        lines.append("Adaptation: preserve the response style/approach that produced positive feedback.")
    if urgent:
        lines.append(f"Recent urgency signals: {len(urgent)}")
        lines.extend(f"- {item}" for item in _ranked_text(urgent, limit=3))
        lines.append(
            "Adaptation: prioritize concise action, current state, and clear next step over broad explanation."
        )
    if tool_failure:
        lines.append("Tools with recent failures:")
        lines.extend(
            f"- {tool}: {count}"
            for tool, count in sorted(tool_failure.items(), key=lambda x: (-x[1], x[0]))[:6]
        )
        lines.append("Adaptation: if retrying a failed tool, change strategy or inspect the error first.")
    if tool_success:
        lines.append("Tools with recent successful evidence:")
        lines.extend(
            f"- {tool}: {count}"
            for tool, count in sorted(tool_success.items(), key=lambda x: (-x[1], x[0]))[:6]
        )
    if provider_errors:
        lines.append(
            f"Provider errors observed: {provider_errors}; "
            "adapt by using simpler tool calls and shorter structured requests."
        )
    if stopped_reasons:
        lines.append("Recent assistant stop reasons:")
        lines.extend(
            f"- {reason}: {count}"
            for reason, count in sorted(stopped_reasons.items(), key=lambda x: (-x[1], x[0]))[:5]
        )

    value = "\n".join(lines)
    if len(value) <= max_chars:
        return value
    return value[: max(1, max_chars - 36)].rstrip() + "\n[...truncated learning signals]"


# ── Internal helpers ──────────────────────────────────────────────────

def _clip(text: str, limit: int) -> str:
    value = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    return value if len(value) <= limit else value[: max(1, limit - 3)].rstrip() + "..."


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


def _ranked_text(items: List[tuple[int, int, str]], *, limit: int) -> List[str]:
    ranked = sorted(items, key=lambda item: (item[0], item[1]), reverse=True)
    return [text for _, _, text in ranked[:limit]]
