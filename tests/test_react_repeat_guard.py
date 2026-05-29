"""Tests for the in-rollout repeat-guard helpers in the ReAct loop.

These cover the pure helpers (``_call_signature`` / ``_repeat_directive``)
that detect when the agent re-issues an identical tool call within a single
rollout — the classic ``mkdir -p`` Windows loop — and steer it to write_file.
"""
from __future__ import annotations

from augment.loop.react import _call_signature, _repeat_directive


def test_call_signature_is_stable_and_order_independent():
    a = _call_signature("write_file", {"path": "a.html", "content": "x"})
    b = _call_signature("write_file", {"content": "x", "path": "a.html"})
    assert a == b  # key order must not change the signature


def test_call_signature_differs_on_args():
    a = _call_signature("run_command", {"command": "mkdir -p foo"})
    b = _call_signature("run_command", {"command": "mkdir -p bar"})
    assert a != b


def test_repeat_directive_generic_message():
    msg = _repeat_directive("read_file", {"path": "x"}, 2)
    assert "REPEAT GUARD" in msg
    assert "Do" in msg and "NOT repeat" in msg


def test_repeat_directive_mkdir_points_at_write_file():
    msg = _repeat_directive("run_command", {"command": "mkdir -p C:/cake"}, 3)
    assert "write_file" in msg
    assert "mkdir -p" in msg
    assert "Windows" in msg


def test_repeat_directive_non_mkdir_command_has_no_mkdir_hint():
    msg = _repeat_directive("run_command", {"command": "npm run build"}, 2)
    assert "write_file creates all parent directories" not in msg
