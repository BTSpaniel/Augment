from __future__ import annotations

import json
import re
from typing import Any

from augment.tools.registry import ToolRegistry

_TOOL_PLAN_RE = re.compile(r"<tool_plan>\s*(.*?)\s*</tool_plan>", re.DOTALL | re.IGNORECASE)
_MAX_CALLS = 40


def extract_tool_plans(content: str) -> list[list[dict[str, Any]]]:
    plans: list[list[dict[str, Any]]] = []
    for match in _TOOL_PLAN_RE.finditer(content or ""):
        calls = _coerce_calls(_parse_payload(match.group(1).strip()))
        if calls:
            plans.append(calls[:_MAX_CALLS])
    return plans


def strip_tool_plan_blocks(content: str) -> str:
    return _TOOL_PLAN_RE.sub("", content or "").strip()


async def execute_tool_plan(plan: list[dict[str, Any]], registry: ToolRegistry, *, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    read_only: list[dict[str, Any]] = []
    mutations: list[dict[str, Any]] = []
    for call in plan:
        tool = registry.get(call["name"])
        if tool and tool.read_only:
            read_only.append(call)
        else:
            mutations.append(call)
    output: list[dict[str, Any]] = []
    if read_only:
        results = await registry.execute_parallel(read_only, context=context)
        for call, result in zip(read_only, results):
            output.append(_result_dict(call, result))
    for call in mutations:
        result = await registry.execute(call["name"], call.get("args", {}), context=context)
        output.append(_result_dict(call, result))
    return output


def format_plan_results(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in results:
        status = "ok" if item["success"] else "error"
        content = item["output"] if item["success"] else item["error"]
        parts.append(f"<tool_result name=\"{item['tool']}\" status=\"{status}\">\n{content}\n</tool_result>")
    return "\n\n".join(parts)


def _parse_payload(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return None


def _coerce_calls(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        items = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        return []
    calls: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("tool") or item.get("name") or "").strip()
        args = item.get("args") or item.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"_raw": args}
        if name:
            calls.append({"name": name, "args": args if isinstance(args, dict) else {}})
    return calls


def _result_dict(call: dict[str, Any], result: Any) -> dict[str, Any]:
    return {"tool": call["name"], "args": call.get("args", {}), "success": bool(result.success), "output": result.output, "error": result.error, "duration_ms": result.duration_ms}
