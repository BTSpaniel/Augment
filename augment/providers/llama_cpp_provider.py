"""llama-cpp-python local provider — run GGUF models with CPU/GPU offload.

Sections: LlamaCppProvider (complete/stream/list_models/health/close),
build_llama_cpp_provider convenience constructor.

Activation: set provider.id == "llama-local" (or any id containing
"llama") in config.yaml / settings, with model_path (or env var via
model_path_env) pointing at a .gguf file.

Config extras (in config.yaml provider block):
    extras:
        model_path:     /path/to/model.gguf
        model_path_env: LOCAL_MODEL_PATH   # env var fallback
        n_ctx:          4096
        n_threads:      4
        n_gpu_layers:   0                  # number of layers to offload
        chat_format:    ""                 # llama_cpp chat_format name

Requires: pip install llama-cpp-python
If llama_cpp is not installed, health() returns ok=False with a clear
message rather than crashing at import time.
"""
from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from augment.config import ProviderConfig
from augment.providers.base import AIProvider, LLMResponse, Message, ProviderError


class LlamaCppProvider(AIProvider):
    """Local llama-cpp-python provider for GGUF models."""

    supports_streaming: bool = False

    def __init__(
        self,
        config: ProviderConfig,
        *,
        model_path: str = "",
        model_path_env: str = "",
        n_ctx: int = 4096,
        n_threads: int = 4,
        n_gpu_layers: int = 0,
        chat_format: str = "",
        verbose: bool = False,
    ) -> None:
        self.id = config.id
        self.name = config.name or "Local GGUF"
        self.model = config.model or "local-gguf"
        self._timeout = float(config.timeout_seconds or 120.0)
        self._model_path = str(model_path or "").strip()
        self._model_path_env = str(model_path_env or "").strip()
        self._n_ctx = max(512, int(n_ctx or 4096))
        self._n_threads = max(1, int(n_threads or 4))
        self._n_gpu_layers = int(n_gpu_layers or 0)
        self._chat_format = str(chat_format or "").strip()
        self._verbose = bool(verbose)
        self._lock = threading.Lock()
        self._llm: Any = None
        self._loaded_path: str = ""

    # ── Path resolution ───────────────────────────────────────────────

    def _resolve_model_path(self) -> str:
        raw = self._model_path
        if not raw and self._model_path_env:
            raw = str(os.environ.get(self._model_path_env) or "").strip()
        return os.path.expandvars(os.path.expanduser(str(raw or "").strip()))

    # ── Sync load + complete (run in thread pool) ─────────────────────

    def _load_sync(self) -> None:
        model_path = self._resolve_model_path()
        if not model_path:
            raise ProviderError(f"{self.id}: model path is not configured", retryable=False)
        if not Path(model_path).exists():
            raise ProviderError(f"{self.id}: model file not found: {model_path}", retryable=False)
        with self._lock:
            if self._llm is not None and self._loaded_path == model_path:
                return
            try:
                from llama_cpp import Llama  # type: ignore[import]
            except ImportError as exc:
                raise ProviderError(
                    f"{self.id}: llama_cpp not installed. "
                    "Run: pip install llama-cpp-python",
                    retryable=False,
                ) from exc
            kwargs: Dict[str, Any] = {
                "model_path": model_path,
                "n_ctx": self._n_ctx,
                "n_threads": self._n_threads,
                "n_gpu_layers": self._n_gpu_layers,
                "verbose": self._verbose,
            }
            if self._chat_format:
                kwargs["chat_format"] = self._chat_format
            self._llm = Llama(**kwargs)
            self._loaded_path = model_path

    def _complete_sync(
        self,
        messages: List[Message],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        self._load_sync()
        payload: Dict[str, Any] = {
            "messages": [{"role": str(m.role or "user"), "content": str(m.content or "")} for m in messages],
            "temperature": float(temperature),
        }
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        with self._lock:
            assert self._llm is not None
            response = self._llm.create_chat_completion(**payload)
        choices = response.get("choices") or []
        if not choices:
            return LLMResponse(content="", model=self.model, raw=response, finish_reason="empty")
        choice = choices[0] or {}
        msg = choice.get("message") or {}
        return LLMResponse(
            content=str(msg.get("content") or ""),
            model=str(response.get("model") or self.model),
            finish_reason=str(choice.get("finish_reason") or "stop"),
            tool_calls=list(msg.get("tool_calls") or []),
            raw=response,
        )

    # ── AIProvider interface ──────────────────────────────────────────

    async def complete(
        self,
        messages: List[Message],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._complete_sync,
                    messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError as exc:
            raise ProviderError(f"{self.id}: request timed out after {self._timeout}s", retryable=True) from exc
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"{self.id}: {exc}", retryable=False) from exc

    async def list_models(self) -> List[str]:
        model_path = self._resolve_model_path()
        names = [self.model]
        if model_path:
            stem = Path(model_path).stem
            if stem and stem not in names:
                names.append(stem)
        return names

    async def health(self) -> Dict[str, Any]:
        model_path = self._resolve_model_path()
        if not model_path:
            return {"ok": False, "models": [], "error": "model path not configured"}
        if not Path(model_path).exists():
            return {"ok": False, "models": [], "error": f"model file not found: {model_path}"}
        try:
            import llama_cpp  # noqa: F401
        except ImportError as exc:
            return {"ok": False, "models": [], "error": f"llama_cpp not installed: {exc}"}
        return {"ok": True, "models": [self.model], "error": ""}

    async def close(self) -> None:
        with self._lock:
            self._llm = None
            self._loaded_path = ""


def build_llama_cpp_provider(
    config: ProviderConfig,
    *,
    model_path: str = "",
    model_path_env: str = "",
    n_ctx: int = 4096,
    n_threads: int = 4,
    n_gpu_layers: int = 0,
    chat_format: str = "",
    verbose: bool = False,
) -> LlamaCppProvider:
    """Convenience factory — mirrors ``build_provider`` in registry.py."""
    return LlamaCppProvider(
        config,
        model_path=model_path,
        model_path_env=model_path_env,
        n_ctx=n_ctx,
        n_threads=n_threads,
        n_gpu_layers=n_gpu_layers,
        chat_format=chat_format,
        verbose=verbose,
    )
