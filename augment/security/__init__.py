"""Security primitives — redaction, path guard, output guard, trust, untrusted content.

Ported from FAIL's ``server/security`` package. The mesh-coupled ``safety_monitor``
and ``tool_policy`` are intentionally omitted — Augment's single loop relies on
the simpler ``path_guard`` + ``output_guard`` + ``trust`` triad.
"""
from __future__ import annotations

from augment.security.output_guard import is_safe_url, sanitize_for_html, sanitize_output
from augment.security.path_guard import PathGuard
from augment.security.redaction import contains_sensitive, redact, redact_for_log
from augment.security.trust import TrustLevel, TrustPolicy
from augment.security.untrusted_content import is_untrusted_tool, wrap_untrusted_content

__all__ = [
    "PathGuard",
    "TrustLevel",
    "TrustPolicy",
    "contains_sensitive",
    "is_safe_url",
    "is_untrusted_tool",
    "redact",
    "redact_for_log",
    "sanitize_for_html",
    "sanitize_output",
    "wrap_untrusted_content",
]
