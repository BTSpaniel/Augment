from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ChatMessage:
    role: str
    content: str
    ts: float


class SessionStore:
    def __init__(self, data_dir: Path) -> None:
        self._root = data_dir / "sessions"
        self._root.mkdir(parents=True, exist_ok=True)

    def new_session_id(self) -> str:
        return f"sess_{uuid.uuid4().hex[:12]}"

    def append(self, session_id: str, role: str, content: str) -> None:
        path = self._path(session_id)
        record = {"role": role, "content": content, "ts": time.time()}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def history(self, session_id: str, limit: int = 40) -> list[ChatMessage]:
        path = self._path(session_id)
        if not path.exists():
            return []
        rows: list[ChatMessage] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except Exception:
                continue
            rows.append(ChatMessage(str(item.get("role") or "user"), str(item.get("content") or ""), float(item.get("ts") or 0)))
        return rows[-limit:]

    # ── Project metadata (sidecar) ─────────────────────────────────
    def meta(self, session_id: str) -> dict[str, Any]:
        path = self._meta_path(session_id)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def set_meta(self, session_id: str, **fields: Any) -> dict[str, Any]:
        meta = self.meta(session_id)
        meta.update({k: v for k, v in fields.items() if v is not None})
        meta["updated_at"] = time.time()
        meta.setdefault("created_at", meta["updated_at"])
        self._meta_path(session_id).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return meta

    def set_project(self, session_id: str, project: str) -> dict[str, Any]:
        return self.set_meta(session_id, project=(project or "").strip()[:80])

    def project_for(self, session_id: str, *, default: str = "") -> str:
        return str(self.meta(session_id).get("project") or default)

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for path in sorted(self._root.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True):
            messages = self.history(path.stem, limit=200)
            first_user = next((item.content for item in messages if item.role == "user"), "")
            last = messages[-1] if messages else None
            meta = self.meta(path.stem)
            sessions.append({
                "session_id": path.stem,
                "title": _title_from_text(first_user or (last.content if last else path.stem)),
                "message_count": len(messages),
                "updated_at": path.stat().st_mtime,
                "last_role": last.role if last else "",
                "last_preview": (last.content[:160] if last else ""),
                "project": str(meta.get("project") or ""),
            })
            if len(sessions) >= limit:
                break
        return sessions

    def list_by_project(self, limit: int = 200) -> dict[str, list[dict[str, Any]]]:
        """Group session summaries by project (empty string for unassigned)."""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for session in self.list(limit=limit):
            grouped.setdefault(session.get("project") or "", []).append(session)
        return grouped

    def clear(self, session_id: str) -> None:
        self._path(session_id).write_text("", encoding="utf-8")

    def delete(self, session_id: str) -> None:
        path = self._path(session_id)
        if path.exists():
            path.unlink()
        meta_path = self._meta_path(session_id)
        if meta_path.exists():
            meta_path.unlink()

    def _path(self, session_id: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", session_id or "default")
        return self._root / f"{safe}.jsonl"

    def _meta_path(self, session_id: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", session_id or "default")
        return self._root / f"{safe}.meta.json"


class MailboxStore:
    def __init__(self, data_dir: Path) -> None:
        self._root = data_dir / "mailboxes"
        self._root.mkdir(parents=True, exist_ok=True)

    def add(self, session_id: str, content: str, *, kind: str = "note", actor: str = "user") -> dict[str, Any]:
        item = {"id": f"mail_{uuid.uuid4().hex[:10]}", "session_id": _safe_id(session_id), "kind": kind, "actor": actor, "content": str(content or "").strip(), "ts": time.time()}
        if not item["content"]:
            raise ValueError("Mailbox content is required")
        with self._path(session_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item

    def list(self, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        path = self._path(session_id)
        if not path.exists():
            return []
        items: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                items.append(item)
        return items[-limit:]

    def clear(self, session_id: str) -> None:
        self._path(session_id).write_text("", encoding="utf-8")

    def context_block(self, session_id: str, limit: int = 20) -> str:
        items = self.list(session_id, limit)
        if not items:
            return ""
        lines = ["[SESSION MAILBOX]"]
        for item in items:
            lines.append(f"- {item.get('kind', 'note')} from {item.get('actor', 'user')}: {item.get('content', '')}")
        return "\n".join(lines)

    def _path(self, session_id: str) -> Path:
        return self._root / f"{_safe_id(session_id)}.jsonl"


class MemoryStore:
    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self._path = data_dir / "memory.jsonl"

    def remember_from_user(self, text: str, *, session_id: str = "") -> None:
        content = str(text or "").strip()
        lowered = content.lower()
        explicit = any(marker in lowered for marker in ["remember that", "remember:", "my preference", "i prefer", "call me"])
        if not explicit:
            return
        self.add(content, source="user", session_id=session_id)

    def add(self, fact: str, *, source: str = "user", session_id: str = "") -> None:
        clean = " ".join(str(fact or "").split())[:1000]
        if not clean:
            return
        records = self.all()
        now = time.time()
        for item in records:
            if str(item.get("fact") or "").lower() == clean.lower():
                item["last_seen"] = now
                item["count"] = int(item.get("count") or 1) + 1
                self._write_all(records)
                return
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"fact": clean, "source": source, "session_id": session_id, "created_at": now, "last_seen": now, "count": 1}, ensure_ascii=False) + "\n")

    def all(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                records.append(item)
        return records[-limit:]

    def context_block(self, limit: int = 20) -> str:
        records = self.all(limit)
        if not records:
            return ""
        lines = ["[MEMORY]"]
        for item in records:
            lines.append(f"- {item.get('fact')} (source={item.get('source')}, count={item.get('count', 1)})")
        return "\n".join(lines)

    # ── Keyed fact storage (FAIL-style) ────────────────────────────
    def set_fact(self, key: str, value: str, *, category: str = "general", session_id: str = "") -> dict[str, Any]:
        """Store or update a fact under an explicit key. Returns the saved record."""
        clean_key = str(key or "").strip()[:120]
        clean_value = " ".join(str(value or "").split())[:4000]
        if not clean_key or not clean_value:
            return {}
        records = self.all(limit=10_000)
        now = time.time()
        existing = next((item for item in records if str(item.get("key") or "").lower() == clean_key.lower()), None)
        if existing:
            existing["fact"] = clean_value
            existing["category"] = category or "general"
            existing["last_seen"] = now
            existing["count"] = int(existing.get("count") or 1) + 1
            self._write_all(records)
            return existing
        record = {
            "key": clean_key,
            "fact": clean_value,
            "category": category or "general",
            "source": "tool",
            "session_id": session_id,
            "created_at": now,
            "last_seen": now,
            "count": 1,
        }
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def get_fact(self, key: str) -> dict[str, Any]:
        clean_key = str(key or "").strip().lower()
        if not clean_key:
            return {}
        for item in reversed(self.all(limit=10_000)):
            if str(item.get("key") or "").lower() == clean_key:
                return item
        return {}

    def add_note(self, content: str, *, category: str = "note", session_id: str = "") -> dict[str, Any]:
        clean = " ".join(str(content or "").split())[:1500]
        if not clean:
            return {}
        now = time.time()
        record = {
            "fact": clean,
            "category": category or "note",
            "source": "note",
            "session_id": session_id,
            "created_at": now,
            "last_seen": now,
            "count": 1,
        }
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def search(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        needle = str(query or "").strip().lower()
        if not needle:
            return []
        records = self.all(limit=10_000)

        def score(item: dict[str, Any]) -> float:
            text = " ".join([
                str(item.get("fact") or ""),
                str(item.get("key") or ""),
                str(item.get("category") or ""),
            ]).lower()
            if needle not in text:
                return 0.0
            base = 1.0
            if str(item.get("key") or "").lower() == needle:
                base += 5.0
            if needle in str(item.get("key") or "").lower():
                base += 2.0
            return base + min(1.0, int(item.get("count") or 1) * 0.1)

        scored = [(score(item), item) for item in records]
        scored = [pair for pair in scored if pair[0] > 0]
        scored.sort(key=lambda pair: -pair[0])
        return [item for _, item in scored[:limit]]

    def stats(self) -> dict[str, int]:
        records = self.all(limit=10_000)
        by_category: dict[str, int] = {}
        keyed = 0
        for item in records:
            category = str(item.get("category") or item.get("source") or "general")
            by_category[category] = by_category.get(category, 0) + 1
            if item.get("key"):
                keyed += 1
        return {"total": len(records), "keyed": keyed, "by_category": by_category}

    def _write_all(self, records: list[dict[str, Any]]) -> None:
        with self._path.open("w", encoding="utf-8") as handle:
            for item in records:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def _safe_id(session_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", session_id or "default")


def _title_from_text(text: str) -> str:
    clean = " ".join(str(text or "").split())
    return clean[:48] if clean else "New chat"
