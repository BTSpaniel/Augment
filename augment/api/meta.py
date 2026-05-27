from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from augment.config import ROOT
from augment.security.path_guard import PathGuard


router = APIRouter(prefix="/api", tags=["meta"])


class ProviderUpdate(BaseModel):
    preset: str = ""
    id: str = ""
    name: str = ""
    endpoint: str = ""
    api_key_env: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: float | None = None


class AddProviderBody(BaseModel):
    preset: str = ""
    name: str = ""
    endpoint: str = ""
    api_key: str = ""
    model: str = ""


class SetKeyBody(BaseModel):
    value: str = ""


class SetModelBody(BaseModel):
    model: str = ""


class MailboxBody(BaseModel):
    content: str
    kind: str = "note"


class RevealFileBody(BaseModel):
    path: str = ""


class AgentProfileBody(BaseModel):
    name: str = ""
    role: str = ""
    description: str = ""
    persona: str = ""
    soul_enabled: bool | None = None


class AgentSoulBody(BaseModel):
    enabled: bool | None = None
    files: dict[str, str] = {}


class AgentHistoryLessonBody(BaseModel):
    lesson: str
    metadata: dict[str, Any] = {}


@router.get("/tools")
async def tools(request: Request) -> dict[str, Any]:
    app = request.app.state.augment
    detailed = app.tools_detailed()
    return {"tools": app.tools.all_names(), "items": detailed}


