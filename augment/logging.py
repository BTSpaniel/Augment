from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any

_MAX_MEMORY_EVENTS = 500
_MEMORY_EVENTS: deque[dict[str, Any]] = deque(maxlen=_MAX_MEMORY_EVENTS)
_LOG_PATH: Path | None = None


class JsonlLogHandler(logging.Handler):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, record: logging.LogRecord) -> None:
        event = {
            "ts": time.time(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            event["exc_info"] = self.formatException(record.exc_info)
        write_log_event(event)


def configure_logging(data_dir: Path, *, level: int = logging.INFO) -> Path:
    global _LOG_PATH
    _LOG_PATH = Path(data_dir) / "logs" / "augment.jsonl"
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("augment")
    root.setLevel(level)
    root.propagate = False
    if not any(isinstance(handler, JsonlLogHandler) and handler.path == _LOG_PATH for handler in root.handlers):
        handler = JsonlLogHandler(_LOG_PATH)
        handler.setLevel(level)
        root.addHandler(handler)
    write_log_event({"level": "info", "logger": "augment", "message": "logging configured", "source": "backend"})
    return _LOG_PATH


def get_logger(name: str) -> logging.Logger:
    clean = str(name or "app").strip(".") or "app"
    return logging.getLogger(clean if clean.startswith("augment") else f"augment.{clean}")


def write_log_event(event: dict[str, Any]) -> dict[str, Any]:
    row = dict(event or {})
    row.setdefault("ts", time.time())
    row.setdefault("level", "info")
    row.setdefault("logger", "augment")
    row.setdefault("message", "")
    _MEMORY_EVENTS.append(row)
    if _LOG_PATH is not None:
        try:
            with _LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass
    return row


def read_log_events(*, limit: int = 200, level: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if _LOG_PATH is not None and _LOG_PATH.exists():
        try:
            for line in _LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
        except Exception:
            rows = list(_MEMORY_EVENTS)
    else:
        rows = list(_MEMORY_EVENTS)
    if level:
        needle = level.lower().strip()
        rows = [row for row in rows if str(row.get("level") or "").lower() == needle]
    return rows[-max(1, min(int(limit or 200), 1000)):]


def log_path() -> str:
    return str(_LOG_PATH or "")
