"""Host-environment detection for command compatibility.

A weak model freely generates shell commands that silently break on the
host (classic: ``mkdir -p`` / ``ls`` / ``rm -rf`` on Windows ``cmd``). The
cure has two halves that share this one source of truth:

  1. Inject a ``[ENVIRONMENT]`` block into the system prompt so the model
     *knows* the OS, shell, and which CLI tools actually exist — and which
     POSIX-isms to avoid (see :func:`environment_prompt_block`).
  2. The ``compat`` interceptor (``augment.tools.compat``) uses the same
     detection to decide which commands to shim vs. pass through.

Detection is cached process-wide (``functools.lru_cache``) because the
``shutil.which`` probes are stable for a session; call
:func:`detect_environment` with ``refresh=True`` to re-probe.

Sections (in order):
  1. detect_environment — probe OS / shell / available binaries.
  2. environment_prompt_block — render the SMART_TOP context block.
"""
from __future__ import annotations

import os
import platform
import shutil
from functools import lru_cache
from typing import Dict, List


# Binaries worth probing — presence/absence materially changes which
# commands the model should emit. Ordered for stable, readable output.
_PROBE_BINARIES: tuple[str, ...] = (
    "git", "python", "pip", "node", "npm", "npx", "deno", "bun",
    "tsc", "cargo", "go", "make", "docker", "rg",
)


# ── 1. Detection ────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _detect_cached() -> Dict[str, object]:
    """Probe the host once; cached for the process lifetime."""
    system = platform.system() or "Unknown"
    is_windows = system.lower().startswith("win")
    shell = _detect_shell(is_windows)
    available: List[str] = [name for name in _PROBE_BINARIES if shutil.which(name)]
    missing: List[str] = [name for name in _PROBE_BINARIES if name not in available]
    return {
        "os": system,
        "os_release": platform.release(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "is_windows": is_windows,
        "shell": shell,
        "available_tools": available,
        "missing_tools": missing,
    }


def detect_environment(*, refresh: bool = False) -> Dict[str, object]:
    """Return a dict describing the host environment.

    Keys: ``os``, ``os_release``, ``machine``, ``python_version``,
    ``is_windows``, ``shell``, ``available_tools``, ``missing_tools``.
    Pass ``refresh=True`` to bypass the process cache and re-probe.
    """
    if refresh:
        _detect_cached.cache_clear()
    return dict(_detect_cached())


def _detect_shell(is_windows: bool) -> str:
    """Best-effort name of the interactive shell subprocess will use."""
    if is_windows:
        # PowerShell 7+ (pwsh) is preferred when present, else Windows
        # PowerShell, else the cmd.exe pointed to by COMSPEC.
        if shutil.which("pwsh"):
            return "pwsh"
        if shutil.which("powershell"):
            return "powershell"
        comspec = os.environ.get("COMSPEC") or ""
        return os.path.basename(comspec) or "cmd.exe"
    shell = os.environ.get("SHELL") or ""
    return os.path.basename(shell) or "sh"


# ── 2. Prompt block ─────────────────────────────────────────────────


def environment_prompt_block(*, refresh: bool = False) -> str:
    """Render the ``[ENVIRONMENT]`` system-prompt section.

    Tells the model the OS/shell, which binaries exist, and (on Windows)
    the POSIX-isms to avoid — steering it toward built-in tools that work
    everywhere (``write_file`` / ``read_file`` / ``list_dir``).
    """
    env = detect_environment(refresh=refresh)
    lines: List[str] = ["[ENVIRONMENT]"]
    lines.append(
        f"Host: {env['os']} {env['os_release']} ({env['machine']}); "
        f"shell: {env['shell']}; Python {env['python_version']}."
    )
    available = env.get("available_tools") or []
    missing = env.get("missing_tools") or []
    if available:
        lines.append("Available CLI tools: " + ", ".join(available) + ".")
    if missing:
        lines.append(
            "NOT installed (do not call these): " + ", ".join(missing) + "."
        )
    lines.append(
        "Generate only commands compatible with the shell above. Prefer the "
        "built-in file tools (write_file / read_file / list_dir / edit_file) "
        "over shell commands — they are cross-platform and create parent "
        "directories automatically."
    )
    if env.get("is_windows"):
        lines.append(
            "This is Windows: POSIX commands and flags do NOT work. Do NOT use "
            "`mkdir -p`, `touch`, `ls`, `cat`, `rm -rf`, or `&&` chaining in cmd. "
            "There is no need for mkdir at all — write_file creates directories. "
            "If you must run a shell command, use PowerShell-native syntax."
        )
    return "\n".join(lines)
