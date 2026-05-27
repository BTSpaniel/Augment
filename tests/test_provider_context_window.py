"""Tests for ``augment.providers.context_window`` resolver + adapters."""
from __future__ import annotations

from unittest.mock import patch

from augment.providers.context_window import (
    DEFAULT_FALLBACK,
    STATIC_CATALOG,
    _introspect_groq,
    _introspect_lmstudio,
    _introspect_llamacpp,
    _introspect_ollama,
    _introspect_openrouter,
    lookup_static_catalog,
    resolve_context_window,
)


# ── Static catalog ─────────────────────────────────────────────────────


def test_static_catalog_matches_anthropic_claude_4():
    assert lookup_static_catalog("claude-sonnet-4-20250514") == 200_000
    assert lookup_static_catalog("claude-opus-4-20250101") == 200_000
    assert lookup_static_catalog("claude-3.5-sonnet") == 200_000
    assert lookup_static_catalog("claude-3-haiku") == 200_000


def test_static_catalog_matches_openai_gpt_4o():
    assert lookup_static_catalog("gpt-4o") == 128_000
    assert lookup_static_catalog("gpt-4o-mini") == 128_000
    assert lookup_static_catalog("gpt-4-turbo-2024-04-09") == 128_000


def test_static_catalog_matches_openai_o1_o3_reasoners():
    assert lookup_static_catalog("o1") == 200_000
    assert lookup_static_catalog("o3-mini") == 200_000
    assert lookup_static_catalog("o3") == 200_000


def test_static_catalog_matches_legacy_openai_models():
    """gpt-4 (no suffix) is the original 8k context model."""
    assert lookup_static_catalog("gpt-4") == 8_192
    assert lookup_static_catalog("gpt-3.5-turbo") == 16_385
    assert lookup_static_catalog("gpt-3.5-turbo-16k") == 16_385


def test_static_catalog_matches_llama_families():
    assert lookup_static_catalog("llama-3.1-70b") == 128_000
    assert lookup_static_catalog("llama-4-maverick") == 128_000


def test_static_catalog_returns_none_for_unknown_model():
    assert lookup_static_catalog("") is None
    assert lookup_static_catalog("totally-made-up-model-foo") is None


def test_catalog_is_sorted_so_specific_patterns_match_first():
    """Sanity: gpt-4o should match before generic gpt-4."""
    # Both patterns exist in STATIC_CATALOG; the catalog is order-sensitive.
    assert lookup_static_catalog("gpt-4o") == 128_000  # specific wins
    assert lookup_static_catalog("gpt-4") == 8_192     # generic falls through


# ── 3-tier resolver ────────────────────────────────────────────────────


def test_explicit_override_wins_over_everything():
    profile = {
        "preset_id": "openai",
        "model": "gpt-4o",
        "context_window": 999_999,   # explicit override
    }
    assert resolve_context_window(profile, allow_introspection=False) == 999_999


def test_falls_back_to_static_catalog_when_no_introspection():
    profile = {"preset_id": "openai", "model": "gpt-4o", "context_window": 0}
    # OpenAI is not in INTROSPECTORS, so this hits the catalog tier.
    assert resolve_context_window(profile, allow_introspection=False) == 128_000


def test_returns_default_fallback_when_everything_misses():
    profile = {"preset_id": "unknown", "model": "totally-made-up", "context_window": 0}
    assert resolve_context_window(profile, allow_introspection=False) == DEFAULT_FALLBACK


def test_introspection_disabled_skips_provider_call():
    """When ``allow_introspection=False``, we never hit the network even
    for providers that have an introspection adapter."""
    profile = {
        "preset_id": "openrouter",
        "endpoint": "https://example.invalid/api/v1",
        "model": "openai/gpt-4o-mini",
        "context_window": 0,
    }
    # No exception, falls through to static catalog.
    result = resolve_context_window(profile, allow_introspection=False)
    assert result == 128_000  # static catalog match for gpt-4o-mini


# ── Adapter unit tests (mocked HTTP) ───────────────────────────────────


