"""Project-conventions auto-loader.

Mirrors FAIL's `AGENTS.md` pattern: any of a handful of well-known
manifesto files at the workspace root get auto-discovered and injected
into every prompt as a high-priority context section.

Discovered filenames, in priority order (first hit wins per directory):

* `AGENTS.md`               -- FAIL convention; OpenAI's agentic guideline format.
* `CONVENTIONS.md`
* `STYLE.md`
* `RULES.md`
* `CONTRIBUTING.md`
* `.augment/RULES.md`       -- Augment-specific override location.
* `.cursorrules`            -- Cursor IDE format; widely adopted.
* `.windsurfrules`          -- Windsurf format.
* `CLAUDE.md`               -- Claude Code format.

All matches are concatenated (each with a small header) and capped at
``max_chars`` total so a pathological 200-page contributing guide can't
blow out the context budget on its own. Reads are cached by mtime so
repeated builds in the same session are free.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("augment.context.conventions")


# Order matters: when multiple files exist we list them all, but in this
# stable order so the most-canonical name appears first.
DEFAULT_CONVENTION_FILES: tuple[str, ...] = (
    "AGENTS.md",
    "CONVENTIONS.md",
    "STYLE.md",
    "RULES.md",
    "CONTRIBUTING.md",
    ".augment/RULES.md",
    ".cursorrules",
    ".windsurfrules",
    "CLAUDE.md",
)


@dataclass
class _CacheEntry:
    mtime: float
    size: int
    text: str


class ConventionsLoader:
    """Discover + read project convention files from the workspace root.

    Usage::

        loader = ConventionsLoader(workspace_root=Path("/my/project"))
        block = loader.context_block()  # "" if nothing found
    """

    # Max chars per individual file before we truncate with a marker.
    _PER_FILE_CAP = 4_000
    # Overall cap on the combined block.
    _TOTAL_CAP = 8_000

    def __init__(
        self,
        workspace_root: Path | str,
        *,
        filenames: Iterable[str] | None = None,
        per_file_cap: int = 0,
        total_cap: int = 0,
    ) -> None:
        self._root = Path(workspace_root)
        self._filenames: tuple[str, ...] = (
            tuple(filenames) if filenames is not None else DEFAULT_CONVENTION_FILES
        )
        if per_file_cap > 0:
            self._PER_FILE_CAP = int(per_file_cap)
        if total_cap > 0:
            self._TOTAL_CAP = int(total_cap)
        # Cache: relative-filename -> (mtime, size, text)
        self._cache: dict[str, _CacheEntry] = {}

    # ── Public API ─────────────────────────────────────────────────

    def discover(self) -> list[tuple[str, Path]]:
        """Return ``[(label, absolute_path), ...]`` for every present file."""
        out: list[tuple[str, Path]] = []
        for name in self._filenames:
            path = (self._root / name).resolve()
            try:
                if path.exists() and path.is_file():
                    out.append((name, path))
            except OSError:
                continue
        return out

    def context_block(self) -> str:
        """Render the combined ``[PROJECT CONVENTIONS]`` block.

        Returns an empty string when no convention files are present, so
        callers can blindly append it without inflating an empty section.
        """
        parts: list[str] = []
        total = 0
        for label, path in self.discover():
            text = self._read_cached(label, path)
            if not text:
                continue
            if len(text) > self._PER_FILE_CAP:
                text = text[: self._PER_FILE_CAP].rstrip() + "\n[...truncated]"
            header = f"--- {label} ---"
            chunk = f"{header}\n{text}"
            if total + len(chunk) > self._TOTAL_CAP:
                # Stop before we blow the cap; the next file goes
                # unread (consistent ordering by DEFAULT_CONVENTION_FILES).
                parts.append(f"[...{label} and later files omitted: cap reached]")
                break
            parts.append(chunk)
            total += len(chunk)
        if not parts:
            return ""
        return "[PROJECT CONVENTIONS]\n" + "\n\n".join(parts)

    def clear_cache(self) -> None:
        self._cache.clear()

    # ── Internals ──────────────────────────────────────────────────

    def _read_cached(self, label: str, path: Path) -> str:
        try:
            stat = path.stat()
        except OSError:
            return ""
        cached = self._cache.get(label)
        if cached and cached.mtime == stat.st_mtime and cached.size == stat.st_size:
            return cached.text
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            logger.debug("ConventionsLoader read failed for %s: %s", path, exc)
            return ""
        self._cache[label] = _CacheEntry(mtime=stat.st_mtime, size=stat.st_size, text=text)
        return text
