"""Plan models — PlanStep + PlanGraph.

Ported from FAIL's ``server/planning/models.py`` unchanged in shape so future
LLM-generated plans from either system can be loaded interchangeably.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class PlanStep:
    id: str = field(default_factory=lambda: f"step_{uuid.uuid4().hex[:8]}")
    title: str = ""
    description: str = ""
    status: str = "pending"
    project_root: str = ""
    cwd: str = ""
    target_path: str = ""
    workspace_hint: str = ""
    concrete_scope: str = ""
    files: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    tool_hint: str = ""
    expected_output: str = ""
    fallback: str = ""
    requires_approval: bool = False
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    updated_at: float = field(default_factory=time.time)
    result: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanStep":
        if not isinstance(data, dict):
            data = {}
        values: Dict[str, Any] = {}
        for field_name in cls.__dataclass_fields__:
            if field_name in data:
                values[field_name] = data[field_name]
        values["files"] = list(data.get("files") or [])
        values["depends_on"] = list(data.get("depends_on") or [])
        values["result"] = dict(data.get("result") or {})
        return cls(**{key: value for key, value in values.items() if value is not None})


@dataclass
class PlanGraph:
    id: str = field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:10]}")
    session_id: str = ""
    goal_id: str = ""
    goal: str = ""
    status: str = "active"
    steps: List[PlanStep] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    stop_conditions: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "goal_id": self.goal_id,
            "goal": self.goal,
            "status": self.status,
            "steps": [step.to_dict() for step in self.steps],
            "success_criteria": list(self.success_criteria),
            "stop_conditions": list(self.stop_conditions),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanGraph":
        if not isinstance(data, dict):
            data = {}
        return cls(
            id=str(data.get("id") or f"plan_{uuid.uuid4().hex[:10]}"),
            session_id=str(data.get("session_id") or ""),
            goal_id=str(data.get("goal_id") or ""),
            goal=str(data.get("goal") or ""),
            status=str(data.get("status") or "active"),
            steps=[PlanStep.from_dict(item) for item in (data.get("steps") or []) if isinstance(item, dict)],
            success_criteria=list(data.get("success_criteria") or []),
            stop_conditions=list(data.get("stop_conditions") or []),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            metadata=dict(data.get("metadata") or {}),
        )

    def context_block(self, *, max_chars: int = 5000) -> str:
        if not self.goal and not self.steps:
            return ""
        lines = ["[ACTIVE PLAN GRAPH]", f"Plan: {self.id}", f"Status: {self.status}"]
        if self.goal:
            lines.append(f"Goal: {self.goal}")
        if self.success_criteria:
            lines.append("Success criteria:")
            lines.extend(f"- {item}" for item in self.success_criteria[:8])
        if self.stop_conditions:
            lines.append("Stop conditions:")
            lines.extend(f"- {item}" for item in self.stop_conditions[:8])
        if self.steps:
            lines.append("Steps:")
            for step in self.steps[:20]:
                hints = []
                if step.project_root:
                    hints.append(f"root={step.project_root}")
                if step.cwd:
                    hints.append(f"cwd={step.cwd}")
                if step.target_path:
                    hints.append(f"target={step.target_path}")
                if step.files:
                    hints.append(f"files={','.join(step.files[:5])}")
                if step.tool_hint:
                    hints.append(f"tool={step.tool_hint}")
                if step.requires_approval:
                    hints.append("requires_approval=true")
                suffix = f" ({'; '.join(hints)})" if hints else ""
                lines.append(f"- [{step.status}] {step.title or step.description}{suffix}")
                if step.expected_output:
                    lines.append(f"  expected: {step.expected_output[:220]}")
        value = "\n".join(lines)
        if len(value) <= max_chars:
            return value
        return value[: max(1, max_chars - 32)].rstrip() + "\n[...truncated active plan graph]"
