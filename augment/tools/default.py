from __future__ import annotations

from augment.tools.browser import register_browser_tools
from augment.tools.codex_tools import register_codex_tools
from augment.tools.commands import register_command_tools
from augment.tools.compat import register_compat_tools
from augment.tools.files import register_file_tools
from augment.tools.git import register_git_tools
from augment.tools.introspection import register_introspection_tools
from augment.tools.investigation import register_investigation_tools
from augment.tools.memory_tools import register_memory_tools
from augment.tools.registry import ToolRegistry
from augment.tools.sandbox import register_sandbox_tools
from augment.tools.search import register_search_tools
from augment.tools.web import register_web_tools
from augment.tools.wiki import register_wiki_tools


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    # Core workspace tools
    register_file_tools(registry)
    register_search_tools(registry)
    # Ported FAIL tool packs
    register_memory_tools(registry)
    register_command_tools(registry)
    register_compat_tools(registry)
    register_sandbox_tools(registry)
    register_git_tools(registry)
    register_wiki_tools(registry)
    register_introspection_tools(registry)
    register_investigation_tools(registry)
    register_web_tools(registry)
    register_browser_tools(registry)
    register_codex_tools(registry)
    return registry
