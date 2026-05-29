"""Tests for conversation-history context-rot defense.

Covers the detector (redundancy / repeated-turn flagging), the compressor
(dedup of older duplicate turns while keeping the recent window verbatim),
and the stuck-loop breaker that fires on near-identical assistant turns.
"""
from __future__ import annotations

from augment.context.context_rot import (
    STUCK_LOOP_DIRECTIVE,
    ContextCompressor,
    ContextRotDetector,
    detect_stuck_loop,
)


def _poisoned_history(repeats: int = 8) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for _ in range(repeats):
        history.append({"role": "user", "content": "webgpu 3d canvas 3d cake sexy shader effects"})
        history.append({"role": "assistant", "content": "I can help you create a 3D scene. What kind of scene, what objects, what platform?"})
    return history


def test_detector_flags_redundant_repeated_history():
    report = ContextRotDetector().check(_poisoned_history())
    assert report.health in {"degrading", "critical"}
    assert report.redundancy > 0.4
    assert report.repeated_indices  # older duplicate turns are flagged


def test_detector_clean_history_is_healthy():
    history = [
        {"role": "user", "content": "add a dark mode toggle to the settings page"},
        {"role": "assistant", "content": "Done — added a toggle wired to localStorage and a CSS variable swap."},
        {"role": "user", "content": "now persist it across reloads using a cookie instead"},
    ]
    report = ContextRotDetector().check(history)
    assert report.health == "healthy"
    assert report.repeated_indices == []


def test_compressor_dedups_older_duplicate_turns():
    history = _poisoned_history(repeats=8)
    compressed = ContextCompressor().compress_history(history)
    # The runaway duplicates should collapse substantially.
    assert len(compressed) < len(history)
    # The most recent turn is preserved verbatim.
    assert compressed[-1]["content"] == history[-1]["content"]


def test_compressor_keeps_clean_history_intact():
    history = [
        {"role": "user", "content": "what does resolve_under do?"},
        {"role": "assistant", "content": "It resolves a path under the workspace root and guards against escapes."},
    ]
    assert ContextCompressor().compress_history(history) == history


def test_stuck_loop_detected_on_repeated_assistant_turns():
    directive = detect_stuck_loop(_poisoned_history())
    assert directive == STUCK_LOOP_DIRECTIVE


def test_stuck_loop_not_detected_when_assistant_varies():
    history = [
        {"role": "user", "content": "build a cake"},
        {"role": "assistant", "content": "Created index.html with a 3D canvas and a rotating cake mesh."},
        {"role": "user", "content": "add music"},
        {"role": "assistant", "content": "Added a Web Audio synth loop triggered on first interaction."},
        {"role": "user", "content": "make shaders nicer"},
        {"role": "assistant", "content": "Upgraded the fragment shader with a glowing frosting gradient."},
    ]
    assert detect_stuck_loop(history) is None


# ── hardening: malformed / mixed input ──────────────────────────────


class _MsgObj:
    """Message-like object exposing .role / .content (not a dict)."""

    def __init__(self, role: str, content: str) -> None:
        self.role = role
        self.content = content


def test_handles_none_and_empty_without_crashing():
    assert ContextRotDetector().check([]).health == "healthy"
    assert ContextRotDetector().check(None).health == "healthy"
    assert ContextCompressor().compress_history([]) == []
    assert ContextCompressor().compress_history(None) == []
    assert detect_stuck_loop(None) is None


def test_skips_non_dict_garbage_items_without_crashing():
    history = [None, "stray string", 42, {"role": "user", "content": "hi"}]
    # Should not raise on any path.
    assert ContextRotDetector().check(history) is not None
    assert ContextCompressor().compress_history(history) is not None
    assert detect_stuck_loop(history) is None


def test_detects_loop_on_message_like_objects():
    history = [_MsgObj("assistant", "I can help. What platform and objects?") for _ in range(5)]
    assert detect_stuck_loop(history) == STUCK_LOOP_DIRECTIVE


def test_cluster_detected_even_when_last_turn_differs():
    # Three identical deflections, then a slightly different final turn — the
    # cluster (not anchor-only) logic must still fire.
    deflection = "I can help you build that. Could you clarify the scope first?"
    history = [
        {"role": "assistant", "content": deflection},
        {"role": "assistant", "content": deflection},
        {"role": "assistant", "content": deflection},
        {"role": "assistant", "content": "Sure, starting now with a brand new plan entirely."},
    ]
    assert detect_stuck_loop(history) == STUCK_LOOP_DIRECTIVE
