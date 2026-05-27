"""Tests for the tiered memory system (working / episodic / semantic / procedural)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from augment.main import app
from augment.memory import (
    EpisodicMemory,
    MemoryConsolidator,
    MemoryRetriever,
    MemorySystem,
    ProceduralMemory,
    SemanticMemory,
    WorkingMemory,
)


# ── Unit tests per tier ─────────────────────────────────────────────


def test_working_memory_expiry_and_priority(tmp_path):
    # WorkingMemory enforces a min cap of 5; push past it to exercise prune.
    mem = WorkingMemory(max_items=5)
    mem.put("a", "alpha", ttl=5, priority=9)
    mem.put("b", "beta", ttl=5, priority=2)
    mem.put("c", "gamma", ttl=5, priority=7)
    mem.put("d", "delta", ttl=5, priority=8)
    mem.put("e", "epsilon", ttl=5, priority=6)
    mem.put("f", "zeta", ttl=5, priority=10)
    keys = {item["key"] for item in mem.all_items()}
    # 6 items, cap 5: lowest-priority (b, priority 2) is the one evicted.
    assert "b" not in keys
    assert {"a", "c", "d", "e", "f"} <= keys
    assert mem.get("a") == "alpha"
    mem.remove("a")
    assert mem.get("a") is None


def test_working_memory_context_block_renders():
    mem = WorkingMemory()
    mem.put("focus", "edit augment/service.py")
    block = mem.as_context_block()
    assert "[WORKING MEMORY]" in block
    assert "focus" in block


def test_episodic_memory_records_and_recalls(tmp_path):
    em = EpisodicMemory(tmp_path)
    em.record(session_id="sess_1", summary="ran the loop", outcome="success",
              tools_used=["read_file"], lessons=["always read first"])
    em.record(session_id="sess_2", summary="hit a 429", outcome="error")
    recent = em.recall(limit=5)
    assert len(recent) == 2
    success_only = em.recall(limit=5, outcome="success")
    assert len(success_only) == 1
    hits = em.search("429")
    assert hits and hits[0]["session_id"] == "sess_2"
    # Reload from disk and confirm persistence.
    reloaded = EpisodicMemory(tmp_path).recall(limit=5)
    assert len(reloaded) == 2


def test_semantic_memory_persists_and_searches(tmp_path):
    sm = SemanticMemory(tmp_path)
    sm.store("workspace", "C:/Coding/augment", category="env", confidence=0.95)
    sm.store("user_handle", "vex", category="user", confidence=0.7)
    assert sm.recall("workspace") == "C:/Coding/augment"
    hits = sm.search("vex")
    assert hits and hits[0]["key"] == "user_handle"
    by_cat = sm.by_category("env")
    assert by_cat and by_cat[0]["key"] == "workspace"
    sm.remove("workspace")
    assert sm.recall("workspace") is None
    # Reload from disk.
    reloaded = SemanticMemory(tmp_path)
    assert reloaded.recall("user_handle") == "vex"


def test_procedural_memory_learns_and_recalls(tmp_path):
    pm = ProceduralMemory(tmp_path)
    pm.learn("clean_python", steps=["py_compile", "pytest"], trigger="python edit", success_rate=0.9)
    pm.learn("clean_python", steps=["py_compile", "pytest", "mypy"], success_rate=1.0)
    proc = pm.recall("clean_python")
    assert proc is not None
    assert proc["use_count"] >= 2
    # Success rate should be the running average (0.9 + 1.0) / 2 = 0.95
    assert 0.9 <= proc["success_rate"] <= 1.0
    hits = pm.find_for_trigger("python")
    assert hits and hits[0]["name"] == "clean_python"
    # Reload.
    reloaded = ProceduralMemory(tmp_path)
    assert reloaded.recall("clean_python") is not None


def test_retriever_ranks_across_tiers(tmp_path):
    system = MemorySystem(tmp_path)
    system.working.put("focus", "vision endpoint code path", priority=9)
    system.semantic.store("vision_pref", "user wants image support", confidence=0.9)
    system.episodic.record(session_id="sess_vision", summary="added vision attach UI")
    system.procedural.learn("vision_flow", steps=["read", "edit", "verify"], trigger="vision endpoint", success_rate=1.0)

    results = system.retriever.retrieve("vision", limit=10)
    tiers = {r["tier"] for r in results}
    # All four tiers should contribute.
    assert {"working", "semantic", "episodic", "procedural"} <= tiers
    # Working memory should rank first (score=1.0).
    assert results[0]["tier"] == "working"


def test_consolidator_records_episode_and_clears_working(tmp_path):
    system = MemorySystem(tmp_path)
    system.working.put("scratch", "ephemeral", priority=3)
    system.consolidator.consolidate_session(
        session_id="sess_1",
        summary="did a thing",
        outcome="success",
        tools_used=["read_file", "edit_file"],
        lessons=["scope the edit"],
    )
    assert system.working.all_items() == []
    episodes = system.episodic.recall(limit=5)
    assert len(episodes) == 1
    assert episodes[0]["summary"] == "did a thing"
    assert episodes[0]["tools_used"] == ["read_file", "edit_file"]


def test_consolidator_promotes_high_priority_working(tmp_path):
    system = MemorySystem(tmp_path)
    system.working.put("a", "low", priority=4)
    system.working.put("b", "high", priority=9)
    promoted = system.consolidator.consolidate_working(min_priority=8)
    assert promoted == 1
    assert system.semantic.recall("b") == "high"
    assert system.semantic.recall("a") is None


# ── HTTP API ────────────────────────────────────────────────────────


def test_memory_tier_endpoints_full_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))

    with TestClient(app) as client:
        # GET /api/memory returns legacy + tiers snapshot.
        body = client.get("/api/memory").json()
        assert "memory" in body and "tiers" in body
        assert body["tiers"]["semantic"]["count"] == 0

        # POST a semantic fact.
        stored = client.post("/api/memory/semantic", json={
            "key": "workspace",
            "value": "augment",
            "category": "env",
            "confidence": 0.9,
        }).json()
        assert stored["key"] == "workspace"
        assert any(f["key"] == "workspace" for f in stored["facts"])

        # Working memory PUT.
        wm = client.post("/api/memory/working", json={
            "key": "focus", "value": "tiered memory", "priority": 9,
        }).json()
        assert any(i["key"] == "focus" for i in wm["items"])

        # Learn a procedure.
        proc = client.post("/api/memory/procedural", json={
            "name": "ship_change",
            "steps": ["read", "edit", "verify"],
            "trigger": "small change",
            "success_rate": 1.0,
        }).json()
        assert proc["name"] == "ship_change"

        # GET per-tier listings.
        semantic = client.get("/api/memory/semantic").json()
        assert any(item["key"] == "workspace" for item in semantic["items"])
        procedural = client.get("/api/memory/procedural").json()
        assert any(item["name"] == "ship_change" for item in procedural["items"])

        # Search across tiers via /retrieve.
        retr = client.get("/api/memory/retrieve", params={"q": "workspace"}).json()
        assert retr["query"] == "workspace"
        assert any(r["tier"] == "semantic" for r in retr["results"])

        # Tier search via /memory/{tier}?q=...
        search = client.get("/api/memory/semantic", params={"q": "augment"}).json()
        assert search["items"], "semantic search must return the stored fact"

        # Delete the semantic fact.
        removed = client.delete("/api/memory/semantic/workspace").json()
        assert removed["removed"] is True
        snapshot = client.get("/api/memory/tiers").json()
        assert snapshot["semantic"]["count"] == 0

        # Manual consolidate puts an episode on disk.
        consolidated = client.post("/api/memory/consolidate", json={
            "session_id": "sess_test", "summary": "manual consolidate", "outcome": "success",
        }).json()
        assert consolidated["episodic"]["count"] >= 1


def test_memory_context_block_combines_tiers(tmp_path):
    system = MemorySystem(tmp_path)
    system.working.put("focus", "current task")
    system.semantic.store("alpha", "the first letter", confidence=0.9)
    system.episodic.record(session_id="x", summary="something happened")

    block = system.context_block(query="alpha")
    assert "[WORKING MEMORY]" in block
    assert "[RELEVANT MEMORIES]" in block
    # Without a query, falls back to recent episodes.
    no_q = system.context_block()
    assert "[EPISODIC MEMORY" in no_q
