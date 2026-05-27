"""Session scratchboard — extract durable hints from user messages.

Sync slim port of FAIL's ``server/sessions/scratchboard.py``. Drops the
async event-store + prompt_config plumbing; persists state as a single
JSON file per session under ``data/sessions_depth/scratchboards/``.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from augment.kernel.atomic_files import write_text_atomically


_SEMANTIC_EXTRACTORS = (
    {
        "category": "memory_instruction",
        "patterns": (
            r"\b(?:remember|note)\s+(?:that\s+)?([^.!?]{4,180})",
            r"\b(?:use|prefer)\s+([^.!?]{4,180})",
        ),
        "prefix": "User preference or durable instruction: ",
        "confidence": 0.85,
    },
    {
        "category": "entity_or_scope_clue",
        "patterns": (
            r"\b(?:i\s+am|i'm|im)\s+(?:in|at|from|near)\s+([^.!?]{2,120})",
            r"\b(?:location|city|place|project|repo|file|target|topic|scope)\s*(?:is|=|:)\s*([^.!?]{2,160})",
        ),
        "prefix": "Entity/scope clue: ",
        "confidence": 0.75,
    },
    {
        "category": "date_or_staleness_correction",
        "patterns": (
            r"\b(?:it'?s|its|it is|year is|current year is|today is|date is)\s+([^.!?]{2,80})",
            r"\b(?:outdated|stale|not current|old info|wrong year)\b[^.!?]{0,160}",
            r"\b20\d{2}\b",
        ),
        "prefix": "Date/currentness correction: ",
        "confidence": 0.9,
    },
)
_SHORT_FOLLOWUP = {
    "category": "short_followup_clue",
    "prefix": "Short follow-up clue: ",
    "confidence": 0.55,
    "min_chars": 2,
    "max_chars": 220,
}


@dataclass
class ScratchboardFact:
    text: str
    display: str
    category: str = "general"
    confidence: float = 0.5
    source: str = "semantic_extractor"
    pattern: str = ""
    first_seen: float = 0.0
    last_seen: float = 0.0
    count: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScratchboardState:
    session_id: str
    facts: List[ScratchboardFact] = field(default_factory=list)
    last_user_message: str = ""
    last_assistant_message: str = ""
    updated_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "facts": [fact.to_dict() for fact in self.facts],
            "last_user_message": self.last_user_message,
            "last_assistant_message": self.last_assistant_message,
            "updated_at": self.updated_at,
        }


class ScratchboardStore:
    """One JSON file per session, holding extracted facts + last messages."""

    def __init__(self, data_dir: Path) -> None:
        self._root = Path(data_dir) / "sessions_depth" / "scratchboards"
        self._root.mkdir(parents=True, exist_ok=True)

    def load(self, session_id: str) -> ScratchboardState:
        path = self._path(session_id)
        if not path.exists():
            return ScratchboardState(session_id=session_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return ScratchboardState(session_id=session_id)
        return _state_from_dict(session_id, data if isinstance(data, dict) else {})

    def update(self, session_id: str, *, role: str, content: str) -> ScratchboardState:
        if not session_id:
            return ScratchboardState(session_id="")
        state = self.load(session_id)
        role_value = (role or "").strip().lower()
        text = _clean(content, max_chars=500)
        if role_value == "user":
            records = _extract_facts(content)
            state.last_user_message = text
            _merge_facts(state, records)
        elif role_value == "assistant":
            state.last_assistant_message = text
        state.updated_at = time.time()
        self._save(state)
        return state

    def context_block(self, session_id: str, *, max_chars: int = 3000) -> str:
        if not session_id:
            return ""
        state = self.load(session_id)
        if not state.facts and not state.last_user_message and not state.last_assistant_message:
            return ""
        lines = ["[SESSION SCRATCHBOARD]"]
        if state.facts:
            lines.append("Durable/recent facts:")
            for fact in state.facts[-12:]:
                meta = (
                    f"category={fact.category} confidence={fact.confidence:.2f} "
                    f"source={fact.source} count={fact.count}"
                )
                lines.append(f"- {fact.display} ({meta})")
        if state.last_user_message:
            lines.append(f"Last user message: {state.last_user_message}")
        if state.last_assistant_message:
            lines.append(f"Last assistant reply: {state.last_assistant_message}")
        value = "\n".join(lines)
        if len(value) <= max_chars:
            return value
        return value[: max(1, max_chars - 36)].rstrip() + "\n[...truncated session scratchboard]"

    def clear(self, session_id: str) -> None:
        path = self._path(session_id)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass

    def _save(self, state: ScratchboardState) -> None:
        write_text_atomically(
            self._path(state.session_id),
            json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
        )

    def _path(self, session_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id or "default") or "default"
        return self._root / f"{safe}.json"


# ── Helpers ──────────────────────────────────────────────────────────


def _clean(value: str, *, max_chars: int = 700) -> str:
    return " ".join(str(value or "").split())[: max_chars]


def _extract_facts(content: str) -> List[ScratchboardFact]:
    text = _clean(content)
    if not text:
        return []
    now = time.time()
    facts: List[ScratchboardFact] = []
    seen: set[str] = set()
    for extractor in _SEMANTIC_EXTRACTORS:
        category = extractor["category"]
        prefix = extractor["prefix"]
        confidence = float(extractor["confidence"])
        for pattern in extractor["patterns"]:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                fact_text = _clean(match.group(0), max_chars=240)
                key = f"{category}:{fact_text}".lower()
                if len(fact_text) >= 4 and key not in seen:
                    seen.add(key)
                    facts.append(
                        ScratchboardFact(
                            text=fact_text,
                            display=f"{prefix}{fact_text}",
                            category=category,
                            confidence=confidence,
                            pattern=pattern,
                            first_seen=now,
                            last_seen=now,
                        )
                    )
    # Short-followup catch-all.
    if _SHORT_FOLLOWUP["min_chars"] <= len(text) <= _SHORT_FOLLOWUP["max_chars"]:
        key = f"{_SHORT_FOLLOWUP['category']}:{text}".lower()
        if key not in seen:
            facts.append(
                ScratchboardFact(
                    text=text,
                    display=f"{_SHORT_FOLLOWUP['prefix']}{text}",
                    category=_SHORT_FOLLOWUP["category"],
                    confidence=float(_SHORT_FOLLOWUP["confidence"]),
                    first_seen=now,
                    last_seen=now,
                )
            )
    return facts[:8]


def _merge_facts(state: ScratchboardState, records: List[ScratchboardFact]) -> None:
    existing = {f"{fact.category}:{fact.text}".lower(): fact for fact in state.facts}
    for record in records:
        key = f"{record.category}:{record.text}".lower()
        current = existing.get(key)
        if current:
            current.last_seen = record.last_seen
            current.count += 1
            current.confidence = max(current.confidence, record.confidence)
        else:
            state.facts.append(record)
            existing[key] = record
    state.facts = state.facts[-80:]


def _state_from_dict(session_id: str, data: Dict[str, Any]) -> ScratchboardState:
    facts: List[ScratchboardFact] = []
    for raw in data.get("facts") or []:
        if not isinstance(raw, dict):
            continue
        facts.append(
            ScratchboardFact(
                text=str(raw.get("text") or ""),
                display=str(raw.get("display") or raw.get("text") or ""),
                category=str(raw.get("category") or "general"),
                confidence=float(raw.get("confidence") or 0.5),
                source=str(raw.get("source") or "semantic_extractor"),
                pattern=str(raw.get("pattern") or ""),
                first_seen=float(raw.get("first_seen") or 0.0),
                last_seen=float(raw.get("last_seen") or 0.0),
                count=int(raw.get("count") or 1),
            )
        )
    return ScratchboardState(
        session_id=session_id,
        facts=facts,
        last_user_message=str(data.get("last_user_message") or ""),
        last_assistant_message=str(data.get("last_assistant_message") or ""),
        updated_at=float(data.get("updated_at") or 0.0),
    )
