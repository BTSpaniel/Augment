"""Per-session coding contract.

Mirrors FAIL's ``ContextPacket.rules`` slot: a tiny per-session list of
free-form rules that the user (or the UI) pins for the duration of a
chat session. Examples::

    "All new code in TypeScript, never JavaScript."
    "Do not touch /api/legacy/**."
    "Tests required for every public function."
    "Match the project's existing tab indentation (no spaces)."

The contract is injected into every prompt as a high-priority
``[CODING CONTRACT]`` section sitting in the ``smart_top`` zone, right
under the agent identity. The model SEES the rules every turn; the
hard-gate edit-receipt machinery still enforces structural invariants
(workspace root, full-rewrite guard, pattern preservation).

Persistence: one JSON file per session at
``<data_dir>/sessions_depth/coding_contracts/<session_id>.json``.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass
class CodingContract:
    session_id: str
    rules: list[str] = field(default_factory=list)
    notes: str = ""
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class CodingContractStore:
    """Per-session JSON coding-contract store."""

    # Bound: drop any rule longer than this so a runaway paste can't blow
    # out the prompt budget.
    _MAX_RULE_CHARS = 600
    # Bound: keep the most recent N rules.
    _MAX_RULES = 30
    # Bound: notes free-form text cap.
    _MAX_NOTES_CHARS = 2_000

    def __init__(self, data_dir: Path) -> None:
        self._root = Path(data_dir) / "sessions_depth" / "coding_contracts"
        self._root.mkdir(parents=True, exist_ok=True)

    # ── Persistence ────────────────────────────────────────────────

    def _path(self, session_id: str) -> Path:
        safe = "".join(c for c in str(session_id or "") if c.isalnum() or c in "-_") or "default"
        return self._root / f"{safe}.json"

    def load(self, session_id: str) -> CodingContract:
        path = self._path(session_id)
        if not path.exists():
            return CodingContract(session_id=session_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return CodingContract(session_id=session_id)
        if not isinstance(data, dict):
            return CodingContract(session_id=session_id)
        raw_rules = data.get("rules") or []
        rules = [str(r).strip()[: self._MAX_RULE_CHARS] for r in raw_rules if str(r).strip()]
        return CodingContract(
            session_id=session_id,
            rules=rules[-self._MAX_RULES :],
            notes=str(data.get("notes") or "")[: self._MAX_NOTES_CHARS],
            updated_at=float(data.get("updated_at") or 0.0),
        )

    def _save(self, contract: CodingContract) -> None:
        contract.updated_at = time.time()
        self._path(contract.session_id).write_text(
            json.dumps(contract.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    # ── CRUD ───────────────────────────────────────────────────────

    def set_rules(self, session_id: str, rules: Iterable[str]) -> CodingContract:
        """Replace the rule list with ``rules`` (deduplicated, ordered)."""
        contract = self.load(session_id)
        cleaned: list[str] = []
        seen: set[str] = set()
        for r in rules:
            text = str(r).strip()
            if not text:
                continue
            text = text[: self._MAX_RULE_CHARS]
            if text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        contract.rules = cleaned[-self._MAX_RULES :]
        self._save(contract)
        return contract

    def append_rule(self, session_id: str, rule: str) -> CodingContract:
        """Add a single rule. No-op if blank or already present."""
        text = str(rule or "").strip()
        if not text:
            return self.load(session_id)
        return self.set_rules(session_id, [*self.load(session_id).rules, text])

    def remove_rule(self, session_id: str, rule: str) -> CodingContract:
        """Drop the matching rule (exact match, trimmed)."""
        target = str(rule or "").strip()
        if not target:
            return self.load(session_id)
        contract = self.load(session_id)
        contract.rules = [r for r in contract.rules if r != target]
        self._save(contract)
        return contract

    def set_notes(self, session_id: str, notes: str) -> CodingContract:
        contract = self.load(session_id)
        contract.notes = str(notes or "")[: self._MAX_NOTES_CHARS]
        self._save(contract)
        return contract

    def clear(self, session_id: str) -> None:
        path = self._path(session_id)
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    # ── Context block ──────────────────────────────────────────────

    def context_block(self, session_id: str) -> str:
        """Render the section that goes into the assembled prompt.

        Returns an empty string when no contract exists, so the builder
        can append it unconditionally without inflating an empty section.
        """
        contract = self.load(session_id)
        if not contract.rules and not contract.notes:
            return ""
        lines = ["[CODING CONTRACT]"]
        lines.append("These rules were pinned by the user for this session.")
        lines.append("Treat them as hard requirements; if they conflict, ask.")
        for idx, rule in enumerate(contract.rules, 1):
            lines.append(f"{idx}. {rule}")
        if contract.notes:
            lines.append("")
            lines.append("Notes:")
            lines.append(contract.notes)
        return "\n".join(lines)
