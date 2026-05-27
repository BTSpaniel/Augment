"""Real-tokenizer counting + truncation for context budgeting.

Replaces the legacy chars/4 heuristic used everywhere else in
augment.context. Backed by tiktoken when it is installed; falls back to
the 4-chars-per-token estimate when it is not.

Why tiktoken:

* tiktoken is exact for OpenAI families (GPT-4o, GPT-4, o1, o3,
  GPT-5/Codex bridge) via the o200k_base and cl100k_base encodings.
* For non-OpenAI families (Claude, Llama, Mistral, Qwen, Gemini,
  DeepSeek) tiktoken o200k_base is a good-enough universal estimator
  with ~5-15% error, which sits comfortably inside our 9% buffer slot.
* Loading an HF tokenizer requires the model tokenizer.json to be
  cached locally (gated, slow). tiktoken loads from package data and
  is instant.

When you need exact counts for a non-OpenAI provider, call the
provider official count_tokens API directly. This module is for
budget enforcement, not billing.

Public API:

* count_tokens(text, model) -> int
* truncate_to_token_budget(text, max_tokens, model) -> str
* encoding_name_for_model(model) -> str
* is_available() -> bool
"""
from __future__ import annotations

import functools
import hashlib
import logging
import re

logger = logging.getLogger("augment.context.tokens")

try:
    import tiktoken
    _HAS_TIKTOKEN = True
except Exception:  # pragma: no cover -- import guard
    tiktoken = None  # type: ignore
    _HAS_TIKTOKEN = False


# Model -> encoding name. Order matters; first regex match wins.
# Everything that does not match falls through to DEFAULT_ENCODING.
_ENCODING_RULES: list[tuple[str, str]] = [
    # OpenAI native (exact counts)
    (r"^(gpt-5|codex|gpt-4o|gpt-4\.1|o[13](?:[-_]|$))",       "o200k_base"),
    (r"^(gpt-4(?!o|\.1)|gpt-3\.5)",                            "cl100k_base"),
    (r"^(text-davinci|davinci-002|babbage-002|code-davinci)",  "p50k_base"),
    (r"^(gpt-3|davinci|babbage|ada|curie)",                    "r50k_base"),
    # Non-OpenAI families (estimate via o200k_base)
    (r"claude",                                                "o200k_base"),
    (r"llama",                                                 "o200k_base"),
    (r"qwen",                                                  "o200k_base"),
    (r"mistral|mixtral",                                       "o200k_base"),
    (r"gemini|gemma",                                          "o200k_base"),
    (r"deepseek",                                              "o200k_base"),
]


DEFAULT_ENCODING = "o200k_base"
"""Fallback encoding when no rule matches. o200k_base is the most-recent
OpenAI tokenizer and the closest universal estimator we have for
non-OpenAI families."""


def encoding_name_for_model(model: str) -> str:
    """Map a model id to the best tiktoken encoding name."""
    name = (model or "").strip().lower()
    if not name:
        return DEFAULT_ENCODING
    for pattern, enc in _ENCODING_RULES:
        if re.search(pattern, name):
            return enc
    return DEFAULT_ENCODING


def is_available() -> bool:
    """Return True iff tiktoken is importable + at least one encoder loads."""
    if not _HAS_TIKTOKEN:
        return False
    return _encoder(DEFAULT_ENCODING) is not None


@functools.lru_cache(maxsize=8)
def _encoder(encoding_name: str):
    """Load and memoise a tiktoken encoder. Returns None on failure."""
    if not _HAS_TIKTOKEN:
        return None
    try:
        return tiktoken.get_encoding(encoding_name)
    except Exception as exc:
        logger.warning("tiktoken.get_encoding(%r) failed: %s", encoding_name, exc)
        return None


# Token-count cache. A single chat build asks the counter the same
# question many times (system prompt, agent soul, memory). Cache by
# (encoding_name, md5(text)) so we only encode each unique block once
# per process. Capped at 512 entries to bound memory.
_COUNT_CACHE: dict[tuple[str, str], int] = {}
_COUNT_CACHE_MAX = 512


def _hash_text(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()


def _cache_put(key: tuple[str, str], value: int) -> None:
    if len(_COUNT_CACHE) >= _COUNT_CACHE_MAX:
        # Drop one arbitrary entry; coarse LRU is overkill for our scale.
        _COUNT_CACHE.pop(next(iter(_COUNT_CACHE)), None)
    _COUNT_CACHE[key] = value


def count_tokens(text: str, model: str = "") -> int:
    """Return the token count of `text` for `model`.

    Always returns >= 0. Falls back to len(text) // 4 when tiktoken is
    unavailable or the encoder load failed.

    Cache semantics: the cache is checked **before** the encoder is
    loaded, so once a (text, encoding) pair has been counted with a real
    encoder, subsequent calls return that count without re-encoding —
    even if the encoder later fails to load.
    """
    if not text:
        return 0

    encoding_name = encoding_name_for_model(model)
    key = (encoding_name, _hash_text(text))
    cached = _COUNT_CACHE.get(key)
    if cached is not None:
        return cached

    encoder = _encoder(encoding_name)
    if encoder is None:
        return max(0, len(text) // 4)

    try:
        # disallowed_special=() means special-token literals in the
        # text (rare, but they happen in code samples) are encoded as
        # regular characters instead of raising.
        count = len(encoder.encode(text, disallowed_special=()))
    except Exception as exc:
        logger.warning("tiktoken encode failed (%s); falling back to chars/4", exc)
        count = max(0, len(text) // 4)

    _cache_put(key, count)
    return count


def truncate_to_token_budget(text: str, max_tokens: int, model: str = "") -> str:
    """Truncate `text` so its token count is <= `max_tokens`.

    When tiktoken is available we do an exact encode -> slice -> decode
    so the result lands on a clean token boundary. Otherwise we fall
    back to a char-based slice with the 4x heuristic.
    """
    if not text or max_tokens <= 0:
        return ""

    encoding_name = encoding_name_for_model(model)
    encoder = _encoder(encoding_name)
    if encoder is None:
        return text[: max_tokens * 4]

    try:
        ids = encoder.encode(text, disallowed_special=())
    except Exception:
        return text[: max_tokens * 4]

    if len(ids) <= max_tokens:
        return text
    try:
        return encoder.decode(ids[:max_tokens])
    except Exception:
        # decode can fail on partial multi-byte UTF-8 boundaries; fall
        # back to the char heuristic.
        return text[: max_tokens * 4]


def clear_cache() -> None:
    """Drop the token-count cache. Useful in tests."""
    _COUNT_CACHE.clear()
