from __future__ import annotations

from augment.config import AppConfig, ProviderConfig
from augment.providers.base import AIProvider
from augment.providers.codex_provider import CodexProvider
from augment.providers.openai_compat import OpenAICompatProvider


def _is_codex_profile(cfg: ProviderConfig) -> bool:
    return str(getattr(cfg, "id", "") or "").lower() == "codex"


def build_provider(cfg: ProviderConfig) -> AIProvider:
    """Pick the right provider implementation for the active profile."""
    if _is_codex_profile(cfg):
        return CodexProvider(model=str(cfg.model or ""))
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
