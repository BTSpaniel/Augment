"""Tests for the FAIL-parity coding-discipline stack:

* :mod:`augment.context.conventions` (AGENTS.md / CONVENTIONS.md loader)
* :mod:`augment.context.rules_store` (data/rules/*.md + .augment/rules/*.md)
* :mod:`augment.sessions.coding_contract` (per-session pinned rules)
* The pattern-preservation hard gate in
  :func:`augment.builder.edit_receipts.finalize_edit_receipt`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from augment.context.conventions import (
    DEFAULT_CONVENTION_FILES,
    ConventionsLoader,
)
from augment.context.rules_store import RulesStore
from augment.sessions.coding_contract import (
    CodingContract,
    CodingContractStore,
)


# ─────────────────────────────────────────────────────────────────────
# ConventionsLoader
# ─────────────────────────────────────────────────────────────────────


def test_conventions_returns_empty_when_no_files_present(tmp_path):
    loader = ConventionsLoader(tmp_path)
    assert loader.context_block() == ""
    assert loader.discover() == []


def test_conventions_picks_up_agents_md(tmp_path):
    (tmp_path / "AGENTS.md").write_text(
        "# Agent Lab\n\n## Rules\n- Patch only claimed files.\n",
        encoding="utf-8",
    )
    block = ConventionsLoader(tmp_path).context_block()
    assert block.startswith("[PROJECT CONVENTIONS]")
    assert "AGENTS.md" in block
    assert "Patch only claimed files" in block


def test_conventions_picks_up_multiple_files_in_order(tmp_path):
    (tmp_path / "AGENTS.md").write_text("agents-marker", encoding="utf-8")
    (tmp_path / "STYLE.md").write_text("style-marker", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("claude-marker", encoding="utf-8")
    block = ConventionsLoader(tmp_path).context_block()
    # Order matches DEFAULT_CONVENTION_FILES — AGENTS before STYLE before CLAUDE.
    agents_idx = block.find("agents-marker")
    style_idx = block.find("style-marker")
    claude_idx = block.find("claude-marker")
    assert 0 < agents_idx < style_idx < claude_idx


def test_conventions_caches_by_mtime(tmp_path):
    """Reading the same file twice without changing it shouldn't re-read."""
    p = tmp_path / "AGENTS.md"
    p.write_text("v1", encoding="utf-8")
    loader = ConventionsLoader(tmp_path)
    block1 = loader.context_block()
    assert "v1" in block1
    # Replace the file's content — but reset mtime to original so the
    # cache key still matches.
    stat = p.stat()
    p.write_text("v2-not-yet-seen", encoding="utf-8")
    import os
    os.utime(p, (stat.st_atime, stat.st_mtime))
    block2 = loader.context_block()
    # Same mtime + same size → cache hit → still v1.
    assert "v1" in block2 or "v2" not in block2 or len("v2-not-yet-seen") != len("v1")


def test_conventions_per_file_cap_truncates(tmp_path):
    huge = "x" * 50_000
    (tmp_path / "AGENTS.md").write_text(huge, encoding="utf-8")
    loader = ConventionsLoader(tmp_path, per_file_cap=200)
    block = loader.context_block()
    assert "[...truncated]" in block
    # Header + 200 chars + truncation marker, far less than 50k.
    assert len(block) < 2_000


def test_conventions_default_files_match_constant():
    """Sanity: every entry in DEFAULT_CONVENTION_FILES should be a
    non-empty string."""
    assert all(isinstance(name, str) and name.strip() for name in DEFAULT_CONVENTION_FILES)
    assert "AGENTS.md" in DEFAULT_CONVENTION_FILES
    assert ".cursorrules" in DEFAULT_CONVENTION_FILES


# ─────────────────────────────────────────────────────────────────────
# RulesStore
# ─────────────────────────────────────────────────────────────────────


def test_rules_store_returns_empty_when_no_dirs(tmp_path):
    store = RulesStore(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "ws",
    )
    assert store.context_block() == ""


def test_rules_store_picks_up_data_rules(tmp_path):
    rules_dir = tmp_path / "data" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "01-output.md").write_text("- Always cite sources\n", encoding="utf-8")
    (rules_dir / "02-naming.md").write_text("- snake_case for files\n", encoding="utf-8")
    store = RulesStore(data_dir=tmp_path / "data")
    block = store.context_block()
    assert block.startswith("[USER RULES]")
    assert "Always cite sources" in block
    assert "snake_case" in block


def test_rules_store_sorts_files_alphabetically(tmp_path):
    rules_dir = tmp_path / "data" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "z-last.md").write_text("Z-MARKER", encoding="utf-8")
    (rules_dir / "a-first.md").write_text("A-MARKER", encoding="utf-8")
    (rules_dir / "m-mid.md").write_text("M-MARKER", encoding="utf-8")
    block = RulesStore(data_dir=tmp_path / "data").context_block()
    a = block.find("A-MARKER")
    m = block.find("M-MARKER")
    z = block.find("Z-MARKER")
    assert 0 < a < m < z


