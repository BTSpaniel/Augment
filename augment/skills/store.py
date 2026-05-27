"""Persistent store for adaptive skills — distilled from FAIL."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class AdaptiveSkill:
    id: str = field(default_factory=lambda: f"skill_{uuid.uuid4().hex[:10]}")
    kind: str = "general"
    title: str = ""
    priority: float = 0.5
    instructions: str = ""
    signals: List[str] = field(default_factory=list)
    source: str = "adaptive_generator"
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AdaptiveSkill":
        return cls(
            id=str(data.get("id") or f"skill_{uuid.uuid4().hex[:10]}"),
            kind=str(data.get("kind") or "general"),
            title=str(data.get("title") or ""),
            priority=float(data.get("priority") or 0.5),
            instructions=str(data.get("instructions") or ""),
            signals=list(data.get("signals") or []),
            source=str(data.get("source") or "adaptive_generator"),
            metadata=dict(data.get("metadata") or {}),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
        )


class SkillStore:
    def __init__(self, data_root: str | Path) -> None:
        self._root = Path(data_root) / "adaptive-skills"
        self._root.mkdir(parents=True, exist_ok=True)

    def save_many(self, skills: List[AdaptiveSkill]) -> List[AdaptiveSkill]:
        return [self.save(skill) for skill in skills]

    def save(self, skill: AdaptiveSkill) -> AdaptiveSkill:
        skill.updated_at = time.time()
        path = self._path(skill.id)
        path.write_text(json.dumps(skill.to_dict(), indent=2, default=str), encoding="utf-8")
        return skill

    def list(self, *, limit: int = 50) -> List[AdaptiveSkill]:
        skills: List[AdaptiveSkill] = []
        for path in sorted(self._root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            try:
                skills.append(AdaptiveSkill.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except Exception:
                continue
        skills.sort(key=lambda skill: (-skill.priority, skill.updated_at))
        return skills

    def clear(self) -> int:
        count = 0
        for path in self._root.glob("*.json"):
            try:
                path.unlink()
                count += 1
            except Exception:
                continue
        return count

    def context_block(self, *, max_chars: int = 5000) -> str:
        skills = self.list(limit=20)
        if not skills:
            return ""
        lines = ["[ADAPTIVE SKILLS]"]
        for skill in skills[:12]:
            lines.append(f"- {skill.title} kind={skill.kind} priority={skill.priority:.2f}")
            if skill.signals:
                lines.append(f"  signals: {'; '.join(skill.signals[:5])}")
            if skill.instructions:
                lines.append(f"  instructions: {skill.instructions[:420]}")
        value = "\n".join(lines)
        if len(value) <= max_chars:
            return value
        return value[: max(1, max_chars - 36)].rstrip() + "\n[...truncated adaptive skills]"

    def _path(self, skill_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(skill_id or "skill")) or "skill"
        return self._root / f"{safe}.json"
