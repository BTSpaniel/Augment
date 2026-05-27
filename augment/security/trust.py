"""Trust levels — coarse tool-access policy keyed by current mode."""
from __future__ import annotations

import logging
from enum import IntEnum
from typing import Dict, List, Optional, Set


logger = logging.getLogger("augment.security.trust")


class TrustLevel(IntEnum):
    """Trust levels for tool access."""

    RESTRICTED = 0  # Read-only tools only
    STANDARD = 1  # Read + write, no commands
    ELEVATED = 2  # All tools except browser automation
    FULL = 3  # All tools


_MODE_TRUST: Dict[str, TrustLevel] = {
    "chat": TrustLevel.RESTRICTED,
    "workbench": TrustLevel.ELEVATED,
    "automation": TrustLevel.FULL,
    "investigation": TrustLevel.STANDARD,
    "sprint": TrustLevel.ELEVATED,
}


_TRUST_ALLOWLIST: Dict[TrustLevel, Optional[Set[str]]] = {
    TrustLevel.RESTRICTED: {
        "web_search", "fetch_url", "read_file", "list_dir",
        "search_files", "search_code", "wiki_read", "wiki_search",
        "wiki_list", "recall_fact", "search_memory", "tool_status",
        "memory_status", "agent_status", "get_current_datetime", "eval_python",
    },
    TrustLevel.STANDARD: {
        "web_search", "fetch_url", "read_file", "list_dir",
        "search_files", "search_code", "wiki_read", "wiki_search",
        "wiki_list", "wiki_write", "recall_fact", "search_memory",
        "store_fact", "add_note", "tool_status", "memory_status",
        "agent_status", "get_current_datetime", "investigate",
        "eval_python", "run_code", "git_status", "git_log", "git_diff",
    },
    TrustLevel.ELEVATED: {
        "web_search", "fetch_url", "read_file", "list_dir",
        "search_files", "search_code", "write_file", "edit_file",
        "wiki_read", "wiki_search", "wiki_list", "wiki_write",
        "wiki_delete", "recall_fact", "search_memory", "store_fact",
        "add_note", "tool_status", "memory_status", "agent_status",
        "get_current_datetime", "investigate", "eval_python",
        "run_code", "run_command", "git_status", "git_log", "git_diff",
    },
    TrustLevel.FULL: None,  # None = all tools allowed
}


class TrustPolicy:
    """Filter tool lists by trust level + per-tool overrides."""

    def __init__(self, default_level: TrustLevel = TrustLevel.STANDARD) -> None:
        self._level = default_level
        self._overrides: Dict[str, bool] = {}

    @property
    def level(self) -> TrustLevel:
        return self._level

    def set_level(self, level: TrustLevel) -> None:
        self._level = TrustLevel(int(level))

    def for_mode(self, mode: str) -> TrustLevel:
        return _MODE_TRUST.get(str(mode or "").strip().lower(), TrustLevel.STANDARD)

    def is_allowed(self, tool_name: str, *, mode: str = "workbench") -> bool:
        if tool_name in self._overrides:
            return self._overrides[tool_name]
        level = self.for_mode(mode)
        allowlist = _TRUST_ALLOWLIST.get(level)
        if allowlist is None:
            return True
        return tool_name in allowlist

    def allowed_tools(self, all_tools: List[str], *, mode: str = "workbench") -> List[str]:
        return [tool for tool in all_tools if self.is_allowed(tool, mode=mode)]

    def override(self, tool_name: str, allowed: bool) -> None:
        self._overrides[tool_name] = bool(allowed)

    def clear_overrides(self) -> None:
        self._overrides.clear()

    def snapshot(self) -> Dict[str, object]:
        return {
            "level": int(self._level),
            "level_name": self._level.name,
            "overrides": dict(self._overrides),
        }
