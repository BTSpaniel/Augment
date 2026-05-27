"""Tests for ``augment.context.budget.ContextBudgetAllocator``."""
from __future__ import annotations

from augment.context.budget import (
    DEFAULT_SLOTS,
    AllocationResult,
    ContextBudgetAllocator,
)


# ── Phase 1: targets ─────────────────────────────────────────────────


def test_targets_default_slots_sum_to_total_budget():
    """The sum of all targets at default percentages should be within a
    handful of tokens of the total (allowing for integer truncation)."""
    total = 100_000
    alloc = ContextBudgetAllocator(total)
    targets = alloc.get_targets()
    s = sum(targets.values())
    assert s <= total
    assert s >= total - len(DEFAULT_SLOTS)  # at most 1 token of slack per slot
    # Every default section should have an entry.
    for name in DEFAULT_SLOTS:
        assert name in targets


def test_targets_respect_min_floor():
    """A section's target should never drop below its min_pct floor."""
    total = 1_000_000
    # Override identity to a TINY percentage; min_pct should still kick in.
    alloc = ContextBudgetAllocator(total, overrides={"identity": 0.01})
    targets = alloc.get_targets()
    # Default identity min_pct is 3% → 30_000 tokens. (Lowered from 4%
    # when the project_conventions / user_rules / coding_contract slots
    # were carved into the smart_top zone.)
    assert targets["identity"] >= 30_000


def test_targets_respect_max_ceiling():
    """A section's target should never exceed its max_pct ceiling."""
    total = 100_000
    # Push agent_soul to 99% → max_pct (12%) should clamp it.
    alloc = ContextBudgetAllocator(total, overrides={"agent_soul": 99.0})
    targets = alloc.get_targets()
    # Default agent_soul max_pct is 12% → 12_000 tokens.
    assert targets["agent_soul"] <= 12_000


def test_normalization_when_overrides_dont_sum_to_100():
    """If the user's overrides skew the total, percentages re-scale."""
    total = 100_000
    # Massively bump identity; everything else should scale down so the
    # total still allocates around 100% of the budget.
    alloc = ContextBudgetAllocator(total, overrides={"identity": 50.0})
    targets = alloc.get_targets()
    assert sum(targets.values()) <= total  # never over-allocate


# ── Phase 2: finalize / surplus redistribution ───────────────────────


def test_finalize_returns_allocation_result():
    alloc = ContextBudgetAllocator(50_000)
    result = alloc.finalize({})
    assert isinstance(result, AllocationResult)
    assert result.total_budget == 50_000


def test_finalize_residual_section_absorbs_leftover():
    """recent_history (residual) should grow when other sections are tiny."""
    alloc = ContextBudgetAllocator(100_000)
    # Every non-residual section uses zero — recent_history should absorb
    # the bulk of the budget.
    result = alloc.finalize({name: 0 for name in DEFAULT_SLOTS if name != "recent_history"})
    rh = result.finals["recent_history"]
    # Should be well above the default 32% target, capped at 55% max.
    assert rh >= 32_000  # at least the target
    assert rh <= 55_000  # respects max_pct ceiling


def test_finalize_surplus_redistributes_to_overflowed_sections():
    """When a section exceeds its target, it should get extra from the
    surplus pool (up to its max ceiling)."""
    alloc = ContextBudgetAllocator(100_000)
    # agent_soul wants 12000 but target is 7000 — should grow to 12000 cap.
    actuals = {name: 0 for name in DEFAULT_SLOTS}
    actuals["agent_soul"] = 12_000
    result = alloc.finalize(actuals)
    assert result.finals["agent_soul"] >= 10_000  # got extra
    assert result.finals["agent_soul"] <= 12_000  # capped at max_pct


def test_finalize_caps_at_max_pct_even_with_huge_actual():
    """A section can't grow past its max_pct ceiling, no matter what."""
    alloc = ContextBudgetAllocator(100_000)
    actuals = {name: 0 for name in DEFAULT_SLOTS}
    actuals["identity"] = 999_999  # absurd
    result = alloc.finalize(actuals)
    # identity max_pct = 15% → 15_000 tokens
    assert result.finals["identity"] <= 15_000


def test_buffer_is_never_redistributed():
    """The buffer slot should keep its target allocation, even under pressure."""
    alloc = ContextBudgetAllocator(100_000)
    actuals = {name: 99_999 for name in DEFAULT_SLOTS}  # everyone's hungry
    result = alloc.finalize(actuals)
    # buffer default = 9% → 9000 tokens
    assert result.finals["buffer"] == result.targets["buffer"]


# ── Char conversion helpers ──────────────────────────────────────────


def test_chars_for_uses_4x_factor():
    alloc = ContextBudgetAllocator(10_000)
    result = alloc.finalize({})
    rh_tokens = result.tokens_for("recent_history")
    rh_chars = result.chars_for("recent_history")
    assert rh_chars == rh_tokens * 4


def test_tokens_to_chars_and_back():
    assert ContextBudgetAllocator.tokens_to_chars(100) == 400
    assert ContextBudgetAllocator.chars_to_tokens(400) == 100
    # Edge cases
    assert ContextBudgetAllocator.tokens_to_chars(0) == 0
    assert ContextBudgetAllocator.tokens_to_chars(-5) == 0


# ── Model-scaling smoke test ─────────────────────────────────────────


def test_budget_scales_with_total():
    """A 200k context model should get ~6× more recent_history than a 32k one."""
    small = ContextBudgetAllocator(32_768).finalize({})
    big = ContextBudgetAllocator(200_000).finalize({})
    assert big.tokens_for("recent_history") > small.tokens_for("recent_history") * 5


def test_custom_section_can_be_added_via_override():
    """Brand-new section names (not in DEFAULT_SLOTS) can be added with a
    3-tuple override and get allocated."""
    alloc = ContextBudgetAllocator(
        100_000,
        overrides={"experimental": (5.0, 1.0, 10.0)},
    )
    targets = alloc.get_targets()
    assert "experimental" in targets
    assert targets["experimental"] > 0


