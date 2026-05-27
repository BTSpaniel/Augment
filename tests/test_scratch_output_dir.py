"""Tests for the scratch / output_dir write policy."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from augment.context.memory import SessionStore
from augment.main import app
from augment.tools.files import (
    _resolve_write_target,
    edit_file,
    set_output_dir,
    write_file,
)


# ── _resolve_write_target ───────────────────────────────────────────


def test_relative_path_lands_in_scratch_session_dir(tmp_path):
    ctx = {
        "workspace_root": str(tmp_path / "ws"),
        "scratch_root": str(tmp_path / "scratch"),
        "session_id": "sess_a",
    }
    target, base, kind = _resolve_write_target("notes.txt", ctx)
    assert kind == "scratch"
    assert base == (tmp_path / "scratch" / "sess_a")
    assert target == base / "notes.txt"


def test_output_dir_override_redirects_relative_path(tmp_path):
    override = tmp_path / "cake"
    ctx = {
        "workspace_root": str(tmp_path / "ws"),
        "scratch_root": str(tmp_path / "scratch"),
        "output_dir": str(override),
        "session_id": "sess_b",
    }
    target, base, kind = _resolve_write_target("recipe.md", ctx)
    assert kind == "override"
    assert base == override.resolve()
    assert target == (override / "recipe.md").resolve()
    assert override.exists()  # ensured by resolver


def test_absolute_path_returns_literal_target(tmp_path):
    literal = tmp_path / "literal" / "out.txt"
    ctx = {
        "workspace_root": str(tmp_path / "ws"),
        "scratch_root": str(tmp_path / "scratch"),
        "session_id": "sess_c",
    }
    target, base, kind = _resolve_write_target(str(literal), ctx)
    assert kind == "absolute"
    assert target == literal.resolve()


def test_relative_path_cannot_escape_scratch(tmp_path):
    ctx = {
        "workspace_root": str(tmp_path / "ws"),
        "scratch_root": str(tmp_path / "scratch"),
        "session_id": "sess_d",
    }
    try:
        _resolve_write_target("../../escape.txt", ctx)
    except ValueError:
        return  # expected — ../ escape rejected
    raise AssertionError("expected ValueError when escaping scratch dir")


# ── write_file behavior ─────────────────────────────────────────────


def test_write_file_defaults_to_scratch(tmp_path):
    ctx = {
        "workspace_root": str(tmp_path / "ws"),
        "scratch_root": str(tmp_path / "scratch"),
        "session_id": "sess_w",
    }
    result = write_file("hello.txt", "hi there", _context=ctx)
    assert "scratch" in result
    landed = tmp_path / "scratch" / "sess_w" / "hello.txt"
    assert landed.exists()
    assert landed.read_text(encoding="utf-8") == "hi there"


def test_write_file_uses_output_dir_override(tmp_path):
    override = tmp_path / "cake"
    ctx = {
        "workspace_root": str(tmp_path / "ws"),
        "scratch_root": str(tmp_path / "scratch"),
        "output_dir": str(override),
        "session_id": "sess_w2",
    }
    result = write_file("recipe.md", "flour + sugar", _context=ctx)
    assert "output_dir override" in result
    assert (override / "recipe.md").exists()
    # Scratch dir should not have been used.
    assert not (tmp_path / "scratch" / "sess_w2").exists()


def test_write_file_rejects_sensitive_absolute_path(tmp_path):
    ctx = {
        "workspace_root": str(tmp_path / "ws"),
        "scratch_root": str(tmp_path / "scratch"),
        "session_id": "sess_w3",
    }
    # PathGuard blocks .env in any form.
    result = write_file(str(tmp_path / "config" / ".env"), "SECRET=x", _context=ctx)
    assert "refused" in result.lower()
    assert not (tmp_path / "config" / ".env").exists()


def test_write_file_blocks_code_without_required_comments(tmp_path):
    ctx = {
        "workspace_root": str(tmp_path / "ws"),
        "scratch_root": str(tmp_path / "scratch"),
        "session_id": "sess_style",
    }

    result = write_file("cake.html", "<!DOCTYPE html>\n<html></html>\n", _context=ctx)

    assert "coding style gate blocked" in result
    assert "file-header banner" in result
    assert not (tmp_path / "scratch" / "sess_style" / "cake.html").exists()


def test_write_file_accepts_commented_code_file(tmp_path):
    ctx = {
        "workspace_root": str(tmp_path / "ws"),
        "scratch_root": str(tmp_path / "scratch"),
        "session_id": "sess_style_ok",
    }
    content = """<!DOCTYPE html>
