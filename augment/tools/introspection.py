"""Introspection tools — let the agent inspect its own runtime (FAIL port)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from augment.tools.registry import ToolRegistry


def get_current_datetime(timezone: str = "", _context: Dict[str, Any] | None = None) -> str:
    try:
        if timezone:
            try:
                from zoneinfo import ZoneInfo
                now = datetime.now(ZoneInfo(timezone))
                tz_label = timezone
            except Exception:
                now = datetime.now().astimezone()
                tz_label = "local"
        else:
            now = datetime.now().astimezone()
            tz_label = "local"
    except Exception as exc:
        return f"Clock error: {exc}"
    offset = now.strftime("%z")
    utc_offset = f"UTC{offset[:3]}:{offset[3:]}" if offset else ""
    return "\n".join([
        f"Current date/time ({tz_label}):",
        f"Date: {now.strftime('%A, %B %d, %Y').replace(' 0', ' ')}",
        f"Time: {now.strftime('%I:%M:%S %p').lstrip('0')} {now.tzname() or ''} ({utc_offset})",
        f"Year: {now.year}",
        f"Month: {now.strftime('%B')}",
        f"Day: {now.strftime('%A')}",
        f"ISO 8601: {now.isoformat(timespec='seconds')}",
    ])


def tool_status(_context: Dict[str, Any] | None = None) -> str:
    registry = (_context or {}).get("tool_registry") if isinstance(_context, dict) else None
    if registry is None:
        return "Error: tool registry unavailable"
    tools = registry.all()
    lines = [f"Registered tools ({len(tools)}):"]
    for tool in tools:
        flags = " [read-only]" if tool.read_only else ""
        tags = f" ({', '.join(tool.tags)})" if tool.tags else ""
        lines.append(f"  - {tool.name}{flags}{tags}")
    return "\n".join(lines)


def memory_status(_context: Dict[str, Any] | None = None) -> str:
    store = (_context or {}).get("memory") if isinstance(_context, dict) else None
    if store is None:
        return "Error: memory unavailable"
    stats = store.stats()
    lines = ["Memory Status:", f"  Total entries: {stats.get('total', 0)}", f"  Keyed facts: {stats.get('keyed', 0)}"]
    categories = stats.get("by_category") or {}
    if categories:
        lines.append("  By category:")
        for name in sorted(categories):
            lines.append(f"    - {name}: {categories[name]}")
    recent = store.all(limit=5)
    if recent:
        lines.append("  Recent:")
        for item in recent[-3:]:
            key = item.get("key") or item.get("category") or "fact"
            lines.append(f"    - [{key}] {str(item.get('fact') or '')[:100]}")
    return "\n".join(lines)


def agent_status(_context: Dict[str, Any] | None = None) -> str:
    agent = (_context or {}).get("agent") if isinstance(_context, dict) else None
    if agent is None:
        return "Error: agent monitor unavailable"
    profile = agent.profile()
    capability = profile.get("capability") or {}
    stats = profile.get("stats") or {}
    return "\n".join([
        "Agent Status:",
        f"  Name: {profile.get('name', 'Augment')} ({profile.get('role', '')})",
        f"  Status: {profile.get('status', 'idle')}",
        f"  Tool runs: {stats.get('tool_runs', 0)} (failures: {stats.get('tool_failures', 0)})",
        f"  Success rate: {int((capability.get('success_rate') or 1.0) * 100)}%",
        f"  Sessions: {stats.get('sessions_started', 0)} started, {stats.get('sessions_resumed', 0)} resumed",
        f"  Soul enabled: {profile.get('soul_enabled', True)}",
    ])


def register_introspection_tools(registry: ToolRegistry) -> None:
    registry.register_fn(
        "get_current_datetime",
        "Return the current date, time, year, day, timezone, and ISO datetime from the system clock.",
        {"type": "object", "properties": {
            "timezone": {"type": "string", "description": "Optional IANA timezone such as America/New_York. Blank for local."},
        }},
        get_current_datetime, read_only=True, tags=["introspection", "time"],
    )
    registry.register_fn(
        "tool_status",
        "List all tools currently registered with the agent and their read-only/effectful state.",
        {"type": "object", "properties": {}},
        tool_status, read_only=True, tags=["introspection"],
    )
    registry.register_fn(
        "memory_status",
        "Report memory store size, category breakdown, and the most recent entries.",
        {"type": "object", "properties": {}},
        memory_status, read_only=True, tags=["introspection"],
    )
    registry.register_fn(
        "agent_status",
        "Report the agent's current profile, status, tool run stats, and capability score.",
        {"type": "object", "properties": {}},
        agent_status, read_only=True, tags=["introspection"],
    )
