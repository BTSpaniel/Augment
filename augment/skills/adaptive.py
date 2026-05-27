"""Adaptive skill generator — single-agent flavor of FAIL's generator.

Pulls signals from the running ``AugmentApp`` (tool inventory, memory, recent
agent activity, workspace folder, default provider) and produces a small set of
``AdaptiveSkill`` records that the system prompt can inject.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, List

from augment.skills.holmes import holmes_skill
from augment.skills.pocock_packs import pocock_skills_for
from augment.skills.store import AdaptiveSkill, SkillStore

if TYPE_CHECKING:  # pragma: no cover
    from augment.service import AugmentApp


def generate_adaptive_skills(app: "AugmentApp", *, session_id: str = "", objective: str = "") -> List[AdaptiveSkill]:
    store = SkillStore(app.config.data_dir)
    skills: List[AdaptiveSkill] = []

    derived_objective = objective.strip() or _objective_from_session(app, session_id)

    # Holmes investigation skill — auto-activates on explore/audit/understand intents.
    holmes = holmes_skill(app, objective=derived_objective)
    if holmes is not None:
        skills.append(holmes)

    # Pocock-style skills (caveman / grill-me / handoff) triggered by phrases.
    skills.extend(pocock_skills_for(derived_objective))

    workspace_signals = _workspace_signals(app.config.workspace_root)
    memory_signals = _memory_signals(app)
    activity_signals = _activity_signals(app)
    provider_signals = _provider_signals(app)

    if derived_objective or workspace_signals:
        skills.append(AdaptiveSkill(
            id="adaptive_current_build",
            kind="current_build",
            title="Adaptive Current Build Skill",
            priority=0.9,
            signals=([f"objective: {derived_objective[:240]}"] if derived_objective else []) + workspace_signals[:10],
            instructions="Before editing, identify the authoritative files, the expected output, and the smallest validation command. Avoid broad rewrites. Preserve the user's current objective and verify changed behavior with the narrowest available smoke or focused test.",
            metadata={"workspace_root": str(app.config.workspace_root), "objective": derived_objective[:300]},
        ))

    tool_signals = _tool_inventory_signals(app)
    skills.append(AdaptiveSkill(
        id="adaptive_tool_graph",
        kind="tool_graph",
        title="Adaptive Tool Graph",
        priority=0.78,
        signals=tool_signals,
        instructions="Choose tools by trust, read/write behavior, and available categories. Prefer read-only inspection before mutation and honor the read_only flag.",
        metadata={"tool_count": len(app.tools.all_names())},
    ))

    if memory_signals:
        skills.append(AdaptiveSkill(
            id="adaptive_memory_recall",
            kind="memory_recall",
            title="Adaptive Memory Recall",
            priority=0.85,
            signals=memory_signals[:10],
            instructions="Before answering, recall durable facts the user has established. Use them to disambiguate references and avoid asking the user to repeat preferences.",
            metadata={"memory_count": len(memory_signals)},
        ))

    if activity_signals:
        skills.append(AdaptiveSkill(
            id="adaptive_session_activity",
            kind="session_activity",
            title="Adaptive Session Activity",
            priority=0.72,
            signals=activity_signals[:10],
            instructions="Continue from where the most recent tool runs left off. Prefer follow-up tools that build on previous evidence instead of re-running discovery.",
            metadata={"activity_count": len(activity_signals)},
        ))

    if provider_signals:
        skills.append(AdaptiveSkill(
            id="adaptive_provider_profile",
            kind="provider_profile",
            title="Adaptive Provider Profile",
            priority=0.6,
            signals=provider_signals,
            instructions="Tune verbosity and tool aggressiveness to the active provider/model. Local providers tolerate more tool calls; hosted models prefer concise prompts.",
            metadata={"default_id": app.settings.default_profile_id()},
        ))

    store.clear()
    return store.save_many(skills)


def _objective_from_session(app: "AugmentApp", session_id: str) -> str:
    if not session_id:
        return ""
    try:
        history = app.sessions.history(session_id, limit=10)
    except Exception:
        return ""
    for entry in reversed(history):
        if entry.role == "user" and (entry.content or "").strip():
            return entry.content.strip()
    return ""


def _workspace_signals(root: Path) -> List[str]:
    signals: List[str] = []
    try:
        entries = sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    except Exception:
        return signals
    folders: List[str] = []
    files: List[str] = []
    for item in entries:
        if item.name.startswith("."):
            continue
        if item.is_dir():
            folders.append(item.name)
        else:
            files.append(item.name)
        if len(folders) + len(files) >= 24:
            break
    if folders:
        signals.append("folders: " + ", ".join(folders[:12]))
    if files:
        signals.append("files: " + ", ".join(files[:12]))
    return signals


def _tool_inventory_signals(app: "AugmentApp") -> List[str]:
    tools = app.tools.all()
    groups: dict[str, list[str]] = {}
    for tool in tools:
        tags = tool.tags or ["other"]
        for tag in tags:
            groups.setdefault(str(tag), []).append(tool.name)
    signals = [f"{tag}: {', '.join(sorted(names)[:12])}" for tag, names in sorted(groups.items())]
    read_only = sorted(tool.name for tool in tools if tool.read_only)
    mutating = sorted(tool.name for tool in tools if not tool.read_only)
    if read_only:
        signals.append("read_only: " + ", ".join(read_only[:16]))
    if mutating:
        signals.append("mutating: " + ", ".join(mutating[:16]))
    return signals[:12]


def _memory_signals(app: "AugmentApp") -> List[str]:
    try:
        items = app.memory.all() or []
    except Exception:
        return []
    signals: List[str] = []
    for item in items[:10]:
        fact = str(item.get("fact") or "").strip()
        if not fact:
            continue
        count = int(item.get("count") or 0)
        signals.append(f"memory: {fact[:200]} (seen {count}x)")
    return signals


def _activity_signals(app: "AugmentApp") -> List[str]:
    activity = list(app.agent.profile().get("recent_activity") or [])
    signals: List[str] = []
    tools_used: Counter = Counter()
    for event in activity[-12:]:
        kind = str(event.get("kind") or "")
        detail = str(event.get("detail") or "")
        if kind == "tool" and detail:
            tools_used[detail.split(" ")[0]] += 1
        signals.append(f"{kind}: {detail[:140]}")
    if tools_used:
        ranked = ", ".join(f"{name}x{count}" for name, count in tools_used.most_common(6))
        signals.append(f"tool_frequency: {ranked}")
    return signals


def _provider_signals(app: "AugmentApp") -> List[str]:
    snapshot = app.settings.public_snapshot()
    provider = snapshot.get("provider") or {}
    if not provider:
        return []
    signals = []
    if provider.get("name"):
        signals.append(f"provider: {provider.get('name')} ({provider.get('preset_id') or provider.get('id')})")
    if provider.get("model"):
        signals.append(f"model: {provider['model']}")
    if provider.get("endpoint"):
        signals.append(f"endpoint: {provider['endpoint']}")
    return signals
