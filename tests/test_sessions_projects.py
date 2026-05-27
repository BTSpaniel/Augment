"""Tests for project tagging on sessions + the grill-project synthesizer."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from augment.context.memory import SessionStore
from augment.main import app


# ── SessionStore unit tests ─────────────────────────────────────────


def test_session_store_project_metadata(tmp_path: Path):
    store = SessionStore(tmp_path)
    sid = store.new_session_id()
    store.append(sid, "user", "hello")
    # No project until set.
    assert store.project_for(sid) == ""
    meta = store.set_project(sid, "augment")
    assert meta["project"] == "augment"
    assert store.project_for(sid) == "augment"

    listed = store.list()
    assert any(s["session_id"] == sid and s["project"] == "augment" for s in listed)

    grouped = store.list_by_project()
    assert "augment" in grouped
    assert any(s["session_id"] == sid for s in grouped["augment"])


def test_session_delete_removes_meta_sidecar(tmp_path: Path):
    store = SessionStore(tmp_path)
    sid = store.new_session_id()
    store.append(sid, "user", "ping")
    store.set_project(sid, "demo")
    meta_path = tmp_path / "sessions" / f"{sid}.meta.json"
    assert meta_path.exists()
    store.delete(sid)
    assert not meta_path.exists()


def test_sessions_truncated_project_field(tmp_path: Path):
    store = SessionStore(tmp_path)
    sid = store.new_session_id()
    store.append(sid, "user", "x")
    store.set_project(sid, "a" * 200)
    assert len(store.project_for(sid)) == 80


# ── HTTP API ────────────────────────────────────────────────────────


def test_sessions_by_project_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    with TestClient(app) as client:
        # Seed sessions with two different projects via the SessionStore.
        api = client.app.state.augment
        s1 = api.sessions.new_session_id()
        s2 = api.sessions.new_session_id()
        s3 = api.sessions.new_session_id()
        api.sessions.append(s1, "user", "build feature A")
        api.sessions.append(s2, "user", "investigate the bug")
        api.sessions.append(s3, "user", "unassigned")
        api.sessions.set_project(s1, "alpha")
        api.sessions.set_project(s2, "beta")
        # s3 left untagged.

        body = client.get("/api/sessions/by_project").json()
        projects = {p["project"]: p for p in body["projects"]}
        assert "alpha" in projects
        assert "beta" in projects
        assert "" in projects  # unassigned bucket
        assert projects["alpha"]["session_count"] == 1
        assert body["total_sessions"] == 3


def test_set_session_project_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    with TestClient(app) as client:
        api = client.app.state.augment
        sid = api.sessions.new_session_id()
        api.sessions.append(sid, "user", "x")
        result = client.put(
            f"/api/sessions/{sid}/project",
            json={"project": "manual_tag"},
        ).json()
        assert result["meta"]["project"] == "manual_tag"
        assert api.sessions.project_for(sid) == "manual_tag"


def test_grill_project_endpoint_with_stub_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    with TestClient(app) as client:
        api = client.app.state.augment
        # Seed two sessions in the same project.
        s1 = api.sessions.new_session_id()
        s2 = api.sessions.new_session_id()
        api.sessions.append(s1, "user", "What does the memory tier system do?")
        api.sessions.append(s1, "assistant", "It has four tiers...")
        api.sessions.append(s2, "user", "Add Holmes investigation mode.")
        api.sessions.append(s2, "assistant", "Done — see augment/skills/holmes.py")
        api.sessions.set_project(s1, "augment")
        api.sessions.set_project(s2, "augment")

        # Stub the provider so we don't hit the network.
        class _StubResponse:
            content = "Theme: AI infrastructure.\nNext step: ship more tests."

        class _StubProvider:
            model = "stub"
            async def complete(self, *_a: Any, **_kw: Any) -> _StubResponse:
                return _StubResponse()

        monkeypatch.setattr(api.settings, "has_default_profile", lambda: True)
        monkeypatch.setattr(api.providers, "default", lambda: _StubProvider())

        body = client.post(
            "/api/sessions/grill",
            json={"project": "augment", "max_sessions": 5},
        ).json()
        assert body["project"] == "augment"
        assert "Theme" in body["summary"]
        assert len(body["sessions"]) == 2

        # The synthesis should be recorded as an inner-monologue entry.
        monologue = api.mind.monologue.recent(limit=5)
        assert any("augment" in (e.get("thought") or "") for e in monologue)


def test_grill_unknown_project_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    with TestClient(app) as client:
        body = client.post(
            "/api/sessions/grill",
            json={"project": "does_not_exist"},
        ).json()
        assert body["sessions"] == []
        assert body["summary"] == ""