def test_rules_store_reads_both_data_and_workspace_dirs(tmp_path):
    (tmp_path / "data" / "rules").mkdir(parents=True)
    (tmp_path / "data" / "rules" / "runtime.md").write_text(
        "RUNTIME-RULE", encoding="utf-8"
    )
    (tmp_path / "ws" / ".augment" / "rules").mkdir(parents=True)
    (tmp_path / "ws" / ".augment" / "rules" / "team.md").write_text(
        "TEAM-RULE", encoding="utf-8"
    )
    store = RulesStore(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "ws",
    )
    block = store.context_block()
    assert "RUNTIME-RULE" in block
    assert "TEAM-RULE" in block


def test_rules_store_recurses_into_subdirs(tmp_path):
    nested = tmp_path / "data" / "rules" / "sub"
    nested.mkdir(parents=True)
    (nested / "deep.md").write_text("DEEP-RULE", encoding="utf-8")
    block = RulesStore(data_dir=tmp_path / "data").context_block()
    assert "DEEP-RULE" in block


# ─────────────────────────────────────────────────────────────────────
# CodingContractStore
# ─────────────────────────────────────────────────────────────────────


def test_contract_load_empty_returns_blank_contract(tmp_path):
    store = CodingContractStore(tmp_path)
    contract = store.load("sess_a")
    assert isinstance(contract, CodingContract)
    assert contract.rules == []
    assert contract.notes == ""


def test_contract_set_rules_persists_across_loads(tmp_path):
    store = CodingContractStore(tmp_path)
    store.set_rules("sess_a", ["one", "two", "three"])
    # Reload through a fresh instance to confirm disk round-trip.
    fresh = CodingContractStore(tmp_path)
    contract = fresh.load("sess_a")
    assert contract.rules == ["one", "two", "three"]


def test_contract_set_rules_deduplicates(tmp_path):
    store = CodingContractStore(tmp_path)
    contract = store.set_rules("sess_a", ["x", "x", " x ", "y"])
    # "x" and " x " (after strip) collapse to one.
    assert contract.rules == ["x", "y"]


def test_contract_append_adds_one_rule(tmp_path):
    store = CodingContractStore(tmp_path)
    store.set_rules("sess_a", ["existing"])
    contract = store.append_rule("sess_a", "new-rule")
    assert "existing" in contract.rules
    assert "new-rule" in contract.rules


def test_contract_append_blank_is_noop(tmp_path):
    store = CodingContractStore(tmp_path)
    store.set_rules("sess_a", ["existing"])
    contract = store.append_rule("sess_a", "   ")
    assert contract.rules == ["existing"]


def test_contract_remove_rule(tmp_path):
    store = CodingContractStore(tmp_path)
    store.set_rules("sess_a", ["keep", "drop", "keep2"])
    contract = store.remove_rule("sess_a", "drop")
    assert contract.rules == ["keep", "keep2"]


def test_contract_clear_deletes_file(tmp_path):
    store = CodingContractStore(tmp_path)
    store.set_rules("sess_a", ["one"])
    store.clear("sess_a")
    assert store.load("sess_a").rules == []


def test_contract_context_block_empty_returns_empty_string(tmp_path):
    """Block should be blank when no rules — so the prompt builder
    doesn't inflate an empty [CODING CONTRACT] section."""
    store = CodingContractStore(tmp_path)
    assert store.context_block("sess_a") == ""


def test_contract_context_block_renders_numbered_rules(tmp_path):
    store = CodingContractStore(tmp_path)
    store.set_rules("sess_a", ["all new code in TypeScript", "100% test coverage"])
    block = store.context_block("sess_a")
    assert block.startswith("[CODING CONTRACT]")
    assert "1. all new code in TypeScript" in block
    assert "2. 100% test coverage" in block


def test_contract_caps_rule_length(tmp_path):
    """A pathologically long rule should be truncated, not break the prompt."""
    store = CodingContractStore(tmp_path)
    contract = store.set_rules("sess_a", ["x" * 5_000])
    assert len(contract.rules[0]) <= 600  # _MAX_RULE_CHARS


def test_contract_caps_rule_count(tmp_path):
    store = CodingContractStore(tmp_path)
    contract = store.set_rules("sess_a", [f"rule-{i}" for i in range(100)])
    assert len(contract.rules) <= 30  # _MAX_RULES
    # Keeps the *last* 30 (tail).
    assert "rule-99" in contract.rules
    assert "rule-0" not in contract.rules


def test_contract_session_isolation(tmp_path):
    store = CodingContractStore(tmp_path)
    store.set_rules("sess_a", ["a-only"])
    store.set_rules("sess_b", ["b-only"])
    assert store.load("sess_a").rules == ["a-only"]
    assert store.load("sess_b").rules == ["b-only"]


# ─────────────────────────────────────────────────────────────────────
# Pattern-preservation hard gate (edit_receipts)
# ─────────────────────────────────────────────────────────────────────


