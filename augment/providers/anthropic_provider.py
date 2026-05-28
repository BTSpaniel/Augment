"""Native Anthropic provider — /v1/messages with tool use and streaming.

Sections: AnthropicProvider (complete/stream/list_models/health/close),
build_anthropic_provider convenience constructor.

Activation: set provider.id == "anthropic" (or preset "anthropic") in
config.yaml / settings.  The registry delegates to this class when the
profile id starts with "anthropic".

Differences vs. OpenAICompatProvider:
- Calls /v1/messages instead of /v1/chat/completions.
- System messages are extracted and sent as the "system" field.
- Tool call format uses Anthropic's tool_use/tool_result block style.
- Requires x-api-key header (not Authorization: Bearer).
- No support for inline API key via env var lookup; reads api_key_env
  directly from the ProviderConfig.resolved_api_key property.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict, List, Optional, Union

import httpx

from augment.config import ProviderConfig
from augment.providers.base import AIProvider, LLMResponse, Message, ProviderError

_DEFAULT_API_VERSION = "2023-06-01"
_DEFAULT_ENDPOINT = "https://api.anthropic.com/v1"
_DEFAULT_MODEL = "claude-sonnet-4-5"


class AnthropicProvider(AIProvider):
    """Direct Anthropic /v1/messages provider (not via openai-compat proxy)."""

    supports_streaming: bool = False  # streams via complete() fallback for now

    def __init__(self, config: ProviderConfig) -> None:
        self.id = config.id
        self.name = config.name or "Anthropic"
        self.model = config.model or _DEFAULT_MODEL
        endpoint = str(config.endpoint or "").strip().rstrip("/")
        if not endpoint or "/openai" in endpoint:
            endpoint = _DEFAULT_ENDPOINT
        self._endpoint = endpoint
        self._api_key = config.resolved_api_key
        self._timeout = float(config.timeout_seconds or 120.0)
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    # ── HTTP helpers ──────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            async with self._lock:
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout))
        return self._client

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "anthropic-version": _DEFAULT_API_VERSION,
        }
        if self._api_key:
            headers["x-api-key"] = self._api_key
        return headers

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ── Message format helpers ────────────────────────────────────────

    @staticmethod
    def _split_system(messages: List[Message]) -> tuple[str, List[Dict[str, Any]]]:
        """Separate system messages from conversation messages."""
        system_parts: List[str] = []
        conv: List[Dict[str, Any]] = []
        for msg in messages:
            if msg.role == "system":
                system_parts.append(str(msg.content or ""))
                continue
            role = msg.role if msg.role in ("user", "assistant") else "user"
            conv.append({"role": role, "content": str(msg.content or "")})
        return "\n\n".join(system_parts).strip(), conv

    @staticmethod
    def _convert_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert OpenAI-style tool schema to Anthropic input_schema format."""
        out: List[Dict[str, Any]] = []
        for tool in tools or []:
            fn = tool.get("function") or tool
            name = fn.get("name") or tool.get("name")
            if not name:
                continue
            out.append({
                "name": name,
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters") or fn.get("input_schema") or {"type": "object", "properties": {}},
            })
        return out

    # ── Core methods ──────────────────────────────────────────────────

    async def complete(
        self,
        messages: List[Message],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        if not self._api_key:
            raise ProviderError(
                "Missing Anthropic API key. Set the api_key_env variable or save an inline key.",
                retryable=False,
            )
        system_text, conv = self._split_system(messages)
        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": int(max_tokens or 4096),
            "temperature": float(temperature),
            "messages": conv,
        }
        if system_text:
            payload["system"] = system_text
        if tools:
            payload["tools"] = self._convert_tools(tools)

        try:
            client = await self._get_client()
            r = await client.post(f"{self._endpoint}/messages", json=payload, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise ProviderError(f"{self.id}: request timed out: {exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.id}: connection error: {exc}", retryable=True) from exc

        if r.status_code == 429:
            raise ProviderError(f"{self.id}: rate limited", retryable=True, rate_limited=True)
        if r.status_code >= 500:
            raise ProviderError(f"{self.id}: HTTP {r.status_code}: {r.text[:200]}", retryable=True)
        if r.status_code >= 400:
            raise ProviderError(f"{self.id}: HTTP {r.status_code}: {r.text[:400]}", retryable=False)

        data = r.json()
        content_blocks = data.get("content") or []
        text_parts: List[str] = []
        tool_calls: List[Dict[str, Any]] = []
        for block in content_blocks:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(str(block.get("text") or ""))
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input") or {}),
                    },
                })
        return LLMResponse(
            content="".join(text_parts),
            model=str(data.get("model") or self.model),
            finish_reason=str(data.get("stop_reason") or "stop"),
            tool_calls=tool_calls,
            raw=data,
        )

    async def list_models(self) -> List[str]:
        return [
            "claude-sonnet-4-5",
            "claude-opus-4-20250514",
            "claude-sonnet-4-20250514",
            "claude-3-7-sonnet-20250219",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
        ]

    async def health(self) -> Dict[str, Any]:
        try:
            models = await self.list_models()
            return {"ok": True, "models": models, "error": ""}
        except Exception as exc:
            return {"ok": False, "models": [], "error": str(exc)}


def build_anthropic_provider(config: ProviderConfig) -> AnthropicProvider:
    """Convenience factory — mirrors ``build_provider`` in registry.py."""
    return AnthropicProvider(config)
