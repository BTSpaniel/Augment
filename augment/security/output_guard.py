"""Output guard — sanitize agent output before sending to user."""
from __future__ import annotations

import logging
import re

from augment.security.redaction import contains_sensitive, redact


logger = logging.getLogger("augment.security.output_guard")

_MAX_OUTPUT_SIZE = 50_000
_INJECTION_PATTERNS = (
    re.compile(r"<script[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE),
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"on\w+\s*=\s*[\"']", re.IGNORECASE),
)


def sanitize_output(text: str, *, redact_pii: bool = True, max_size: int = _MAX_OUTPUT_SIZE) -> str:
    """Truncate, redact, and strip XSS-ish patterns from ``text``."""
    if not text:
        return text
    result = text
    if len(result) > max_size:
        result = result[:max_size] + "\n... [output truncated]"
    if redact_pii and contains_sensitive(result):
        result = redact(result)
        logger.info("redacted sensitive data from output")
    for pattern in _INJECTION_PATTERNS:
        result = pattern.sub("[removed]", result)
    return result


def sanitize_for_html(text: str) -> str:
    """HTML-escape for safe embedding."""
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def is_safe_url(url: str) -> bool:
    """Block data:, javascript:, vbscript:, file:/// and non-http(s) URLs."""
    cleaned = str(url or "").strip().lower()
    if not cleaned:
        return False
    if cleaned.startswith(("javascript:", "data:", "vbscript:", "file:///")):
        return False
    if not cleaned.startswith(("http://", "https://")):
        return False
    return True
