from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScratchpadEntry:
    kind: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Scratchpad:
    entries: list[ScratchpadEntry] = field(default_factory=list)

    def thought(self, content: str) -> None:
        self.entries.append(ScratchpadEntry("thought", content))

    def action(self, tool: str, args: dict[str, Any]) -> None:
        self.entries.append(ScratchpadEntry("action", tool, {"args": args}))

    def observation(self, content: str, *, success: bool) -> None:
        self.entries.append(ScratchpadEntry("observation", content, {"success": success}))

    def error(self, content: str) -> None:
        self.entries.append(ScratchpadEntry("error", content))

    def to_list(self) -> list[dict[str, Any]]:
        return [{"kind": item.kind, "content": item.content, "metadata": item.metadata} for item in self.entries]
