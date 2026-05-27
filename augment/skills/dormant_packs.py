"""Dormant specialist skill packs catalog — ported verbatim from FAIL.

These packs are not always-on roles. The single Augment loop summons their
behavior only when the current task matches the pack's domain. The catalog is
exposed to the UI and surfaced into the system prompt via the adaptive skill
context block.
"""
from __future__ import annotations

from typing import Any, Dict, List

from augment.skills.holmes import HOLMES_DORMANT_PACK
from augment.skills.pocock_packs import POCOCK_DORMANT_PACKS


TOP_LEVEL_CATEGORIES = [
    "Control",
    "Planning",
    "Research",
    "Product",
    "Design",
    "Architecture",
    "Code",
    "Testing",
    "Security",
    "Data",
    "Memory",
    "Automation",
    "Browser",
    "Operations",
    "Performance",
    "Content",
    "Review",
    "Support",
]


def _pack(
    pack_id: str,
    name: str,
    category: str,
    description: str,
    when_to_use: List[str],
    outputs: List[str],
    required_tools: List[str],
    permissions: List[str],
    risk_level: str,
    handoffs: List[str],
) -> Dict[str, Any]:
    return {
        "id": pack_id,
        "name": name,
        "category": category,
        "description": description,
        "when_to_use": when_to_use,
        "when_not_to_use": [
            "Do not activate for unrelated tasks.",
            "Do not duplicate work already owned by another active specialist.",
            "Do not mutate files unless this pack explicitly owns writing or has a handoff from the single writer.",
        ],
        "inputs": ["work_order", "roadmap", "current_task", "available_evidence"],
        "outputs": outputs,
        "required_tools": required_tools,
        "allowed_permissions": permissions,
        "risk_level": risk_level,
        "steps": [
            "Read the active task, mailbox notes, and acceptance criteria.",
            "Identify the smallest useful contribution for this specialist pack.",
            "Produce structured output with evidence, blockers, confidence, and handoff target.",
            "Record durable findings to memory or the session mailbox when relevant.",
        ],
        "acceptance_check": "The pack output is specific, bounded, evidence-backed, and gives the next step a clear handoff or completion signal.",
        "handoff_targets": handoffs,
        "memory_write_policy": "Write only durable decisions, reusable facts, verified outcomes, unresolved blockers, and user preferences. Avoid noisy transcript dumps.",
        "active_by_default": False,
    }


