"""Active-stream registry — page-reload-safe streaming chat.

The previous design owned the chat task inside the SSE generator's
local scope. When the browser reloaded mid-stream the SSE generator's
``finally`` cancelled the task, the LLM call died, and the partial
content was lost.

Now the chat task is owned by the registry. The SSE endpoint
**subscribes** to events from the registry and forwards them; a reload
just drops the subscription. A second SSE endpoint
(``/api/chat/stream/resume/{sid}``) lets a fresh page re-subscribe,
replaying buffered events from a sequence number before resuming live.

Lifecycle of one chat turn::

    +---------+ start() +-----------+ subscribe() +--------+
    | client  |-------->|   stream  |<------------|  SSE   |
    |  POST   |         |  registry |             | sender |
    +---------+         +-----------+             +--------+
                              |
                              | spawns asyncio.Task
                              v
                       +--------------+
                       | AugmentApp   |
                       |   .chat()    |
                       +--------------+
                              |
                              | step_callback(event) -> stream.publish(event)
                              v
                       events broadcast to every subscriber

Each :class:`ActiveStream` keeps:

* ``events`` — append-only buffer (capped at ``MAX_BUFFER`` events) of
  every event published, each carrying a monotonic ``seq`` so replay
  callers can ask for "everything after seq N".
* ``content`` — the concatenation of every ``token_delta``/``final``
  event content, so a late subscriber can paint the current best-effort
  body without waiting for replay.
* ``listeners`` — async queues that receive each new event live.
* ``done`` / ``result`` — terminal state, kept around for ~30 s after
  completion so a reload that lands just-after-done still gets the
  final ``done`` event.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional


# How many recent events we keep in the per-stream buffer. A long
# tool-using turn might emit ~200 events (thoughts, tool plans, results,
# token deltas); 1000 is plenty for any single chat turn while keeping
# the per-stream memory bounded.
MAX_BUFFER = 1000

# How long we keep a finished stream in the registry before reaping it.
# Lets a fresh page reload that lands just-after-done still receive the
# final `done` event + content.
COMPLETION_RETAIN_SECONDS = 30.0


@dataclass
class StreamEvent:
    """One event in the per-stream buffer.

    ``seq`` is monotonic per-stream, starting at 1. ``kind`` is the
    augment-internal event name (``token_delta``, ``thought``, ``done``,
    etc.). ``data`` is the raw payload dict; the SSE layer translates
    it into wire events.
    """

    seq: int
    kind: str
    data: dict[str, Any]
    ts: float = field(default_factory=time.time)


class ActiveStream:
    """One in-flight (or just-finished) streaming chat turn."""

    def __init__(self, session_id: str, *, request_id: str = "") -> None:
        self.session_id = session_id
        self.request_id = request_id
        self.started_at = time.time()
        self.events: list[StreamEvent] = []
        self.listeners: set[asyncio.Queue] = set()
        # Accumulated assistant content, kept in sync as token_delta /
        # final events arrive. This is the source of truth for "what
        # has the model typed so far" surfaced via the status endpoint.
        self.content: str = ""
        # Set once chat() returns or errors.
        self.done: bool = False
        self.result: dict[str, Any] | None = None
        self.error: str = ""
        self._seq_counter = 0
        # The asyncio.Task running app.chat(). Owned by the registry so
        # an SSE disconnect doesn't cancel it.
        self.task: asyncio.Task | None = None
        # Timestamp marking when the stream finished (for reaping).
        self.finished_at: float | None = None

    # ── Snapshot API (for /active-stream and tests) ────────────────

    def snapshot(self) -> dict[str, Any]:
        """Cheap summary the UI consumes to decide whether to resume."""
        return {
            "session_id": self.session_id,
            "request_id": self.request_id,
            "active": not self.done,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "content": self.content,
            "content_chars": len(self.content),
            "event_count": len(self.events),
            "next_seq": self._seq_counter + 1,
            "result": self.result if self.done else None,
            "error": self.error if self.done else "",
        }

    # ── Publishing (called from chat()'s step_callback) ────────────

    async def publish(self, event: dict[str, Any]) -> None:
        """Append an event to the buffer and fan out to live subscribers."""
        self._seq_counter += 1
        kind = str(event.get("kind") or "")
        evt = StreamEvent(seq=self._seq_counter, kind=kind, data=dict(event))
        self.events.append(evt)
        # Trim the buffer to keep memory bounded. We drop from the head
        # so the newest events are always retained — late subscribers
        # may miss early events on very long streams, but they will
        # always have the most recent context.
        if len(self.events) > MAX_BUFFER:
            del self.events[: len(self.events) - MAX_BUFFER]
        # Mirror content-bearing events into the accumulator so the
        # status snapshot reflects what the model has typed so far.
        if kind == "token_delta":
            self.content += str(event.get("content") or "")
        elif kind == "final":
            # `final` carries the full content of the iteration; use it
            # as the authoritative source if it's longer than what we
            # have streamed (catches non-streaming providers).
            final_content = str(event.get("content") or "")
            if len(final_content) > len(self.content):
                self.content = final_content
        # Broadcast to every live subscriber. We never block — a slow
        # consumer just loses events (their queue fills).
        for q in list(self.listeners):
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                # Drop the event for this slow subscriber; they can
                # re-subscribe with a `from_seq` to catch up.
                continue

    def mark_done(self, result: Optional[dict[str, Any]] = None, error: str = "") -> None:
        """Mark the stream complete and notify all subscribers.

        After this is called the stream stays in the registry for
        ``COMPLETION_RETAIN_SECONDS`` (see
        :meth:`StreamRegistry._reap_loop`) so a fresh page reload can
        still pull the final result.
        """
        if self.done:
            return
        self.done = True
        self.result = result
        self.error = error
        self.finished_at = time.time()
        # Sentinel None tells subscribers to stop iterating.
        for q in list(self.listeners):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                continue

    # ── Subscription (called from the SSE endpoint) ────────────────

    async def subscribe(
        self, *, from_seq: int = 0, queue_size: int = 256
    ) -> AsyncIterator[StreamEvent]:
        """Replay buffered events from ``from_seq``, then yield live events.

        The caller iterates this with ``async for evt in stream.subscribe()``.
        On normal completion the iterator returns (after the ``done``
        event). On client disconnect the caller's surrounding task
        cancellation breaks the loop and ``__aexit__`` style cleanup
        removes the subscriber from ``self.listeners`` via the
        ``finally`` block in the SSE generator.
        """
        # Phase 1 — replay buffered events the caller missed.
        replayed_seq = 0
        for evt in list(self.events):
            if evt.seq <= from_seq:
                continue
            replayed_seq = evt.seq
            yield evt
        # Phase 2 — if the stream already finished, signal completion.
        if self.done:
            return
        # Phase 3 — subscribe to live events.
        q: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self.listeners.add(q)
        try:
            while True:
                item = await q.get()
                if item is None:
                    return
                # Avoid re-emitting events we already replayed (race when
                # publish() fires between the replay loop and listener
                # registration).
                if item.seq <= replayed_seq:
                    continue
                replayed_seq = item.seq
                yield item
        finally:
            self.listeners.discard(q)


class StreamRegistry:
    """Process-wide registry of active chat streams keyed by session id.

    Only one in-flight stream per session — a new chat() call for a
    session that already has an active stream replaces the old one
    (the old task is cancelled and its subscribers receive a final
    sentinel).
    """

    def __init__(self) -> None:
        self._streams: dict[str, ActiveStream] = {}
        self._reap_task: asyncio.Task | None = None

    def get(self, session_id: str) -> ActiveStream | None:
        return self._streams.get(session_id)

    def has_active(self, session_id: str) -> bool:
        stream = self._streams.get(session_id)
        return bool(stream and not stream.done)

    def register(self, stream: ActiveStream) -> None:
        """Insert a new stream. If a stream already exists for this
        session it is marked done (forcing its task to be cancelled
        by the caller) and replaced."""
        existing = self._streams.get(stream.session_id)
        if existing and not existing.done:
            existing.mark_done(error="superseded by new chat")
            if existing.task and not existing.task.done():
                existing.task.cancel()
        self._streams[stream.session_id] = stream
        self._ensure_reaper()

    def list_active(self) -> list[ActiveStream]:
        return [s for s in self._streams.values() if not s.done]

    def list_all(self) -> list[ActiveStream]:
        return list(self._streams.values())

    # ── Reaping (background task) ──────────────────────────────────

    def _ensure_reaper(self) -> None:
        if self._reap_task and not self._reap_task.done():
            return
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
        if loop.is_running():
            self._reap_task = loop.create_task(self._reap_loop())

    async def _reap_loop(self) -> None:
        """Periodically remove finished streams older than the retain window."""
        while True:
            try:
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                return
            now = time.time()
            stale: list[str] = []
            for sid, stream in self._streams.items():
                if not stream.done:
                    continue
                if stream.finished_at is None:
                    continue
                if now - stream.finished_at > COMPLETION_RETAIN_SECONDS:
                    stale.append(sid)
            for sid in stale:
                self._streams.pop(sid, None)
            # If nothing is left to track, stop the reaper; _ensure_reaper
            # will restart it on the next register().
            if not self._streams:
                return

    # ── Test helpers ───────────────────────────────────────────────

    def reset(self) -> None:
        """Drop all streams. Tests call this between cases."""
        for stream in list(self._streams.values()):
            if stream.task and not stream.task.done():
                stream.task.cancel()
        self._streams.clear()
        if self._reap_task and not self._reap_task.done():
            self._reap_task.cancel()
            self._reap_task = None
