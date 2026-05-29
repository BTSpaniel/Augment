"""Conversation-history context-rot defense for the ReAct loop.

Augment's loop feeds the last N turns of history straight into the model.
When a session degenerates (the user re-sends the same request and a weak
model echoes the same deflection), that raw history poisons every later
turn: the model pattern-matches its own repetition and keeps looping.

This module is the single defense ported from Blackboard's
``blackboard/coding/context_rot.py`` and FAIL's ``server/agent/context_rot.py``,
adapted to operate on Augment's plain ``{"role", "content"}`` history dicts.

Sections (in order):
  1. Report / config dataclasses.
  2. ContextRotDetector — scores redundancy + staleness, flags repeated turns.
  3. ContextCompressor — dedups and compacts older near-duplicate turns.
  4. detect_stuck_loop — emits a forceful "stop deflecting, execute" directive
     when the most recent assistant turns are near-identical.

Load-bearing: the loop-breaker directive string is asserted by
``tests/test_context_rot.py`` — keep ``STUCK_LOOP_DIRECTIVE`` in sync.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── 1. Report / config ──────────────────────────────────────────────


@dataclass(frozen=True)
class ContextRotReport:
    """Outcome of one rot check over a history window."""

    health: str
    redundancy: float
    staleness: float
    repeated_indices: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly view for diagnostics."""
        return {
            "health": self.health,
            "redundancy": round(self.redundancy, 3),
            "staleness": round(self.staleness, 3),
            "repeated_indices": list(self.repeated_indices),
        }


@dataclass(frozen=True)
class ContextRotConfig:
    """Tunables for detection and compaction."""

    recent_turns_full: int = 6
    long_turn_chars: int = 1600
    compact_cap_chars: int = 600
    redundancy_overlap: float = 0.55
    stuck_overlap: float = 0.8
    stuck_min_repeats: int = 2


# ── helpers ─────────────────────────────────────────────────────────


def _normalize(content: Any) -> str:
    """Lowercase + whitespace-collapse a message body for comparison.

    Multipart (vision) content is reduced to its text fragments so a
    history dict with image parts still compares sanely.
    """
    if isinstance(content, list):
        parts = [str(part.get("text") or "") for part in content if isinstance(part, dict)]
        content = " ".join(parts)
    return " ".join(str(content or "").lower().split())


def _word_overlap(left: str, right: str) -> float:
    """Jaccard overlap of the word sets of two normalized strings."""
    left_words = set(left.split())
    right_words = set(right.split())
    if not left_words or not right_words:
        return 0.0
    return len(left_words & right_words) / max(len(left_words | right_words), 1)


# ── 2. Detector ─────────────────────────────────────────────────────


class ContextRotDetector:
    """Score a history window for redundancy + staleness."""

    def __init__(self, config: Optional[ContextRotConfig] = None) -> None:
        self._config = config or ContextRotConfig()

    def check(self, messages: List[Dict[str, Any]]) -> ContextRotReport:
        """Return a :class:`ContextRotReport` for *messages*.

        ``messages`` is a list of ``{"role", "content"}`` dicts. System
        turns are ignored. Health is ``critical`` / ``degrading`` /
        ``healthy`` based on the redundancy and staleness scores.
        """
        redundancy = self._redundancy(messages)
        staleness = self._staleness(messages)
        repeated = self._repeated_indices(messages)
        if redundancy > 0.7 or staleness > 0.7:
            health = "critical"
        elif redundancy > 0.4 or staleness > 0.4:
            health = "degrading"
        else:
            health = "healthy"
        return ContextRotReport(health, redundancy, staleness, repeated)

    def _redundancy(self, messages: List[Dict[str, Any]]) -> float:
        """Fraction of near-neighbor turn pairs that overlap heavily."""
        fingerprints = [
            _normalize(item.get("content"))[:240]
            for item in messages
            if str(item.get("role") or "") != "system" and _normalize(item.get("content"))
        ]
        if len(fingerprints) < 4:
            return 0.0
        overlaps = 0
        comparisons = 0
        for index, left in enumerate(fingerprints):
            for right in fingerprints[index + 1:index + 5]:
                comparisons += 1
                if _word_overlap(left, right) > self._config.redundancy_overlap:
                    overlaps += 1
        return overlaps / max(comparisons, 1)

    def _staleness(self, messages: List[Dict[str, Any]]) -> float:
        """Heuristic share of bulky/low-signal turns plus a length factor."""
        stale = 0.0
        total = 0
        for item in messages:
            if str(item.get("role") or "") == "system":
                continue
            content = str(item.get("content") or "")
            if not content:
                continue
            total += 1
            if len(content) > self._config.long_turn_chars:
                stale += 0.35
        if total <= 0:
            return 0.0
        length_factor = min(1.0, len(messages) / 40)
        return min(1.0, stale / total * 0.75 + length_factor * 0.25)

    def _repeated_indices(self, messages: List[Dict[str, Any]]) -> List[int]:
        """Indices of older turns whose normalized body already appeared."""
        repeated: List[int] = []
        seen: Dict[str, int] = {}
        for index, item in enumerate(messages):
            content = _normalize(item.get("content"))[:180]
            if not content:
                continue
            if content in seen and index < len(messages) - 4:
                repeated.append(index)
            seen[content] = index
        return repeated


