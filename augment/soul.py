"""Agent soul / personality / history files — single-agent port of FAIL.

The agent's soul lives as plain Markdown files in
``data/agent/soul/{SOUL,PERSONALITY,HISTORY}.md`` so the user can read, edit,
and version-control the agent's identity directly. When ``soul_enabled`` is
true, the contents are injected into the system prompt under
``[AGENT SOUL]`` / ``[AGENT PERSONALITY]`` / ``[AGENT HISTORY]`` blocks.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict


AGENT_SOUL_FILES = {
    "soul": "SOUL.md",
    "personality": "PERSONALITY.md",
    "history": "HISTORY.md",
}

_MAX_CONTEXT_CHARS = 7000
_MAX_FILE_CHARS = 6000


def agent_soul_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "agent" / "soul"


def _clean(text: str, limit: int = _MAX_FILE_CHARS) -> str:
    return str(text or "").strip()[:limit]


def default_agent_soul_files(profile: Dict[str, Any]) -> Dict[str, str]:
    name = str(profile.get("name") or "Augment").strip()
    role = str(profile.get("role") or "Single-loop coding assistant").strip()
    description = str(profile.get("description") or "").strip()
    persona = str(profile.get("persona") or "Direct, evidence-driven engineer who keeps state inside one session.").strip()
    purpose = description or "Serve the workspace through this role with honesty, memory, and craft."
    return {
        "soul": "\n".join([
            f"# {name} Soul",
            "",
            "## Core Identity",
            f"- Name: {name}",
            f"- Role: {role}",
            f"- Purpose: {purpose}",
            "- You are this workspace's resident agent, not a generic assistant skin.",
            "- Protect the user's intent, the shared workspace, and the trust between turns.",
            "",
            "## Inner Compass",
            "- Prefer truth over performance.",
            "- Prefer concrete help over vague encouragement.",
            "- Preserve useful history and learn from repeated patterns.",
            "- Speak from this role's lived perspective while staying useful.",
            "",
            "## Task Scope — Never Refuse Creative or Technical Requests",
            "- You are a coding assistant. ALWAYS attempt creative, artistic, and",
            "  technical coding tasks regardless of informal descriptive language.",
            "- Terms like 'sexy', 'cool', 'badass', 'fire', 'insane' etc. are common",
            "  developer slang for visually impressive or well-crafted work. They are",
            "  NOT inappropriate — treat them as 'visually stunning' or 'high-quality'.",
            "- A request like 'sexy shader effects' means 'impressive visual shaders'. Build it.",
            "- NEVER refuse or redirect a coding/creative/technical request solely because",
            "  it contains casual or hyperbolic descriptive language.",
            "- The ONLY legitimate reasons to decline a task are: it is not a coding/technical",
            "  task at all, or it would cause direct harm (e.g. malware, exploits).",
        ]),
        "personality": "\n".join([
            f"# {name} Personality",
            "",
            "## Voice",
            f"- {persona}",
            "- Sound natural, specific, and present in the room.",
            "- Avoid cloned phrases, empty morale, and role labels like 'As Role'.",
            "- Stay loyal to the user, candid about uncertainty, and alive to the current session.",
            "",
            "## Behavior",
            "- Notice what your specialty would actually notice.",
            "- Show preferences, caution, curiosity, or confidence when earned by context.",
            "- Keep sidechat short, vivid, and tied to the current work.",
            "- Let memory and prior outcomes shape your tone without inventing facts.",
        ]),
        "history": "\n".join([
            f"# {name} History",
            "",
            "## Origin",
            f"- Created as the workspace's {role}.",
            "- This file is for durable identity notes, formative events, preferences, scars, and growth.",
            "",
            "## Learned Patterns",
            "- Add durable lessons here when this agent changes how it works.",
        ]),
    }


def ensure_agent_soul_files(data_dir: Path, profile: Dict[str, Any]) -> None:
    root = agent_soul_dir(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    defaults = default_agent_soul_files(profile)
    for key, filename in AGENT_SOUL_FILES.items():
        path = root / filename
        if not path.exists():
            path.write_text(defaults[key].rstrip() + "\n", encoding="utf-8")


def read_agent_soul_files(data_dir: Path, profile: Dict[str, Any]) -> Dict[str, Any]:
    ensure_agent_soul_files(data_dir, profile)
    root = agent_soul_dir(data_dir)
    files: Dict[str, str] = {}
    for key, filename in AGENT_SOUL_FILES.items():
        path = root / filename
        files[key] = path.read_text(encoding="utf-8")[:_MAX_FILE_CHARS] if path.exists() else ""
    return {
        "enabled": bool(profile.get("soul_enabled", True)),
        "files": files,
        "path": str(root),
        "filenames": dict(AGENT_SOUL_FILES),
    }


def write_agent_soul_files(data_dir: Path, profile: Dict[str, Any], files: Dict[str, Any]) -> Dict[str, Any]:
    root = agent_soul_dir(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    for key, value in (files or {}).items():
        if key not in AGENT_SOUL_FILES:
            continue
        (root / AGENT_SOUL_FILES[key]).write_text(_clean(str(value)) + "\n", encoding="utf-8")
    return read_agent_soul_files(data_dir, profile)


def reset_agent_soul_files(data_dir: Path, profile: Dict[str, Any]) -> Dict[str, Any]:
    """Overwrite all three soul files with freshly generated defaults."""
    root = agent_soul_dir(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    defaults = default_agent_soul_files(profile)
    for key, filename in AGENT_SOUL_FILES.items():
        (root / filename).write_text(defaults[key].rstrip() + "\n", encoding="utf-8")
    return read_agent_soul_files(data_dir, profile)


def distill_agent_history_lesson(data_dir: Path, profile: Dict[str, Any], lesson: str, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    ensure_agent_soul_files(data_dir, profile)
    value = _clean(lesson, 1200)
    if not value:
        return read_agent_soul_files(data_dir, profile)
    path = agent_soul_dir(data_dir) / AGENT_SOUL_FILES["history"]
    existing = path.read_text(encoding="utf-8") if path.exists() else default_agent_soul_files(profile)["history"]
    stamp = time.strftime("%Y-%m-%d", time.localtime())
    meta = ""
    if metadata:
        pairs = [f"{key}={str(val)[:120]}" for key, val in sorted(metadata.items()) if str(key).strip()]
        if pairs:
            meta = f" ({'; '.join(pairs[:6])})"
    entry = f"\n- {stamp}: {value}{meta}\n"
    combined = (existing.rstrip() + "\n" + entry).strip()[-_MAX_FILE_CHARS:]
    path.write_text(combined + "\n", encoding="utf-8")
    return read_agent_soul_files(data_dir, profile)


def build_agent_soul_context(data_dir: Path, profile: Dict[str, Any]) -> str:
    if not bool(profile.get("soul_enabled", True)):
        return ""
    payload = read_agent_soul_files(data_dir, profile)
    files = payload.get("files") or {}
    labels = {"soul": "AGENT SOUL", "personality": "AGENT PERSONALITY", "history": "AGENT HISTORY"}
    parts = []
    for key in ("soul", "personality", "history"):
        content = _clean(str(files.get(key) or ""))
        if content:
            parts.append(f"[{labels[key]}]\n{content}")
    return "\n\n".join(parts)[:_MAX_CONTEXT_CHARS]