<!--
  Tiny generated page.
  Sections: Document body and script helpers.
  Keep this file self-contained for browser preview.
-->
<html lang="en">
<body>
  <!-- Document body -->
  <main>Hello</main>
  <script>
    /**
     * Start the tiny page behavior.
     *
     * Kept as a public function so the coding-style gate can verify docs.
     */
    function startPage() {
      document.body.dataset.ready = '1';
    }
    startPage();
  </script>
</body>
</html>
"""

    result = write_file("cake.html", content, _context=ctx)

    assert "Written" in result
    assert (tmp_path / "scratch" / "sess_style_ok" / "cake.html").exists()


# ── set_output_dir tool ─────────────────────────────────────────────


def test_set_output_dir_writes_session_meta(tmp_path):
    sessions = SessionStore(tmp_path)
    sid = sessions.new_session_id()
    sessions.append(sid, "user", "hi")
    target = tmp_path / "cake"
    ctx = {"session_id": sid, "sessions_store": sessions}

    result = set_output_dir(str(target), _context=ctx)
    assert "Output directory set" in result
    assert sessions.meta(sid).get("output_dir") == str(target.resolve())
    assert target.exists()


def test_set_output_dir_clears_when_empty(tmp_path):
    sessions = SessionStore(tmp_path)
    sid = sessions.new_session_id()
    sessions.append(sid, "user", "hi")
    sessions.set_meta(sid, output_dir=str(tmp_path / "cake"))
    ctx = {"session_id": sid, "sessions_store": sessions}

    result = set_output_dir("", _context=ctx)
    assert "Cleared" in result
    assert sessions.meta(sid).get("output_dir") == ""


def test_set_output_dir_rejects_sensitive_path(tmp_path):
    sessions = SessionStore(tmp_path)
    sid = sessions.new_session_id()
    sessions.append(sid, "user", "hi")
    ctx = {"session_id": sid, "sessions_store": sessions}

    # .env path is blocked by PathGuard.
    result = set_output_dir(str(tmp_path / ".env"), _context=ctx)
    assert "refused" in result.lower()
    assert sessions.meta(sid).get("output_dir", "") == ""


# ── edit_file resolves scratch + override paths ─────────────────────


def test_edit_file_finds_file_in_scratch_dir(tmp_path):
    ctx = {
        "workspace_root": str(tmp_path / "ws"),
        "scratch_root": str(tmp_path / "scratch"),
        "session_id": "sess_e",
    }
    (tmp_path / "ws").mkdir(parents=True, exist_ok=True)
    write_file("draft.txt", "hello world", _context=ctx)

    result = edit_file("draft.txt", "world", "vex", _context=ctx)
    assert "replaced 1 occurrence" in result
    landed = tmp_path / "scratch" / "sess_e" / "draft.txt"
    assert landed.read_text(encoding="utf-8") == "hello vex"


# ── HTTP API ────────────────────────────────────────────────────────


def test_set_output_dir_endpoint_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    with TestClient(app) as client:
        api = client.app.state.augment
        sid = api.sessions.new_session_id()
        api.sessions.append(sid, "user", "x")

        target = tmp_path / "cake"
        resp = client.put(
            f"/api/sessions/{sid}/output_dir",
            json={"path": str(target)},
        ).json()
        assert resp["meta"]["output_dir"] == str(target.resolve())
        assert target.exists()

        clear = client.put(
            f"/api/sessions/{sid}/output_dir",
            json={"path": ""},
        ).json()
        assert clear["cleared"] is True
        assert clear["meta"]["output_dir"] == ""


def test_set_output_dir_endpoint_rejects_sensitive(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    with TestClient(app) as client:
        api = client.app.state.augment
        sid = api.sessions.new_session_id()
        api.sessions.append(sid, "user", "x")

        resp = client.put(
            f"/api/sessions/{sid}/output_dir",
            json={"path": str(tmp_path / "secret" / ".env")},
        )
        assert resp.status_code == 400


# ── Config default ──────────────────────────────────────────────────


def test_config_scratch_root_defaults_to_workspace_temp(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.delenv("AUGMENT_SCRATCH_ROOT", raising=False)

    from augment.config import load_config

    cfg = load_config()
    assert cfg.scratch_root == (tmp_path / "ws").resolve() / "temp"


def test_config_scratch_root_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    custom = tmp_path / "custom_scratch"
    monkeypatch.setenv("AUGMENT_SCRATCH_ROOT", str(custom))

    from augment.config import load_config

    cfg = load_config()
    assert cfg.scratch_root == custom.resolve()