DORMANT_SKILL_PACKS: List[Dict[str, Any]] = [
    _pack("task_manager", "Task Manager", "Control", "Creates, orders, pauses, resumes, and closes tasks on the shared state board.", ["The work order has multiple steps, blockers, dependencies, or needs resume/continue handling."], ["ordered task list", "status changes", "blocked/resume/close decisions"], ["mailbox"], ["state_write"], "medium", ["planner", "state_board"]),
    _pack("policy_guard", "Policy Guard", "Control", "Applies permission checks, risk gates, human approval rules, and unsafe action blockers.", ["A tool call, file change, network action, secret, approval, or destructive operation may be risky."], ["risk decision", "approval requirement", "blocked action rationale"], ["mailbox"], ["policy_review"], "high", ["security_reviewer", "tool_router"]),
    _pack("state_board", "State Board", "Control", "Maintains task state, evidence, and ownership across the session mailbox.", ["The session needs visible execution state, evidence, or task ownership updated."], ["board update", "evidence link", "owner/status map"], ["mailbox"], ["state_write"], "medium", ["task_manager", "planner"]),
    _pack("web_researcher", "Web Researcher", "Research", "Plans searches, ranks sources, extracts facts, and checks current information.", ["The task needs current web information, source discovery, or external examples."], ["search plan", "ranked sources", "fact extracts"], ["search_code", "search_files"], ["network"], "medium", ["source_verifier", "evidence_board"]),
    _pack("source_verifier", "Source Verifier", "Research", "Checks primary sources, citations, contradictions, recency, and source quality.", ["Claims need proof, citation audit, contradiction scan, or confidence scoring."], ["verified claims", "citation audit", "contradiction report"], ["read_file", "search_code"], ["network"], "medium", ["evidence_board", "reviewer"]),
    _pack("product_designer", "Product Designer", "Product", "Defines user stories, feature slices, MVP boundaries, and product tradeoffs.", ["The request is product-shaped, has vague scope, or needs MVP slicing."], ["user stories", "MVP boundary", "feature priorities"], ["mailbox"], ["analysis"], "low", ["ux_designer", "planner", "architect"]),
    _pack("ux_designer", "UX Designer", "Design", "Designs flows, wireframes, user journeys, friction audits, and usability improvements.", ["The task involves user flow, interaction friction, onboarding, or usability."], ["flow map", "wireframe notes", "friction audit"], ["mailbox"], ["analysis"], "low", ["ui_designer", "interaction_designer", "frontend_engineer"]),
    _pack("codebase_mapper", "Codebase Mapper", "Architecture", "Discovers files, call graph, ownership, dependency boundaries, and affected paths.", ["Before implementation/refactor/debugging when code ownership or impact is unclear."], ["file map", "call graph notes", "impact zone"], ["search_code", "read_file", "list_dir"], ["filesystem_read"], "low", ["architect", "builder", "debugger"]),
    _pack("debugger", "Debugger", "Code", "Builds repro steps, reads logs, hunts root cause, and separates symptoms from causes.", ["There is a bug, failing test, error log, regression, or unknown runtime behavior."], ["repro steps", "root cause", "fix target"], ["read_file", "search_code"], ["filesystem_read"], "medium", ["builder", "tester", "reviewer"]),
    _pack("refactorer", "Refactorer", "Code", "Simplifies code, removes dead paths, splits modules, and reduces duplication safely.", ["The code works but needs simplification, cleanup, duplication removal, or maintainability improvements."], ["refactor plan", "safe edit scope", "risk list"], ["search_code", "read_file"], ["filesystem_read"], "medium", ["architect", "builder", "regression_tester"]),
    _pack(
        "code_style",
        "Code Style & Comments",
        "Code",
        # Description — what this pack enforces when active.
        "Enforces well-commented, well-structured code. Adds section banners, "
        "docstrings, why-not-what comments, and a file-header summary block for "
        "every new or substantially-modified file.",
        # when_to_use
        [
            "About to write a brand-new file (single-file demo, page, module).",
            "Adding a new function/class/section to an existing file.",
            "Refactoring code where the original lacks comments or structural markers.",
            "User asks for 'production quality' / 'well-commented' / 'clean' code.",
        ],
        # outputs — what artifacts this pack guarantees on its turns.
        [
            "File-header banner summarising purpose + key sections",
            "Section comments (HTML <!-- -->, JS/CSS /* ... */, Python # ── ──)",
            "Docstrings on every exported function/class",
            "Inline comments only where they explain WHY, never WHAT",
            "Consistent naming / spacing / import order with the rest of the file",
        ],
        # required_tools
        ["read_file", "write_file", "edit_file"],
        # permissions
        ["filesystem_read", "filesystem_write"],
        # risk_level
        "low",
        # handoff_targets
        ["reviewer", "regression_tester"],
    ),
    _pack("frontend_engineer", "Frontend Engineer", "Code", "Builds components, state, forms, styling, accessibility hooks, and UI integration.", ["The work touches frontend UI, components, forms, layout, or client-side state."], ["frontend implementation plan", "component map", "UI acceptance checks"], ["read_file", "search_code"], ["filesystem_read"], "medium", ["builder", "ux_designer"]),
    _pack("backend_engineer", "Backend Engineer", "Code", "Designs and implements routes, services, persistence, queues, and backend workflows.", ["The work touches APIs, server routes, services, storage, auth, or backend jobs."], ["backend implementation plan", "service boundaries", "API behavior"], ["read_file", "search_code"], ["filesystem_read"], "medium", ["builder", "api_designer", "integration_tester"]),
    _pack("database_designer", "Database Designer", "Data", "Designs schemas, migrations, indexes, query paths, and persistence invariants.", ["The task changes storage, schemas, query performance, migrations, or data integrity."], ["schema proposal", "migration notes", "index/query review"], ["read_file", "search_code"], ["filesystem_read"], "high", ["backend_engineer", "migration_planner", "tester"]),
    _pack("api_designer", "API Designer", "Architecture", "Defines REST/RPC schemas, errors, versioning, payloads, and compatibility rules.", ["An endpoint, provider adapter, RPC surface, or external contract needs design/review."], ["API contract", "error model", "compatibility notes"], ["read_file", "search_code"], ["filesystem_read"], "medium", ["schema", "backend_engineer", "integration_engineer"]),
    _pack("test_planner", "Test Planner", "Testing", "Defines the right test strategy before implementation claims completion.", ["A change needs validation strategy or unclear test coverage."], ["test matrix", "acceptance checks", "risk-based test priorities"], ["mailbox"], ["analysis"], "low", ["unit_tester", "integration_tester", "e2e_tester"]),
    _pack("regression_tester", "Regression Tester", "Testing", "Prevents old bugs and existing workflows from breaking after changes.", ["A bug fix, refactor, or high-risk edit could re-break prior behavior."], ["regression cases", "pass/fail evidence", "coverage gaps"], ["read_file", "search_code"], ["filesystem_read"], "medium", ["verification_runner", "quality_gate", "reviewer"]),
    _pack("quality_gate", "Quality Gate", "Review", "Makes pass/fail completion decisions using evidence, acceptance criteria, and review scores.", ["Before marking any Work Order complete or shipping a result."], ["gate decision", "blockers", "required fixes"], ["mailbox"], ["review"], "high", ["reviewer", "tester"]),
    _pack("secrets_auditor", "Secrets Auditor", "Security", "Finds leaked keys, unsafe env handling, secrets in logs, and credential exposure risk.", ["The task touches keys, env files, logs, providers, auth, or deployment."], ["secret risk report", "redactions", "safe storage recommendations"], ["search_code", "read_file"], ["filesystem_read"], "high", ["security_reviewer", "policy_guard", "deployment"]),
    _pack("permission_auditor", "Permission Auditor", "Security", "Reviews tool access, file access, network permissions, and least-privilege boundaries.", ["Agents/tools gain capabilities or a workflow uses filesystem/network/shell/browser access."], ["permission matrix", "least-privilege fixes", "approval gates"], ["read_file", "mailbox"], ["policy_review"], "high", ["policy_guard", "sandbox_manager"]),
    _pack("prompt_injection_guard", "Prompt Injection Guard", "Security", "Detects hostile instructions in retrieved data, web pages, files, and tool outputs.", ["The task consumes external/untrusted content or browser/tool observations."], ["injection risk findings", "trusted/untrusted boundaries", "safe handling rules"], ["read_file", "mailbox"], ["network", "filesystem_read"], "high", ["security_reviewer", "tool_router", "reviewer"]),
    _pack("observability", "Observability", "Operations", "Adds or reviews logs, metrics, traces, dashboards, and runtime debug surfaces.", ["The system needs better visibility into state, errors, tasks, traces, or performance."], ["observability plan", "log/metric/trace map", "dashboard notes"], ["read_file", "search_code"], ["filesystem_read"], "medium", ["backend_engineer", "incident_responder"]),
    _pack("cost_controller", "Cost Controller", "Operations", "Controls token/call limits, provider routing, budgets, retries, and expensive workflows.", ["The system may overuse models/tools or needs provider/model budget routing."], ["cost policy", "routing recommendation", "limit settings"], ["mailbox"], ["analysis"], "medium", ["tool_router", "policy_guard"]),
    _pack("knowledge_curator", "Knowledge Curator", "Memory", "Keeps useful facts, removes stale junk, and promotes durable knowledge.", ["Memory needs cleanup, promotion, or stale fact review."], ["curated facts", "stale removals", "memory write decisions"], ["read_file", "mailbox"], ["memory_write"], "medium", ["memory_manager", "citation_memory"]),
    _pack("file_state", "File State", "Memory", "Tracks file purpose, ownership, status, invariants, known problems, and review history.", ["A project has many files or future runs need durable file ownership/invariant context."], ["file state map", "invariants", "known problems"], ["read_file", "search_code"], ["filesystem_read", "memory_write"], "low", ["codebase_mapper", "architect", "builder"]),
    _pack("automation_builder", "Automation Builder", "Automation", "Creates repeatable workflows, triggers, scheduled jobs, and human-approval pauses.", ["The user wants recurring actions, scripted processes, workflows, triggers, or automations."], ["automation design", "trigger plan", "approval checkpoints"], ["read_file", "write_file"], ["filesystem_write"], "high", ["policy_guard", "browser_operator", "tester"]),
    HOLMES_DORMANT_PACK,
    *POCOCK_DORMANT_PACKS,
]


def dormant_skill_catalog() -> Dict[str, Any]:
    by_category: Dict[str, List[Dict[str, Any]]] = {category: [] for category in TOP_LEVEL_CATEGORIES}
    for pack in DORMANT_SKILL_PACKS:
        by_category.setdefault(pack["category"], []).append(pack)
    return {
        "categories": TOP_LEVEL_CATEGORIES,
        "packs": DORMANT_SKILL_PACKS,
        "by_category": by_category,
    }
