"""Per-session turn state — phase, depth, active topic / entity, correction signals."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from augment.kernel.atomic_files import write_text_atomically


_CORRECTION_PATTERNS = (
    r"\b(?:it'?s|its|it is|year is|current year is|today is|date is)\s+[^.!?]{1,80}",
    r"\b(?:outdated|stale|not current|old info|wrong year|incorrect|not what i meant)\b",
    r"\b20\d{2}\b",
)
_ENTITY_PATTERN = re.compile(
    r"\b(?:location|city|place|project|repo|file|target|topic|scope)\s*(?:is|=|:)\s*([^.!?]{2,160})",
    re.IGNORECASE,
)


@dataclass
class TurnState:
    session_id: str
    phase: str = "new"
    depth: int = 0
    user_turns: int = 0
    assistant_turns: int = 0
    active_topic: str = ""
    active_entity: str = ""
    last_user_message: str = ""
    last_assistant_message: str = ""
    correction_signals: List[str] = field(default_factory=list)
    unresolved_asks: List[str] = field(default_factory=list)
    updated_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TurnStateStore:
    """Per-session JSON turn-state file."""

    def __init__(self, data_dir: Path) -> None:
        self._root = Path(data_dir) / "sessions_depth" / "turn_states"
        self._root.mkdir(parents=True, exist_ok=True)

    def load(self, session_id: str) -> TurnState:
        path = self._path(session_id)
        if not path.exists():
            return TurnState(session_id=session_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return TurnState(session_id=session_id)
        if not isinstance(data, dict):
            return TurnState(session_id=session_id)
        return TurnState(
            session_id=session_id,
            phase=str(data.get("phase") or "new"),
            depth=int(data.get("depth") or 0),
            user_turns=int(data.get("user_turns") or 0),
            assistant_turns=int(data.get("assistant_turns") or 0),
            active_topic=str(data.get("active_topic") or ""),
            active_entity=str(data.get("active_entity") or ""),
            last_user_message=str(data.get("last_user_message") or ""),
            last_assistant_message=str(data.get("last_assistant_message") or ""),
            correction_signals=list(data.get("correction_signals") or []),
            unresolved_asks=list(data.get("unresolved_asks") or []),
            updated_at=float(data.get("updated_at") or 0.0),
        )

    def update(self, session_id: str, *, role: str, content: str) -> TurnState:
        state = self.load(session_id)
        role_value = (role or "").strip().lower()
        text = _clean(content, max_chars=700)
        if role_value == "user":
            state.user_turns += 1
            state.depth += 1
            state.last_user_message = text
            state.phase = "user_turn"
            topic = _infer_topic(text)
            if topic:
                state.active_topic = topic
            entity = _infer_entity(text)
            if entity:
                state.active_entity = entity
            signals = _correction_signals(text)
            if signals:
                state.correction_signals = _dedupe_tail(state.correction_signals + signals, 8)
                state.phase = "correction"
            if text.endswith("?"):
                state.unresolved_asks = _dedupe_tail(state.unresolved_asks + [text], 6)
        elif role_value == "assistant":
            state.assistant_turns += 1
            state.last_assistant_message = text
            state.phase = "assistant_turn"
            if state.unresolved_asks:
                state.unresolved_asks = state.unresolved_asks[-3:]
        state.updated_at = time.time()
        self._save(state)
        return state

    def context_block(self, session_id: str, *, max_chars: int = 2000) -> str:
        state = self.load(session_id)
        if state.depth <= 0 and not state.last_user_message and not state.correction_signals:
            return ""
        lines = [
            "[TURN STATE]",
            f"Phase: {state.phase}",
            f"Depth: {state.depth}",
            f"User turns: {state.user_turns}",
            f"Assistant turns: {state.assistant_turns}",
        ]
        if state.active_topic:
            lines.append(f"Active topic: {state.active_topic}")
        if state.active_entity:
            lines.append(f"Active entity/scope: {state.active_entity}")
        if state.correction_signals:
            lines.append("Correction signals:")
            lines.extend(f"- {item}" for item in state.correction_signals[-6:])
        if state.last_user_message:
            lines.append(f"Last user message: {state.last_user_message[:320]}")
        if state.last_assistant_message:
            lines.append(f"Last assistant message: {state.last_assistant_message[:320]}")
        if state.unresolved_asks:
            lines.append("Recent unresolved asks:")
            lines.extend(f"- {item[:240]}" for item in state.unresolved_asks[-4:])
        value = "\n".join(lines)
        if len(value) <= max_chars:
            return value
        return value[: max(1, max_chars - 35)].rstrip() + "\n[...truncated turn state]"

    def clear(self, session_id: str) -> None:
        path = self._path(session_id)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass

    def _save(self, state: TurnState) -> None:
        write_text_atomically(
            self._path(state.session_id),
            json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
        )

    def _path(self, session_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id or "default") or "default"
        return self._root / f"{safe}.json"


def _clean(value: str, *, max_chars: int) -> str:
    return " ".join(str(value or "").split())[: max_chars]


def _correction_signals(text: str) -> List[str]:
    signals: List[str] = []
    for pattern in _CORRECTION_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            signal = _clean(match.group(0), max_chars=180)
            if signal:
                signals.append(signal)
    return _dedupe_tail(signals, 6)


def _infer_entity(text: str) -> str:
    match = _ENTITY_PATTERN.search(text)
    if match:
        return _clean(match.group(1), max_chars=180)
    if 2 <= len(text) <= 120 and not text.endswith("?"):
        words = text.split()
        if len(words) <= 8 and any(any(ch.isupper() for ch in word) for word in words):
            return _clean(text, max_chars=180)
    return ""


def _infer_topic(text: str) -> str:
    lowered = text.lower()
    if "weather" in lowered:
        return "weather/current data"
    if any(term in lowered for term in ("code", "file", "bug", "test", "implement", "repo", "project")):
        return "coding/project work"
    if len(text) > 12:
        return text[:120]
    return ""


def _dedupe_tail(items: List[str], limit: int) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in items:
        value = _clean(item, max_chars=240)
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out[-limit:]