@router.post("/files/reveal")
async def reveal_file(body: RevealFileBody) -> dict[str, Any]:
    raw = body.path.strip()
    if not raw:
        raise HTTPException(400, "path is required")
    if raw.lower().startswith("file:"):
        parsed = urlparse(raw)
        raw = unquote(parsed.path or "")
        if sys.platform.startswith("win") and raw.startswith("/") and len(raw) >= 3 and raw[2] == ":":
            raw = raw[1:]
    candidate = Path(raw).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()
    if not PathGuard().is_safe(str(resolved)):
        raise HTTPException(400, f"refused sensitive path: {resolved}")
    if not resolved.exists():
        raise HTTPException(404, f"file not found: {resolved}")
    try:
        if sys.platform.startswith("win"):
            if resolved.is_file():
                subprocess.Popen(["explorer", "/select,", str(resolved)])
            else:
                subprocess.Popen(["explorer", str(resolved)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R" if resolved.is_file() else str(resolved), str(resolved)] if resolved.is_file() else ["open", str(resolved)])
        else:
            subprocess.Popen(["xdg-open", str(resolved.parent if resolved.is_file() else resolved)])
    except Exception as exc:
        raise HTTPException(500, f"could not open file browser: {exc}") from exc
    return {"ok": True, "path": str(resolved)}


@router.get("/toolpacks")
async def tool_packs(request: Request) -> dict[str, Any]:
    return request.app.state.augment.tool_packs()


@router.get("/skills/catalog")
async def skills_catalog(request: Request) -> dict[str, Any]:
    return request.app.state.augment.skills_catalog()


class GenerateSkillsBody(BaseModel):
    session_id: str = ""
    objective: str = ""


@router.post("/skills/generate")
async def generate_skills(body: GenerateSkillsBody, request: Request) -> dict[str, Any]:
    return {"skills": request.app.state.augment.generate_skills(session_id=body.session_id, objective=body.objective)}


@router.get("/skills/context")
async def skills_context(request: Request, max_chars: int = 4000) -> dict[str, Any]:
    return {"context": request.app.state.augment.skills_context(max_chars=max_chars)}


class HolmesActivateBody(BaseModel):
    objective: str = ""
    session_id: str = ""


@router.post("/skills/holmes/activate")
async def skills_holmes_activate(body: HolmesActivateBody, request: Request) -> dict[str, Any]:
    """Force-activate Holmes investigation mode for the next chat turn."""
    from augment.skills.holmes import holmes_skill
    app = request.app.state.augment
    skill = holmes_skill(app, objective=body.objective, explicit=True)
    if skill is None:
        return {"activated": False}
    app.skills.clear()
    saved = app.skills.save_many([skill])
    return {"activated": True, "skills": saved}


class CodexLoginBody(BaseModel):
    method: str = "device_code"


@router.get("/codex/status")
async def codex_status_endpoint(codex_bin: str = "") -> dict[str, Any]:
    from augment.codex.bridge import codex_status
    return codex_status(codex_bin=codex_bin)


@router.get("/codex/account")
async def codex_account_endpoint() -> dict[str, Any]:
    from augment.codex.bridge import codex_account_status
    return codex_account_status()


@router.get("/codex/login")
async def codex_login_status_endpoint() -> dict[str, Any]:
    from augment.codex.bridge import codex_login_status
    return codex_login_status()


@router.post("/codex/login")
async def codex_login_start(body: CodexLoginBody) -> dict[str, Any]:
    from augment.codex.bridge import start_codex_chatgpt_login
    return start_codex_chatgpt_login(method=body.method)


@router.post("/codex/login/cancel")
async def codex_login_cancel() -> dict[str, Any]:
    from augment.codex.bridge import cancel_codex_login
    return cancel_codex_login()


@router.get("/agent")
async def agent(request: Request) -> dict[str, Any]:
    app = request.app.state.augment
    profile = app.agent.profile()
    provider = app.settings.public_snapshot()["provider"]
    return {
        "agent": profile,
        "provider": {"name": provider.get("name"), "id": provider.get("id"), "model": provider.get("model")},
        "tools": [
            {"name": tool.name, "description": tool.description, "read_only": tool.read_only}
            for tool in app.tools.all()
        ],
        "context": app.context.stats(),
    }


@router.put("/agent")
async def update_agent(body: AgentProfileBody, request: Request) -> dict[str, Any]:
    raw = body.model_dump()
    values: dict[str, Any] = {}
    for key in ("name", "role", "description", "persona"):
        if raw.get(key):
            values[key] = raw[key]
    if raw.get("soul_enabled") is not None:
        values["soul_enabled"] = bool(raw["soul_enabled"])
    return {"agent": request.app.state.augment.agent.update_profile(values)}


@router.get("/agent/soul")
async def get_agent_soul(request: Request) -> dict[str, Any]:
    return request.app.state.augment.soul()


@router.put("/agent/soul")
async def update_agent_soul(body: AgentSoulBody, request: Request) -> dict[str, Any]:
    return request.app.state.augment.update_soul(files=body.files or None, enabled=body.enabled)


@router.post("/agent/soul/reset")
async def reset_agent_soul(request: Request) -> dict[str, Any]:
    return request.app.state.augment.reset_soul()


@router.post("/agent/soul/history")
async def record_history_lesson(body: AgentHistoryLessonBody, request: Request) -> dict[str, Any]:
    return request.app.state.augment.record_history_lesson(body.lesson, body.metadata or None)


@router.get("/providers")
async def providers(request: Request) -> dict[str, Any]:
    app = request.app.state.augment
    snapshot = app.settings.public_snapshot()
    health = await app.provider_health()
    return {**snapshot, "health": health}


@router.get("/providers/presets")
async def providers_presets(request: Request) -> dict[str, Any]:
    return {"presets": request.app.state.augment.settings.presets_catalog()}


@router.put("/providers")
async def update_provider(body: ProviderUpdate, request: Request) -> dict[str, Any]:
    values = {key: value for key, value in body.model_dump().items() if value not in ("", None)}
    return await request.app.state.augment.update_provider(values)


@router.post("/providers/add")
async def add_provider(body: AddProviderBody, request: Request) -> dict[str, Any]:
    values = {key: value for key, value in body.model_dump().items() if value not in ("", None)}
    return await request.app.state.augment.add_provider(values)


@router.delete("/providers/{profile_id}")
async def remove_provider(profile_id: str, request: Request) -> dict[str, Any]:
    return await request.app.state.augment.remove_provider(profile_id)


@router.post("/providers/{profile_id}/default")
async def set_default_provider(profile_id: str, request: Request) -> dict[str, Any]:
    return await request.app.state.augment.set_default_provider(profile_id)


@router.post("/providers/{profile_id}/key")
async def set_profile_key(profile_id: str, body: SetKeyBody, request: Request) -> dict[str, Any]:
    return await request.app.state.augment.set_profile_key(profile_id, body.value)


@router.post("/providers/{profile_id}/model")
async def set_profile_model(profile_id: str, body: SetModelBody, request: Request) -> dict[str, Any]:
    return await request.app.state.augment.set_profile_model(profile_id, body.model)


@router.post("/providers/{profile_id}/models/refresh")
async def refresh_profile_models(profile_id: str, request: Request) -> dict[str, Any]:
    return await request.app.state.augment.refresh_provider_models(profile_id)


@router.post("/providers/models/refresh")
async def refresh_provider_models(request: Request) -> dict[str, Any]:
    return await request.app.state.augment.refresh_provider_models()


@router.post("/providers/discover")
async def discover_providers(request: Request) -> dict[str, Any]:
    return await request.app.state.augment.discover_providers()


@router.post("/providers/discover/restore/{preset_id}")
async def restore_preset(preset_id: str, request: Request) -> dict[str, Any]:
    return await request.app.state.augment.restore_preset(preset_id)


@router.get("/sessions")
async def sessions(request: Request, limit: int = 100) -> dict[str, Any]:
    return {"sessions": request.app.state.augment.sessions.list(limit=limit)}


@router.get("/sessions/by_project")
async def sessions_by_project(request: Request, limit: int = 200) -> dict[str, Any]:
    return request.app.state.augment.list_sessions_by_project(limit=limit)


class SessionProjectBody(BaseModel):
    project: str


@router.put("/sessions/{session_id}/project")
async def set_session_project(session_id: str, body: SessionProjectBody, request: Request) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "meta": request.app.state.augment.set_session_project(session_id, body.project),
    }


class SessionOutputDirBody(BaseModel):
    path: str = ""


@router.put("/sessions/{session_id}/output_dir")
async def set_session_output_dir(session_id: str, body: SessionOutputDirBody, request: Request) -> dict[str, Any]:
    """Pin where new files written this session land.

    Pass an empty string to clear the override and return to the default
    scratch directory.
    """
    from pathlib import Path

    from augment.security.path_guard import PathGuard

    app = request.app.state.augment
    clean = body.path.strip()
    if not clean:
        meta = app.sessions.set_meta(session_id, output_dir="")
        return {"session_id": session_id, "meta": meta, "cleared": True}
    resolved = Path(clean).expanduser().resolve()
    if not PathGuard().is_safe(str(resolved)):
        raise HTTPException(400, f"refused sensitive path: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    meta = app.sessions.set_meta(session_id, output_dir=str(resolved))
    return {"session_id": session_id, "meta": meta, "output_dir": str(resolved)}


# ── Per-session coding contract ────────────────────────────────────────
#
# Mirrors FAIL's ContextPacket.rules slot. The contract is a tiny list of
# free-form rules the user pins for this session (e.g. "all new code in
# TypeScript", "no edits under /api/legacy/**", "100% test coverage").
# Injected as the [CODING CONTRACT] section in the smart_top zone of
# every assembled prompt.


class CodingContractBody(BaseModel):
    rules: list[str] = []
    notes: str = ""


@router.get("/sessions/{session_id}/coding-contract")
async def get_coding_contract(session_id: str, request: Request) -> dict[str, Any]:
    """Return the current contract for ``session_id`` (rules + notes)."""
    app = request.app.state.augment
    return app.coding_contracts.load(session_id).to_dict()


@router.put("/sessions/{session_id}/coding-contract")
async def set_coding_contract(
    session_id: str, body: CodingContractBody, request: Request
) -> dict[str, Any]:
    """Replace the contract for ``session_id``. Pass ``rules=[]`` to clear
    just the rules; PUT with all-empty fields followed by DELETE to wipe."""
    app = request.app.state.augment
    contract = app.coding_contracts.set_rules(session_id, body.rules)
    if body.notes is not None:
        contract = app.coding_contracts.set_notes(session_id, body.notes)
    return contract.to_dict()


class CodingContractAppendBody(BaseModel):
    rule: str


@router.post("/sessions/{session_id}/coding-contract/append")
async def append_coding_contract(
    session_id: str, body: CodingContractAppendBody, request: Request
) -> dict[str, Any]:
    """Append a single rule (no-op if blank or already present)."""
    app = request.app.state.augment
    contract = app.coding_contracts.append_rule(session_id, body.rule)
    return contract.to_dict()


@router.delete("/sessions/{session_id}/coding-contract")
async def clear_coding_contract(session_id: str, request: Request) -> dict[str, Any]:
    """Delete the contract for ``session_id``."""
    app = request.app.state.augment
    app.coding_contracts.clear(session_id)
    return {"session_id": session_id, "cleared": True}


class GrillProjectBody(BaseModel):
    project: str
    max_sessions: int = 20


@router.post("/sessions/grill")
async def grill_project(body: GrillProjectBody, request: Request) -> dict[str, Any]:
    return await request.app.state.augment.grill_project(
        body.project, max_sessions=max(1, min(int(body.max_sessions or 20), 100)),
    )


@router.get("/sessions/{session_id}/history")
async def session_history(session_id: str, request: Request, limit: int = 200) -> dict[str, Any]:
    history = request.app.state.augment.sessions.history(session_id, limit=limit)
    return {"session_id": session_id, "history": [item.__dict__ for item in history]}


@router.delete("/sessions/{session_id}/history")
async def clear_session_history(session_id: str, request: Request) -> dict[str, Any]:
    request.app.state.augment.sessions.clear(session_id)
    return {"ok": True, "session_id": session_id}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, request: Request) -> dict[str, Any]:
    app = request.app.state.augment
    app.sessions.delete(session_id)
    app.mailboxes.clear(session_id)
    return {"ok": True, "session_id": session_id}


@router.get("/sessions/{session_id}/mailbox")
async def session_mailbox(session_id: str, request: Request, limit: int = 100) -> dict[str, Any]:
    return {"session_id": session_id, "mailbox": request.app.state.augment.mailboxes.list(session_id, limit=limit)}


@router.post("/sessions/{session_id}/mailbox")
async def add_session_mailbox(session_id: str, body: MailboxBody, request: Request) -> dict[str, Any]:
    item = request.app.state.augment.mailboxes.add(session_id, body.content, kind=body.kind)
    return {"item": item}


@router.get("/memory")
async def memory(request: Request) -> dict[str, Any]:
    app = request.app.state.augment
    return {
        "memory": app.memory.all(),
        "tiers": app.memory_snapshot(),
    }


# ── Tiered memory (working / episodic / semantic / procedural) ──────


class MemoryWorkingBody(BaseModel):
    key: str
    value: Any
    ttl: float = 600.0
    priority: int = 5


class MemorySemanticBody(BaseModel):
    key: str
    value: str
    category: str = "general"
    confidence: float = 0.8
    source: str = ""


class MemoryProcedureBody(BaseModel):
    name: str
    steps: list[str]
    trigger: str = ""
    success_rate: float = 1.0


class MemoryConsolidateBody(BaseModel):
    session_id: str = ""
    summary: str = ""
    outcome: str = "success"


@router.get("/memory/tiers")
async def memory_tiers(request: Request) -> dict[str, Any]:
    return request.app.state.augment.memory_snapshot()


@router.get("/memory/retrieve")
async def memory_retrieve(request: Request, q: str = "", limit: int = 10) -> dict[str, Any]:
    return {
        "query": q,
        "results": request.app.state.augment.memory_retrieve(q, limit=limit),
    }


@router.get("/memory/{tier}")
async def memory_tier(tier: str, request: Request, q: str = "", limit: int = 50) -> dict[str, Any]:
    app = request.app.state.augment
    if q:
        return {"tier": tier, "items": app.memory_search_tier(tier, q, limit=limit)}
    snap = app.memory_snapshot()
    if tier == "working":
        return {"tier": tier, "items": snap["working"]["items"]}
    if tier == "episodic":
        return {"tier": tier, "items": snap["episodic"]["recent"]}
    if tier == "semantic":
        return {"tier": tier, "items": snap["semantic"]["facts"]}
    if tier == "procedural":
        return {"tier": tier, "items": snap["procedural"]["procedures"]}
    return {"tier": tier, "items": []}


@router.post("/memory/working")
async def memory_put_working(body: MemoryWorkingBody, request: Request) -> dict[str, Any]:
    return request.app.state.augment.memory_put_working(
        body.key, body.value, ttl=body.ttl, priority=body.priority,
    )


@router.post("/memory/semantic")
async def memory_store_semantic(body: MemorySemanticBody, request: Request) -> dict[str, Any]:
    return request.app.state.augment.memory_store_semantic(
        body.key, body.value,
        category=body.category, confidence=body.confidence, source=body.source,
    )


@router.post("/memory/procedural")
async def memory_learn_procedure(body: MemoryProcedureBody, request: Request) -> dict[str, Any]:
    return request.app.state.augment.memory_learn_procedure(
        body.name, steps=body.steps, trigger=body.trigger, success_rate=body.success_rate,
    )


@router.delete("/memory/{tier}/{key}")
async def memory_remove(tier: str, key: str, request: Request) -> dict[str, Any]:
    removed = request.app.state.augment.memory_remove(tier, key)
    return {"removed": removed, "tier": tier, "key": key}


@router.post("/memory/consolidate")
async def memory_consolidate(body: MemoryConsolidateBody, request: Request) -> dict[str, Any]:
    return request.app.state.augment.memory_consolidate(
        session_id=body.session_id, summary=body.summary, outcome=body.outcome,
    )


@router.get("/context/preview")
async def context_preview(request: Request, message: str = "") -> dict[str, Any]:
    app = request.app.state.augment
    text = app.context.build(message=message, history=[])
    return {"context": text, "stats": app.context.stats()}


# ── Mind layer ──────────────────────────────────────────────────────


class MindEventBody(BaseModel):
    event_type: str
    detail: str = ""


@router.get("/mind")
async def mind_snapshot(request: Request) -> dict[str, Any]:
    return request.app.state.augment.mind_snapshot()


@router.post("/mind/event")
async def mind_event(body: MindEventBody, request: Request) -> dict[str, Any]:
    return request.app.state.augment.mind_event(body.event_type, body.detail)


@router.post("/mind/decay")
async def mind_decay(request: Request) -> dict[str, Any]:
    return request.app.state.augment.mind_decay()


# ── Mind extensions (monologue / beliefs / self_model / metacognition / user) ─


class MonologueBody(BaseModel):
    thought: str
    category: str = "reflection"


class BeliefBody(BaseModel):
    key: str
    value: Any
    confidence: float = 0.8


class WorldFactBody(BaseModel):
    fact: str
    source: str = ""


class CapabilityBody(BaseModel):
    skill: str
    confidence: float


class LearningBody(BaseModel):
    what: str
    context: str = ""


class LimitationBody(BaseModel):
    limitation: str


class StrategyBody(BaseModel):
    strategy: str
    reason: str = ""


class StrategyOutcomeBody(BaseModel):
    strategy: str
    success: bool
    duration_s: float = 0.0


class ReflectionBody(BaseModel):
    thought: str


class UserPreferenceBody(BaseModel):
    key: str
    value: Any


class UserObservationBody(BaseModel):
    observation: str
    category: str = "general"


class UserStyleBody(BaseModel):
    aspect: str
    value: str


@router.get("/mind/monologue")
async def mind_monologue(request: Request, limit: int = 25) -> dict[str, Any]:
    mind = request.app.state.augment.mind
    return {"recent": mind.monologue.recent(limit=max(1, min(int(limit or 25), 200)))}


@router.post("/mind/monologue")
async def mind_monologue_post(body: MonologueBody, request: Request) -> dict[str, Any]:
    mind = request.app.state.augment.mind
    mind.monologue.think(body.thought, category=body.category)
    return {"recent": mind.monologue.recent(limit=25)}


@router.get("/mind/beliefs")
async def mind_beliefs(request: Request) -> dict[str, Any]:
    mind = request.app.state.augment.mind
    return {
        "beliefs": mind.beliefs.all_beliefs(),
        "world": mind.beliefs.world_facts(limit=40),
    }


@router.post("/mind/beliefs")
async def mind_beliefs_set(body: BeliefBody, request: Request) -> dict[str, Any]:
    mind = request.app.state.augment.mind
    mind.beliefs.believe(body.key, body.value, confidence=body.confidence)
    return {"beliefs": mind.beliefs.all_beliefs()}


@router.post("/mind/beliefs/world")
async def mind_world_fact(body: WorldFactBody, request: Request) -> dict[str, Any]:
    mind = request.app.state.augment.mind
    mind.beliefs.add_world_fact(body.fact, source=body.source)
    return {"world": mind.beliefs.world_facts(limit=40)}


@router.get("/mind/self")
async def mind_self(request: Request) -> dict[str, Any]:
    mind = request.app.state.augment.mind
    return {
        "capabilities": mind.self_model.capabilities(),
        "learned": mind.self_model.learned(limit=50),
        "limitations": mind.self_model.limitations(),
    }


@router.post("/mind/self/capability")
async def mind_self_capability(body: CapabilityBody, request: Request) -> dict[str, Any]:
    mind = request.app.state.augment.mind
    mind.self_model.update_capability(body.skill, body.confidence)
    return {"capabilities": mind.self_model.capabilities()}


@router.post("/mind/self/learning")
async def mind_self_learning(body: LearningBody, request: Request) -> dict[str, Any]:
    mind = request.app.state.augment.mind
    mind.self_model.record_learning(body.what, context=body.context)
    return {"learned": mind.self_model.learned(limit=10)}


@router.post("/mind/self/limitation")
async def mind_self_limitation(body: LimitationBody, request: Request) -> dict[str, Any]:
    mind = request.app.state.augment.mind
    mind.self_model.add_limitation(body.limitation)
    return {"limitations": mind.self_model.limitations()}


@router.get("/mind/metacognition")
async def mind_metacognition(request: Request) -> dict[str, Any]:
    return request.app.state.augment.mind.metacognition.snapshot()


@router.post("/mind/metacognition/strategy")
async def mind_strategy(body: StrategyBody, request: Request) -> dict[str, Any]:
    mind = request.app.state.augment.mind
    mind.metacognition.set_strategy(body.strategy, reason=body.reason)
    return mind.metacognition.snapshot()


@router.post("/mind/metacognition/outcome")
async def mind_strategy_outcome(body: StrategyOutcomeBody, request: Request) -> dict[str, Any]:
    mind = request.app.state.augment.mind
    mind.metacognition.record_outcome(body.strategy, body.success, duration_s=body.duration_s)
    return mind.metacognition.snapshot()


@router.post("/mind/metacognition/reflect")
async def mind_metacognition_reflect(body: ReflectionBody, request: Request) -> dict[str, Any]:
    mind = request.app.state.augment.mind
    mind.metacognition.reflect(body.thought)
    return mind.metacognition.snapshot()


@router.get("/mind/user_profile")
async def mind_user_profile(request: Request) -> dict[str, Any]:
    mind = request.app.state.augment.mind
    return {
        "preferences": mind.user_profile.preferences(),
        "style": mind.user_profile.style(),
        "observations": mind.user_profile.observations(limit=20),
    }


@router.post("/mind/user_profile/preference")
async def mind_user_pref(body: UserPreferenceBody, request: Request) -> dict[str, Any]:
    mind = request.app.state.augment.mind
    mind.user_profile.set_preference(body.key, body.value)
    return {"preferences": mind.user_profile.preferences()}


@router.post("/mind/user_profile/observation")
async def mind_user_observe(body: UserObservationBody, request: Request) -> dict[str, Any]:
    mind = request.app.state.augment.mind
    mind.user_profile.observe(body.observation, category=body.category)
    return {"observations": mind.user_profile.observations(limit=20)}


@router.post("/mind/user_profile/style")
async def mind_user_style(body: UserStyleBody, request: Request) -> dict[str, Any]:
    mind = request.app.state.augment.mind
    mind.user_profile.set_style(body.aspect, body.value)
    return {"style": mind.user_profile.style()}


# ── Planning ────────────────────────────────────────────────────────


class PlanBuildBody(BaseModel):
    goal: str
    session_id: str = ""
    cwd: str | None = None
    llm_json: dict[str, Any] | str | None = None


class PlanSaveBody(BaseModel):
    plan: dict[str, Any]


@router.get("/plans")
async def list_plans(request: Request, limit: int = 50) -> dict[str, Any]:
    return {"plans": request.app.state.augment.plan_list(limit=limit)}


@router.post("/plans/build")
async def build_plan(body: PlanBuildBody, request: Request) -> dict[str, Any]:
    return {
        "plan": request.app.state.augment.plan_build(
            body.goal,
            session_id=body.session_id,
            cwd=body.cwd,
            llm_json=body.llm_json,
        )
    }


@router.get("/plans/{session_id}")
async def get_plan(session_id: str, request: Request) -> dict[str, Any]:
    return {"session_id": session_id, "plan": request.app.state.augment.plan_get(session_id)}


@router.put("/plans/{session_id}")
async def save_plan(session_id: str, body: PlanSaveBody, request: Request) -> dict[str, Any]:
    payload = dict(body.plan or {})
    payload["session_id"] = session_id
    return {"plan": request.app.state.augment.plan_save(payload)}


@router.delete("/plans/{session_id}")
async def delete_plan(session_id: str, request: Request) -> dict[str, Any]:
    removed = request.app.state.augment.plan_delete(session_id)
    return {"removed": removed, "session_id": session_id}


# ── Builder (file policies + environment) ───────────────────────────


@router.get("/builder/policies")
async def builder_policies(request: Request) -> dict[str, Any]:
    return {"policies": request.app.state.augment.file_policies()}


@router.get("/builder/policy")
async def builder_policy_for(request: Request, path: str = "", content_hint: str = "") -> dict[str, Any]:
    return {"path": path, "policy": request.app.state.augment.file_policy_for(path, content_hint=content_hint)}


@router.get("/builder/environment")
async def builder_environment(request: Request) -> dict[str, Any]:
    return request.app.state.augment.environment_snapshot()


# ── Edit receipts (diff trail) ──────────────────────────────────────


@router.get("/builder/receipts")
async def builder_receipts(request: Request, limit: int = 50) -> dict[str, Any]:
    return {"receipts": request.app.state.augment.list_edit_receipts(limit=limit)}


@router.get("/builder/receipts/{receipt_id}")
async def builder_receipt(receipt_id: str, request: Request) -> dict[str, Any]:
    payload = request.app.state.augment.get_edit_receipt(receipt_id)
    return {"receipt_id": receipt_id, "receipt": payload}


# ── Verification profiles ───────────────────────────────────────────


class VerifyBody(BaseModel):
    files: list[str]
    profile: str = ""
    root: str | None = None


@router.get("/builder/verify/profiles")
async def builder_verify_profiles(request: Request) -> dict[str, Any]:
    return request.app.state.augment.verification_profiles()


@router.post("/builder/verify")
async def builder_verify(body: VerifyBody, request: Request) -> dict[str, Any]:
    return {
        "result": request.app.state.augment.verify_files(
            list(body.files or []),
            profile=body.profile,
            root=body.root,
        )
    }


# ── Background thinking ─────────────────────────────────────────────


class ThinkingStartBody(BaseModel):
    interval_s: float | None = None


@router.get("/mind/thinking")
async def thinking_status(request: Request, limit: int = 50) -> dict[str, Any]:
    app = request.app.state.augment
    return {"status": app.mind.thinking.status(), "log": app.thinking_log(limit=limit)}


@router.post("/mind/thinking/start")
async def thinking_start(body: ThinkingStartBody, request: Request) -> dict[str, Any]:
    return {"status": request.app.state.augment.start_thinking(interval_s=body.interval_s)}


@router.post("/mind/thinking/stop")
async def thinking_stop(request: Request) -> dict[str, Any]:
    return {"status": request.app.state.augment.stop_thinking()}
