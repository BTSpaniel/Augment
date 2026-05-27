"""Inner monologue — background self-reflection persisted as JSONL.

Ported from FAIL's ``server/mind/monologue.py`` with the kernel-logger swap.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


logger = logging.getLogger("augment.mind.monologue")

_MAX_ENTRIES = 200
_MAX_CONTEXT_ENTRIES = 5


class InnerMonologue:
    """Background self-reflection that records private thoughts.

    Thoughts are persisted in JSONL format and injected into context so the
    agent has continuity between turns / sessions.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._data_dir / "monologue.jsonl"

    def think(
        self,
        thought: str,
        *,
        category: str = "reflection",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        text = str(thought or "").strip()[:1000]
        if not text:
            return
        entry: Dict[str, Any] = {
            "ts": time.time(),
            "thought": text,
            "category": category,
        }
        if metadata:
            entry["metadata"] = metadata
        try:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("monologue write failed: %s", exc)
        self._compact_if_needed()

    def recent(self, limit: int = _MAX_CONTEXT_ENTRIES) -> List[Dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            lines = self._path.read_text(encoding="utf-8").strip().splitlines()
        except Exception:
            return []
        entries: List[Dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
        return entries

    def _compact_if_needed(self) -> None:
        if not self._path.exists():
            return
        try:
            lines = self._path.read_text(encoding="utf-8").strip().splitlines()
            if len(lines) > _MAX_ENTRIES:
                self._path.write_text("\n".join(lines[-_MAX_ENTRIES:]) + "\n", encoding="utf-8")
        except Exception:
            pass

    def as_context_block(self) -> str:
        entries = self.recent()
        if not entries:
            return ""
        lines = ["[INNER MONOLOGUE - Recent Thoughts]"]
        for entry in entries:
            ts = time.strftime("%H:%M", time.localtime(entry.get("ts", 0)))
            thought = str(entry.get("thought") or "")[:200]
            lines.append(f"- [{ts}] {thought}")
        return "\n".join(lines)

    def clear(self) -> None:
        if self._path.exists():
            try:
                self._path.unlink()
            except OSError:
                pass
