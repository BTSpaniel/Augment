"""Follow-up context — wrap short user messages with recent history for resolution.

When the user sends a very short message (≤5 words / ≤40 chars), fragments
like "do it again", "try python", or "what about X?" don't carry enough
context on their own.  This module prepends a compact history window so
the model can resolve the pronoun or fragment correctly.

Sections: build_followup_context (main entry).
No audit dependency — self-contained.
"""
from __future__ import annotations

from typing import Dict, List

# ── Defaults ──────────────────────────────────────────────────────────

_MAX_SHORT_MESSAGE_CHARS = 40
_MAX_SHORT_MESSAGE_WORDS = 5
_RECENT_HISTORY_LIMIT = 8
_RECENT_MESSAGE_CHARS = 260

_HEADER = "[FOLLOW-UP CONTEXT]"
_INSTRUCTION = (
    "The current user message is short and may refine the recent conversation. "
    "Resolve fragments against the recent messages before asking for clarification. "
    "If the topic is a current-data lookup and the user provides a partial context, "
    "combine it with known prior context and answer directly when specific enough."
)
_CURRENT_HEADER = "[CURRENT USER MESSAGE]"


# ── Public entry point ────────────────────────────────────────────────

def build_followup_context(
    message: str,
    history: List[Dict[str, str]],
    scratchboard_context: str = "",
) -> str:
    """Return an enriched message string when the original is a short fragment.

    If the message is long enough to be self-contained, returns it unchanged.
    Otherwise, prepends the [FOLLOW-UP CONTEXT] header + recent history turns
    so the model can resolve the fragment.
    """
    text = str(message or "").strip()
    words = [w for w in text.replace(",", " ").split() if w]
    # Return unchanged if the message is long enough to be self-contained
    if (
        len(text) > _MAX_SHORT_MESSAGE_CHARS
        or len(words) > _MAX_SHORT_MESSAGE_WORDS
        or (not history and not scratchboard_context)
    ):
        return message

    recent: List[str] = []
    for item in history[-_RECENT_HISTORY_LIMIT:]:
        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            recent.append(f"{role}: {content[:_RECENT_MESSAGE_CHARS]}")

    if not recent and not scratchboard_context:
        return message

    parts = [f"{_HEADER}\n{_INSTRUCTION}"]
    if scratchboard_context:
        parts.append(scratchboard_context)
    if recent:
        parts.append("\n".join(recent))
    parts.append(f"\n{_CURRENT_HEADER}\n{text}")
    return "\n".join(parts)
