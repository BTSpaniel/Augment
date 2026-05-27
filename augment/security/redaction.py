"""Redaction — strip PII and sensitive data from text before logging/display."""
from __future__ import annotations

import re


_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+?1[-.]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CREDIT_CARD_RE = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")
_API_KEY_RE = re.compile(
    r"\b(?:sk-|pk-|key-|token-|api[_-]?key[=:]?\s*)[A-Za-z0-9_-]{20,}\b",
    re.IGNORECASE,
)
_IP_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_PASSWORD_RE = re.compile(r"(?:password|passwd|pwd)\s*[=:]\s*\S+", re.IGNORECASE)

_PATTERNS = (
    (_EMAIL_RE, "[EMAIL]"),
    (_PHONE_RE, "[PHONE]"),
    (_SSN_RE, "[SSN]"),
    (_CREDIT_CARD_RE, "[CARD]"),
    (_API_KEY_RE, "[API_KEY]"),
    (_PASSWORD_RE, "[PASSWORD]"),
)


def redact(text: str, *, redact_ips: bool = False) -> str:
    """Replace common PII / secret patterns in ``text`` with placeholder tokens."""
    if not text:
        return text
    result = text
    for pattern, replacement in _PATTERNS:
        result = pattern.sub(replacement, result)
    if redact_ips:
        result = _IP_RE.sub("[IP]", result)
    return result


def contains_sensitive(text: str) -> bool:
    """Return True when ``text`` contains any of the tracked sensitive patterns."""
    if not text:
        return False
    for pattern, _ in _PATTERNS:
        if pattern.search(text):
            return True
    return False


def redact_for_log(text: str, max_len: int = 500) -> str:
    """Redact then truncate so logs stay short and safe."""
    result = redact(text or "")
    if len(result) > max_len:
        result = result[:max_len] + "..."
    return result
