"""Tests for the mind / planning / builder layers ported from FAIL."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from augment.builder import (
    PatternSnapshot,
    check_read_before_edit,
    default_file_policies,
    detect_environment,
    resolve_file_policy,
    snapshot_file,
)
from augment.builder.read_gate import file_hash
from augment.main import app
from augment.mind import Mind
from augment.mind.drives import DriveSystem
from augment.mind.personality import Mood, Personality
from augment.planning import PlanGraph, PlanStateStore, StructuredPlanner


# ── Mind ────────────────────────────────────────────────────────────


def test_personality_mood_shift_persists(tmp_path):
    p = Personality(tmp_path)
    original_valence = p.mood.valence
    p.on_event("task_success", "ran a green test")
    assert p.mood.valence > original_valence
    # Reload from disk and confirm state persisted.
    reloaded = Personality(tmp_path)
    assert reloaded.mood.valence == p.mood.valence
    assert reloaded.mood.label == p.mood.label
    assert any("task_success" in entry.get("reason", "") for entry in reloaded.mood.shift_history)


def test_drive_system_satisfy_decays_urgency(tmp_path):
    drives = DriveSystem(tmp_path)
    initial = drives.get("completion").urgency
    drives.satisfy("completion", 0.5)
    assert drives.get("completion").urgency < initial
    reloaded = DriveSystem(tmp_path)
    assert reloaded.get("completion").urgency == drives.get("completion").urgency


def test_mind_context_block_includes_personality_and_drives(tmp_path):
    mind = Mind(tmp_path)
    block = mind.context_block()
    assert "[PERSONALITY STATE]" in block
    assert "[DRIVES]" in block


def test_mood_label_resolves_extremes():
    mood = Mood()
    mood.shift(0.4, 0.4, reason="boost")
    assert mood.label in {"enthusiastic", "content", "alert", "neutral"}
    mood.shift(-2.0, -2.0, reason="crash")
    assert mood.label in {"sad", "angry", "disappointed", "frustrated", "distressed", "melancholic"}


# ── Planning ────────────────────────────────────────────────────────


def test_heuristic_planner_emits_four_step_plan(tmp_path):
    planner = StructuredPlanner()
    graph = planner.heuristic_plan(
        "edit augment/service.py to add a planner",
        session_id="sess_abc",
        cwd=str(tmp_path),
    )
    assert len(graph.steps) == 4
    assert "augment/service.py" in (graph.metadata.get("path_hints") or [])
    # The third step (implement) should flag approval because the goal mentions 'edit'.
    assert graph.steps[2].requires_approval is True


def test_plan_state_store_roundtrip(tmp_path):
    store = PlanStateStore(tmp_path)
    graph = PlanGraph(session_id="sess_round", goal="round-trip", steps=[])
    store.save(graph)
    loaded = store.load("sess_round")
    assert loaded is not None
    assert loaded.session_id == "sess_round"
    assert loaded.goal == "round-trip"
    # delete removes the file.
    assert store.delete("sess_round") is True
    assert store.load("sess_round") is None


def test_plangraph_context_block_truncates():
    # Empty graph yields no block.
    assert PlanGraph().context_block() == ""
    graph = PlanGraph(goal="x" * 5)
    block = graph.context_block(max_chars=64)
    assert block.startswith("[ACTIVE PLAN GRAPH]")
    assert len(block) <= 64 or block.endswith("[...truncated active plan graph]")


def test_planner_from_llm_json_payload(tmp_path):
    planner = StructuredPlanner()
    payload = {
        "goal": "ship",
        "success_criteria": ["lights green"],
        "steps": [{"title": "ship it", "description": "deploy"}],
    }
    graph = planner.from_llm_json(payload, cwd=str(tmp_path))
    assert graph.goal == "ship"
    assert graph.success_criteria == ["lights green"]
    assert len(graph.steps) == 1
    assert graph.steps[0].cwd == str(tmp_path)


# ── Builder ─────────────────────────────────────────────────────────


def test_file_policy_resolves_sensitive_paths():
    env_policy = resolve_file_policy(".env")
    assert env_policy.sensitive is True
    assert env_policy.risk == "critical"
    py_policy = resolve_file_policy("augment/service.py")
    assert py_policy.file_type == "backend.python"
    assert "py_compile" in py_policy.required_verification
    fallback = resolve_file_policy("random.unknown")
    assert fallback.file_type == "unknown"


def test_default_file_policies_serialise():
    policies = default_file_policies()
    assert any(p.file_type == "secrets.env" for p in policies)
    payload = [p.to_dict() for p in policies]
    assert all("pattern" in entry for entry in payload)


def test_pattern_snapshot_python(tmp_path: Path):
    target = tmp_path / "snip.py"
    target.write_text(
        "from x import y\n\nclass A:\n    def m(self):\n        return 1\n\ndef foo():\n    pass\n",
        encoding="utf-8",
    )
    snap = snapshot_file(target)
    assert isinstance(snap, PatternSnapshot)
    assert snap.language == "python"
    assert "imports" in snap.section_order
    assert "classes" in snap.section_order
    assert "A" in snap.symbols and "foo" in snap.symbols


def test_environment_snapshot_shape():
    env = detect_environment().to_dict()
    assert "platform" in env and "tools" in env
    # `python` probe should always succeed because it uses sys.executable.
    assert env["tools"]["python"]["available"] is True


def test_read_gate_blocks_without_receipt(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "file.py"
    target.write_text("x = 1\n", encoding="utf-8")
    context = {
        "workspace_root": str(workspace),
        "read_provenance": [],
    }
    error = check_read_before_edit("edit_file", {"path": "file.py", "old_string": "x"}, context)
    assert error.startswith("builder_gate_no_read_receipt")


def test_edit_receipt_records_diff_on_successful_write(tmp_path: Path):
    """Mutation tools that succeed should produce a recorded receipt with a diff preview."""
    from augment.builder.edit_receipts import (
        finalize_edit_receipt,
        prepare_edit_receipt,
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "hello.py"
    target.write_text("print('one')\n", encoding="utf-8")

    data_dir = tmp_path / "data"
    context = {"workspace_root": str(workspace), "data_dir": str(data_dir)}

    args = {"path": "hello.py"}
    draft = prepare_edit_receipt("write_file", args, context)
    assert draft is not None and len(draft.targets) == 1
    assert draft.targets[0].existed_before is True

    # Simulate a normal targeted edit.
    target.write_text("print('one')\nprint('two')\n", encoding="utf-8")
    outcome = finalize_edit_receipt(draft, "write_file", args, context, success=True, output="")
    assert outcome["blocked"] is False
    receipt = outcome["receipt"]
    assert receipt["status"] == "recorded"
    assert receipt["targets"][0]["pattern_preserved"] in (True, False)  # at least populated
    assert "+print('two')" in receipt["targets"][0]["diff_preview"]
    persisted = (data_dir / "edit_receipts" / f"{receipt['edit_receipt_id']}.json")
    assert persisted.exists()


def test_edit_receipt_blocks_and_restores_full_rewrite(tmp_path: Path):
    """Massive rewrites should be rolled back when refactor mode is off."""
    from augment.builder.edit_receipts import (
        finalize_edit_receipt,
        prepare_edit_receipt,
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "core.py"
    original_lines = "\n".join(f"def func_{i}(): return {i}" for i in range(40)) + "\n"
    target.write_text(original_lines, encoding="utf-8")

    context = {"workspace_root": str(workspace), "data_dir": str(tmp_path / "data")}
    args = {"path": "core.py"}

    draft = prepare_edit_receipt("write_file", args, context)
    assert draft is not None

    # Completely replace the file.
    target.write_text("print('nuked')\n", encoding="utf-8")
    outcome = finalize_edit_receipt(draft, "write_file", args, context, success=True, output="")

    assert outcome["blocked"] is True
    assert "full_rewrite_blocked" in outcome["error"]
    # File should have been restored to its prior contents.
    assert target.read_text(encoding="utf-8") == original_lines


def test_verification_profile_runs_py_compile(tmp_path: Path):
    from augment.builder import run_verification_profile

    workspace = tmp_path / "ws"
    workspace.mkdir()
    good = workspace / "ok.py"
    good.write_text("x = 1\n", encoding="utf-8")
    bad = workspace / "bad.py"
    bad.write_text("def broken(:\n", encoding="utf-8")  # syntax error

    result_ok = run_verification_profile(workspace, ["ok.py"]).to_dict()
    assert result_ok["profile"] == "backend.python"
    py_checks_ok = [c for c in result_ok["checks"] if c["name"] == "py_compile"]
    assert py_checks_ok and py_checks_ok[0]["status"] == "passed"

    result_bad = run_verification_profile(workspace, ["bad.py"]).to_dict()
    py_checks_bad = [c for c in result_bad["checks"] if c["name"] == "py_compile"]
    assert py_checks_bad and py_checks_bad[0]["status"] == "failed"
    assert result_bad["overall"] == "failed"


def test_verification_profile_json_parse(tmp_path: Path):
    from augment.builder import run_verification_profile

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "ok.json").write_text('{"a": 1}', encoding="utf-8")
    (workspace / "bad.json").write_text("{not json", encoding="utf-8")

    res = run_verification_profile(workspace, ["ok.json", "bad.json"]).to_dict()
    assert res["profile"] == "config.json"
    parse = next(c for c in res["checks"] if c["name"] == "json_parse")
    assert parse["status"] == "failed"
    assert "bad.json" in parse["evidence"]


def test_read_gate_accepts_matching_receipt(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "file.py"
    target.write_text("x = 1\n", encoding="utf-8")
    receipt = {
        "path": "file.py",
        "content_hash": file_hash(target),
        "start_line": 1,
        "end_line": 1,
        "total_lines": 1,
    }
    context = {
        "workspace_root": str(workspace),
        "read_provenance": [receipt],
    }
    error = check_read_before_edit("write_file", {"path": "file.py"}, context)
    assert error == ""


# ── HTTP API surfaces ───────────────────────────────────────────────


def test_api_mind_plan_and_builder_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    with TestClient(app) as client:
        # Mind
        mind = client.get("/api/mind").json()
        assert "personality" in mind and "drives" in mind and "thinking" in mind
        event = client.post("/api/mind/event", json={"event_type": "user_praise", "detail": "nice"}).json()
        assert event["personality"]["mood"]["valence"] >= mind["personality"]["mood"]["valence"]

        # Planning
        build = client.post(
            "/api/plans/build",
            json={"goal": "edit augment/service.py", "session_id": "sess_api_plan"},
        ).json()
        assert build["plan"]["session_id"] == "sess_api_plan"
        assert len(build["plan"]["steps"]) == 4

        got = client.get("/api/plans/sess_api_plan").json()
        assert got["plan"]["session_id"] == "sess_api_plan"

        listing = client.get("/api/plans").json()
        assert any(plan["session_id"] == "sess_api_plan" for plan in listing["plans"])

        deleted = client.delete("/api/plans/sess_api_plan").json()
        assert deleted["removed"] is True

        # Builder
        policies = client.get("/api/builder/policies").json()
        assert any(p["file_type"] == "secrets.env" for p in policies["policies"])
        single = client.get("/api/builder/policy", params={"path": ".env"}).json()
        assert single["policy"]["sensitive"] is True
        env = client.get("/api/builder/environment").json()
        assert "platform" in env and "tools" in env

        # Verification profiles
        profiles = client.get("/api/builder/verify/profiles").json()
        assert "backend.python" in profiles["profiles"]

        (tmp_path / "workspace").mkdir(parents=True, exist_ok=True)
        (tmp_path / "workspace" / "snippet.py").write_text("y = 2\n", encoding="utf-8")
        verify = client.post(
            "/api/builder/verify",
            json={"files": ["snippet.py"]},
        ).json()
        assert verify["result"]["profile"] == "backend.python"

        # Edit receipts (empty store).
        receipts = client.get("/api/builder/receipts").json()
        assert receipts["receipts"] == []
        missing = client.get("/api/builder/receipts/er_nonexistent").json()
        assert missing["receipt"] is None

        # Thinking lifecycle (without starting — keeps tests fast / offline).
        thinking = client.get("/api/mind/thinking").json()
        assert thinking["status"]["running"] is False
        assert thinking["log"] == []
        stopped = client.post("/api/mind/thinking/stop").json()
        assert stopped["status"]["running"] is False
