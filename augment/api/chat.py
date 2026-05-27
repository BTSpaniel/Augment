"""Chat API — non-streaming + SSE streaming with FAIL-style typed events.

Event types emitted on ``POST /api/chat/stream`` AND
``GET /api/chat/stream/resume/{session_id}``:

- ``started``       — chat is starting; payload: ``{session_id, model}``.
- ``thinking``      — agent thought / reasoning text (chunked from the loop).
- ``token_delta``   — live per-token content chunk from provider.stream().
- ``reasoning_delta``— live chain-of-thought delta (o1/o3/Claude/Codex).
- ``tool_plan``     — a batch of parallel tool calls about to fire.
- ``tool_call``     — single tool invocation (action).
- ``tool_result``   — observation from a tool (success, output preview, error).
- ``error``         — non-fatal error during the run.
- ``done``          — final answer + result summary; stream completes.
- ``heartbeat``     — keep-alive every ~60s while the loop is still running.

Reload-safe by design: the chat task runs as a long-lived background
task owned by :class:`augment.streaming.StreamRegistry`. The SSE
endpoint just subscribes; a dropped subscription does NOT cancel the
underlying LLM call. Reload the page and re-attach via the resume
endpoint to pick up where you left off.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from augment.streaming.active_stream import ActiveStream, StreamEvent


router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""
    # Optional list of image URLs (HTTP(S) or data: URIs). Forwarded to the
    # active provider as OpenAI-style multipart user content when present.
    images: list[str] = []


@router.post("/chat")
async def chat(body: ChatRequest, request: Request) -> dict[str, Any]:
    app = request.app.state.augment
    try:
        result = await app.chat(body.message, session_id=body.session_id, images=body.images)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result.__dict__


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
    app = request.app.state.augment

    if not app.settings.has_default_profile():
        raise HTTPException(status_code=400, detail="No provider configured. Add one in Settings → Providers & Keys.")

    # Resolve the session_id BEFORE starting the chat task so the `started`
    # event carries the canonical id the loop will actually write to. The UI
    # uses this to pin its streaming bubble to the right session and to ignore
    # late events if the user has switched sessions mid-stream.
    resolved_session_id = body.session_id or app.sessions.new_session_id()

    async def generate() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def callback(event: dict[str, Any]) -> None:
            await queue.put(event)

        try:
            model = app.providers.default().model
        except Exception:
            model = ""
        yield _sse("started", {"session_id": resolved_session_id, "model": str(model)})

        task = asyncio.create_task(
            app.chat(
                body.message,
                session_id=resolved_session_id,
                step_callback=callback,
                images=body.images,
            )
        )

        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    if task.done():
                        break
                    yield _sse("heartbeat", {"ts": time.time()})
                    continue

                kind = str(event.get("kind") or "")
                if kind == "bleep":
                    yield _sse("bleep", {
                        "session_id": str(event.get("session_id") or ""),
                        "stats": event.get("stats") or {},
                        "prompt_preview": str(event.get("prompt_preview") or ""),
                        "prompt_chars": int(event.get("prompt_chars") or 0),
                        "message": str(event.get("message") or ""),
                    })
                elif kind == "thought":
                    yield _sse("thinking", {"content": str(event.get("content") or "")[:1200]})
                elif kind == "token_delta":
                    # Live typed-token chunk from provider.stream(). Don't
                    # truncate — UI accumulates chunks in real time.
                    yield _sse("token_delta", {"content": str(event.get("content") or "")})
                elif kind == "reasoning_delta":
                    # Live chain-of-thought delta from o1/o3/Claude/Codex
                    # reasoning streams. Goes into the live-thinking panel.
                    yield _sse("reasoning_delta", {"content": str(event.get("content") or "")})
                elif kind == "action":
                    yield _sse("tool_call", {
                        "tool": str(event.get("tool") or ""),
                        "args": event.get("args") or {},
                        "tool_calls": int(event.get("tool_calls") or 0),
                    })
                elif kind == "observation":
                    yield _sse("tool_result", {
                        "tool": str(event.get("tool") or ""),
                        "success": bool(event.get("success")),
                        "output": str(event.get("output") or "")[:1500],
                        "error": str(event.get("error") or "")[:500],
                        "duration_ms": float(event.get("duration_ms") or 0.0),
                        "tool_calls": int(event.get("tool_calls") or 0),
                    })
                elif kind == "tool_plan":
                    yield _sse("tool_plan", {
                        "calls": list(event.get("calls") or []),
                        "tool_calls": int(event.get("tool_calls") or 0),
                    })
                elif kind == "final":
                    # Loop signalled the final answer chunk — emit a single token
                    # event so the UI can switch from "thinking" to the answer
                    # immediately even before the chat() coroutine returns.
                    yield _sse("token", {"content": str(event.get("content") or "")})
                    # "final" is the last callback the loop emits before
                    # returning ReActResult. Break immediately so we don't
                    # wait up to 15 s for the queue-get timeout before
                    # we can emit the "done" event with real metadata.
                    break
                elif kind == "error":
                    yield _sse("error", {"content": str(event.get("content") or "")})
                    # Same — loop returns after emitting the error callback.
                    break

            # Drain any events that arrived after the loop exited so nothing is lost.
            while not queue.empty():
                event = queue.get_nowait()
                kind = str(event.get("kind") or "")
                if kind == "action":
                    yield _sse("tool_call", {
                        "tool": str(event.get("tool") or ""),
                        "args": event.get("args") or {},
                        "tool_calls": int(event.get("tool_calls") or 0),
                    })
                elif kind == "observation":
                    yield _sse("tool_result", {
                        "tool": str(event.get("tool") or ""),
                        "success": bool(event.get("success")),
                        "output": str(event.get("output") or "")[:1500],
                        "error": str(event.get("error") or "")[:500],
                        "duration_ms": float(event.get("duration_ms") or 0.0),
                        "tool_calls": int(event.get("tool_calls") or 0),
                    })
                elif kind == "tool_plan":
                    yield _sse("tool_plan", {
                        "calls": list(event.get("calls") or []),
                        "tool_calls": int(event.get("tool_calls") or 0),
                    })
                else:
                    yield _sse("step", event)

            try:
                result = await task
            except Exception as exc:
                yield _sse("error", {"error": str(exc)})
                return

            yield _sse("done", {
                "session_id": result.session_id,
                "content": result.reply,
                "model": result.model,
                "tool_calls": result.tool_calls,
                "iterations": result.iterations,
                "stopped_reason": result.stopped_reason,
                "context_stats": result.context_stats,
                "scratchpad": result.scratchpad,
                "tool_count_sources": result.tool_count_sources,
            })
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
