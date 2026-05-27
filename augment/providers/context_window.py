"""Per-provider context window resolution.

Three-tier resolver, in order of precedence:

1. **Explicit override** — ``profile["context_window"]`` from
   ``data/settings.json`` (set via UI or YAML) always wins.
2. **Live introspection** — for providers whose API exposes the window
   per-model (OpenRouter, Groq, Mistral, Together, Fireworks, Ollama,
   LM Studio, llama.cpp), call the right endpoint and read it.
   Best-effort: any failure falls through to the next tier.
3. **Static catalog** — for providers whose API doesn't expose it
   (OpenAI, Anthropic, Cerebras), pattern-match the model id against a
   curated table.

If all three miss, we fall back to a conservative ``DEFAULT_FALLBACK``
(32_768 tokens) — enough for any current frontier model's mini variant.

Live introspection is **best-effort and offline-safe** — every adapter
swallows network errors and returns ``None``. Tests should mock the
``requests.get`` boundary (or run in offline mode where every adapter
quietly returns ``None``).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, Mapping, Optional

logger = logging.getLogger("augment.providers.context_window")


DEFAULT_FALLBACK: int = 32_768
"""Last-resort context window when every other tier misses."""


# ── Static catalog for providers that don't expose context_length ─────
#
# Each entry is ``(regex, window)``. The regex is matched
# case-insensitively against the model id. First match wins, so order
# matters — put more specific patterns first.
#
# Sources: each provider's official model page, last-checked May 2026.
STATIC_CATALOG: list[tuple[str, int]] = [
    # ── Anthropic ──────────────────────────────────────────────────
    (r"claude-(opus|sonnet|haiku)-(4|3[\.-]?7|3[\.-]?5)", 200_000),
    (r"claude-3",                                          200_000),
    (r"claude-2",                                          100_000),
    # ── OpenAI ─────────────────────────────────────────────────────
    (r"o[13](?:[-_]|$)",                                   200_000),  # o1 / o3 reasoners
    (r"gpt-5",                                             256_000),
    (r"gpt-4\.1",                                        1_000_000),
    (r"gpt-4o",                                            128_000),
    (r"gpt-4-turbo",                                       128_000),
    (r"gpt-4(?!-1|o|-turbo|\.1)",                            8_192),
    (r"gpt-3\.5-turbo-16k",                                 16_385),
    (r"gpt-3\.5",                                           16_385),
    # ── Cerebras ───────────────────────────────────────────────────
    (r"llama-?3\.[13]-70b",                                128_000),
    (r"llama-?3\.[13]-8b",                                 128_000),
    (r"qwen-?3-32b",                                        32_768),
    (r"gpt-oss",                                           128_000),
    # ── Generic Llama / Qwen / Mistral families (catch-all) ───────
    (r"llama-?(3|4)",                                      128_000),
    (r"qwen-?(2\.5|3)",                                    128_000),
    (r"mistral-large",                                     128_000),
    (r"mistral-(medium|small)",                             32_768),
    (r"mixtral",                                            32_768),
    # ── Local placeholders (very conservative) ─────────────────────
    (r"local-(model|gguf)",                                 32_768),
]


def lookup_static_catalog(model: str) -> Optional[int]:
    """Pattern-match ``model`` against :data:`STATIC_CATALOG`.

    Returns the catalog window in tokens, or ``None`` if nothing matched.
    """
    name = (model or "").lower()
    if not name:
        return None
    for pattern, window in STATIC_CATALOG:
        if re.search(pattern, name):
            return int(window)
    return None


# ── Live introspection adapters ────────────────────────────────────────
#
# Each adapter takes the profile dict (id, endpoint, api_key, model, …)
# and returns the model's context window in tokens, or ``None`` on any
# failure. Adapters are deliberately tiny + best-effort — never raise.

ProfileLike = Mapping[str, Any]
Introspector = Callable[[ProfileLike], Optional[int]]


def _safe_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 5.0) -> Any:
    """``requests.get(...).json()`` wrapper that swallows every failure."""
    try:
        import requests  # local import — keeps the cold start cheap
    except Exception:
        return None
    try:
        resp = requests.get(url, headers=headers or {}, timeout=timeout)
        if not resp.ok:
            return None
        return resp.json()
    except Exception:
        return None


def _safe_post(
    url: str,
    payload: Mapping[str, Any],
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 5.0,
) -> Any:
    try:
        import requests
    except Exception:
        return None
    try:
        resp = requests.post(url, json=dict(payload), headers=headers or {}, timeout=timeout)
        if not resp.ok:
            return None
        return resp.json()
    except Exception:
        return None


def _profile_endpoint(profile: ProfileLike) -> str:
    return str(profile.get("endpoint") or "").rstrip("/")


def _bearer_headers(profile: ProfileLike) -> Dict[str, str]:
    key = str(profile.get("api_key") or "")
    return {"Authorization": f"Bearer {key}"} if key else {}


# ─── OpenRouter: GET /api/v1/models  → data[].context_length ──────────
def _introspect_openrouter(profile: ProfileLike) -> Optional[int]:
    url = f"{_profile_endpoint(profile)}/models"
    data = _safe_get(url, _bearer_headers(profile))
    if not isinstance(data, dict):
        return None
    target = str(profile.get("model") or "").strip()
    for entry in (data.get("data") or []):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("id") or "") != target:
            continue
        # OpenRouter sometimes nests it under top_provider.context_length
        for key in ("context_length",):
            val = entry.get(key)
            if isinstance(val, (int, float)) and val > 0:
                return int(val)
        top = entry.get("top_provider") or {}
        if isinstance(top, dict):
            val = top.get("context_length")
            if isinstance(val, (int, float)) and val > 0:
                return int(val)
    return None


# ─── Groq: GET /v1/models  → data[].context_window ────────────────────
def _introspect_groq(profile: ProfileLike) -> Optional[int]:
    url = f"{_profile_endpoint(profile)}/models"
    data = _safe_get(url, _bearer_headers(profile))
    if not isinstance(data, dict):
        return None
    target = str(profile.get("model") or "").strip()
    for entry in (data.get("data") or []):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("id") or "") != target:
            continue
        for key in ("context_window", "context_length", "max_context_length"):
            val = entry.get(key)
            if isinstance(val, (int, float)) and val > 0:
                return int(val)
    return None


# ─── Mistral / Together / Fireworks: same shape as Groq ───────────────
_introspect_mistral = _introspect_groq
_introspect_together = _introspect_groq
_introspect_fireworks = _introspect_groq


# ─── Ollama: POST /api/show → model_info["<arch>.context_length"] ─────
def _introspect_ollama(profile: ProfileLike) -> Optional[int]:
    # Ollama lives at e.g. http://127.0.0.1:11434/v1 ; /api/show is at /api.
    base = _profile_endpoint(profile)
    if base.endswith("/v1"):
        base = base[:-3]
    url = f"{base.rstrip('/')}/api/show"
    target = str(profile.get("model") or "").strip()
    if not target:
        return None
    data = _safe_post(url, {"name": target})
    if not isinstance(data, dict):
        return None
    info = data.get("model_info") or {}
    if not isinstance(info, dict):
        return None
    # The key is "<arch>.context_length" — try common architectures first,
    # then any *.context_length match.
    for arch in ("llama", "qwen2", "qwen3", "mistral", "phi3", "gemma", "deepseek"):
        val = info.get(f"{arch}.context_length")
        if isinstance(val, (int, float)) and val > 0:
            return int(val)
    for key, val in info.items():
        if str(key).endswith(".context_length") and isinstance(val, (int, float)) and val > 0:
            return int(val)
    return None


# ─── LM Studio: GET /v1/models/{id} → loaded_context_length ──────────
def _introspect_lmstudio(profile: ProfileLike) -> Optional[int]:
    target = str(profile.get("model") or "").strip()
    if not target:
        return None
    url = f"{_profile_endpoint(profile)}/models/{target}"
    data = _safe_get(url)
    if not isinstance(data, dict):
        return None
    for key in ("loaded_context_length", "max_context_length", "context_length"):
        val = data.get(key)
        if isinstance(val, (int, float)) and val > 0:
            return int(val)
    return None


# ─── llama.cpp server: GET /props → default_generation_settings.n_ctx ─
def _introspect_llamacpp(profile: ProfileLike) -> Optional[int]:
    base = _profile_endpoint(profile)
    if base.endswith("/v1"):
        base = base[:-3]
    url = f"{base.rstrip('/')}/props"
    data = _safe_get(url)
    if not isinstance(data, dict):
        return None
    settings = data.get("default_generation_settings") or {}
    if isinstance(settings, dict):
        val = settings.get("n_ctx")
        if isinstance(val, (int, float)) and val > 0:
            return int(val)
    val = data.get("n_ctx")
    if isinstance(val, (int, float)) and val > 0:
        return int(val)
    return None


INTROSPECTORS: Dict[str, Introspector] = {
    "openrouter": _introspect_openrouter,
    "groq":       _introspect_groq,
    "mistral":    _introspect_mistral,
    "together":   _introspect_together,
    "fireworks":  _introspect_fireworks,
    "ollama":     _introspect_ollama,
    "lmstudio":   _introspect_lmstudio,
    "llamacpp":   _introspect_llamacpp,
}


# ── Public API ─────────────────────────────────────────────────────────


def resolve_context_window(
    profile: ProfileLike,
    *,
    allow_introspection: bool = True,
    default: int = DEFAULT_FALLBACK,
) -> int:
    """Resolve the active context window for a provider profile.

    Args:
        profile: Provider profile dict (id, preset_id, endpoint, model,
            api_key, optionally an explicit ``context_window`` override).
        allow_introspection: Set to ``False`` in tests / offline use to
            skip every network call.
        default: Returned when every tier misses.

    Returns:
        Context window in tokens.
    """
    # ── Tier 1: explicit override ─────────────────────────────────
    explicit = profile.get("context_window")
    if isinstance(explicit, (int, float)) and explicit > 0:
        return int(explicit)

    preset_id = str(profile.get("preset_id") or profile.get("id") or "").lower()
    model = str(profile.get("model") or "")

    # ── Tier 2: live introspection ────────────────────────────────
    if allow_introspection and preset_id in INTROSPECTORS:
        try:
            value = INTROSPECTORS[preset_id](profile)
        except Exception:  # belt-and-braces — adapters already swallow
            value = None
        if isinstance(value, int) and value > 0:
            logger.info("Introspected %s context_window=%d", preset_id, value)
            return value

    # ── Tier 3: static catalog by model id ────────────────────────
    catalog = lookup_static_catalog(model)
    if catalog is not None:
        return int(catalog)

    # ── Fallback ──────────────────────────────────────────────────
    return int(default)
