from __future__ import annotations

import json
from typing import Any, AsyncIterator, Union

import httpx

from augment.config import ProviderConfig
from augment.providers.base import AIProvider, LLMResponse, Message, ProviderError


class OpenAICompatProvider(AIProvider):
    # We implement a real per-chunk SSE stream below — turn the flag on
    # so the ReActLoop picks the streaming code path.
    supports_streaming = True

    def __init__(self, config: ProviderConfig) -> None:
        self.id = config.id
        self.name = config.name
        self.model = config.model
        self._endpoint = config.endpoint.rstrip("/")
        self._api_key = config.resolved_api_key
        self._client = httpx.AsyncClient(timeout=config.timeout_seconds)

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        if not self._api_key and not self._is_local_endpoint():
            raise ProviderError("Missing provider API key. Set AUGMENT_API_KEY or provider.api_key.", retryable=False)
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_message_to_dict(message) for message in messages],
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            response = await self._client.post(
                f"{self._endpoint}/chat/completions",
                headers=headers,
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(f"Provider timeout: {exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Provider connection error: {exc}", retryable=True) from exc
        if response.status_code >= 400:
            retryable = response.status_code in {408, 409, 429, 500, 502, 503, 504}
            raise ProviderError(
                f"Provider HTTP {response.status_code}: {response.text[:1000]}",
                retryable=retryable,
                rate_limited=response.status_code == 429,
            )
        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return LLMResponse(
            content=str(message.get("content") or ""),
            model=str(data.get("model") or self.model),
            finish_reason=str(choice.get("finish_reason") or "stop"),
            tool_calls=list(message.get("tool_calls") or []),
            raw=data,
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[Union[str, dict[str, Any]]]:
        """SSE-streamed completion. Ports FAIL's streaming path.

        Yields:

        * ``str`` — each ``delta.content`` chunk as it arrives.
        * ``{"type": "thinking", ...}`` — ``delta.reasoning_content`` /
          ``delta.thinking`` deltas (for o1/o3/Claude reasoning models).
        * ``{"type": "tool_call_delta", "index", "id", "function": {...}}``
          — each streaming tool-call chunk. Callers merge by ``index``
          (OpenAI streaming tool-call pattern).
        * ``{"type": "usage", ...}`` — optional final usage record.
        """
        if not self._api_key and not self._is_local_endpoint():
            raise ProviderError(
                "Missing provider API key. Set AUGMENT_API_KEY or provider.api_key.",
                retryable=False,
            )
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_message_to_dict(message) for message in messages],
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        url = f"{self._endpoint}/chat/completions"
        try:
            async with self._client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")[:1000]
                    retryable = response.status_code in {408, 409, 429, 500, 502, 503, 504}
                    raise ProviderError(
                        f"Provider HTTP {response.status_code}: {body}",
                        retryable=retryable,
                        rate_limited=response.status_code == 429,
                    )
                async for raw in response.aiter_lines():
                    if not raw or not raw.startswith("data:"):
                        continue
                    line = raw[5:].strip()
                    if line == "[DONE]":
                        return
                    try:
                        chunk = json.loads(line)
                    except Exception:
                        continue
                    # Optional usage record (some providers send this on
                    # the last chunk before [DONE]).
                    usage = chunk.get("usage") or {}
                    if usage:
                        yield {
                            "type": "usage",
                            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                            "completion_tokens": int(usage.get("completion_tokens") or 0),
                            "model": str(chunk.get("model") or payload["model"]),
                        }
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    # Reasoning-content delta (o1/o3 + Anthropic-via-
                    # OpenAI-compat sometimes return one of these keys).
                    reasoning = (
                        delta.get("reasoning_content")
                        or delta.get("reasoning")
                        or delta.get("thinking")
                    )
                    if reasoning:
                        yield {"type": "thinking", "content": str(reasoning)}
                    # Plain content delta (the typed-token text).
                    content = delta.get("content")
                    if isinstance(content, list):
                        # Some providers chunk multimodal content as a
                        # list of {"type": "text", "text": "..."} parts.
                        content = "".join(
                            part.get("text", "")
                            for part in content
                            if isinstance(part, dict)
                        )
                    if content:
                        yield str(content)
                    # Tool-call streaming deltas — yield each so the
                    # ReActLoop can merge by index.
                    for tc in (delta.get("tool_calls") or []):
                        yield {
                            "type": "tool_call_delta",
                            "index": int(tc.get("index", 0) or 0),
                            "id": tc.get("id"),
                            "function": tc.get("function") or {},
                        }
        except httpx.TimeoutException as exc:
            raise ProviderError(f"Provider stream timeout: {exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Provider stream error: {exc}", retryable=True) from exc

    async def list_models(self) -> list[str]:
        if not self._api_key and not self._is_local_endpoint():
            raise ProviderError("Missing provider API key. Set the configured API key env var or save an inline key.", retryable=False)
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            response = await self._client.get(
                f"{self._endpoint}/models",
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(f"Provider timeout: {exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Provider connection error: {exc}", retryable=True) from exc
        if response.status_code >= 400:
            raise ProviderError(f"Provider HTTP {response.status_code}: {response.text[:1000]}", retryable=response.status_code >= 500)
        data = response.json()
        models = data.get("data") if isinstance(data, dict) else []
        names: list[str] = []
        if isinstance(models, list):
            for item in models:
                if isinstance(item, dict) and item.get("id"):
                    names.append(str(item["id"]))
                elif isinstance(item, str):
                    names.append(item)
        return sorted(dict.fromkeys(names))

    async def health(self) -> dict[str, object]:
        try:
            models = await self.list_models()
            return {"ok": True, "models": models[:200], "error": ""}
        except Exception as exc:
            return {"ok": False, "models": [], "error": str(exc)}

    async def close(self) -> None:
        await self._client.aclose()

    def _is_local_endpoint(self) -> bool:
        lowered = self._endpoint.lower()
        return lowered.startswith("http://127.0.0.1") or lowered.startswith("http://localhost")


def _message_to_dict(message: Message) -> dict[str, Any]:
    data: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.name:
        data["name"] = message.name
    if message.tool_call_id:
        data["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        data["tool_calls"] = message.tool_calls
    return data
