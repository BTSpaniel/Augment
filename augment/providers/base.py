from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Union


class ProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, rate_limited: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.rate_limited = rate_limited


@dataclass
class Message:
    role: str
    # ``content`` is normally a plain string but vision-capable user messages
    # use OpenAI's multipart shape, e.g.
    #   [{"type": "text", "text": "look at this"},
    #    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]
    content: Any
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass
class LLMResponse:
    content: str
    model: str = ""
    finish_reason: str = "stop"
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class AIProvider(abc.ABC):
    id: str = ""
    name: str = ""
    model: str = ""
    # Subclasses set this True when they implement a real ``stream()`` —
    # the ReActLoop uses it to decide between the streaming and the
    # blocking code path.
    supports_streaming: bool = False

    @abc.abstractmethod
    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    async def stream(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[Union[str, dict[str, Any]]]:
        """Stream a response chunk-by-chunk.

        Yields one of:

        * ``str`` — a plain content delta (typed token text).
        * ``{"type": "thinking", "content": "..."}`` — a reasoning-content
          delta from o1/o3/Claude-style reasoning models.
        * ``{"type": "tool_call_delta", "index": int, "id": str|None,
          "function": {"name": str, "arguments": str}}`` — a streaming
          tool-call delta. Callers merge by ``index`` (OpenAI streaming
          tool-call pattern).
        * ``{"type": "usage", "prompt_tokens": int, "completion_tokens": int,
          "model": str}`` — optional final usage record.

        Default implementation: providers without a real streaming
        backend fall back to ``complete()`` and emit the full content
        as one chunk so callers get a uniform interface.
        """
        # Default fallback so any provider works with the streaming code
        # path even if it never wrote a real stream() method. Subclasses
        # that DO implement streaming should set ``supports_streaming = True``.
        response = await self.complete(
            messages, tools=tools, temperature=temperature, max_tokens=max_tokens,
        )
        if response.content:
            yield response.content
        for call in response.tool_calls or []:
            yield {"type": "tool_call_delta", "index": 0, **call}

    async def close(self) -> None:
        return None
