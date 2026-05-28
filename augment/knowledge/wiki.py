"""Markdown wiki manager — durable structured knowledge base.

Ported from Blackboard's ``blackboard/wiki/manager.py``. Removed:
- data_protection_governor (no PII layer in augment)
- atomic_files / json_schema (use plain pathlib writes + stdlib json)

Pages are Markdown files with YAML frontmatter stored under
``<data_dir>/wiki/``.  A flat-file ``index.md`` is rebuilt on every
write, and ``log.md`` keeps a chronological audit trail.

Search is keyword-only (no vector DB needed for < 5 k pages).
``context_block()`` returns a ``<wiki_context>`` XML snippet suitable for
direct prompt injection via the :class:`augment.context.builder.ContextBuilder`.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("augment.knowledge.wiki")

_FRONTMATTER_RE = re.compile(r"^---\n[\s\S]*?\n---\n?", re.MULTILINE)


# ── Data class ───────────────────────────────────────────────────────

@dataclass
class WikiPage:
    path: Path
    name: str     # relative path without .md, e.g. "decisions/AuthDesign"
    content: str  # raw markdown (includes frontmatter)
    mtime: float

    @property
    def summary_line(self) -> str:
        text = _FRONTMATTER_RE.sub("", self.content).strip()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped[:160]
        return ""

    def body(self) -> str:
        """Content without frontmatter."""
        return _FRONTMATTER_RE.sub("", self.content).strip()

    def to_dict(self, root: Path, *, include_content: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": self.name,
            "path": str(self.path.relative_to(root)).replace("\\", "/"),
            "summary": self.summary_line,
            "mtime": self.mtime,
        }
        if include_content:
            payload["content"] = self.content
        return payload


# ── Manager ──────────────────────────────────────────────────────────

class WikiManager:
    """Persistent Markdown wiki for durable project knowledge.

    Usage::

        wiki = WikiManager(data_dir / "wiki")
        wiki.write_page("decisions/AuthDesign", "# Auth Design\\n...")
        block = wiki.context_block("authentication flow")
        # inject block into system prompt
    """

    def __init__(self, wiki_dir: Path) -> None:
        self.root = Path(wiki_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "raw").mkdir(exist_ok=True)
        self._lock = threading.Lock()
        logger.debug("wiki manager initialised at %s", self.root)

    # ── CRUD ─────────────────────────────────────────────────────────

    def read_page(self, name: str) -> Optional[str]:
        """Return raw markdown (with frontmatter) or None."""
        path = self._page_path(name)
        if not path.exists() or not self._within_root(path):
            return None
        return path.read_text(encoding="utf-8")

    def write_page(self, name: str, content: str, *, source: str = "manual") -> WikiPage:
        """Create or update a wiki page; rebuild index + append log."""
        safe_name = self._safe_page_name(name)
        path = self._page_path(safe_name)
        now = _iso_now()
        with self._lock:
            created = now
            if path.exists():
                existing = path.read_text(encoding="utf-8")
                match = re.search(r"^created:\s*(\S+)", existing, re.MULTILINE)
                if match:
                    created = match.group(1)
            body = _ensure_frontmatter(content, created=created, updated=now, source=source)
            path.parent.mkdir(parents=True, exist_ok=True)
            _safe_write(path, body)
            self._append_log_locked("write", f"{safe_name} | source={source}")
        self.rebuild_index()
        return self._read_page_object(path)

    def store_raw(self, name: str, content: str) -> Path:
        """Store raw ingested text verbatim (no frontmatter)."""
        safe_name = self._safe_page_name(name)
        path = (self.root / "raw" / safe_name).with_suffix(".md").resolve()
        if not self._within_root(path):
            raise ValueError("raw path outside wiki root")
        path.parent.mkdir(parents=True, exist_ok=True)
        _safe_write(path, content)
        with self._lock:
            self._append_log_locked("raw", safe_name)
        return path

    def delete_page(self, name: str) -> bool:
        """Delete a wiki page and rebuild index. Returns True if deleted."""
        path = self._page_path(name)
        if not path.exists() or not self._within_root(path):
            return False
        path.unlink()
        with self._lock:
            self._append_log_locked("delete", name)
        self.rebuild_index()
        return True

    # ── Query ────────────────────────────────────────────────────────

    def list_pages(self, subdir: str = "") -> List[WikiPage]:
        """List all pages, excluding index/log/schema/raw."""
        base = self.root / subdir if subdir else self.root
        if not self._within_root(base):
            return []
        pages: List[WikiPage] = []
        for path in sorted(base.rglob("*.md")):
            rel = str(path.relative_to(self.root)).replace("\\", "/")
            if rel in {"index.md", "log.md", "schema.md"} or rel.startswith("raw/"):
                continue
            pages.append(self._read_page_object(path))
        return pages

    def search(self, query: str, max_results: int = 6) -> List[WikiPage]:
        """Keyword search across page name + content."""
        terms = [t.lower() for t in re.split(r"\W+", query or "") if len(t) > 2]
        if not terms:
            return []
        scored: List[tuple[int, WikiPage]] = []
        for page in self.list_pages():
            haystack = f"{page.name}\n{page.content}".lower()
            score = sum(haystack.count(t) for t in terms)
            if score > 0:
                scored.append((score, page))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [page for _, page in scored[: max(1, int(max_results or 6))]]

    def context_block(
        self,
        query: str = "",
        *,
        max_results: int = 3,
        per_page_chars: int = 1200,
    ) -> str:
        """Return a ``<wiki_context>`` XML snippet for prompt injection."""
        hits = self.search(query, max_results=max_results) if query else self.list_pages()[:max_results]
        if not hits:
            return ""
        lines = ["<wiki_context>", "Relevant wiki pages:"]
        for page in hits:
            excerpt = page.body()[:per_page_chars]
            lines.append(f"\n### [[{page.name}]]")
            lines.append(excerpt)
        lines.append("</wiki_context>")
        return "\n".join(lines)

    # ── Maintenance ──────────────────────────────────────────────────

    def rebuild_index(self) -> None:
        """Rebuild ``index.md`` from all current pages."""
        pages = self.list_pages()
        groups: Dict[str, List[WikiPage]] = {}
        for page in pages:
            group = page.name.split("/", 1)[0] if "/" in page.name else "root"
            groups.setdefault(group, []).append(page)
        lines = ["# Wiki Index", "", f"*{len(pages)} pages — updated {_iso_now()}*", ""]
        for group, group_pages in sorted(groups.items()):
            lines.append(f"## {group.title()}")
            lines.append("")
            for page in sorted(group_pages, key=lambda item: item.name):
                summary = page.summary_line or "(no summary)"
                lines.append(f"- [[{page.name}]] — {summary}")
            lines.append("")
        _safe_write(self.root / "index.md", "\n".join(lines) + "\n")

    def health(self) -> Dict[str, Any]:
        """Deterministic health check: broken links, orphans, duplicates."""
        pages = self.list_pages()
        names = {page.name for page in pages}
        inbound: Dict[str, int] = {name: 0 for name in names}
        broken_links: List[Dict[str, str]] = []
        pages_without_summary: List[str] = []
        for page in pages:
            if not page.summary_line:
                pages_without_summary.append(page.name)
            for link in re.findall(r"\[\[([^\]|#]+)", page.content):
                target = link.strip()
                if target in inbound:
                    inbound[target] += 1
                else:
                    broken_links.append({"page": page.name, "target": target})
        orphans = [name for name, count in inbound.items() if count == 0]
        duplicate_summaries: Dict[str, List[str]] = {}
        for page in pages:
            summary = page.summary_line.strip().lower()
            if summary:
                duplicate_summaries.setdefault(summary, []).append(page.name)
        duplicate_summaries = {
            s: ns for s, ns in duplicate_summaries.items() if len(ns) > 1
        }
        return {
            "total_pages": len(pages),
            "orphans": sorted(orphans),
            "broken_links": broken_links,
            "pages_without_summary": sorted(pages_without_summary),
            "duplicate_summaries": duplicate_summaries,
        }

    def stats(self) -> Dict[str, Any]:
        pages = self.list_pages()
        log_path = self.root / "log.md"
        log_entries = log_path.read_text(encoding="utf-8").count("\n## [") if log_path.exists() else 0
        return {
            "wiki_dir": str(self.root),
            "total_pages": len(pages),
            "index_exists": (self.root / "index.md").exists(),
            "log_exists": log_path.exists(),
            "log_entries": log_entries,
        }

    def all_pages_as_json(self, *, include_content: bool = False) -> List[Dict[str, Any]]:
        return [p.to_dict(self.root, include_content=include_content) for p in self.list_pages()]

    # ── Internals ────────────────────────────────────────────────────

    def _page_path(self, name: str) -> Path:
        safe_name = self._safe_page_name(name)
        path = (self.root / safe_name).with_suffix(".md").resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _read_page_object(self, path: Path) -> WikiPage:
        return WikiPage(
            path=path,
            name=str(path.relative_to(self.root).with_suffix("")).replace("\\", "/"),
            content=path.read_text(encoding="utf-8"),
            mtime=path.stat().st_mtime,
        )

    def _append_log_locked(self, operation: str, description: str) -> None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_path = self.root / "log.md"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n## [{date}] {operation} | {description}\n")
        except Exception as exc:
            logger.warning("wiki log write failed: %s", exc)

    def _safe_page_name(self, name: str) -> str:
        raw = str(name or "").strip().replace("\\", "/").strip("/")
        if not raw:
            raise ValueError("wiki page name required")
        parts = []
        for part in raw.split("/"):
            cleaned = re.sub(r"[^A-Za-z0-9_. -]", "_", part).strip(". ")
            if cleaned:
                parts.append(cleaned)
        if not parts:
            raise ValueError("wiki page name required")
        return "/".join(parts)

    def _within_root(self, path: Path) -> bool:
        try:
            Path(path).resolve().relative_to(self.root.resolve())
            return True
        except Exception:
            return False


# ── Helpers ──────────────────────────────────────────────────────────

def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_frontmatter(content: str, *, created: str, updated: str, source: str) -> str:
    body = _FRONTMATTER_RE.sub("", content or "").strip()
    frontmatter = "\n".join([
        "---",
        f"created: {created}",
        f"updated: {updated}",
        f"sources: [{source}]",
        "---",
        "",
    ])
    return frontmatter + body + "\n"


def _safe_write(path: Path, content: str) -> None:
    try:
        path.write_text(content, encoding="utf-8")
    except Exception as exc:
        logger.error("wiki write failed %s: %s", path, exc)
