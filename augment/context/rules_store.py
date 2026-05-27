"""Free-form rule-sheet loader.

Mirrors FAIL's ``data/rules/*.md`` + ``skills/_*-rules.md`` pattern: drop
markdown rule sheets into either ``data/rules/`` (runtime, user-managed)
or ``.augment/rules/`` (workspace-checked-in) and they get auto-loaded
into every prompt as a ``[USER RULES]`` section.

Why two directories:

* ``data/rules/`` lives next to other runtime stores like ``memory.jsonl``
  and ``settings.json`` — easy place for the user to drop ad-hoc policy
  notes that survive across sessions but stay local to the install.
* ``.augment/rules/`` lives inside the workspace itself — so team rules
  travel with the repo and apply to anyone who runs Augment against it.

Files are sorted alphabetically by relative path for stable ordering.
Each file is capped at ``PER_FILE_CAP`` chars; the combined block at
``TOTAL_CAP``. Reads are mtime-cached.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("augment.context.rules_store")


@dataclass
class _CacheEntry:
    mtime: float
    size: int
    text: str


class RulesStore:
    """Discover + read rule sheets from a fixed set of directories.

    Usage::

        rules = RulesStore(
            data_dir=Path("data"),
            workspace_root=Path("/my/project"),
        )
        block = rules.context_block()
    """

    _PER_FILE_CAP = 4_000
    _TOTAL_CAP = 8_000

    def __init__(
        self,
        *,
        data_dir: Path | str | None = None,
        workspace_root: Path | str | None = None,
        extra_dirs: Iterable[Path | str] | None = None,
        per_file_cap: int = 0,
        total_cap: int = 0,
    ) -> None:
        roots: list[Path] = []
        if data_dir is not None:
            roots.append(Path(data_dir) / "rules")
        if workspace_root is not None:
            roots.append(Path(workspace_root) / ".augment" / "rules")
        for extra in extra_dirs or ():
            roots.append(Path(extra))
        # De-dupe while preserving order.
        seen: set[str] = set()
        self._roots: list[Path] = []
        for root in roots:
            key = str(root.resolve()) if root.exists() else str(root)
            if key in seen:
                continue
            seen.add(key)
            self._roots.append(root)
        if per_file_cap > 0:
            self._PER_FILE_CAP = int(per_file_cap)
        if total_cap > 0:
            self._TOTAL_CAP = int(total_cap)
        self._cache: dict[str, _CacheEntry] = {}

    # ── Public API ─────────────────────────────────────────────────

    def discover(self) -> list[tuple[str, Path]]:
        """Return ``[(relative_label, absolute_path), ...]`` sorted by label."""
        items: list[tuple[str, Path]] = []
        for root in self._roots:
            try:
                if not root.exists() or not root.is_dir():
                    continue
                for path in sorted(root.rglob("*.md")):
                    if not path.is_file():
                        continue
                    try:
                        rel = path.relative_to(root)
                    except ValueError:
                        rel = path
                    label = f"{root.name}/{rel.as_posix()}"
                    items.append((label, path))
            except OSError:
                continue
        # Stable global sort across all roots.
        items.sort(key=lambda pair: pair[0].lower())
        return items

    def context_block(self) -> str:
        """Render the combined ``[USER RULES]`` block, or ``""`` if empty."""
        parts: list[str] = []
        total = 0
        for label, path in self.discover():
            text = self._read_cached(label, path)
            if not text:
                continue
            if len(text) > self._PER_FILE_CAP:
                text = text[: self._PER_FILE_CAP].rstrip() + "\n[...truncated]"
            chunk = f"--- {label} ---\n{text}"
            if total + len(chunk) > self._TOTAL_CAP:
                parts.append(f"[...{label} and later rule sheets omitted: cap reached]")
                break
            parts.append(chunk)
            total += len(chunk)
        if not parts:
            return ""
        return "[USER RULES]\n" + "\n\n".join(parts)

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
            logger.debug("RulesStore read failed for %s: %s", path, exc)
            return ""
        self._cache[label] = _CacheEntry(mtime=stat.st_mtime, size=stat.st_size, text=text)
        return text
