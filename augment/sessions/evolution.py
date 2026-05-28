"""Evolution suggestions — behavioral adaptation hints derived from audit + user model.

Reads recent message/tool audit events and the UserModelStore to produce a
[EVOLUTION SUGGESTIONS] block.  Each suggestion carries a confidence score
(1-5) derived from signal frequency.  This block is advisory only — the
agent must not auto-edit its identity or persistent memories from it.

Sections: build_evolution_suggestions_context (main entry), internal helpers.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from augment.audit.ledger import AuditLedger
from augment.sessions.user_model import UserModelStore

# ── Keyword lists ─────────────────────────────────────────────────────

_CORRECTION_TERMS = (
    "wrong", "incorrect", "not right", "actually", "instead",
    "i meant", "try again", "not mathing", "use your tools", "listen", "bruh",
)
_FRUSTRATION_TERMS = (
    "frustrated", "annoying", "broken", "bad", "ugh", "wtf",
    "useless", "confused", "angry",
)
_TOOL_REQUEST_TERMS = (
    "use your tools", "check", "verify", "look", "search", "read", "run", "test",
)
_BREVITY_TERMS = ("shorter", "brief", "tldr", "just the", "quick")
_DEPTH_TERMS = ("detail", "deep", "explain", "why", "how does", "thorough")


# ── Public entry point ────────────────────────────────────────────────

def build_evolution_suggestions_context(
    data_root: str | Path,
    *,
    session_id: str = "",
    query: str = "",
    max_chars: int = 2200,
) -> str:
    """Return an [EVOLUTION SUGGESTIONS] block, or '' if no signals detected."""
    suggestions: List[Dict[str, Any]] = []

    user_model = UserModelStore(Path(data_root)).load()
    try:
        events = AuditLedger(data_root).tail(session_id=session_id, limit=180)
    except Exception:
        events = []

    user_messages: List[str] = []
    tool_failures = 0
    tool_successes = 0
    provider_errors = 0

    for event in events:
        payload: Dict[str, Any] = event.payload or {}
        if event.event_type == "message" and event.actor == "user":
            user_messages.append(str(payload.get("content") or ""))
        elif event.event_type == "tool":
            if event.status == "ok":
                tool_successes += 1
            else:
                tool_failures += 1
        elif event.event_type == "provider_error":
            provider_errors += 1

    all_user_text = "\n".join(user_messages).lower()
    style_votes = dict(user_model.style_votes or {})
    dominant_style = (
        max(style_votes, key=lambda k: int(style_votes.get(k, 0)))
        if style_votes
        else "conversational"
    )
    correction_count = _count_terms(all_user_text, _CORRECTION_TERMS)
    frustration_count = _count_terms(all_user_text, _FRUSTRATION_TERMS)
    tool_request_count = _count_terms(all_user_text, _TOOL_REQUEST_TERMS)
    brevity_count = _count_terms(all_user_text, _BREVITY_TERMS)
    depth_count = _count_terms(all_user_text, _DEPTH_TERMS)
    preferences = dict(user_model.preferences or {})

    if tool_request_count >= 1 or preferences.get("tool_use_when_requested"):
        suggestions.append(_suggestion(
            "tool_backed_directness",
            "User prefers direct/tool-backed answers.",
            "When the user asks to check, verify, inspect, or use tools, "
            "call available tools before asserting facts.",
            tool_request_count + (2 if preferences.get("tool_use_when_requested") else 0),
        ))
    if correction_count >= 1:
        suggestions.append(_suggestion(
            "correction_responsiveness",
            "User corrections should change behavior immediately.",
            "Acknowledge the correction briefly, verify the updated fact/path/state, "
            "and avoid repeating the previous answer pattern.",
            correction_count,
        ))
    if frustration_count >= 1:
        suggestions.append(_suggestion(
            "reduced_filler_under_frustration",
            "Reduce cheerful filler when user is frustrated.",
            "Use calm, concise, action-focused responses; "
            "avoid performative enthusiasm and long preambles.",
            frustration_count,
        ))
    if tool_failures >= 2 or provider_errors >= 1:
        suggestions.append(_suggestion(
            "failure_aware_strategy",
            "Recent execution failures call for strategy changes.",
            "Inspect errors and change approach before retrying; "
            "do not claim completion from failed tools.",
            tool_failures + provider_errors,
        ))
    dominant_style_score = int(style_votes.get(dominant_style, 0))
    if dominant_style in {"terse", "technical"} and dominant_style_score > 0:
        suggestions.append(_suggestion(
            "match_user_style",
            f"User communication style trends {dominant_style}.",
            "Prefer concise technical summaries, explicit file/tool names, "
            "and clear completion status.",
            dominant_style_score,
        ))
    if brevity_count > depth_count and brevity_count >= 1:
        suggestions.append(_suggestion(
            "brevity_preference",
            "User has signaled preference for brevity.",
            "Lead with the answer/status, then only include details needed for the next decision.",
            brevity_count,
        ))
    elif depth_count > brevity_count and depth_count >= 1:
        suggestions.append(_suggestion(
            "depth_preference",
            "User has signaled interest in deeper explanations.",
            "Include concise rationale and implications after the direct answer.",
            depth_count,
        ))
    if tool_successes >= 3 and tool_failures == 0:
        suggestions.append(_suggestion(
            "preserve_tool_workflow",
            "Recent tool-backed workflow is succeeding.",
            "Keep using the inspect → edit → validate pattern and cite validation evidence.",
            tool_successes,
        ))
    if not suggestions:
        return ""

    suggestions.sort(key=lambda item: int(item.get("confidence", 0)), reverse=True)
    lines = [
        "[EVOLUTION SUGGESTIONS]",
        "Safety: suggestions are advisory only. Do not auto-edit personality, "
        "prompts, memories, or identity from this section.",
    ]
    if query:
        lines.append(f"Current objective lens: {_clip(query, 180)}")
    for item in suggestions[:6]:
        lines.append(f"- {item['title']} confidence={item['confidence']}: {item['guidance']}")

    value = "\n".join(lines)
    if len(value) <= max_chars:
        return value
    return value[: max(1, max_chars - 39)].rstrip() + "\n[...truncated evolution suggestions]"


# ── Internal helpers ──────────────────────────────────────────────────

def _suggestion(kind: str, title: str, guidance: str, strength: int) -> Dict[str, Any]:
    confidence = min(5, max(1, int(strength or 1)))
    return {"kind": kind, "title": title, "guidance": guidance, "confidence": confidence}


def _count_terms(text: str, terms: tuple[str, ...]) -> int:
    lowered = str(text or "").lower()
    return sum(lowered.count(term) for term in terms)


def _clip(text: str, limit: int) -> str:
    value = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    return value if len(value) <= limit else value[: max(1, limit - 3)].rstrip() + "..."
