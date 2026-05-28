"""Context health diagnostics — lightweight inline block for large/redundant sections.

Analyzes the assembled section map and warns about sections that are
disproportionately large or appear to duplicate content already present
elsewhere.  The output is included in the bleep event for UI display and
can optionally be appended to the prompt.

Sections: build_context_health_block (main entry), analyze_context_sections.
"""
from __future__ import annotations

from typing import Any, Dict, List

# ── Constants ─────────────────────────────────────────────────────────

_DEFAULT_WARN_CHARS = 20_000
_SOURCE_OF_TRUTH_SECTIONS = {
    "identity", "project_conventions", "user_rules", "coding_contract",
    "agent_soul", "active_plan",
}


# ── Public entry points ───────────────────────────────────────────────

def build_context_health_block(
    sections: Dict[str, str],
    *,
    warn_chars: int = _DEFAULT_WARN_CHARS,
) -> str:
    """Return a plain-text context health diagnostic block, or '' if all clear.

    Meant to be included in the ``bleep`` SSE event so the UI can surface
    it in the expandable context inspector panel.  Optionally also include
    it in the prompt if the caller wants the model aware of heavy sections.
    """
    reports = analyze_context_sections(sections, warn_chars=warn_chars)
    if not reports:
        return ""
    lines = ["[CONTEXT HEALTH]", "Diagnostics (informational — budget allocator handles truncation):"]
    for report in reports[:10]:
        lines.append(f"- {report['section']}: {report['message']}")
    return "\n".join(lines)


def analyze_context_sections(
    sections: Dict[str, str],
    *,
    warn_chars: int = _DEFAULT_WARN_CHARS,
) -> List[Dict[str, Any]]:
    """Return a list of diagnostic dicts for over-sized or redundant sections."""
    reports: List[Dict[str, Any]] = []
    seen: Dict[str, str] = {}
    for name, content in sections.items():
        text = content or ""
        if len(text) > warn_chars:
            reports.append({
                "section": name,
                "severity": "warn",
                "message": f"large section ({len(text):,} chars); budget allocator may truncate it",
            })
        fingerprint = " ".join(text.lower().split())[:1000]
        if fingerprint and fingerprint in seen and name not in _SOURCE_OF_TRUTH_SECTIONS:
            reports.append({
                "section": name,
                "severity": "info",
                "message": f"appears redundant with '{seen[fingerprint]}'",
            })
        elif fingerprint:
            seen[fingerprint] = name
    return reports
