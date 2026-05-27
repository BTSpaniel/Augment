"""Integration tests for the new model-aware ContextBuilder.

Verifies:
* The assembled prompt's budget scales with the active model's context
  window (the whole point of the port).
* Sections are emitted in smart_top → dumb_middle → smart_bottom order.
* The stats dict surfaces the new fields.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from augment.config import AppConfig, ContextConfig, LoopConfig, ProviderConfig, ServerConfig
from augment.context.builder import ContextBuilder
from augment.context.memory import ChatMessage, MemoryStore


def _msg(role: str, content: str) -> ChatMessage:
    """Construct a ChatMessage with a fake timestamp (tests don't care)."""
    return ChatMessage(role=role, content=content, ts=0.0)


def _make_config(tmp_path: Path, **ctx_overrides) -> AppConfig:
    return AppConfig(
        server=ServerConfig(),
        provider=ProviderConfig(),
        loop=LoopConfig(),
        context=ContextConfig(**ctx_overrides),
        workspace_root=tmp_path / "ws",
        data_dir=tmp_path / "data",
        scratch_root=tmp_path / "scratch",
    )


def _make_builder(tmp_path, *, window_tokens=None, model="gpt-4o", **ctx_overrides):
    cfg = _make_config(tmp_path, **ctx_overrides)
    cfg.workspace_root.mkdir(parents=True, exist_ok=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.scratch_root.mkdir(parents=True, exist_ok=True)
    mem = MemoryStore(cfg.data_dir)
    provider = (lambda: window_tokens) if window_tokens else None
    model_provider = (lambda: model) if model else None
    return ContextBuilder(
        cfg, mem,
        context_window_provider=provider,
        active_model_provider=model_provider,
    )


# ── Model-aware budget scaling ────────────────────────────────────────


def test_200k_model_allows_far_more_history_than_32k(tmp_path):
    """The whole point: bigger window → bigger assembled prompt.

    Pumps in enough history that the 32k window has to truncate but the
    200k window doesn't.
    """
    # 600 turns × 1000 chars ≈ 600 KB → ~150_000 tokens of raw input.
    # Beyond the 32k budget (history slot gets ~4k tokens ≈ 16 KB) but
    # under the 200k budget (history slot ~31k tokens ≈ 125 KB).
    big_history = [_msg("user", "x" * 1000) for _ in range(600)]

    small = _make_builder(tmp_path / "s", total_budget_chars=0, window_tokens=32_768)
    large = _make_builder(tmp_path / "l", total_budget_chars=0, window_tokens=200_000)

    small_prompt = small.build(message="hi", history=big_history)
    large_prompt = large.build(message="hi", history=big_history)

    assert len(large_prompt) >= len(small_prompt) * 2, (
        f"expected 200k prompt ({len(large_prompt)}) to be much larger "
        f"than 32k prompt ({len(small_prompt)})"
    )


def test_stats_exposes_context_window_and_budget(tmp_path):
    builder = _make_builder(tmp_path, window_tokens=128_000)
    builder.build(message="hi", history=[])
    stats = builder.stats()
    assert stats["context_window_tokens"] == 128_000
    # target_utilization defaults to 0.5 → 0.5 * (128_000 - 4_096) ≈ 61_952
    expected_tokens = int((128_000 - 4_096) * 0.5)
    assert abs(stats["total_budget_tokens"] - expected_tokens) <= 5


def test_max_output_reserved_from_total(tmp_path):
    """Bumping max_output_tokens should shrink the effective input
    budget by the same amount (× target_utilization)."""
    small_output = _make_builder(tmp_path / "a", window_tokens=128_000,
                                 max_output_tokens=4096)
    big_output = _make_builder(tmp_path / "b", window_tokens=128_000,
                               max_output_tokens=32_000)
    small_output.build(message="hi", history=[])
    big_output.build(message="hi", history=[])
    assert (
        small_output.stats()["total_budget_tokens"]
        > big_output.stats()["total_budget_tokens"]
    )


def test_target_utilization_affects_budget(tmp_path):
    """target_utilization=1.0 should yield twice the budget of 0.5."""
    half = _make_builder(tmp_path / "h", window_tokens=200_000,
                         target_utilization=0.5)
    full = _make_builder(tmp_path / "f", window_tokens=200_000,
                         target_utilization=1.0)
    half.build(message="hi", history=[])
    full.build(message="hi", history=[])
    assert full.stats()["total_budget_tokens"] > half.stats()["total_budget_tokens"] * 1.5


# ── Fallback when no provider configured ──────────────────────────────


def test_fallback_to_legacy_char_cap_when_no_provider(tmp_path):
    """With no context_window_provider, the builder honours the legacy
    char cap so existing tests + setups don't explode."""
    builder = _make_builder(tmp_path, total_budget_chars=8000)
    out = builder.build(message="hi", history=[])
    assert len(out) <= 8000
    stats = builder.stats()
    assert stats["context_window_tokens"] == 0
    # total_budget exposed in chars uses the legacy cap.
    assert stats["total_budget"] == 8000


# ── Zone ordering ─────────────────────────────────────────────────────


def test_smart_top_sections_come_before_dumb_middle_in_output(tmp_path):
    """The assembled prompt must put identity (smart_top) before tools
    (dumb_middle) before recent_history (smart_bottom)."""
    builder = _make_builder(tmp_path, window_tokens=128_000)
    history = [_msg("user", "HISTORY_MARKER_XYZ")]
    prompt = builder.build(
        message="hi",
        history=history,
        soul_context="[AGENT SOUL]\nSOUL_MARKER",
        memory_tiers="[MEMORY TIERS]\nTIERS_MARKER",
    )
    # Identity always present (it's a non-empty default).
    idx_identity = prompt.find("[AUGMENT]")
    idx_tiers = prompt.find("TIERS_MARKER")
    idx_history = prompt.find("HISTORY_MARKER_XYZ")
    assert idx_identity != -1
    assert idx_history != -1
    assert idx_identity < idx_history, "identity must precede recent_history"
    if idx_tiers != -1:
        assert idx_identity < idx_tiers < idx_history, (
            "dumb_middle (memory_tiers) must sit between smart_top "
            "(identity) and smart_bottom (recent_history)"
        )


def test_section_records_carry_zone_label(tmp_path):
    builder = _make_builder(tmp_path, window_tokens=128_000)
    builder.build(
        message="hi",
        history=[_msg("user", "hello")],
        soul_context="some soul text",
    )
    stats = builder.stats()
    sections = {s["name"]: s for s in stats["sections"]}
    assert sections["identity"]["zone"] == "smart_top"
    assert sections["agent_soul"]["zone"] == "smart_top"
    assert sections["memory"]["zone"] == "dumb_middle"
    assert sections["recent_history"]["zone"] == "smart_bottom"


# ── Smart-bottom recency invariant ────────────────────────────────────


def test_stats_exposes_tokenizer_diagnostics(tmp_path):
    """stats() must report which encoding is in use so the UI can
    surface whether real token counting is active."""
    builder = _make_builder(tmp_path, window_tokens=128_000, model="gpt-4o")
    builder.build(message="hi", history=[])
    info = builder.stats().get("tokenizer") or {}
    assert info.get("active_model") == "gpt-4o"
    assert info.get("encoding") == "o200k_base"
    # available is a bool — true when tiktoken is installed (CI: it is).
    assert isinstance(info.get("available"), bool)


def test_section_records_carry_token_counts(tmp_path):
    """Per-section records expose real token counts (not just chars)."""
    builder = _make_builder(tmp_path, window_tokens=128_000, model="gpt-4o")
    builder.build(
        message="hi",
        history=[_msg("user", "hello world")],
        soul_context="[AGENT SOUL]\nyou are augment",
    )
    sections = {s["name"]: s for s in builder.stats()["sections"]}
    identity = sections["identity"]
    # Real tokens > 0 for the always-present identity block.
    assert identity["original_tokens"] > 0
    assert identity["final_tokens"] > 0
    # Token count should be a tighter estimate than chars/4 for English.
    # identity is ~340 chars → chars/4 = 85, real ≈ 60-80.
    assert identity["original_tokens"] < identity["original_chars"]


def test_recent_history_lives_at_the_end_of_prompt(tmp_path):
    """Recent history must be in the smart_bottom zone (final block) to
    benefit from recency bias in the U-shaped attention curve."""
    builder = _make_builder(tmp_path, window_tokens=128_000)
    history = [_msg("user", f"turn-{i}") for i in range(5)]
    prompt = builder.build(message="hi", history=history)
    # The last history entry should appear near the end of the prompt.
    pos = prompt.find("turn-4")
    assert pos > len(prompt) * 0.4, (
        "recent_history must sit in the back half of the prompt "
        f"(found at {pos}/{len(prompt)})"
    )