# ── 3. Compressor ───────────────────────────────────────────────────


class ContextCompressor:
    """Dedup + compact a history window before it enters the prompt."""

    def __init__(self, config: Optional[ContextRotConfig] = None) -> None:
        self._config = config or ContextRotConfig()
        self._detector = ContextRotDetector(self._config)
        self.last_report: Optional[ContextRotReport] = None

    def compress_history(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return a cleaned copy of *messages*.

        Recent turns (``recent_turns_full``) are kept verbatim. Older turns
        that are exact normalized duplicates of a later turn are dropped;
        remaining bulky older turns are head/tail compacted. This breaks the
        runaway-repetition pattern that poisons weak models while keeping the
        latest exchange intact so the model can still act on it.
        """
        if not messages:
            return []
        report = self._detector.check(messages)
        self.last_report = report
        if report.health == "healthy":
            return list(messages)

        recent_window = self._config.recent_turns_full
        total = len(messages)
        keep_from = max(0, total - recent_window)

        result: List[Dict[str, Any]] = []
        seen_recent: Dict[str, int] = {}
        for index, item in enumerate(messages):
            # Always keep the most-recent window verbatim.
            if index >= keep_from:
                result.append(item)
                continue
            content = str(item.get("content") or "")
            norm = _normalize(content)[:180]
            # Drop an older turn that is an exact normalized duplicate of one
            # we already kept — this is the poisoning signal.
            if norm and norm in seen_recent:
                continue
            if norm:
                seen_recent[norm] = index
            if len(content) > self._config.long_turn_chars:
                item = {**item, "content": self._compact(content)}
            result.append(item)
        return result

    def _compact(self, content: str) -> str:
        """Head/tail compaction marker for an over-long older turn."""
        cap = self._config.compact_cap_chars
        if len(content) <= cap:
            return content
        head = max(40, cap // 2)
        tail = max(40, cap - head - 40)
        return f"[COMPACTED OLDER TURN]\n{content[:head]}\n...\n{content[-tail:]}"


# ── 4. Stuck-loop breaker ───────────────────────────────────────────


STUCK_LOOP_DIRECTIVE = (
    "[STUCK-LOOP BREAKER] Your last few responses have been near-identical. "
    "You are stuck repeating yourself instead of doing the work. STOP. Do not "
    "ask for clarification, do not explain that the input is repeating, do not "
    "restate prior answers. The user's request is clear enough to act on RIGHT "
    "NOW — use your tools to execute it this turn and produce the concrete "
    "deliverable. If a path is involved, read/list/write it immediately."
)


def detect_stuck_loop(
    messages: List[Dict[str, Any]],
    *,
    config: Optional[ContextRotConfig] = None,
) -> Optional[str]:
    """Return :data:`STUCK_LOOP_DIRECTIVE` when the agent is looping.

    Looks at the most recent assistant turns. If at least
    ``stuck_min_repeats`` of them are near-identical (word overlap above
    ``stuck_overlap``, or exact normalized duplicates), the agent is echoing
    itself and the caller should inject the directive to force action.
    Returns ``None`` otherwise.
    """
    cfg = config or ContextRotConfig()
    assistant = [
        _normalize(item.get("content"))
        for item in messages
        if str(item.get("role") or "") == "assistant" and _normalize(item.get("content"))
    ]
    recent = assistant[-4:]
    if len(recent) < cfg.stuck_min_repeats + 1:
        return None
    anchor = recent[-1]
    matches = 0
    for prior in recent[:-1]:
        if prior == anchor or _word_overlap(prior, anchor) >= cfg.stuck_overlap:
            matches += 1
    if matches >= cfg.stuck_min_repeats:
        return STUCK_LOOP_DIRECTIVE
    return None
