"""Provider presets — distilled from FAIL's server/providers/presets.py.

Paste an API key and Augment auto-detects the endpoint, default model, and
capabilities. Same single-source-of-truth catalog FAIL uses, trimmed for
Augment's single-profile model.
"""
from __future__ import annotations

from typing import Any, Dict, List


PRESETS: Dict[str, Dict[str, Any]] = {
    "groq": {
        "name": "Groq",
        "endpoint": "https://api.groq.com/openai/v1",
        "default_model": "meta-llama/llama-4-maverick-17b-128e-instruct",
        "capabilities": ["chat", "tools", "streaming"],
        "key_prefix": "gsk_",
        "api_key_env": "GROQ_API_KEY",
        # Llama 4 Maverick / Scout advertise 128k–10M; 128k is the safe default
        # for the ones Groq actually serves. `/v1/models` exposes
        # ``context_window`` per-model so live introspection can override.
        "context_window": 128_000,
        "description": "Ultra-fast inference. Free tier available.",
    },
    "openai": {
        "name": "OpenAI",
        "endpoint": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "capabilities": ["chat", "tools", "streaming", "vision"],
        "key_prefix": "sk-",
        "api_key_env": "OPENAI_API_KEY",
        # GPT-4o family = 128k. OpenAI's `/v1/models` does NOT expose
        # context_length, so the static catalog in context_window.py picks
        # the right window based on model id (gpt-4o → 128k, o1/o3 → 200k,
        # gpt-3.5-turbo → 16k, etc.).
        "context_window": 128_000,
        "description": "GPT-4o, o1, o3. Most capable general models.",
    },
    "anthropic": {
        "name": "Anthropic (OpenAI-compatible)",
        "endpoint": "https://api.anthropic.com/v1",
        "default_model": "claude-sonnet-4-20250514",
        "capabilities": ["chat", "tools", "streaming"],
        "key_prefix": "sk-ant-",
        "api_key_env": "ANTHROPIC_API_KEY",
        # Claude 3.5/3.7/4 Sonnet & Opus all 200k. Anthropic's /v1/models
        # doesn't expose context_length; rely on the static catalog.
        "context_window": 200_000,
        "description": "Claude 4 Sonnet/Opus. Strong reasoning and coding.",
    },
    "openrouter": {
        "name": "OpenRouter",
        "endpoint": "https://openrouter.ai/api/v1",
        "default_model": "openai/gpt-4o-mini",
        "capabilities": ["chat", "tools", "streaming"],
        "key_prefix": "sk-or-",
        "api_key_env": "OPENROUTER_API_KEY",
        # OpenRouter's /api/v1/models DOES expose context_length per model
        # — live introspection wins here. Default is the GPT-4o-mini window.
        "context_window": 128_000,
        "description": "300+ models via one key.",
    },
    "together": {
        "name": "Together AI",
        "endpoint": "https://api.together.xyz/v1",
        "default_model": "meta-llama/Llama-3-70b-chat-hf",
        "capabilities": ["chat", "tools", "streaming"],
        "key_prefix": "",
        "api_key_env": "TOGETHER_API_KEY",
        "context_window": 128_000,
        "description": "Open-source model inference.",
    },
    "fireworks": {
        "name": "Fireworks AI",
        "endpoint": "https://api.fireworks.ai/inference/v1",
        "default_model": "accounts/fireworks/models/llama-v3p1-8b-instruct",
        "capabilities": ["chat", "tools", "streaming", "vision"],
        "key_prefix": "",
        "api_key_env": "FIREWORKS_API_KEY",
        "context_window": 128_000,
        "description": "OpenAI-compatible serverless inference.",
    },
    "cerebras": {
        "name": "Cerebras",
        "endpoint": "https://api.cerebras.ai/v1",
        "default_model": "gpt-oss-120b",
        "capabilities": ["chat", "streaming"],
        "key_prefix": "",
        "api_key_env": "CEREBRAS_API_KEY",
        "context_window": 32_768,
        "description": "Fast OpenAI-compatible Cerebras inference.",
    },
    "mistral": {
        "name": "Mistral AI",
        "endpoint": "https://api.mistral.ai/v1",
        "default_model": "mistral-large-latest",
        "capabilities": ["chat", "tools", "streaming"],
        "key_prefix": "",
        "api_key_env": "MISTRAL_API_KEY",
        # Mistral Large 2 = 128k.
        "context_window": 128_000,
        "description": "Mistral Large, Medium, Small.",
    },
    "ollama": {
        "name": "Ollama (Local)",
        "endpoint": "http://127.0.0.1:11434/v1",
        "default_model": "llama3.1",
        "capabilities": ["chat", "streaming"],
        "key_prefix": "",
        "api_key_env": "AUGMENT_LOCAL_API_KEY",
        "requires_key": False,
        # Ollama's /api/show returns model_info["<arch>.context_length"]
        # per loaded model — live introspection always wins. Default is
        # llama3.1's full 128k window.
        "context_window": 128_000,
        "description": "Local models. No API key needed.",
    },
    "lmstudio": {
        "name": "LM Studio (Local)",
        "endpoint": "http://127.0.0.1:1234/v1",
        "default_model": "local-model",
        "capabilities": ["chat", "streaming"],
        "key_prefix": "",
        "api_key_env": "AUGMENT_LOCAL_API_KEY",
        "requires_key": False,
        # LM Studio /v1/models returns loaded_context_length; default is
        # conservative for unknown loaded GGUFs.
        "context_window": 32_768,
        "description": "Local models via LM Studio.",
    },
    "llamacpp": {
        "name": "llama.cpp Server (Local)",
        "endpoint": "http://127.0.0.1:8051/v1",
        "default_model": "local-gguf",
        "capabilities": ["chat", "streaming"],
        "key_prefix": "",
        "api_key_env": "AUGMENT_LOCAL_API_KEY",
        "requires_key": False,
        # llama.cpp's /props returns default_generation_settings.n_ctx.
        "context_window": 32_768,
        "description": "Local GGUF models via llama-server.",
    },
    "codex": {
        "name": "ChatGPT / Codex",
        "endpoint": "",
        "default_model": "gpt-5.5 (medium)",
        "capabilities": ["chat", "vision"],
        "key_prefix": "",
        "api_key_env": "",
        "requires_key": False,
        # GPT-5 family — assumed 256k matching ChatGPT's web context.
        "context_window": 256_000,
        "description": "Use your ChatGPT Codex login (local Codex bridge, no API key).",
    },
    "custom": {
        "name": "Custom (OpenAI-compatible)",
        "endpoint": "",
        "default_model": "",
        "capabilities": ["chat", "tools", "streaming"],
        "key_prefix": "",
        "api_key_env": "AUGMENT_API_KEY",
        # Conservative — user should override per-profile.
        "context_window": 32_768,
        "description": "Any OpenAI-compatible endpoint.",
    },
}


def detect_provider_from_key(key: str) -> str:
    """Sniff the API key prefix to guess the preset (FAIL parity)."""
    value = (key or "").strip()
    if not value:
        return ""
    if value.startswith("gsk_"):
        return "groq"
    if value.startswith("sk-ant-"):
        return "anthropic"
    if value.startswith("sk-or-"):
        return "openrouter"
    if value.startswith("sk-"):
        return "openai"
    return ""


def get_preset(preset_id: str) -> Dict[str, Any]:
    return dict(PRESETS.get(preset_id, PRESETS["custom"]))


def list_presets() -> List[Dict[str, Any]]:
    return [{"id": preset_id, **values} for preset_id, values in PRESETS.items()]


def preset_is_local(preset_id: str) -> bool:
    preset = PRESETS.get(preset_id) or {}
    return preset.get("requires_key") is False
