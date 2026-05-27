"""Per-session message receipts — causal trail of inbound + outbound messages."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class MessageReceipt:
    message_id: str
    session_id: str
    role: str
    direction: str
    status: str = "recorded"
    source: str = "chat"
    correlation_id: str = ""
    reply_to: str = ""
    run_id: str = ""
    payload_size: int = 0
    content_preview: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent_correlation_id: str = ""
    causal_role: str = ""
    sequence: int = 0
    ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MessageLedger:
    """Append-only JSONL of message receipts, one file per session."""

    def __init__(self, data_dir: Path) -> None:
        self._root = Path(data_dir) / "sessions_depth" / "message_ledgers"
        self._root.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        direction: str,
        source: str = "chat",
        correlation_id: str = "",
        reply_to: str = "",
        run_id: str = "",
        parent_correlation_id: str = "",
        causal_role: str = "",
        status: str = "recorded",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MessageReceipt:
        existing = self.list(session_id, limit=1)
        receipt = MessageReceipt(
            message_id=f"msg_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            role=(role or "").strip().lower(),
            direction=(direction or "").strip().lower(),
            status=str(status or "recorded"),
            source=str(source or "chat"),
            correlation_id=str(correlation_id or ""),
            reply_to=str(reply_to or ""),
            run_id=str(run_id or ""),
            payload_size=len(str(content or "")),
            content_preview=_preview(content),
            metadata=_sanitize(metadata or {}),
            parent_correlation_id=str(parent_correlation_id or ""),
            causal_role=str(causal_role or direction or ""),
            sequence=(existing[-1].sequence + 1) if existing else 1,
            ts=time.time(),
        )
        path = self._path(session_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt.to_dict(), ensure_ascii=False) + "\n")
        return receipt

    def list(self, session_id: str, *, limit: int = 40) -> List[MessageReceipt]:
        path = self._path(session_id)
        if not path.exists():
            return []
        receipts: List[MessageReceipt] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                data = json.loads(line)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            receipts.append(
                MessageReceipt(
                    message_id=str(data.get("message_id") or ""),
                    session_id=str(data.get("session_id") or session_id),
                    role=str(data.get("role") or ""),
                    direction=str(data.get("direction") or ""),
                    status=str(data.get("status") or "recorded"),
                    source=str(data.get("source") or "chat"),
                    correlation_id=str(data.get("correlation_id") or ""),
                    reply_to=str(data.get("reply_to") or ""),
                    run_id=str(data.get("run_id") or ""),
                    payload_size=int(data.get("payload_size") or 0),
                    content_preview=str(data.get("content_preview") or ""),
                    metadata=dict(data.get("metadata") or {}),
                    parent_correlation_id=str(data.get("parent_correlation_id") or ""),
                    causal_role=str(data.get("causal_role") or ""),
                    sequence=int(data.get("sequence") or 0),
                    ts=float(data.get("ts") or 0.0),
                )
            )
        return receipts[-max(1, limit):]

    def context_block(self, session_id: str, *, max_chars: int = 2500) -> str:
        receipts = self.list(session_id, limit=24)
        if not receipts:
            return ""
        lines = ["[MESSAGE LEDGER]"]
        total = len(lines[0])
        for receipt in receipts[-12:]:
            parent = f" parent={receipt.parent_correlation_id}" if receipt.parent_correlation_id else ""
            entry = (
                f"- #{receipt.sequence} {receipt.direction} {receipt.role} "
                f"{receipt.status} cid={receipt.correlation_id or '-'}{parent} "
                f"role={receipt.causal_role or '-'} size={receipt.payload_size}: "
                f"{receipt.content_preview}"
            )
            if total + len(entry) > max_chars:
                lines.append("[...truncated message ledger]")
                break
            lines.append(entry)
            total += len(entry)
        return "\n".join(lines)

    def clear(self, session_id: str) -> None:
        path = self._path(session_id)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass

    def _path(self, session_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id or "default") or "default"
        return self._root / f"{safe}.jsonl"


def _preview(value: str) -> str:
    return " ".join(str(value or "").split())[:360]


def _sanitize(value: Dict[str, Any]) -> Dict[str, Any]:
    safe: Dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key)
        lowered = key_text.lower()
        if any(term in lowered for term in ("key", "secret", "token", "password", "authorization")):
            safe[key_text] = "[redacted]"
        elif isinstance(item, (str, int, float, bool)) or item is None:
            safe[key_text] = item
        else:
            safe[key_text] = str(item)[:300]
    return safe
