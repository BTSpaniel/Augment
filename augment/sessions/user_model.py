"""User model — observe communication style, intent, expertise, preferences.

Sync port of FAIL's ``server/sessions/user_model.py`` using the local atomic
file writer. State lives at ``<data_dir>/sessions_depth/user_model.json``.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

from augment.kernel.atomic_files import write_text_atomically


_QUESTION_RE = re.compile(
    r"\b(what|how|why|when|where|who|which|can you|could you|do you|is it|are there)\b|\?",
    re.IGNORECASE,
)
_COMMAND_RE = re.compile(
    r"^(please |can you |could you )?"
    r"(write|create|make|build|generate|fix|update|change|add|remove|delete|"
    r"run|execute|search|find|show|list|tell me|explain|summarize|continue|check)",
    re.IGNORECASE,
)
_CORRECTION_RE = re.compile(
    r"\b(no,|wrong|incorrect|that's not right|you said|actually|instead|i meant|not what i wanted|try again)\b",
    re.IGNORECASE,
)
_POSITIVE_RE = re.compile(
    r"\b(thanks|thank you|great|perfect|awesome|love it|nice|good job|exactly|works)\b",
    re.IGNORECASE,
)
_NEGATIVE_RE = re.compile(
    r"\b(ugh|bad|terrible|awful|wrong|broken|failed|doesn't work|frustrated|confused|angry|useless)\b",
    re.IGNORECASE,
)
_TECHNICAL_RE = re.compile(
    r"\b(function|class|module|import|async|await|api|endpoint|database|algorithm|"
    r"refactor|debug|stack trace|exception|git|commit|merge|docker|config|context|"
    r"memory|agent|tool)\b",
    re.IGNORECASE,
)


@dataclass
class UserModelState:
    total_turns: int = 0
    style_votes: Dict[str, int] = field(
        default_factory=lambda: {"terse": 0, "conversational": 0, "technical": 0, "verbose": 0}
    )
    expertise: Dict[str, float] = field(default_factory=dict)
    intent_counts: Dict[str, int] = field(default_factory=dict)
    recent_intents: List[Dict[str, Any]] = field(default_factory=list)
    recent_emotions: List[Dict[str, Any]] = field(default_factory=list)
    preferences: Dict[str, Any] = field(default_factory=dict)
    updated_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class UserModelStore:
    def __init__(self, data_dir: Path) -> None:
        self._root = Path(data_dir) / "sessions_depth"
        self._path = self._root / "user_model.json"

    def load(self) -> UserModelState:
        if not self._path.exists():
            return UserModelState()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return UserModelState()
        if not isinstance(data, dict):
            return UserModelState()
        return UserModelState(
            total_turns=int(data.get("total_turns") or 0),
            style_votes={**UserModelState().style_votes, **dict(data.get("style_votes") or {})},
            expertise=dict(data.get("expertise") or {}),
            intent_counts=dict(data.get("intent_counts") or {}),
            recent_intents=list(data.get("recent_intents") or [])[-20:],
            recent_emotions=list(data.get("recent_emotions") or [])[-12:],
            preferences=dict(data.get("preferences") or {}),
            updated_at=float(data.get("updated_at") or 0.0),
        )

    def save(self, state: UserModelState) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        write_text_atomically(
            self._path,
            json.dumps(state.to_dict(), indent=2, ensure_ascii=False, default=str),
        )

    def observe(self, message: str, *, session_id: str = "") -> Dict[str, Any]:
        state = self.load()
        text = str(message or "")
        intent = _classify_intent(text)
        style = _infer_style(text)
        topic = _classify_topic(text)
        urgency = _classify_urgency(text)
        valence, arousal = _classify_emotion(text)
        state.total_turns += 1
        state.style_votes[style] = int(state.style_votes.get(style, 0)) + 1
        state.intent_counts[intent] = int(state.intent_counts.get(intent, 0)) + 1
        if topic == "programming":
            state.expertise["programming"] = min(
                1.0, float(state.expertise.get("programming", 0.35)) + 0.02
            )
        _extract_preferences(text, state.preferences)
        now = time.time()
        event = {
            "session_id": session_id,
            "intent": intent,
            "topic": topic,
            "urgency": urgency,
            "style": style,
            "ts": now,
        }
        state.recent_intents = [*state.recent_intents, event][-20:]
        state.recent_emotions = [
            *state.recent_emotions,
            {"valence": valence, "arousal": arousal, "ts": now},
        ][-12:]
        state.updated_at = now
        self.save(state)
        return {
            "intent": intent,
            "topic": topic,
            "urgency": urgency,
            "style": style,
            "valence": valence,
            "arousal": arousal,
        }

    def context_block(self, *, max_chars: int = 1800) -> str:
        state = self.load()
        if state.total_turns <= 0:
            return ""
        dominant_style = max(state.style_votes, key=lambda key: int(state.style_votes.get(key, 0)))
        programming_score = float(state.expertise.get("programming", 0.35))
        expertise = (
            "expert" if programming_score >= 0.7
            else "intermediate" if programming_score >= 0.4
            else "novice"
        )
        recent = state.recent_intents[-1] if state.recent_intents else {}
        avg_valence = sum(float(item.get("valence") or 0) for item in state.recent_emotions) / max(
            1, len(state.recent_emotions)
        )
        avg_arousal = sum(float(item.get("arousal") or 0) for item in state.recent_emotions) / max(
            1, len(state.recent_emotions)
        )
        lines = [
            "[USER MODEL]",
            f"Observed turns: {state.total_turns}",
            f"Dominant communication style: {dominant_style}",
            f"Programming expertise estimate: {expertise}",
        ]
        if recent:
            lines.append(
                f"Current inferred intent: {recent.get('intent', 'unknown')} · "
                f"topic={recent.get('topic', 'general')} · "
                f"urgency={float(recent.get('urgency') or 0):.2f}"
            )
        if avg_valence < -0.25:
            lines.append(
                "Recent emotional signal: frustrated/negative; be direct, careful, and "
                "avoid repeating failed answers."
            )
        elif avg_valence > 0.3:
            lines.append("Recent emotional signal: positive/engaged.")
        if avg_arousal > 0.5:
            lines.append("Recent arousal signal: high; prioritize concise action and clear next steps.")
        if state.preferences:
            pref_items = [f"{k}={v}" for k, v in sorted(state.preferences.items())[:6]]
            lines.append("Known preferences: " + ", ".join(pref_items))
        value = "\n".join(lines)
        if len(value) <= max_chars:
            return value
        return value[: max(1, max_chars - 34)].rstrip() + "\n[...truncated user model]"


def _classify_intent(message: str) -> str:
    if _CORRECTION_RE.search(message):
        return "correction"
    if _POSITIVE_RE.search(message):
        return "praise"
    if _COMMAND_RE.search(message):
        return "command"
    if _QUESTION_RE.search(message):
        return "question"
    if len(message.split()) < 5:
        return "chitchat"
    return "statement"


def _classify_topic(message: str) -> str:
    lowered = message.lower()
    if any(word in lowered for word in ("code", "function", "class", "bug", "error", "python", "script", "context", "agent", "tool", "memory")):
        return "programming"
    if any(word in lowered for word in ("file", "folder", "directory", "path", "read", "write")):
        return "files"
    if any(word in lowered for word in ("search", "find", "look up", "browse", "web", "online")):
        return "search"
    if any(word in lowered for word in ("remember", "recall", "know", "fact", "wiki")):
        return "memory"
    return "general"


def _classify_urgency(message: str) -> float:
    lowered = message.lower()
    score = 0.25
    if any(word in lowered for word in ("urgent", "asap", "immediately", "now", "quick", "hurry", "listen")):
        score += 0.35
    if _CORRECTION_RE.search(message) or "use your tools" in lowered:
        score += 0.25
    if "!" in message:
        score += 0.15
    return min(1.0, score)


def _classify_emotion(message: str) -> Tuple[float, float]:
    positive = len(_POSITIVE_RE.findall(message))
    negative = len(_NEGATIVE_RE.findall(message))
    valence = (positive - negative) / max(1, positive + negative + 1)
    arousal = min(
        1.0,
        (message.count("!") + message.count("?")) * 0.2 + (0.35 if negative > 0 else 0.0),
    )
    return valence, arousal


def _infer_style(message: str) -> str:
    words = len(message.split())
    if _TECHNICAL_RE.search(message):
        return "technical"
    if words < 15 and not _QUESTION_RE.search(message):
        return "terse"
    if words > 60:
        return "verbose"
    return "conversational"


def _extract_preferences(message: str, preferences: Dict[str, Any]) -> None:
    lowered = message.lower()
    if any(term in lowered for term in ("shorter", "brief", "tldr", "just the")):
        preferences["response_length"] = "brief"
    if any(term in lowered for term in ("detail", "deep", "explain more", "thorough")):
        preferences["response_length"] = "detailed"
    if "use your tools" in lowered:
        preferences["tool_use_when_requested"] = True
    if any(term in lowered for term in ("no emojis", "stop emojis")):
        preferences["emoji_style"] = "avoid"
