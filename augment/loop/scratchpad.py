from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScratchpadEntry:
    kind: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    iteration: int = 0
    duration_ms: float = 0.0


@dataclass
class Scratchpad:
    entries: list[ScratchpadEntry] = field(default_factory=list)

    def thought(self, content: str, *, iteration: int = 0, duration_ms: float = 0.0) -> None:
        self.entries.append(ScratchpadEntry("thought", content, iteration=iteration, duration_ms=duration_ms))

    def action(self, tool: str, args: dict[str, Any], *, iteration: int = 0) -> None:
        self.entries.append(ScratchpadEntry("action", tool, {"args": args}, iteration=iteration))

    def observation(self, content: str, *, success: bool, iteration: int = 0, duration_ms: float = 0.0) -> None:
        self.entries.append(ScratchpadEntry("observation", content, {"success": success}, iteration=iteration, duration_ms=duration_ms))

    def error(self, content: str, *, iteration: int = 0) -> None:
        self.entries.append(ScratchpadEntry("error", content, iteration=iteration))

    def to_list(self) -> list[dict[str, Any]]:
        return [
            {
                "kind": item.kind,
                "content": item.content,
                "metadata": item.metadata,
                "ts": item.ts,
                "iteration": item.iteration,
                "duration_ms": item.duration_ms,
            }
            for item in self.entries
        ]
