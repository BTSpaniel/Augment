"""Pattern snapshots — capture a file's shape before editing.

Distilled from FAIL's ``server/builder/patterns.py``. The mesh-only receipt
writer is dropped; everything else is identical so snapshots round-trip
between FAIL and Augment.
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class PatternSnapshot:
    pattern_snapshot_id: str
    path: str
    language: str
    file_type: str
    module_style: str = "unknown"
    section_order: List[str] = field(default_factory=list)
    symbols: List[str] = field(default_factory=list)
    formatting: Dict[str, Any] = field(default_factory=dict)
    comment_style: str = "unknown"
    safe_edit_zones: List[str] = field(default_factory=list)
    forbidden_changes: List[str] = field(default_factory=list)
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def snapshot_file(path: str | Path, *, display_path: str = "") -> PatternSnapshot:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    shown = display_path or p.as_posix()
    suffix = p.suffix.lower()
    if suffix in {".js", ".mjs", ".cjs"}:
        return _snapshot_javascript(text, shown)
    if suffix in {".ts", ".tsx"}:
        snap = _snapshot_javascript(text, shown)
        snap.language = "typescript"
        snap.file_type = "frontend.typescript"
        return snap
    if suffix == ".py":
        return _snapshot_python(text, shown)
    if suffix in {".html", ".htm"}:
        return _snapshot_markup(text, shown, "html", "frontend.html")
    if suffix == ".css":
        return _snapshot_css(text, shown)
    if suffix == ".json":
        return _generic_snapshot(text, shown, "json", "config.json")
    if suffix in {".md", ".markdown"}:
        return _snapshot_markdown(text, shown)
    return _generic_snapshot(text, shown, "text", "unknown")


def _snapshot_javascript(text: str, path: str) -> PatternSnapshot:
    symbols = _js_symbols(text)
    sections = _js_sections(text, symbols)
    browser_global = bool(re.search(r"\b(window|document|localStorage|requestAnimationFrame)\b", text)) and not re.search(r"^\s*(import|export)\s+", text, re.M)
    file_type = "frontend.single_file_game" if browser_global and len(text.splitlines()) >= 80 else "frontend.javascript"
    return PatternSnapshot(
        pattern_snapshot_id=_snapshot_id(),
        path=path,
        language="javascript",
        file_type=file_type,
        module_style=(
            "browser-global-script"
            if browser_global
            else ("esm" if re.search(r"^\s*(import|export)\s+", text, re.M) else "script")
        ),
        section_order=sections,
        symbols=symbols,
        formatting=_formatting(text),
        comment_style=_comment_style(text),
        safe_edit_zones=_safe_zones(file_type, sections),
        forbidden_changes=_forbidden_changes(file_type),
        created_at=time.time(),
    )


def _snapshot_python(text: str, path: str) -> PatternSnapshot:
    symbols = re.findall(r"^\s*(?:class|def)\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M)
    sections: List[str] = []
    if re.search(r"^\s*(import|from)\s+", text, re.M):
        sections.append("imports")
    if re.search(r"^\s*class\s+", text, re.M):
        sections.append("classes")
    if re.search(r"^\s*def\s+", text, re.M):
        sections.append("functions")
    return PatternSnapshot(
        _snapshot_id(),
        path,
        "python",
        "backend.python",
        "python-module",
        sections,
        symbols,
        _formatting(text),
        _comment_style(text),
        ["near matching class/function"],
        ["do not reorder imports/classes/functions outside requested edit"],
        time.time(),
    )


def _snapshot_markup(text: str, path: str, language: str, file_type: str) -> PatternSnapshot:
    sections = [tag for tag in ("head", "body", "script", "style", "main") if re.search(fr"<\s*{tag}\b", text, re.I)]
    symbols = re.findall(r"\bid=[\"']([^\"']+)[\"']", text)
    return PatternSnapshot(
        _snapshot_id(),
        path,
        language,
        file_type,
        "document",
        sections,
        symbols,
        _formatting(text),
        _comment_style(text),
        ["inside matching tag or component block"],
        ["do not reflow unrelated markup"],
        time.time(),
    )


def _snapshot_css(text: str, path: str) -> PatternSnapshot:
    selectors = [match.strip() for match in re.findall(r"(^[^{}@][^{]+)\{", text, re.M)[:80]]
    sections = ["rules"] if selectors else []
    if re.search(r"@media\b", text):
        sections.append("media-queries")
    return PatternSnapshot(
        _snapshot_id(),
        path,
        "css",
        "frontend.css",
        "stylesheet",
        sections,
        selectors,
        _formatting(text),
        _comment_style(text),
        ["near matching selector"],
        ["do not reorder unrelated selectors"],
        time.time(),
    )


def _snapshot_markdown(text: str, path: str) -> PatternSnapshot:
    headings = re.findall(r"^#{1,6}\s+(.+)$", text, re.M)
    return PatternSnapshot(
        _snapshot_id(),
        path,
        "markdown",
        "docs.markdown",
        "document",
        headings,
        headings,
        _formatting(text),
        _comment_style(text),
        ["under matching heading"],
        ["do not rewrite unrelated sections"],
        time.time(),
    )


def _generic_snapshot(text: str, path: str, language: str, file_type: str) -> PatternSnapshot:
    return PatternSnapshot(
        _snapshot_id(),
        path,
        language,
        file_type,
        "unknown",
        [],
        [],
        _formatting(text),
        _comment_style(text),
        ["targeted exact range"],
        ["do not rewrite whole file unless explicitly approved"],
        time.time(),
    )


def _js_symbols(text: str) -> List[str]:
    names = re.findall(r"^\s*function\s+([A-Za-z_$][\w$]*)\s*\(", text, re.M)
    names.extend(re.findall(r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", text, re.M))
    names.extend(re.findall(r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*function\b", text, re.M))
    return list(dict.fromkeys(names))[:200]


def _js_sections(text: str, symbols: List[str]) -> List[str]:
    sections: List[str] = []
    probes = [
        ("imports", r"^\s*import\s+"),
        ("constants", r"^\s*(?:const|let|var)\s+[A-Z0-9_]{2,}\b"),
        ("state", r"\b(?:state|gameState|player|settings)\b"),
        ("input", r"\baddEventListener\s*\(\s*[\"'](?:keydown|keyup|pointer|click|mousemove)"),
        ("save-load", r"\b(?:localStorage|saveGame|loadGame|serialize|deserialize)\b"),
        ("ui-rendering", r"\b(?:render|draw|html|innerHTML|template)\b"),
        ("utilities", r"\b(?:clamp|lerp|rand|random|format|uid)\b"),
        ("boot", r"\b(?:DOMContentLoaded|init|boot|requestAnimationFrame)\b"),
    ]
    for name, pattern in probes:
        if re.search(pattern, text, re.M | re.I):
            sections.append(name)
    if symbols and "functions" not in sections:
        sections.insert(min(len(sections), 2), "functions")
    return list(dict.fromkeys(sections))


def _formatting(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    indents = [len(line) - len(line.lstrip(" ")) for line in lines if line.startswith(" ")]
    positive = [i for i in indents if i > 0]
    indent_label = "unknown"
    if positive:
        smallest = min(positive)
        if smallest == 2:
            indent_label = "2 spaces"
        elif smallest == 4:
            indent_label = "4 spaces"
    return {
        "indent": indent_label,
        "semicolons": text.count(";\n") >= 3,
        "line_count": len(lines),
    }


def _comment_style(text: str) -> str:
    slash = text.count("//") + text.count("/*")
    hash_comments = len(re.findall(r"^\s*#", text, re.M))
    html = text.count("<!--")
    if slash >= hash_comments and slash >= html and slash:
        return "slash"
    if hash_comments:
        return "hash"
    if html:
        return "html"
    return "minimal"


def _safe_zones(file_type: str, sections: List[str]) -> List[str]:
    if file_type == "frontend.single_file_game":
        return [f"inside existing {section} section" for section in sections] or ["inside matching existing function"]
    return ["near matching symbol or section"]


def _forbidden_changes(file_type: str) -> List[str]:
    if file_type == "frontend.single_file_game":
        return [
            "do not convert to modules",
            "do not reformat whole file",
            "do not move unrelated gameplay/render/router functions",
        ]
    return ["do not reformat whole file", "do not move unrelated sections"]


def _snapshot_id() -> str:
    return f"ps_{uuid.uuid4().hex[:12]}"
