from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from augment.agent import AgentMonitor
from augment.builder import (
    VerificationReceipt,
    detect_environment,
    get_receipt,
    list_receipts,
    policy_registry_payload,
    profile_for_files,
    resolve_file_policy,
    run_verification_profile,
    verification_profile_registry,
)
from augment.config import AppConfig, load_config
from augment.context.builder import ContextBuilder
from augment.context.conventions import ConventionsLoader
from augment.context.memory import MailboxStore, MemoryStore, SessionStore
from augment.context.rules_store import RulesStore
from augment.loop.react import ReActLoop
from augment.memory import MemorySystem
from augment.mind import Mind
from augment.planning import PlanGraph, PlanStateStore, StructuredPlanner
from augment.providers.registry import ProviderRegistry
from augment.sessions import MessageLedger, ScratchboardStore, TurnStateStore, UserModelStore
from augment.settings import SettingsStore
from augment.skills.adaptive import generate_adaptive_skills
from augment.streaming import StreamRegistry
from augment.skills.dormant_packs import dormant_skill_catalog
from augment.skills.store import SkillStore
from augment.soul import (
    build_agent_soul_context,
    distill_agent_history_lesson,
    read_agent_soul_files,
    reset_agent_soul_files,
    write_agent_soul_files,
)
from augment.tools.default import build_tool_registry
from augment.tools.packs import list_tool_packs, list_tools
from augment.tools.registry import ToolRegistry


@dataclass
class ChatResult:
    reply: str
    session_id: str
    model: str
    tool_calls: int
    iterations: int
    stopped_reason: str
    scratchpad: list[dict[str, Any]]
    context_stats: dict[str, object]


