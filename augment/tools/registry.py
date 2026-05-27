from __future__ import annotations

import asyncio
import inspect
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


ToolHandler = Callable[..., str | dict[str, Any] | list[Any] | Awaitable[str | dict[str, Any] | list[Any]]]


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    read_only: bool = False
    timeout_seconds: float = 60.0
    tags: list[str] = field(default_factory=list)


@dataclass
class ToolResult:
    tool_name: str
    success: bool
    output: str
    error: str = ""
    duration_ms: float = 0.0


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def register_fn(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
        *,
        read_only: bool = False,
        timeout_seconds: float = 60.0,
        tags: list[str] | None = None,
    ) -> None:
        self.register(ToolDefinition(name, description, parameters, handler, read_only, timeout_seconds, tags or []))

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def all_names(self) -> list[str]:
        return sorted(self._tools)

    def all(self) -> list[ToolDefinition]:
        return [self._tools[name] for name in sorted(self._tools)]

    def schemas(self, allowed: list[str] | None = None) -> list[dict[str, Any]]:
        names = set(allowed) if allowed else None
        schemas: list[dict[str, Any]] = []
        for tool in self._tools.values():
            if names is not None and tool.name not in names:
                continue
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters or {"type": "object", "properties": {}},
                },
            })
        return schemas

    async def execute(self, name: str, args: dict[str, Any] | None = None, *, context: dict[str, Any] | None = None) -> ToolResult:
        aliases = {"cat": "read_file", "ls": "list_dir", "search": "search_code"}
        name = aliases.get(name, name)
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(name, False, "", f"Unknown tool: {name}")
        started = time.perf_counter()
        try:
            call_args = dict(args or {})
            if "_context" in _handler_params(tool.handler):
                call_args["_context"] = context or {}
            value = tool.handler(**call_args)
            if inspect.isawaitable(value):
                value = await asyncio.wait_for(value, timeout=tool.timeout_seconds)
            output = json.dumps(value, indent=2, default=str) if isinstance(value, (dict, list)) else str(value or "")
            if len(output) > 12000:
                output = output[:12000] + "\n... [truncated]"
            return ToolResult(name, True, output, "", (time.perf_counter() - started) * 1000)
        except asyncio.TimeoutError:
            return ToolResult(name, False, "", f"Timed out after {tool.timeout_seconds:.0f}s", (time.perf_counter() - started) * 1000)
        except Exception as exc:
            return ToolResult(name, False, "", str(exc), (time.perf_counter() - started) * 1000)

    async def execute_parallel(self, calls: list[dict[str, Any]], *, context: dict[str, Any] | None = None) -> list[ToolResult]:
        return list(await asyncio.gather(*(self.execute(call["name"], call.get("args", {}), context=context) for call in calls)))


def _handler_params(handler: ToolHandler) -> set[str]:
    try:
        return set(inspect.signature(handler).parameters)
    except Exception:
        return set()
