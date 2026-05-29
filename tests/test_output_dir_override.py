"""Regression test for the set_output_dir live-context bug.

Bug: set_output_dir persisted the override to the session store but never
updated the per-turn tool_context dict, so write_file calls in the SAME turn
fell back to the scratch directory (observed: cake files landed in
temp/<session> instead of C:\\cake). The fix mutates the live _context in
place; these tests lock that behavior in.
"""
from __future__ import annotations

from augment.tools.files import set_output_dir, write_file


class _FakeSessions:
    """Minimal session store stub capturing set_meta calls."""

    def __init__(self) -> None:
        self.meta: dict[str, dict] = {}

    def set_meta(self, sid: str, **kwargs) -> dict:
        self.meta.setdefault(sid, {}).update(kwargs)
        return self.meta[sid]


def _ctx(tmp_path) -> dict:
    return {
        "session_id": "sess1",
        "sessions_store": _FakeSessions(),
        "workspace_root": str(tmp_path / "ws"),
        "scratch_root": str(tmp_path / "scratch"),
        "output_dir": "",
    }


def test_set_output_dir_mutates_live_context(tmp_path):
    out = tmp_path / "cake"
    ctx = _ctx(tmp_path)
    msg = set_output_dir(str(out), _context=ctx)
    assert "Output directory set to" in msg
    # The live turn context must reflect the override immediately.
    assert ctx["output_dir"] == str(out.resolve())


def test_write_after_set_output_dir_lands_in_override_same_turn(tmp_path):
    out = tmp_path / "cake"
    ctx = _ctx(tmp_path)
    set_output_dir(str(out), _context=ctx)
    res = write_file("notes.txt", "hello cake\n", _context=ctx)
    assert "output_dir override" in res
    assert (out / "notes.txt").exists()
    # And it must NOT have gone to scratch.
    assert not (tmp_path / "scratch" / "sess1" / "notes.txt").exists()


def test_clear_output_dir_reverts_to_scratch(tmp_path):
    out = tmp_path / "cake"
    ctx = _ctx(tmp_path)
    set_output_dir(str(out), _context=ctx)
    set_output_dir("", _context=ctx)
    assert ctx["output_dir"] == ""
    res = write_file("again.txt", "back to scratch\n", _context=ctx)
    assert "scratch" in res
    assert (tmp_path / "scratch" / "sess1" / "again.txt").exists()
