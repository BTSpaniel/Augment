"""Background thinking — optional autonomous reflection loop.

Distilled from FAIL's ``server/mind/thinking.py``. Augment stays single-loop
so this is *opt-in*: nothing starts it automatically. Wire a ``think_fn`` if
you want periodic reflections (e.g., to update drives or beliefs).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional


logger = logging.getLogger("augment.mind.thinking")


class BackgroundThinking:
    """Optional background reflection loop.

    The provided ``think_fn`` is called every ``interval_s`` seconds with a
    reflection prompt; it must return a short string. The loop never invokes
    tools and never talks to the user.
    """

    def __init__(
        self,
        think_fn: Optional[Callable[[str], Awaitable[str]]] = None,
        interval_s: float = 120.0,
    ) -> None:
        self._think_fn = think_fn
        self._interval = max(30.0, float(interval_s))
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_thought_ts: float = 0.0
        self._thought_count: int = 0
        self._last_thought: str = ""

    @property
    def is_running(self) -> bool:
        return self._running

    def set_think_fn(self, think_fn: Callable[[str], Awaitable[str]]) -> None:
        self._think_fn = think_fn

    def start(self) -> None:
        if self._running or not self._think_fn:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("thinking.start called outside event loop; deferring")
            return
        self._running = True
        self._task = loop.create_task(self._loop())
        logger.info("background thinking started (interval=%.0fs)", self._interval)

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        logger.info("background thinking stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                if not self._running:
                    break
                await self._think_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("thinking loop error: %s", exc)
                await asyncio.sleep(30)

    async def _think_once(self) -> None:
        if not self._think_fn:
            return
        prompt = self._build_thinking_prompt()
        try:
            result = await self._think_fn(prompt)
            self._last_thought = (result or "").strip()
            self._last_thought_ts = time.time()
            self._thought_count += 1
        except Exception as exc:
            logger.warning("think_fn error: %s", exc)

    def _build_thinking_prompt(self) -> str:
        return (
            "You are in background reflection mode. Briefly note:\n"
            "1. What just happened in the recent session?\n"
            "2. Anything worth remembering or preparing for?\n"
            "3. One insight from the interaction.\n"
            "Keep the reflection to 2-3 sentences. Be honest and brief."
        )

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "thought_count": self._thought_count,
            "last_thought_ts": self._last_thought_ts,
            "interval_s": self._interval,
            "last_thought": self._last_thought,
            "has_think_fn": self._think_fn is not None,
        }
