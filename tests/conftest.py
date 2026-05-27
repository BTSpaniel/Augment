"""Pytest setup: clear provider env vars by default so discovery doesn't leak."""
from __future__ import annotations

import pytest


PROVIDER_ENV_VARS = (
    "AUGMENT_API_KEY",
    "AUGMENT_LOCAL_API_KEY",
    "AUGMENT_DISCOVER_SOURCES",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "TOGETHER_API_KEY",
    "FIREWORKS_API_KEY",
    "CEREBRAS_API_KEY",
    "MISTRAL_API_KEY",
)


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch):
    """Tests run with a clean provider env unless they re-set values explicitly."""
    for name in PROVIDER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    # Disable sibling FAIL data-dir auto-detect by pointing discovery at the
    # caller's tmp area when no test override is set.
    monkeypatch.setenv("AUGMENT_DISCOVER_SOURCES", "")
    # Never let the local Codex auth on the developer's machine leak into
    # tests as an auto-discovered provider profile.
    monkeypatch.setattr(
        "augment.settings.SettingsStore._codex_authenticated",
        staticmethod(lambda: False),
    )
    yield
