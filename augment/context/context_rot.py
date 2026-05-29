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
    stuck_window: int = 4


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


def _role_content(item: Any) -> tuple[str, Any]:
    """Safely pull ``(role, content)`` from a history entry.

    Accepts the loop's plain ``{"role", "content"}`` dicts and objects that
    expose ``.role`` / ``.content`` attributes (e.g. a provider ``Message``).
    Anything else yields ``("", None)`` so a malformed entry is skipped
    rather than raising and taking down the whole turn assembly.
    """
    if isinstance(item, dict):
        return str(item.get("role") or ""), item.get("content")
    return str(getattr(item, "role", "") or ""), getattr(item, "content", None)


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
        if not messages:
            return ContextRotReport("healthy", 0.0, 0.0, [])
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
        fingerprints: List[str] = []
        for item in messages:
            role, content = _role_content(item)
            if role == "system":
                continue
            norm = _normalize(content)
            if norm:
                fingerprints.append(norm[:240])
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
            role, raw = _role_content(item)
            if role == "system":
                continue
            content = str(raw or "")
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
            _, raw = _role_content(item)
            content = _normalize(raw)[:180]
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
            _, raw = _role_content(item)
            content = str(raw or "")
            norm = _normalize(raw)[:180]
            # Drop an older turn that is an exact normalized duplicate of one
            # we already kept — this is the poisoning signal.
            if norm and norm in seen_recent:
                continue
            if norm:
                seen_recent[norm] = index
            # Only dict items can be safely rebuilt with a compacted body;
            # other shapes are passed through untouched.
            if isinstance(item, dict) and len(content) > self._config.long_turn_chars:
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

    Scans the most recent ``stuck_window`` assistant turns and finds the
    largest cluster of near-identical ones (exact normalized duplicates, or
    word overlap at/above ``stuck_overlap``). If that cluster is at least
    ``stuck_min_repeats + 1`` turns, the agent is echoing itself and the
    caller should inject the directive to force action. Using a cluster (not
    just comparing against the last turn) catches a loop even when the most
    recent turn differs slightly. Returns ``None`` otherwise.
    """
    cfg = config or ContextRotConfig()
    assistant: List[str] = []
    for item in (messages or []):
        role, content = _role_content(item)
        if role != "assistant":
            continue
        norm = _normalize(content)
        if norm:
            assistant.append(norm)
    window = max(cfg.stuck_window, cfg.stuck_min_repeats + 1)
    recent = assistant[-window:]
    if len(recent) < cfg.stuck_min_repeats + 1:
        return None
    largest = 1
    for i, anchor in enumerate(recent):
        cluster = 1
        for j, other in enumerate(recent):
            if i == j:
                continue
            if other == anchor or _word_overlap(anchor, other) >= cfg.stuck_overlap:
                cluster += 1
        largest = max(largest, cluster)
    if largest >= cfg.stuck_min_repeats + 1:
        return STUCK_LOOP_DIRECTIVE
    return None