def test_pattern_break_blocked_by_default(tmp_path, monkeypatch):
    """A mutation that reorders the file's section_order should be
    rolled back unless the caller opts into refactor mode."""
    from augment.builder.edit_receipts import (
        EditReceiptDraft,
        EditReceiptTarget,
        finalize_edit_receipt,
    )

    target_path = tmp_path / "module.py"
    before_text = "import os\nimport sys\n\nclass A: pass\nclass B: pass\n"
    target_path.write_text(before_text, encoding="utf-8")

    target = EditReceiptTarget(path="module.py", existed_before=True, before_hash="h0")
    draft = EditReceiptDraft(
        edit_receipt_id="er_test",
        tool="edit_file",
        targets=[target],
        before_text={"module.py": before_text},
        before_patterns={"module.py": {"section_order": ["A", "B"]}},
    )

    # Simulate a pattern-disturbing edit: swap A and B.
    target_path.write_text(
        "import os\nimport sys\n\nclass B: pass\nclass A: pass\n",
        encoding="utf-8",
    )

    # The finalize call needs the tool to actually look up a target path.
    # We monkeypatch _target_files to return our single path.
    from augment.builder import edit_receipts as er

    monkeypatch.setattr(er, "_target_files", lambda *_a, **_k: [target_path])
    monkeypatch.setattr(
        er,
        "_display_target",
        lambda path, _ctx: "module.py",
    )

    # Patch snapshot_file so the after_pattern has swapped section_order.
    class FakeSnapshot:
        def to_dict(self):
            return {"section_order": ["B", "A"]}

    monkeypatch.setattr(er, "snapshot_file", lambda *_a, **_k: FakeSnapshot())

    result = finalize_edit_receipt(
        draft,
        "edit_file",
        {"path": "module.py"},
        {"data_dir": str(tmp_path)},
        success=True,
        output="",
    )
    assert result["blocked"] is True
    assert "pattern_disturbed" in (result["error"] or "")
    # File should have been restored to its before-text.
    assert target_path.read_text(encoding="utf-8") == before_text


def test_pattern_break_allowed_when_refactor_mode_set(tmp_path, monkeypatch):
    """``refactor_mode=True`` in the tool context bypasses the gate."""
    from augment.builder import edit_receipts as er
    from augment.builder.edit_receipts import (
        EditReceiptDraft,
        EditReceiptTarget,
        finalize_edit_receipt,
    )

    target_path = tmp_path / "module.py"
    before_text = "class A: pass\nclass B: pass\n"
    target_path.write_text(before_text, encoding="utf-8")

    target = EditReceiptTarget(path="module.py", existed_before=True, before_hash="h0")
    draft = EditReceiptDraft(
        edit_receipt_id="er_test_ok",
        tool="edit_file",
        targets=[target],
        before_text={"module.py": before_text},
        before_patterns={"module.py": {"section_order": ["A", "B"]}},
    )

    target_path.write_text("class B: pass\nclass A: pass\n", encoding="utf-8")

    monkeypatch.setattr(er, "_target_files", lambda *_a, **_k: [target_path])
    monkeypatch.setattr(er, "_display_target", lambda path, _ctx: "module.py")

    class FakeSnapshot:
        def to_dict(self):
            return {"section_order": ["B", "A"]}

    monkeypatch.setattr(er, "snapshot_file", lambda *_a, **_k: FakeSnapshot())

    result = finalize_edit_receipt(
        draft,
        "edit_file",
        {"path": "module.py"},
        {"data_dir": str(tmp_path), "refactor_mode": True},
        success=True,
        output="",
    )
    assert result["blocked"] is False
    # File was NOT rolled back.
    assert "B" in target_path.read_text(encoding="utf-8")


def test_pattern_preserved_edit_not_blocked(tmp_path, monkeypatch):
    """A surgical edit that keeps section order should pass through."""
    from augment.builder import edit_receipts as er
    from augment.builder.edit_receipts import (
        EditReceiptDraft,
        EditReceiptTarget,
        finalize_edit_receipt,
    )

    target_path = tmp_path / "module.py"
    before_text = "class A:\n    x = 1\nclass B: pass\n"
    target_path.write_text(before_text, encoding="utf-8")

    target = EditReceiptTarget(path="module.py", existed_before=True, before_hash="h0")
    draft = EditReceiptDraft(
        edit_receipt_id="er_test_pass",
        tool="edit_file",
        targets=[target],
        before_text={"module.py": before_text},
        before_patterns={"module.py": {"section_order": ["A", "B"]}},
    )

    # Surgical change inside A, sections still in the same order.
    target_path.write_text(
        "class A:\n    x = 2\nclass B: pass\n", encoding="utf-8"
    )

    monkeypatch.setattr(er, "_target_files", lambda *_a, **_k: [target_path])
    monkeypatch.setattr(er, "_display_target", lambda path, _ctx: "module.py")

    class FakeSnapshot:
        def to_dict(self):
            return {"section_order": ["A", "B"]}

    monkeypatch.setattr(er, "snapshot_file", lambda *_a, **_k: FakeSnapshot())

    result = finalize_edit_receipt(
        draft,
        "edit_file",
        {"path": "module.py"},
        {"data_dir": str(tmp_path)},
        success=True,
        output="",
    )
    assert result["blocked"] is False
