"""Codex provider — wraps the ChatGPT/Codex login bridge as an :class:`AIProvider`.

Ported from FAIL's ``server/providers/codex_provider.py``. Uses the local
``openai_codex`` SDK so chats run through the user's authenticated ChatGPT
account (no API key). Model labels look like ``gpt-5.5 (medium)`` where the
parenthetical is the reasoning effort.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, List, Optional, Union

from augment.codex.bridge import (
    _codex_app_server_config,
    codex_available_model_choices,
    parse_codex_model_choice,
)
from augment.providers.base import AIProvider, LLMResponse, Message, ProviderError


class CodexProvider(AIProvider):
    """Bridge ChatGPT/Codex into the Augment provider interface."""

    # The codex SDK's ``turn.stream()`` yields AgentMessageDelta + reasoning
    # notifications — we wrap that sync generator with a thread → queue
    # bridge so :meth:`stream` produces a proper async iterator.
    supports_streaming = True

    def __init__(self, model: str = "") -> None:
        self.id = "codex"
        self.name = "ChatGPT / Codex"
        self.model = model or "gpt-5.5 (medium)"

    async def health(self) -> dict[str, Any]:
        from augment.codex.bridge import codex_account_status, codex_status

        started = time.monotonic()
        try:
            status = codex_status()
            account = codex_account_status()
            ok = bool(status.get("available") and account.get("authenticated"))
            error = str(account.get("error") or status.get("error") or "")
            return {
                "ok": ok,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "error": "" if ok else error,
            }
        except Exception as exc:
            return {
                "ok": False,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "error": str(exc),
            }

    async def list_models(self) -> List[str]:
        choices = await asyncio.to_thread(codex_available_model_choices)
        labels = [str(item.get("label") or "") for item in choices if item.get("label")]
        # Dedupe while preserving order.
        seen: set[str] = set()
        ordered: List[str] = []
        for label in labels:
            if label and label not in seen:
                seen.add(label)
                ordered.append(label)
        return ordered

    async def complete(
        self,
        messages: List[Message],
        *,
        tools: Optional[List[dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        selected = str(kwargs.get("model") or self.model or "").strip()
        return await asyncio.to_thread(self._complete_sync, list(messages), selected)

    async def stream(
        self,
        messages: List[Message],
        *,
        tools: Optional[List[dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[Union[str, dict[str, Any]]]:
        """Stream a Codex turn delta-by-delta.

        Uses the openai_codex SDK's ``turn.stream()`` to receive
        ``AgentMessageDeltaNotification`` events as the model types,
        plus reasoning-summary deltas (yielded as ``{"type": "thinking",
        ...}``). Because the SDK is synchronous, we run the iterator in
        a worker thread and bridge it to asyncio with a queue —
        identical pattern to Luna's ReactAgent thread bridge.
        """
        try:
            from openai_codex import Codex  # type: ignore  # noqa: F401
            from openai_codex.types import ReasoningEffort  # type: ignore  # noqa: F401
        except Exception as exc:
            raise ProviderError(
                f"codex: openai_codex Python SDK is not installed: {exc}",
                retryable=False,
            ) from exc

        selected = str(kwargs.get("model") or self.model or "").strip()
        choice = parse_codex_model_choice(selected)
        model = choice["model"]
        effort = choice["reasoning_effort"]
        prompt = self._messages_to_prompt(list(messages))

        loop = asyncio.get_event_loop()
        # Sentinel used to signal end-of-stream from the worker thread.
        _SENTINEL: dict[str, Any] = {"__codex_sentinel__": True}
        queue: asyncio.Queue = asyncio.Queue()

        def _drive() -> None:
            """Run the sync ``turn.stream()`` and pump events into the queue."""
            try:
                from openai_codex import Codex  # type: ignore
                from openai_codex.types import ReasoningEffort  # type: ignore

                with Codex(config=_codex_app_server_config()) as codex:
                    thread = codex.thread_start(
                        model=model,
                        config={"model_reasoning_effort": effort},
                    )
                    turn = thread.turn(prompt, model=model, effort=ReasoningEffort(effort))
                    for event in turn.stream():
                        method = getattr(event, "method", "") or ""
                        payload = getattr(event, "payload", None)
                        # Agent message text delta — the typed-token surface.
                        if method == "item/agentMessage/delta":
                            delta = getattr(payload, "delta", "") or ""
                            if delta:
                                loop.call_soon_threadsafe(queue.put_nowait, str(delta))
                            continue
                        # Reasoning-summary deltas — chain-of-thought stream
                        # for o-series/Codex thinking models.
                        if method in (
                            "item/reasoning/delta",
                            "item/reasoningSummary/delta",
                            "item/reasoning_summary/delta",
                        ):
                            delta = getattr(payload, "delta", "") or ""
                            if delta:
                                loop.call_soon_threadsafe(
                                    queue.put_nowait,
                                    {"type": "thinking", "content": str(delta)},
                                )
                            continue
                        # Turn-completed: extract token usage if present.
                        if method == "turn/completed":
                            turn_payload = getattr(payload, "turn", None)
                            if turn_payload is not None:
                                usage = getattr(turn_payload, "usage", None)
                                if usage is not None:
                                    try:
                                        loop.call_soon_threadsafe(
                                            queue.put_nowait,
                                            {
                                                "type": "usage",
                                                "prompt_tokens": int(getattr(usage, "input_tokens", 0) or 0),
                                                "completion_tokens": int(getattr(usage, "output_tokens", 0) or 0),
                                                "model": f"{model} ({effort})",
                                            },
                                        )
                                    except Exception:
                                        pass
                            continue
            except Exception as exc:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    ProviderError(f"codex: {exc}", retryable=False),
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

        # Kick off the worker; consume the queue from the async loop.
        loop.run_in_executor(None, _drive)
        while True:
            item = await queue.get()
            if isinstance(item, dict) and item.get("__codex_sentinel__"):
                return
            if isinstance(item, ProviderError):
                raise item
            yield item

    def _complete_sync(self, messages: List[Message], selected: str) -> LLMResponse:
        try:
            from openai_codex import Codex  # type: ignore
            from openai_codex.types import ReasoningEffort  # type: ignore
        except Exception as exc:
            raise ProviderError(
                f"codex: openai_codex Python SDK is not installed: {exc}",
                retryable=False,
            ) from exc

        choice = parse_codex_model_choice(selected)
        model = choice["model"]
        effort = choice["reasoning_effort"]
        prompt = self._messages_to_prompt(messages)
        try:
            with Codex(config=_codex_app_server_config()) as codex:
                thread = codex.thread_start(model=model, config={"model_reasoning_effort": effort})
                result = thread.run(prompt, model=model, effort=ReasoningEffort(effort))
            content = str(getattr(result, "final_response", "") or "")
            raw: dict[str, Any] = {}
            if hasattr(result, "model_dump"):
                try:
                    raw = result.model_dump(mode="json", by_alias=True)
                except Exception:
                    raw = {}
            return LLMResponse(content=content, model=f"{model} ({effort})", raw=raw)
        except Exception as exc:
            raise ProviderError(f"codex: {exc}", retryable=False) from exc

    @staticmethod
    def _messages_to_prompt(messages: List[Message]) -> str:
        parts: List[str] = []
        for message in messages:
            role = str(message.role or "user").upper()
            content = str(message.content or "").strip()
            if content:
                parts.append(f"[{role}]\n{content}")
        return "\n\n".join(parts).strip()

    async def close(self) -> None:
        return None
