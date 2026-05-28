from __future__ import annotations

from augment.config import AppConfig, ProviderConfig
from augment.providers.base import AIProvider
from augment.providers.codex_provider import CodexProvider
from augment.providers.openai_compat import OpenAICompatProvider


def _profile_id(cfg: ProviderConfig) -> str:
    return str(getattr(cfg, "id", "") or "").lower().strip()


def _is_codex_profile(cfg: ProviderConfig) -> bool:
    return _profile_id(cfg) == "codex"


def _is_anthropic_profile(cfg: ProviderConfig) -> bool:
    pid = _profile_id(cfg)
    return pid.startswith("anthropic") or "claude" in pid


def _is_llama_cpp_profile(cfg: ProviderConfig) -> bool:
    """True only for the embedded llama-cpp-python library, not the HTTP server.

    If a real HTTP endpoint is configured (llama.cpp server, Ollama, LM Studio,
    etc.) we let OpenAICompatProvider handle it — those are all OpenAI-compat.
    The embedded library path requires an explicit model_path with no HTTP
    endpoint, or an id that explicitly signals the Python bindings.
    """
    pid = _profile_id(cfg)
    endpoint = str(getattr(cfg, "endpoint", "") or "").strip()
    # An HTTP endpoint means the user is pointing at a server — not the library.
    if endpoint and endpoint.startswith(("http://", "https://")):
        return False
    # model_path set → definitely the embedded library.
    model_path = str(getattr(cfg, "model_path", "") or "").strip()
    if model_path:
        return True
    # Explicit embedded-library id conventions.
    return (
        "llama-python" in pid
        or "llama-embedded" in pid
        or "llama-local-python" in pid
        or pid == "llama-local"
    )


def build_provider(cfg: ProviderConfig) -> AIProvider:
    """Pick the right provider implementation for the active profile.

    Priority:
    1. codex   → CodexProvider
    2. anthropic / claude prefix → AnthropicProvider (native /v1/messages)
    3. llama / gguf / llama-cpp  → LlamaCppProvider  (local GGUF)
    4. anything else             → OpenAICompatProvider
    """
    if _is_codex_profile(cfg):
        return CodexProvider(model=str(cfg.model or ""))
    if _is_anthropic_profile(cfg):
        from augment.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(cfg)
    if _is_llama_cpp_profile(cfg):
        from augment.providers.llama_cpp_provider import LlamaCppProvider
        model_path = str(getattr(cfg, "model_path", "") or "").strip()
        return LlamaCppProvider(cfg, model_path=model_path)
    return OpenAICompatProvider(cfg)


class ProviderRegistry:
    def __init__(self, config: AppConfig, provider_config: ProviderConfig | None = None) -> None:
        self._provider = build_provider(provider_config or config.provider)

    def default(self) -> AIProvider:
        return self._provider

    async def refresh_models(self) -> list[str]:
        return await self._provider.list_models()

    async def health(self) -> dict[str, object]:
        provider = self._provider
        health = getattr(provider, "health", None)
        if callable(health):
            return await provider.health()
        return {"ok": True, "latency_ms": 0, "error": ""}

    async def close(self) -> None:
        close = getattr(self._provider, "close", None)
        if callable(close):
            await self._provider.close()
