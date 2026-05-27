"""Tool-pack grouping helper — mirrors FAIL's tag-based pack display."""
from __future__ import annotations

from typing import Any, Dict, List

from augment.tools.registry import ToolDefinition, ToolRegistry


def _tool_dict(tool: ToolDefinition) -> Dict[str, Any]:
    parameters = tool.parameters or {}
    properties = parameters.get("properties") if isinstance(parameters, dict) else {}
    required = parameters.get("required") if isinstance(parameters, dict) else []
    state = "ready" if tool.read_only else "effectful"
    return {
        "name": tool.name,
        "description": tool.description,
        "read_only": tool.read_only,
        "tags": list(tool.tags or []),
        "state": state,
        "stats": {
            "timeout_s": float(tool.timeout_seconds),
            "parameter_count": len(properties or {}),
            "required_count": len(required or []),
            "tag_count": len(tool.tags or []),
            "safety": "read_only" if tool.read_only else "approval_or_policy",
        },
    }


def list_tools(registry: ToolRegistry) -> List[Dict[str, Any]]:
    return [_tool_dict(tool) for tool in registry.all()]


def list_tool_packs(registry: ToolRegistry) -> Dict[str, Any]:
    """Group tools by their first tag (primary pack)."""
    packs: Dict[str, List[Dict[str, Any]]] = {}
    for entry in list_tools(registry):
        pack = (entry["tags"] or ["other"])[0]
        packs.setdefault(pack, []).append(entry)
    ordered = sorted(packs.items(), key=lambda item: item[0])
    return {
        "packs": [
            {"id": name, "name": name, "tools": items, "count": len(items)}
            for name, items in ordered
        ],
        "tool_count": sum(len(items) for _, items in ordered),
    }
