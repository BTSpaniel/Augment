"""Tests for the Holmes investigation skill."""
from __future__ import annotations

from fastapi.testclient import TestClient

from augment.main import app
from augment.skills.dormant_packs import dormant_skill_catalog
from augment.skills.holmes import (
    HOLMES_DORMANT_PACK,
    HOLMES_PROMPT,
    matches_investigation_intent,
)


def test_matches_investigation_intent_recognises_keywords():
    positive = [
        "investigate how the chat loop works",
        "help me understand this code",
        "explore the augment service",
        "audit the security layer",
        "how does the memory system work",
        "walk me through the planning module",
        "figure out where the bug originates",
        "trace the request through the API",
    ]
    for message in positive:
        assert matches_investigation_intent(message), message

    negative = [
        "write a function that doubles a list",
        "fix the typo in line 42",
        "add a button to the sidebar",
        "remove the old endpoint",
    ]
    for message in negative:
        assert not matches_investigation_intent(message), message


def test_dormant_catalog_includes_holmes_pack():
    catalog = dormant_skill_catalog()
    pack_ids = {pack["id"] for pack in catalog["packs"]}
    assert "code_investigator" in pack_ids
    assert HOLMES_DORMANT_PACK["category"] in catalog["by_category"]
    arch = catalog["by_category"]["Architecture"]
    assert any(p["id"] == "code_investigator" for p in arch)


def test_holmes_endpoint_activates_with_explicit_objective(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    with TestClient(app) as client:
        # Without a matching objective, force-activation should still succeed.
        result = client.post("/api/skills/holmes/activate", json={
            "objective": "rewrite the README",
        }).json()
        assert result["activated"] is True
        skills = result["skills"]
        assert skills
        assert any(s.get("id") == "adaptive_holmes_investigation" for s in skills)

        # Also reflected in the skills/context endpoint.
        context = client.get("/api/skills/context").json()["context"]
        assert "INVESTIGATION MODE" in context or "Holmes" in context


def test_holmes_skill_auto_generates_on_explore_intent(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    with TestClient(app) as client:
        result = client.post("/api/skills/generate", json={
            "objective": "investigate why the chat freezes during streaming",
        }).json()
        skills = result["skills"]
        assert any(s.get("id") == "adaptive_holmes_investigation" for s in skills)


def test_holmes_skill_does_not_activate_for_trivial_task(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    with TestClient(app) as client:
        result = client.post("/api/skills/generate", json={
            "objective": "fix a typo in the readme",
        }).json()
        skills = result["skills"]
        assert not any(s.get("id") == "adaptive_holmes_investigation" for s in skills)


def test_holmes_prompt_contains_core_instructions():
    assert "Batch reads" in HOLMES_PROMPT
    assert "Think out loud" in HOLMES_PROMPT
    assert "Cite as you go" in HOLMES_PROMPT
    assert "Conclude only when stable" in HOLMES_PROMPT