class AugmentApp:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.config.workspace_root.mkdir(parents=True, exist_ok=True)
        self.settings = SettingsStore(self.config)
        self.discovery_summary = self.settings.discover_providers(self.config.discover_sources)
        self.providers = ProviderRegistry(self.config, self.settings.provider_config())
        self.tools: ToolRegistry = build_tool_registry()
        self.sessions = SessionStore(self.config.data_dir)
        self.mailboxes = MailboxStore(self.config.data_dir)
        self.memory = MemoryStore(self.config.data_dir)
        self.memory_system = MemorySystem(self.config.data_dir)
        # ContextBuilder reads the active provider's context window through
        # this callback so its budget auto-scales when the user switches
        # provider/model. The settings store handles the 3-tier resolver
        # (override → introspection → static catalog → fallback). The
        # active_model callback picks the right tiktoken encoding so token
        # counts are accurate (o200k_base for gpt-4o/o1/o3/Claude/Llama
        # via universal estimator, cl100k_base for gpt-4/gpt-3.5).
        self.context = ContextBuilder(
            self.config,
            self.memory,
            context_window_provider=self.settings.active_context_window,
            active_model_provider=self._active_model_id,
        )
        self.agent = AgentMonitor(self.config.data_dir)
        self.skills = SkillStore(self.config.data_dir)
        self.mind = Mind(self.config.data_dir)
        self.planner = StructuredPlanner()
        self.plans = PlanStateStore(self.config.data_dir)
        # Session depth stores (scratchboard, turn state, message ledger, user model).
        self.scratchboards = ScratchboardStore(self.config.data_dir)
        self.turn_states = TurnStateStore(self.config.data_dir)
        self.message_ledger = MessageLedger(self.config.data_dir)
        self.user_model = UserModelStore(self.config.data_dir)
        # FAIL-parity coding-discipline stack: AGENTS.md auto-loader,
        # data/rules/*.md sheet loader, and per-session coding contract.
        # All three feed into the smart_top zone of the assembled prompt.
        self.conventions = ConventionsLoader(self.config.workspace_root)
        self.rules_store = RulesStore(
            data_dir=self.config.data_dir,
            workspace_root=self.config.workspace_root,
        )
        from augment.sessions.coding_contract import CodingContractStore
        self.coding_contracts = CodingContractStore(self.config.data_dir)
        # Decoupled stream registry: chat tasks live here, not in the
        # SSE generator's local scope. Surviving a browser reload means
        # the in-flight LLM call keeps running while the dropped SSE
        # subscriber goes away cleanly.
        self.streams = StreamRegistry()
        self.mind.on_event("new_session", "service boot")

    def _active_model_id(self) -> str:
        """Active model id for tokenizer selection.

        Tries the live provider first (it's the source of truth — gets
        updated when the user picks a model in the UI). Falls back to
        the settings store's default profile, then to the config default.
        Never raises; an empty string just makes the tokenizer fall back
        to its universal default.
        """
        try:
            provider = self.providers.default()
            if provider and provider.model:
                return str(provider.model)
        except Exception:
            pass
        try:
            return str(self.settings.default_profile().get("model") or "")
        except Exception:
            return ""

    async def chat(self, message: str, *, session_id: str = "", step_callback: Any = None, images: list[str] | None = None) -> ChatResult:
        if not self.settings.has_default_profile():
            raise RuntimeError("No provider configured. Add one in Settings → Providers & Keys.")
        resumed = bool(session_id)
        sid = session_id or self.sessions.new_session_id()
        # Auto-tag the session's project from the workspace folder name.
        if not resumed and not self.sessions.project_for(sid):
            try:
                project = self.config.workspace_root.resolve().name
                if project:
                    self.sessions.set_project(sid, project)
            except Exception:
                pass
        self.agent.record_session(resumed=resumed)
        self.agent.mark_status("thinking", detail=f"session {sid[:14]}")
        self.sessions.append(sid, "user", message)
        self.memory.remember_from_user(message, session_id=sid)
        # Sessions-depth: observe the user turn before building the prompt.
        self.scratchboards.update(sid, role="user", content=message)
        self.turn_states.update(sid, role="user", content=message)
        self.user_model.observe(message, session_id=sid)
        user_receipt = self.message_ledger.record(
            sid,
            role="user",
            content=message,
            direction="inbound",
            source="chat",
        )
        history = self.sessions.history(sid, limit=40)
        profile = self.agent.profile()
        skills_context = self.skills.context_block(max_chars=4000)
        soul_context = build_agent_soul_context(self.config.data_dir, profile)
        identity_override = self._identity_block(profile)
        mind_context = self.mind.context_block(max_chars=1200)
        plan_context = self.plans.context_block(sid, max_chars=5000)
        memory_context = self.memory_system.context_block(query=message, max_chars=2000)
        scratchboard_context = self.scratchboards.context_block(sid, max_chars=3000)
        turn_state_context = self.turn_states.context_block(sid, max_chars=2000)
        user_model_context = self.user_model.context_block(max_chars=1800)
        message_ledger_context = self.message_ledger.context_block(sid, max_chars=2500)
        # FAIL-parity discipline sections — loaded fresh per build so the
        # user's edits to AGENTS.md / data/rules/*.md / the coding contract
        # take effect on the next turn without a server restart.
        project_conventions_block = self.conventions.context_block()
        user_rules_block = self.rules_store.context_block()
        coding_contract_block = self.coding_contracts.context_block(sid)
        system_prompt = self.context.build(
            message=message,
            history=history[:-1],
            mailbox_context=self.mailboxes.context_block(sid),
            skills_context=skills_context,
            soul_context=soul_context,
            identity_override=identity_override,
            mind_context=mind_context,
            plan_context=plan_context,
            memory_tiers=memory_context,
            scratchboard=scratchboard_context,
            turn_state=turn_state_context,
            user_model=user_model_context,
            message_ledger=message_ledger_context,
            project_conventions=project_conventions_block,
            user_rules=user_rules_block,
            coding_contract=coding_contract_block,
        )
        # Emit the assembled-context snapshot so the UI can render a
        # "bleep" expandable panel in the thinking bubble — same idea as
        # Blackboard's "bleeping" phase + FAIL's section inspector but
        # surfaced inline in the streaming chat.
        bleep_event = {
            "kind": "bleep",
            "session_id": sid,
            "stats": self.context.stats(),
            "prompt_preview": system_prompt[:2000],
            "prompt_chars": len(system_prompt),
            "message": message[:300],
        }
        if step_callback:
            outcome = step_callback(bleep_event)
            if hasattr(outcome, "__await__"):
                await outcome
        loop = ReActLoop(
            self.providers.default(),
            self.tools,
            system_prompt=system_prompt,
            max_iterations=self.config.loop.max_iterations,
            temperature=self.config.loop.temperature,
        )
        loop_history = [{"role": item.role, "content": item.content} for item in history[:-1]]

        async def _wrapped_callback(event: dict[str, Any]) -> None:
            if isinstance(event, dict) and event.get("kind") == "observation":
                self.agent.record_tool_run(
                    str(event.get("tool") or "tool"),
                    success=bool(event.get("success", True)),
                    duration_ms=float(event.get("duration_ms") or 0.0),
                )
            if step_callback:
                outcome = step_callback(event)
                if hasattr(outcome, "__await__"):
                    await outcome

        try:
            result = await loop.run(
                message,
                history_messages=loop_history,
                tool_context={
                    "workspace_root": str(self.config.workspace_root),
                    "scratch_root": str(self.config.scratch_root),
                    "output_dir": str(self.sessions.meta(sid).get("output_dir") or ""),
                    "session_id": sid,
                    "sessions_store": self.sessions,
                    "data_dir": str(self.config.data_dir),
                    "memory": self.memory,
                    "memory_system": self.memory_system,
                    "agent": self.agent,
                    "tool_registry": self.tools,
                },
                step_callback=_wrapped_callback,
                images=images,
            )
        except Exception as exc:
            self.agent.mark_status("error")
            self.mind.on_event("task_failure", str(exc)[:120])
            raise
        self.sessions.append(sid, "assistant", result.content)
        self.agent.mark_status("idle", detail=result.stopped_reason)
        # Mirror the assistant turn into sessions-depth.
        self.scratchboards.update(sid, role="assistant", content=result.content)
        self.turn_states.update(sid, role="assistant", content=result.content)
        try:
            self.message_ledger.record(
                sid,
                role="assistant",
                content=result.content,
                direction="outbound",
                source="chat",
                reply_to=getattr(user_receipt, "message_id", ""),
                status=result.stopped_reason,
            )
        except Exception:
            pass
        success_outcome = "final" in (result.stopped_reason or "").lower()
        self.mind.on_event(
            "task_success" if success_outcome else "idle",
            f"{result.iterations} iter / {result.tool_calls} tools",
        )
        # Consolidate this turn into the tiered memory: record an episode +
        # promote any high-priority working items. Cheap, file-local writes.
        try:
            scratchpad = result.scratchpad.to_list()
            tools_used = sorted({
                str(step.get("tool") or "")
                for step in scratchpad
                if step.get("kind") == "action" and step.get("tool")
            })
            self.memory_system.consolidator.consolidate_session(
                session_id=sid,
                summary=message[:480],
                outcome="success" if success_outcome else "error",
                tools_used=list(tools_used) or None,
            )
        except Exception:
            pass
        return ChatResult(
            reply=result.content,
            session_id=sid,
            model=self.providers.default().model,
            tool_calls=result.tool_calls,
            iterations=result.iterations,
            stopped_reason=result.stopped_reason,
            scratchpad=result.scratchpad.to_list(),
            context_stats=self.context.stats(),
        )

    async def _reload_default_provider(self) -> None:
        await self.providers.close()
        self.providers = ProviderRegistry(self.config, self.settings.provider_config())

    async def _refresh_profile_models(self, profile_id: str) -> tuple[list[str], str]:
        from augment.providers.registry import build_provider

        provider_cfg = self.settings.provider_config(profile_id)
        provider = build_provider(provider_cfg)
        try:
            models = await provider.list_models()
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                await provider.close()
        self.settings.save_profile_models(profile_id, models)
        return models, ""

    async def update_provider(self, values: dict[str, Any]) -> dict[str, Any]:
        """Back-compat updater used by ``PUT /api/providers``.

        Find-or-create a profile that matches the supplied preset (or the
        preset auto-detected from the key) and mark it as the default. Mirrors
        FAIL's settings save-and-promote flow.
        """
        result = self.settings.update_default(values)
        await self._reload_default_provider()
        provider = result.get("provider") or {}
        if provider.get("has_env_key") or provider.get("has_inline_key") or not provider.get("key_required", True):
            try:
                models, _ = await self._refresh_profile_models(provider["id"])
                provider["models"] = models
                result["provider"] = provider
            except Exception as exc:
                result["models_error"] = str(exc)
        snapshot = self.settings.public_snapshot()
        return {**result, **snapshot}

    async def add_provider(self, values: dict[str, Any]) -> dict[str, Any]:
        outcome = self.settings.add_profile(values, make_default=True)
        await self._reload_default_provider()
        profile = outcome["profile"]
        if profile.get("has_inline_key") or profile.get("has_env_key") or not profile.get("key_required", True):
            try:
                models, _ = await self._refresh_profile_models(profile["id"])
                profile["models"] = models
            except Exception as exc:
                outcome["models_error"] = str(exc)
        snapshot = self.settings.public_snapshot()
        return {**outcome, **snapshot}

    async def remove_provider(self, profile_id: str) -> dict[str, Any]:
        removed = self.settings.remove_profile(profile_id)
        if removed:
            await self._reload_default_provider()
        return {"removed": removed, **self.settings.public_snapshot()}

    async def set_default_provider(self, profile_id: str) -> dict[str, Any]:
        changed = self.settings.set_default(profile_id)
        if changed:
            await self._reload_default_provider()
        return {"changed": changed, **self.settings.public_snapshot()}

    async def set_profile_key(self, profile_id: str, api_key: str) -> dict[str, Any]:
        profile = self.settings.set_profile_key(profile_id, api_key)
        if profile and profile_id == self.settings.default_profile_id():
            await self._reload_default_provider()
        if profile and (profile.get("has_inline_key") or profile.get("has_env_key") or not profile.get("key_required", True)):
            try:
                models, _ = await self._refresh_profile_models(profile_id)
                profile["models"] = models
            except Exception as exc:
                profile["models_error"] = str(exc)
        return {"profile": profile, **self.settings.public_snapshot()}

    async def set_profile_model(self, profile_id: str, model: str) -> dict[str, Any]:
        profile = self.settings.set_profile_model(profile_id, model)
        if profile and profile_id == self.settings.default_profile_id():
            await self._reload_default_provider()
        return {"profile": profile, **self.settings.public_snapshot()}

    async def refresh_provider_models(self, profile_id: str | None = None) -> dict[str, Any]:
        pid = profile_id or self.settings.default_profile_id()
        models, _ = await self._refresh_profile_models(pid)
        snapshot = self.settings.public_snapshot()
        return {"profile_id": pid, "models": models, "loaded": len(models), **snapshot}

    async def discover_providers(self) -> dict[str, Any]:
        outcome = self.settings.discover_providers(self.config.discover_sources)
        if outcome.get("added"):
            await self._reload_default_provider()
        snapshot = self.settings.public_snapshot()
        return {**outcome, **snapshot}

    async def restore_preset(self, preset_id: str) -> dict[str, Any]:
        self.settings.restore_preset(preset_id)
        outcome = self.settings.discover_providers(self.config.discover_sources)
        if outcome.get("added"):
            await self._reload_default_provider()
        snapshot = self.settings.public_snapshot()
        return {"preset_id": preset_id, **outcome, **snapshot}

    async def provider_health(self) -> dict[str, object]:
        if not self.settings.has_default_profile():
            return {"ok": None, "error": "no provider configured"}
        return await self.providers.health()

    def tool_packs(self) -> dict[str, Any]:
        return list_tool_packs(self.tools)

    def tools_detailed(self) -> list[dict[str, Any]]:
        return list_tools(self.tools)

    def skills_catalog(self) -> dict[str, Any]:
        return {
            "dormant_packs": dormant_skill_catalog(),
            "adaptive_skills": [skill.to_dict() for skill in self.skills.list(limit=50)],
        }

    def generate_skills(self, *, session_id: str = "", objective: str = "") -> list[dict[str, Any]]:
        skills = generate_adaptive_skills(self, session_id=session_id, objective=objective)
        return [skill.to_dict() for skill in skills]

    def skills_context(self, *, max_chars: int = 4000) -> str:
        return self.skills.context_block(max_chars=max_chars)

    def soul(self) -> dict[str, Any]:
        return read_agent_soul_files(self.config.data_dir, self.agent.profile())

    def update_soul(self, *, files: dict[str, Any] | None = None, enabled: bool | None = None) -> dict[str, Any]:
        if enabled is not None:
            self.agent.update_profile({"soul_enabled": bool(enabled)})
        profile = self.agent.profile()
        if files:
            write_agent_soul_files(self.config.data_dir, profile, files)
        return read_agent_soul_files(self.config.data_dir, profile)

    def reset_soul(self) -> dict[str, Any]:
        return reset_agent_soul_files(self.config.data_dir, self.agent.profile())

    def record_history_lesson(self, lesson: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return distill_agent_history_lesson(self.config.data_dir, self.agent.profile(), lesson, metadata)

    # ── Mind / personality / drives ─────────────────────────────────
    def mind_snapshot(self) -> dict[str, Any]:
        return self.mind.snapshot()

    def mind_event(self, event_type: str, detail: str = "") -> dict[str, Any]:
        self.mind.on_event(event_type, detail)
        return self.mind.snapshot()

    def mind_decay(self) -> dict[str, Any]:
        self.mind.decay()
        return self.mind.snapshot()

    # ── Planning ────────────────────────────────────────────────────
    def plan_build(
        self,
        goal: str,
        *,
        session_id: str = "",
        cwd: str | None = None,
        llm_json: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cwd_value = cwd or str(self.config.workspace_root)
        graph: PlanGraph = self.planner.build_plan(
            goal,
            session_id=session_id,
            cwd=cwd_value,
            llm_json=llm_json,
        )
        if session_id:
            self.plans.save(graph)
        return graph.to_dict()

    def plan_get(self, session_id: str) -> dict[str, Any]:
        graph = self.plans.load(session_id)
        return graph.to_dict() if graph else {}

    def plan_list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return [graph.to_dict() for graph in self.plans.list(limit=limit)]

    def plan_save(self, payload: dict[str, Any]) -> dict[str, Any]:
        graph = PlanGraph.from_dict(payload or {})
        self.plans.save(graph)
        return graph.to_dict()

    def plan_delete(self, session_id: str) -> bool:
        return self.plans.delete(session_id)

    # ── Builder (file policies + environment) ───────────────────────
    def file_policies(self) -> list[dict[str, Any]]:
        return policy_registry_payload()

    def file_policy_for(self, path: str, *, content_hint: str = "") -> dict[str, Any]:
        return resolve_file_policy(path, content_hint=content_hint).to_dict()

    def environment_snapshot(self) -> dict[str, Any]:
        return detect_environment().to_dict()

    # ── Edit receipts (diff trail) ──────────────────────────────────
    def list_edit_receipts(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return list_receipts(self.config.data_dir, limit=limit)

    def get_edit_receipt(self, receipt_id: str) -> dict[str, Any] | None:
        return get_receipt(self.config.data_dir, receipt_id)

    # ── Verification profiles ───────────────────────────────────────
    def verification_profiles(self) -> dict[str, Any]:
        return {
            "profiles": verification_profile_registry(),
        }

    def verify_files(
        self,
        files: list[str],
        *,
        profile: str = "",
        root: str | None = None,
    ) -> dict[str, Any]:
        target_root = root or str(self.config.workspace_root)
        result: VerificationReceipt = run_verification_profile(
            target_root,
            files or [],
            profile=profile,
        )
        return result.to_dict()

    # ── Tiered memory (working / episodic / semantic / procedural) ─
    def memory_snapshot(self) -> dict[str, Any]:
        return self.memory_system.snapshot()

    def memory_retrieve(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        return self.memory_system.retriever.retrieve(query, limit=max(1, int(limit or 10)))

    def memory_search_tier(self, tier: str, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        clean_tier = (tier or "").strip().lower()
        if clean_tier == "semantic":
            return self.memory_system.semantic.search(query, limit=limit)
        if clean_tier == "episodic":
            return self.memory_system.episodic.search(query, limit=limit)
        if clean_tier == "procedural":
            return self.memory_system.procedural.find_for_trigger(query)
        if clean_tier == "working":
            needle = (query or "").lower()
            return [
                item for item in self.memory_system.working.all_items()
                if not needle or needle in f"{item.get('key','')} {item.get('value','')}".lower()
            ]
        return []

    def memory_put_working(self, key: str, value: Any, *, ttl: float = 600.0, priority: int = 5) -> dict[str, Any]:
        self.memory_system.working.put(key, value, ttl=ttl, priority=priority)
        return {"key": key, "items": self.memory_system.working.all_items()}

    def memory_store_semantic(
        self,
        key: str,
        value: str,
        *,
        category: str = "general",
        confidence: float = 0.8,
        source: str = "",
    ) -> dict[str, Any]:
        self.memory_system.semantic.store(
            key, value, category=category, confidence=confidence, source=source,
        )
        return {
            "key": key.strip().lower(),
            "facts": self.memory_system.semantic.all_facts(limit=50),
        }

    def memory_learn_procedure(
        self,
        name: str,
        *,
        steps: list[str],
        trigger: str = "",
        success_rate: float = 1.0,
    ) -> dict[str, Any]:
        self.memory_system.procedural.learn(
            name, steps=steps, trigger=trigger, success_rate=success_rate,
        )
        return {
            "name": name.strip().lower(),
            "procedures": self.memory_system.procedural.all_procedures(limit=50),
        }

    def memory_remove(self, tier: str, key: str) -> bool:
        clean_tier = (tier or "").strip().lower()
        if clean_tier == "semantic":
            return self.memory_system.semantic.remove(key)
        if clean_tier == "procedural":
            return self.memory_system.procedural.remove(key)
        if clean_tier == "working":
            self.memory_system.working.remove(key)
            return True
        return False

    def memory_consolidate(
        self,
        *,
        session_id: str = "",
        summary: str = "",
        outcome: str = "success",
    ) -> dict[str, Any]:
        self.memory_system.consolidator.consolidate_session(
            session_id=session_id,
            summary=summary,
            outcome=outcome,
        )
        return self.memory_snapshot()

    # ── Sessions by project ─────────────────────────────────────────
    def list_sessions_by_project(self, *, limit: int = 200) -> dict[str, Any]:
        grouped = self.sessions.list_by_project(limit=limit)
        projects: list[dict[str, Any]] = []
        for project, items in grouped.items():
            items_sorted = sorted(items, key=lambda s: -float(s.get("updated_at") or 0))
            projects.append({
                "project": project,
                "session_count": len(items_sorted),
                "last_updated": items_sorted[0].get("updated_at") if items_sorted else 0,
                "sessions": items_sorted,
            })
        projects.sort(key=lambda p: -float(p.get("last_updated") or 0))
        return {"projects": projects, "total_sessions": sum(p["session_count"] for p in projects)}

    def set_session_project(self, session_id: str, project: str) -> dict[str, Any]:
        return self.sessions.set_project(session_id, project)

    async def grill_project(self, project: str, *, max_sessions: int = 20) -> dict[str, Any]:
        """Run a meta-summarization across all sessions in ``project``.

        Uses the configured default provider and the InnerMonologue to record
        the synthesis. Returns the brief plus a list of contributing sessions.
        """
        from augment.providers.base import Message  # local import to avoid cycle

        clean_project = (project or "").strip()
        grouped = self.sessions.list_by_project(limit=500)
        sessions = list(grouped.get(clean_project, []))[: max(1, max_sessions)]
        if not sessions:
            return {"project": clean_project, "summary": "", "sessions": []}

        # Build a compact transcript of each session — first user turn + last reply.
        digests: list[str] = []
        for session in sessions:
            sid = session.get("session_id") or ""
            history = self.sessions.history(sid, limit=80)
            first_user = next(
                (m.content for m in history if m.role == "user" and (m.content or "").strip()),
                "",
            )
            last = history[-1] if history else None
            digests.append(
                f"Session {sid[:12]} (title='{session.get('title', '')}', "
                f"messages={session.get('message_count', 0)}):\n"
                f"  First ask: {(first_user or '')[:240]}\n"
                f"  Last {last.role if last else 'turn'}: {(last.content if last else '')[:240]}"
            )

        prompt = (
            "Synthesize a project brief from these chat sessions.\n\n"
            f"Project: {clean_project or '(unassigned)'}\n"
            f"Sessions in scope: {len(sessions)}\n\n"
            f"{chr(10).join(digests)}\n\n"
            "Produce:\n"
            "1. **Theme.** What is this project trying to do?\n"
            "2. **Recent work.** What was actually accomplished across sessions?\n"
            "3. **Open threads.** What questions or tasks are still pending?\n"
            "4. **Suggested next step.** The single highest-value next action.\n"
            "Use bullet points and cite specific session IDs when relevant."
        )

        if not self.settings.has_default_profile():
            return {"project": clean_project, "summary": "(no provider configured)", "sessions": sessions}

        provider = self.providers.default()
        response = await provider.complete(
            [
                Message("system", "You are a careful project archivist. Be concise and structured."),
                Message("user", prompt),
            ],
            temperature=0.3,
        )
        summary = (response.content or "").strip()
        # Record the synthesis to the inner monologue so future sessions see it.
        try:
            self.mind.monologue.think(
                f"Grilled project '{clean_project}' across {len(sessions)} sessions: {summary[:600]}",
                category="project_grill",
                metadata={"project": clean_project, "session_count": len(sessions)},
            )
        except Exception:
            pass
        return {"project": clean_project, "summary": summary, "sessions": sessions}

    # ── Thinking (background reflection) ────────────────────────────
    def _thinking_log_path(self):
        return self.config.data_dir / "mind" / "thinking_log.jsonl"

    def _build_think_fn(self):
        from augment.providers.base import Message  # local import to avoid cycle

        async def think_fn(prompt: str) -> str:
            if not self.settings.has_default_profile():
                return ""
            try:
                provider = self.providers.default()
                response = await provider.complete(
                    [
                        Message("system", self._thinking_system_prompt()),
                        Message("user", prompt),
                    ],
                    temperature=0.3,
                    max_tokens=160,
                )
            except Exception as exc:
                return f"[think error: {exc}]"
            reflection = (response.content or "").strip()
            if reflection:
                self._append_thinking_log(reflection)
                # Distil a soft mind signal so personality reflects activity.
                self.mind.on_event("idle", "background thought")
            return reflection

        return think_fn

    def _thinking_system_prompt(self) -> str:
        profile = self.agent.profile()
        name = str(profile.get("name") or "Augment")
        return (
            f"You are {name}'s background reflection loop. You do NOT have tools "
            "and you do NOT talk to the user. Produce a single brief 2-3 sentence "
            "introspective note based on recent activity. Be concrete and honest."
        )

    def _append_thinking_log(self, content: str) -> None:
        import json
        import time as _time

        path = self._thinking_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps({"ts": _time.time(), "content": content}, ensure_ascii=False)
                    + "\n"
                )
        except Exception:
            pass

    def start_thinking(self, *, interval_s: float | None = None) -> dict[str, Any]:
        if interval_s is not None and interval_s > 0:
            self.mind.thinking._interval = max(30.0, float(interval_s))  # noqa: SLF001
        self.mind.thinking.set_think_fn(self._build_think_fn())
        self.mind.thinking.start()
        return self.mind.thinking.status()

    def stop_thinking(self) -> dict[str, Any]:
        self.mind.thinking.stop()
        return self.mind.thinking.status()

    def thinking_log(self, *, limit: int = 50) -> list[dict[str, Any]]:
        import json

        path = self._thinking_log_path()
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except Exception:
                continue
        return rows[-max(1, limit):]

    @staticmethod
    def _identity_block(profile: dict[str, Any]) -> str:
        name = str(profile.get("name") or "Augment").strip()
        role = str(profile.get("role") or "").strip()
        description = str(profile.get("description") or "").strip()
        persona = str(profile.get("persona") or "").strip()
        lines = [f"[AGENT IDENTITY]", f"You are {name}."]
        if role:
            lines.append(f"Role: {role}.")
        if description:
            lines.append(f"Description: {description}")
        if persona:
            lines.append(f"Voice: {persona}")
        lines.append("Answer directly, use tools when they materially improve correctness, and cite tool evidence when relevant. Do not claim files were changed unless a write/edit tool succeeded.")
        return "\n".join(lines)

    async def close(self) -> None:
        await self.providers.close()
