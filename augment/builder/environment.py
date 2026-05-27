"""Environment detection — list tools available on the host.

Distilled from FAIL's ``server/builder/environment.py``. Drops the builder
receipt writer (FAIL-specific) — Augment just returns the snapshot.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class EnvironmentTool:
    name: str
    available: bool
    executable: str = ""
    version: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EnvironmentSnapshot:
    platform: str
    python: str
    tools: Dict[str, EnvironmentTool] = field(default_factory=dict)
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "python": self.python,
            "tools": {name: tool.to_dict() for name, tool in self.tools.items()},
            "created_at": self.created_at,
        }


def detect_environment() -> EnvironmentSnapshot:
    """Probe the local environment for common dev tools."""
    probes: Dict[str, List[str]] = {
        "node": ["node", "--version"],
        "bun": ["bun", "--version"],
        "git": ["git", "--version"],
        "python": [sys.executable, "-V"],
        "pytest": [sys.executable, "-m", "pytest", "--version"],
    }
    tools = {name: _detect_tool(name, command) for name, command in probes.items()}
    return EnvironmentSnapshot(
        platform=platform.platform(),
        python=sys.version.split()[0],
        tools=tools,
        created_at=time.time(),
    )


def _detect_tool(name: str, command: List[str]) -> EnvironmentTool:
    if not command:
        return EnvironmentTool(name=name, available=False)
    executable = command[0] if command[0] == sys.executable else (shutil.which(command[0]) or "")
    if not executable:
        return EnvironmentTool(name=name, available=False)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
    except Exception as exc:
        return EnvironmentTool(name=name, available=False, executable=executable, version=str(exc)[:160])
    output = (result.stdout or result.stderr or "").strip()
    version = output.splitlines()[0] if output else ""
    return EnvironmentTool(
        name=name,
        available=result.returncode == 0,
        executable=executable,
        version=version[:160],
    )
