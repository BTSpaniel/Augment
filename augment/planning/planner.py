"""Structured planner — heuristic plan + LLM JSON ingestion.

Distilled from FAIL's ``server/planning/planner.py``. The heuristic plan is
deterministic and tool-agnostic; if the LLM returns JSON we ingest it directly.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from augment.planning.models import PlanGraph, PlanStep


_PATH_RE = re.compile(r"(?P<path>(?:[A-Za-z]:)?[./\\]?[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)+)")
_APPROVAL_RE = re.compile(
    r"\b(delete|remove|deploy|publish|install|run command|execute|shell|write|modify|edit)\b",
    re.IGNORECASE,
)


def path_hints(text: str) -> List[str]:
    """Extract candidate file paths from free-form goal text."""
    found: List[str] = []
    for match in _PATH_RE.finditer(str(text or "")):
        value = match.group("path").strip("`'\".,;:)")
        if value and value not in found:
            found.append(value)
    return found[:12]


def _resolve_root(cwd: Optional[str | Path]) -> Path:
    if cwd:
        return Path(cwd).resolve()
    return Path.cwd().resolve()


class StructuredPlanner:
    """Build a :class:`PlanGraph` from a free-form goal or LLM JSON payload."""

    def build_plan(
        self,
        goal: str,
        *,
        session_id: str = "",
        goal_id: str = "",
        cwd: str | Path | None = None,
        llm_json: str | Dict[str, Any] | None = None,
    ) -> PlanGraph:
        if llm_json:
            parsed = self.from_llm_json(
                llm_json,
                goal=goal,
                session_id=session_id,
                goal_id=goal_id,
                cwd=cwd,
            )
            if parsed.steps:
                return parsed
        return self.heuristic_plan(goal, session_id=session_id, goal_id=goal_id, cwd=cwd)

    def from_llm_json(
        self,
        payload: str | Dict[str, Any],
        *,
        goal: str = "",
        session_id: str = "",
        goal_id: str = "",
        cwd: str | Path | None = None,
    ) -> PlanGraph:
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except Exception:
                data = {}
        else:
            data = dict(payload or {})
        root = _resolve_root(cwd)
        graph = PlanGraph(
            session_id=session_id,
            goal_id=goal_id,
            goal=str(data.get("goal") or goal),
            success_criteria=list(data.get("success_criteria") or []),
            stop_conditions=list(data.get("stop_conditions") or []),
            metadata=dict(data.get("metadata") or {}),
        )
        for raw in data.get("steps") or []:
            if not isinstance(raw, dict):
                continue
            step = PlanStep.from_dict(raw)
            if not step.project_root:
                step.project_root = str(root)
            if not step.cwd:
                step.cwd = str(cwd or root)
            graph.steps.append(step)
        return graph

    def heuristic_plan(
        self,
        goal: str,
        *,
        session_id: str = "",
        goal_id: str = "",
        cwd: str | Path | None = None,
    ) -> PlanGraph:
        root = _resolve_root(cwd)
        files = path_hints(goal)
        requires_approval = bool(_APPROVAL_RE.search(goal or ""))
        steps: List[PlanStep] = [
            PlanStep(
                title="Clarify objective and scope",
                description="Identify target files, project root, and success criteria before acting.",
                project_root=str(root),
                cwd=str(cwd or root),
                workspace_hint=str(root),
                concrete_scope=goal[:300],
                files=files,
                tool_hint="read_file/search_code",
                expected_output="A precise understanding of affected files and constraints.",
                fallback="Ask for clarification if target scope remains ambiguous.",
            ),
            PlanStep(
                title="Inspect relevant implementation paths",
                description="Read existing code and tests related to the goal.",
                project_root=str(root),
                cwd=str(cwd or root),
                target_path=files[0] if files else "",
                workspace_hint=str(root),
                concrete_scope=goal[:300],
                files=files,
                tool_hint="read_file/search_code",
                expected_output="Impact map and reusable existing code paths.",
            ),
            PlanStep(
                title="Implement minimal coherent changes",
                description="Apply changes while preserving existing behaviour and surrounding context.",
                project_root=str(root),
                cwd=str(cwd or root),
                target_path=files[0] if files else "",
                workspace_hint=str(root),
                concrete_scope=goal[:300],
                files=files,
                tool_hint="edit_file/write_file",
                expected_output="Working implementation matching the objective.",
                fallback="Narrow the change or replan if tests reveal drift.",
                requires_approval=requires_approval,
            ),
            PlanStep(
                title="Verify and record outcome",
                description="Run focused validation and persist results in plan state.",
                project_root=str(root),
                cwd=str(cwd or root),
                workspace_hint=str(root),
                concrete_scope=goal[:300],
                files=files,
                tool_hint="run_command/pytest",
                expected_output="Validation evidence and completion status.",
                requires_approval=True,
            ),
        ]
        return PlanGraph(
            session_id=session_id,
            goal_id=goal_id,
            goal=goal,
            steps=steps,
            success_criteria=[
                "Implementation matches requested behaviour",
                "Focused validation passes",
                "No unrelated behaviour is broken",
            ],
            stop_conditions=[
                "Requirements are ambiguous",
                "Safety policy blocks required action",
                "Repeated verification failures require replanning",
            ],
            metadata={"planner": "heuristic", "path_hints": files},
        )
