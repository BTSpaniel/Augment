"""Safe atomic file writes — write to a temp file then rename."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_text_atomically(path: Path | str, content: str, *, encoding: str = "utf-8") -> None:
    """Write ``content`` to ``path`` via a temp file + os.replace to avoid mid-write corruption."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(content)
        os.replace(tmp, str(target))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