def _mock_get(return_value):
    """Return a context manager that patches ``requests.get`` to return
    a fake response whose ``.json()`` yields ``return_value``."""
    class FakeResp:
        ok = True
        def json(self):
            return return_value
    return patch("requests.get", return_value=FakeResp())


def _mock_post(return_value):
    class FakeResp:
        ok = True
        def json(self):
            return return_value
    return patch("requests.post", return_value=FakeResp())


def test_openrouter_adapter_reads_context_length():
    profile = {
        "endpoint": "https://openrouter.ai/api/v1",
        "model": "anthropic/claude-3.5-sonnet",
        "api_key": "sk-or-fake",
    }
    body = {
        "data": [
            {"id": "anthropic/claude-3.5-sonnet", "context_length": 200_000},
            {"id": "openai/gpt-4o-mini", "context_length": 128_000},
        ]
    }
    with _mock_get(body):
        assert _introspect_openrouter(profile) == 200_000


def test_openrouter_adapter_falls_back_to_top_provider_field():
    profile = {
        "endpoint": "https://openrouter.ai/api/v1",
        "model": "anthropic/claude-3.5-sonnet",
    }
    body = {
        "data": [
            {
                "id": "anthropic/claude-3.5-sonnet",
                "top_provider": {"context_length": 200_000},
            }
        ]
    }
    with _mock_get(body):
        assert _introspect_openrouter(profile) == 200_000


def test_groq_adapter_reads_context_window():
    profile = {
        "endpoint": "https://api.groq.com/openai/v1",
        "model": "llama-3.1-70b-versatile",
    }
    body = {
        "data": [
            {"id": "llama-3.1-70b-versatile", "context_window": 131_072},
        ]
    }
    with _mock_get(body):
        assert _introspect_groq(profile) == 131_072


def test_ollama_adapter_reads_arch_context_length():
    profile = {
        "endpoint": "http://127.0.0.1:11434/v1",
        "model": "llama3.1",
    }
    body = {
        "model_info": {
            "llama.context_length": 131_072,
            "llama.embedding_length": 4096,
        }
    }
    with _mock_post(body):
        assert _introspect_ollama(profile) == 131_072


def test_ollama_adapter_falls_back_to_any_context_length_key():
    profile = {
        "endpoint": "http://127.0.0.1:11434/v1",
        "model": "deepseek-r1",
    }
    body = {
        "model_info": {
            "novelarch.context_length": 65_536,  # unknown architecture
        }
    }
    with _mock_post(body):
        assert _introspect_ollama(profile) == 65_536


def test_lmstudio_adapter_reads_loaded_context_length():
    profile = {
        "endpoint": "http://127.0.0.1:1234/v1",
        "model": "qwen-coder-32b",
    }
    body = {"loaded_context_length": 32_768, "max_context_length": 131_072}
    with _mock_get(body):
        assert _introspect_lmstudio(profile) == 32_768


def test_llamacpp_adapter_reads_n_ctx():
    profile = {"endpoint": "http://127.0.0.1:8051/v1"}
    body = {"default_generation_settings": {"n_ctx": 8192}}
    with _mock_get(body):
        assert _introspect_llamacpp(profile) == 8192


def test_adapter_returns_none_on_http_failure():
    """Any HTTP exception must be swallowed and return None — adapters
    are best-effort and must never crash the chat build."""
    profile = {
        "endpoint": "https://openrouter.ai/api/v1",
        "model": "anything",
    }
    with patch("requests.get", side_effect=RuntimeError("network down")):
        assert _introspect_openrouter(profile) is None


def test_resolver_swallows_introspector_exception():
    """Even if an introspector raises (shouldn't, but just in case), the
    resolver must still return a sensible fallback."""
    profile = {
        "preset_id": "openrouter",
        "endpoint": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
        "context_window": 0,
    }
    with patch("requests.get", side_effect=ValueError("boom")):
        # Should fall back to static catalog for gpt-4o-mini.
        assert resolve_context_window(profile) == 128_000


# ── Catalog regression ────────────────────────────────────────────────


def test_catalog_entries_use_valid_token_counts():
    """Sanity sweep: no catalog entry should have a zero or negative
    window."""
    for pattern, window in STATIC_CATALOG:
        assert window > 0, f"{pattern} has invalid window {window}"
