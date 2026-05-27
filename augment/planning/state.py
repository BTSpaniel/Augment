"""Plan state persistence — file-backed PlanGraph store.

Distilled from FAIL's ``server/planning/state.py`` minus the kernel
atomic-file helper (uses a simple write_text fallback that still avoids
mid-write corruption via tmp+replace).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import List

from augment.planning.models import PlanGraph


def _atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


class PlanStateStore:
    """Persist :class:`PlanGraph` objects under ``<data_dir>/plans``."""

    def __init__(self, data_root: str | Path) -> None:
        self._root = Path(data_root) / "plans"
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, graph: PlanGraph) -> PlanGraph:
        graph.updated_at = time.time()
        key = graph.session_id or graph.goal_id or graph.id
        _atomic_write_text(
            self._path(key),
            json.dumps(graph.to_dict(), indent=2, default=str),
        )
        return graph

    def load(self, session_id: str) -> PlanGraph | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            return PlanGraph.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return None

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        if not path.exists():
            return False
        try:
            path.unlink()
            return True
        except Exception:
            return False

    def list(self, *, limit: int = 50) -> List[PlanGraph]:
        graphs: List[PlanGraph] = []
        files = sorted(self._root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files[: max(1, limit)]:
            try:
                graphs.append(PlanGraph.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except Exception:
                continue
        return graphs

    def context_block(self, session_id: str, *, max_chars: int = 5000) -> str:
        graph = self.load(session_id)
        return graph.context_block(max_chars=max_chars) if graph else ""

    def _path(self, key: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(key or "default")) or "default"
        return self._root / f"{safe}.json"
