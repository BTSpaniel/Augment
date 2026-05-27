"""Tests for the Pocock-style skill packs (caveman / grill-me / handoff)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from augment.main import app
from augment.skills.dormant_packs import dormant_skill_catalog
from augment.skills.pocock_packs import (
    CAVEMAN_PACK,
    CAVEMAN_PROMPT,
    GRILL_PACK,
    GRILL_PROMPT,
    HANDOFF_PACK,
    HANDOFF_PROMPT,
    pocock_skills_for,
)


def test_caveman_trigger_phrases_activate():
    for phrase in [
        "switch to caveman mode please",
        "talk like caveman",
        "use caveman",
        "less tokens",
        "be brief",
    ]:
        skills = pocock_skills_for(phrase)
        ids = {s.id for s in skills}
        assert "adaptive_caveman_mode" in ids, phrase


def test_caveman_off_trigger_deactivates():
    skills = pocock_skills_for("caveman mode for now... actually stop caveman")
    assert not any(s.id == "adaptive_caveman_mode" for s in skills)


def test_grill_trigger_phrases_activate():
    for phrase in [
        "grill me on this plan",
        "stress-test my plan",
        "interview me about the design",
        "poke holes in this approach",
        "find the gaps in my plan",
    ]:
        skills = pocock_skills_for(phrase)
        ids = {s.id for s in skills}
        assert "adaptive_grill_me" in ids, phrase


def test_handoff_trigger_phrases_activate():
    for phrase in [
        "write a handoff document",
        "compact the conversation",
        "continue in a new session",
        "prepare for a fresh agent",
    ]:
        skills = pocock_skills_for(phrase)
        ids = {s.id for s in skills}
        assert "adaptive_handoff_writer" in ids, phrase


def test_explicit_activation_overrides_message():
    skills = pocock_skills_for(
        "just a normal question",
        explicit_ids=["caveman_mode", "grill_me"],
    )
    ids = {s.id for s in skills}
    assert "adaptive_caveman_mode" in ids
    assert "adaptive_grill_me" in ids


def test_pocock_packs_appear_in_dormant_catalog():
    catalog = dormant_skill_catalog()
    pack_ids = {p["id"] for p in catalog["packs"]}
    for expected in ("caveman_mode", "grill_me", "handoff_writer"):
        assert expected in pack_ids


def test_pocock_prompts_carry_persistence_rules():
    assert "Persistence" in CAVEMAN_PROMPT
    assert "Persistence" in GRILL_PROMPT
    # Handoff is one-shot — has no persistence section, but must have all 6 required sections.
    for header in ("Goal", "State so far", "Open threads", "Suggested next step", "Suggested skills", "References"):
        assert header in HANDOFF_PROMPT, header


def test_pocock_pack_metadata_complete():
    for pack in (CAVEMAN_PACK, GRILL_PACK, HANDOFF_PACK):
        for key in ("id", "name", "category", "description", "when_to_use", "when_not_to_use", "steps", "acceptance_check"):
            assert pack.get(key), f"{pack['id']} missing {key}"


def test_no_skill_activates_for_neutral_message():
    skills = pocock_skills_for("explain how the loop works")
    ids = {s.id for s in skills}
    # Holmes might match this, but no Pocock skill should.
    for forbidden in ("adaptive_caveman_mode", "adaptive_grill_me", "adaptive_handoff_writer"):
        assert forbidden not in ids


def test_skills_generate_endpoint_returns_pocock_when_triggered(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    with TestClient(app) as client:
        result = client.post("/api/skills/generate", json={
            "objective": "grill me on this refactor plan",
        }).json()
        ids = {s.get("id") for s in result["skills"]}
        assert "adaptive_grill_me" in ids
