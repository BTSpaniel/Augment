from __future__ import annotations

import ast
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from augment.builder.edit_receipts import (
    finalize_edit_receipt,
    is_mutation_tool,
    prepare_edit_receipt,
)
from augment.loop.scratchpad import Scratchpad
from augment.loop.tool_plan import execute_tool_plan, extract_tool_plans, format_plan_results, strip_tool_plan_blocks
from augment.providers.base import AIProvider, LLMResponse, Message, ProviderError
from augment.security.untrusted_content import is_untrusted_tool, wrap_untrusted_content
from augment.tools.registry import ToolRegistry

_TOOL_CALL_FENCE_RE = re.compile(r"```tool_call\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_EXPLORATION_TOOLS = {"list_dir", "read_file", "search_files", "search_code"}


@dataclass
class ReActResult:
    content: str
    scratchpad: Scratchpad
    tool_calls: int = 0
    iterations: int = 0
    stopped_reason: str = "final_answer"
    mutated_tools: list[str] = field(default_factory=list)


StepCallback = Callable[[dict[str, Any]], Awaitable[None]]


class ReActLoop:
    def __init__(self, provider: AIProvider, tools: ToolRegistry, *, system_prompt: str = "", max_iterations: int = 10, temperature: float = 0.2) -> None:
        self._provider = provider
        self._tools = tools
        self._system_prompt = system_prompt
        self._max_iterations = max_iterations
        self._temperature = temperature

    async def run(
        self,
        message: str,
        *,
        history_messages: list[dict[str, str]] | None = None,
        allowed_tools: list[str] | None = None,
        tool_context: dict[str, Any] | None = None,
        step_callback: StepCallback | None = None,
        images: list[str] | None = None,
    ) -> ReActResult:
        pad = Scratchpad()
        messages: list[Message] = []
        system_text = self._system_text()
        if system_text:
            messages.append(Message("system", system_text))
        for item in (history_messages or [])[-30:]:
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                messages.append(Message(role, content))
        messages.append(Message("user", _build_user_content(message, images)))

        tool_calls = 0
        exploration_streak = 0
        mutated_tools: list[str] = []
        for iteration in range(1, self._max_iterations + 1):
            _gen_start = time.monotonic()
            try:
                response = await self._generate(
                    messages,
                    tool_schemas=self._tools.schemas(allowed_tools),
                    step_callback=step_callback,
                )
            except ProviderError:
                raise
            except Exception as exc:
                _gen_ms = (time.monotonic() - _gen_start) * 1000
                pad.error(str(exc), iteration=iteration)
                if step_callback:
                    await step_callback({"kind": "error", "content": str(exc)})
                return ReActResult(f"Agent error: {exc}", pad, tool_calls, iteration, "error", mutated_tools)
            _gen_ms = (time.monotonic() - _gen_start) * 1000

            plans = extract_tool_plans(response.content)
            native_calls = list(response.tool_calls or [])
            if plans:
                visible = strip_tool_plan_blocks(response.content)
                if visible:
                    pad.thought(visible, iteration=iteration, duration_ms=_gen_ms)
                    if step_callback:
                        await step_callback({"kind": "thought", "content": visible, "duration_ms": _gen_ms})
                messages.append(Message("assistant", response.content))
                for plan in plans:
                    if step_callback:
                        await step_callback({"kind": "tool_plan", "calls": plan})
                    results = await execute_tool_plan(plan, self._tools, context=tool_context)
                    tool_calls += len(results)
                    all_explore = True
                    for item in results:
                        pad.action(item["tool"], item["args"], iteration=iteration)
                        pad.observation(
                            item["output"] if item["success"] else item["error"],
                            success=item["success"],
                            iteration=iteration,
                            duration_ms=float(item.get("duration_ms") or 0.0),
                        )
                        if item["tool"] not in _EXPLORATION_TOOLS:
                            all_explore = False
                            mutated_tools.append(item["tool"])
                        if step_callback:
                            await step_callback({"kind": "observation", **item})
                    messages.append(Message("user", "[TOOL PLAN RESULTS]\n" + format_plan_results(results)))
                    exploration_streak = exploration_streak + 1 if all_explore else 0
                if exploration_streak >= 4:
                    messages.append(Message("user", "You have inspected enough. Provide a concise final answer or make a necessary safe edit now."))
                    exploration_streak = 0
                continue

            if not native_calls:
                native_calls = self._extract_fallback_tool_calls(response.content)
            if native_calls:
                assistant_content = self._strip_fallback_blocks(response.content)
                if assistant_content:
                    pad.thought(assistant_content, iteration=iteration, duration_ms=_gen_ms)
                    if step_callback:
                        await step_callback({"kind": "thought", "content": assistant_content, "duration_ms": _gen_ms})
                messages.append(Message("assistant", assistant_content, tool_calls=native_calls))
                only_explore = True
                for call in native_calls:
                    name, args = self._tool_call_parts(call)
                    pad.action(name, args, iteration=iteration)
                    if step_callback:
                        await step_callback({"kind": "action", "tool": name, "args": args})
                    draft = (
                        prepare_edit_receipt(name, args, tool_context)
                        if is_mutation_tool(name) and tool_context is not None
                        else None
                    )
                    result = await self._tools.execute(name, args, context=tool_context)
                    tool_calls += 1
                    receipt_info: dict[str, Any] = {}
                    if draft is not None and tool_context is not None:
                        receipt_info = finalize_edit_receipt(
                            draft,
                            name,
                            args,
                            tool_context,
                            success=result.success,
                            output=result.output or "",
                            error=result.error or "",
                        )
                        if receipt_info.get("blocked"):
                            # Surface the block as the visible tool error so the
                            # model can replan without unrelated context noise.
                            result.success = False
                            result.error = receipt_info.get("error") or result.error
                    pad.observation(
                        result.output if result.success else result.error,
                        success=result.success,
                        iteration=iteration,
                        duration_ms=result.duration_ms or 0.0,
                    )
                    if name not in _EXPLORATION_TOOLS:
                        only_explore = False
                        mutated_tools.append(name)
                    if step_callback:
                        await step_callback({
                            "kind": "observation",
                            "tool": name,
                            "args": args,
                            "success": result.success,
                            "output": result.output,
                            "error": result.error,
                            "duration_ms": result.duration_ms,
                            "edit_receipt": receipt_info.get("receipt") if receipt_info else None,
                        })
                    tool_tags = []
                    tool_def = self._tools.get(name)
                    if tool_def is not None:
                        tool_tags = list(tool_def.tags or [])
                    tool_payload = result.output if result.success else f"ERROR: {result.error}"
                    if result.success and is_untrusted_tool(name, tool_tags):
                        tool_payload = wrap_untrusted_content(tool_payload, source=name)
                    messages.append(Message(
                        "tool",
                        tool_payload,
                        tool_call_id=str(call.get("id") or name),
                    ))
                exploration_streak = exploration_streak + 1 if only_explore else 0
                continue

            final = response.content.strip()
            pad.thought(final, iteration=iteration, duration_ms=_gen_ms)
            if step_callback:
                await step_callback({"kind": "final", "content": final, "duration_ms": _gen_ms})
            return ReActResult(final, pad, tool_calls, iteration, "final_answer", mutated_tools)

        return ReActResult("I reached the iteration limit before a final answer.", pad, tool_calls, self._max_iterations, "max_iterations", mutated_tools)

    async def _generate(
        self,
        messages: list[Message],
        *,
        tool_schemas: list[dict[str, Any]] | None,
        step_callback: StepCallback | None,
    ) -> LLMResponse:
        """Run one LLM turn, streaming when the provider supports it.

        Always returns an :class:`LLMResponse` so the surrounding loop
        logic stays unchanged. When streaming is available, deltas flow
        through ``step_callback`` as they arrive:

        * ``{"kind": "token_delta", "content": <chunk>}`` — typed text.
        * ``{"kind": "reasoning_delta", "content": <chunk>}`` —
          ``<thinking>`` / reasoning-content text (o1/o3/Claude/Codex
          chain-of-thought).

        Tool-call deltas are accumulated by index (OpenAI streaming
        pattern) and exposed on the final :class:`LLMResponse`. We DO
        NOT emit per-delta tool-call events — the surrounding loop
        handles those once the full response is assembled.
        """
        provider = self._provider
        if not getattr(provider, "supports_streaming", False):
            return await provider.complete(
                messages, tools=tool_schemas, temperature=self._temperature,
            )

        content_parts: list[str] = []
        # Tool calls arrive as a stream of deltas keyed by ``index`` —
        # accumulate function.name + function.arguments per index.
        tool_calls_by_index: dict[int, dict[str, Any]] = {}
        finish_model = ""
        try:
            async for chunk in provider.stream(
                messages, tools=tool_schemas, temperature=self._temperature,
            ):
                if isinstance(chunk, str):
                    content_parts.append(chunk)
                    if step_callback:
                        await step_callback({"kind": "token_delta", "content": chunk})
                    continue
                if not isinstance(chunk, dict):
                    continue
                kind = chunk.get("type") or chunk.get("kind") or ""
                if kind == "thinking":
                    text = str(chunk.get("content") or "")
                    if text and step_callback:
                        await step_callback({"kind": "reasoning_delta", "content": text})
                    continue
                if kind == "tool_call_delta":
                    idx = int(chunk.get("index", 0) or 0)
                    existing = tool_calls_by_index.setdefault(idx, {
                        "id": chunk.get("id"),
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    })
                    fn_chunk = chunk.get("function") or {}
                    name = fn_chunk.get("name")
                    if name:
                        existing["function"]["name"] = str(name)
                    args = fn_chunk.get("arguments")
                    if args is not None:
                        existing["function"]["arguments"] += str(args)
                    if chunk.get("id") and not existing.get("id"):
                        existing["id"] = chunk.get("id")
                    continue
                if kind == "usage":
                    # Stash for the synthetic response below.
                    finish_model = str(chunk.get("model") or "")
                    continue
        except ProviderError:
            raise

        # Order by stream index so tool_calls match the model's wire order.
        ordered_calls = [tool_calls_by_index[i] for i in sorted(tool_calls_by_index)]
        return LLMResponse(
            content="".join(content_parts),
            model=finish_model or getattr(provider, "model", ""),
            finish_reason="stop",
            tool_calls=ordered_calls,
        )

    def _system_text(self) -> str:
        tool_guidance = (
            "TOOL PREFERENCE: Use search_code for any grep/rg-style text search and "
            "search_files to find files by name. "
            "Do NOT run 'rg', 'grep', or 'find' via run_command — "
            "search_code works even when rg is not installed (built-in Python fallback)."
        )
        tool_plan = """When multiple independent reads/searches are useful, emit one JSON array in a <tool_plan> block, for example:
<tool_plan>
[{"tool":"list_dir","args":{"path":"."}}, {"tool":"search_files","args":{"query":"README"}}]
</tool_plan>"""
        return "\n\n".join(part for part in [self._system_prompt, tool_guidance, tool_plan] if part.strip())

    def _extract_fallback_tool_calls(self, content: str) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        for match in _TOOL_CALL_FENCE_RE.finditer(content or ""):
            raw = match.group(1).strip()
            try:
                payload = json.loads(raw)
            except Exception:
                try:
                    payload = ast.literal_eval(raw)
                except Exception:
                    continue
            if isinstance(payload, dict):
                name = str(payload.get("name") or payload.get("tool") or "")
                args = payload.get("arguments") or payload.get("args") or {}
                calls.append({"id": f"fallback_{len(calls)}", "function": {"name": name, "arguments": json.dumps(args)}})
        return calls

    def _strip_fallback_blocks(self, content: str) -> str:
        return _TOOL_CALL_FENCE_RE.sub("", content or "").strip()

    def _tool_call_parts(self, call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        fn = call.get("function") or {}
        name = str(fn.get("name") or "")
        raw_args = fn.get("arguments") or "{}"
        if isinstance(raw_args, dict):
            return name, raw_args
        try:
            parsed = json.loads(str(raw_args))
        except Exception:
            parsed = {}
        return name, parsed if isinstance(parsed, dict) else {}


def _build_user_content(message: str, images: list[str] | None) -> Any:
    """Return either a plain string (no images) or OpenAI multipart content."""
    cleaned = [str(url).strip() for url in (images or []) if str(url or "").strip()]
    if not cleaned:
        return message
    parts: list[dict[str, Any]] = []
    if message:
        parts.append({"type": "text", "text": message})
    for url in cleaned:
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts
