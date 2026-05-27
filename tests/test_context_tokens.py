"""Tests for ``augment.context.tokens`` — real-tokenizer counting + truncation."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from augment.context import tokens as tok
from augment.context.tokens import (
    DEFAULT_ENCODING,
    count_tokens,
    encoding_name_for_model,
    is_available,
    truncate_to_token_budget,
)


# ── Encoding picker ────────────────────────────────────────────────────


def test_encoding_for_gpt_4o_family_uses_o200k():
    assert encoding_name_for_model("gpt-4o") == "o200k_base"
    assert encoding_name_for_model("gpt-4o-mini") == "o200k_base"
    assert encoding_name_for_model("gpt-4.1") == "o200k_base"
    assert encoding_name_for_model("o1") == "o200k_base"
    assert encoding_name_for_model("o3-mini") == "o200k_base"
    assert encoding_name_for_model("gpt-5") == "o200k_base"
    assert encoding_name_for_model("codex-cli") == "o200k_base"


def test_encoding_for_gpt_4_uses_cl100k():
    """gpt-4 (no suffix) and gpt-3.5 use the older cl100k_base encoding."""
    assert encoding_name_for_model("gpt-4") == "cl100k_base"
    assert encoding_name_for_model("gpt-4-turbo") == "cl100k_base"
    assert encoding_name_for_model("gpt-3.5-turbo") == "cl100k_base"


def test_encoding_for_non_openai_families_falls_back_to_o200k():
    """Claude / Llama / Mistral / Qwen / Gemini / DeepSeek all use the
    universal-estimator default."""
    for model in (
        "claude-sonnet-4-20250514",
        "claude-3-haiku",
        "llama-3.1-70b",
        "llama-4-maverick",
        "mistral-large-latest",
        "mixtral-8x7b",
        "qwen-2.5-72b",
        "gemini-2.5-pro",
        "deepseek-chat",
    ):
        assert encoding_name_for_model(model) == "o200k_base", model


def test_encoding_for_unknown_or_empty_returns_default():
    assert encoding_name_for_model("") == DEFAULT_ENCODING
    assert encoding_name_for_model("totally-made-up-foo-bar") == DEFAULT_ENCODING


# ── Counter: exact OpenAI counts ───────────────────────────────────────


def test_count_tokens_returns_zero_for_empty_input():
    assert count_tokens("") == 0
    assert count_tokens("", model="gpt-4o") == 0


@pytest.mark.skipif(not is_available(), reason="tiktoken not installed")
def test_count_tokens_matches_known_tiktoken_outputs():
    """Anchor a few known-stable values so we'd notice if tiktoken's
    behaviour changed across a major version bump."""
    # "hello world" → 2 tokens in cl100k_base AND o200k_base.
    assert count_tokens("hello world", model="gpt-4o") == 2
    assert count_tokens("hello world", model="gpt-4") == 2
    # A single ASCII char is still a token.
    assert count_tokens("x", model="gpt-4o") == 1


@pytest.mark.skipif(not is_available(), reason="tiktoken not installed")
def test_count_tokens_bpe_compresses_repeats():
    """BPE merges runs of the same char — 400 x's should NOT cost 400 tokens."""
    n = count_tokens("x" * 400, model="gpt-4o")
    assert 0 < n < 400 / 4  # well under chars/4


# ── Counter: fallback path ─────────────────────────────────────────────


def test_count_tokens_falls_back_to_chars_div_4_when_tiktoken_missing():
    """When tiktoken isn't loadable, count_tokens uses len(text)//4."""
    with patch.object(tok, "_encoder", return_value=None):
        # The encoder cache is patched to always return None.
        tok.clear_cache()  # important: don't serve a real cached value
        assert count_tokens("x" * 400) == 100  # 400 // 4
        assert count_tokens("hello world") == 2  # 11 // 4 = 2
        assert count_tokens("a") == 0  # 1 // 4 = 0


def test_count_tokens_swallows_encoder_exception():
    """If the encoder raises (corrupted text, etc.) we fall back gracefully."""
    class FakeEncoder:
        def encode(self, *_args, **_kwargs):
            raise RuntimeError("synthetic")

    with patch.object(tok, "_encoder", return_value=FakeEncoder()):
        tok.clear_cache()
        # Falls back to chars/4
        assert count_tokens("hello world") == 2


# ── Counter: cache behaviour ───────────────────────────────────────────


@pytest.mark.skipif(not is_available(), reason="tiktoken not installed")
def test_count_tokens_caches_repeated_calls():
    """The second call for the same text/model should not re-encode."""
    tok.clear_cache()
    text = "the quick brown fox jumps over the lazy dog"
    first = count_tokens(text, model="gpt-4o")
    # After one call, the cache is warm. Now break the encoder; if it
    # were still going through, this would crash.
    with patch.object(tok, "_encoder", return_value=None):
        # The fallback returns len//4 = 10; but the cache returns first.
        second = count_tokens(text, model="gpt-4o")
    assert first == second


# ── Truncator: exact-token slicing ─────────────────────────────────────


@pytest.mark.skipif(not is_available(), reason="tiktoken not installed")
def test_truncate_lands_within_token_budget():
    """The truncated text's token count must be <= the requested budget."""
    text = "The quick brown fox jumps over the lazy dog. " * 200  # ~9000 chars
    for budget in (5, 25, 100, 500):
        out = truncate_to_token_budget(text, budget, model="gpt-4o")
        assert count_tokens(out, model="gpt-4o") <= budget, (
            f"truncate to {budget} produced {count_tokens(out)} tokens"
        )


@pytest.mark.skipif(not is_available(), reason="tiktoken not installed")
def test_truncate_returns_input_unchanged_when_already_under_budget():
    text = "short"
    out = truncate_to_token_budget(text, 1000, model="gpt-4o")
    assert out == text


def test_truncate_zero_budget_returns_empty():
    assert truncate_to_token_budget("anything here", 0) == ""
    assert truncate_to_token_budget("anything here", -1) == ""
    assert truncate_to_token_budget("", 100) == ""


def test_truncate_falls_back_to_char_slice_when_tiktoken_unavailable():
    """Without tiktoken we slice by chars at the 4x heuristic."""
    with patch.object(tok, "_encoder", return_value=None):
        out = truncate_to_token_budget("x" * 100, 10)
        assert out == "x" * 40  # 10 tokens * 4 chars


# ── is_available diagnostic ────────────────────────────────────────────


def test_is_available_returns_bool():
    """Whether tiktoken is loadable or not, this is a clean boolean."""
    assert isinstance(is_available(), bool)
