from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8787


@dataclass(frozen=True)
class ProviderConfig:
    id: str = "default"
    name: str = "OpenAI Compatible"
    endpoint: str = "https://api.groq.com/openai/v1"
    api_key_env: str = "AUGMENT_API_KEY"
    api_key: str = ""
    model: str = "llama-3.1-8b-instant"
    timeout_seconds: float = 120.0
    # 0 means "auto-resolve via augment.providers.context_window". When the
    # user pins an explicit value here (or in the YAML), the resolver
    # treats it as the highest-precedence override.
    context_window: int = 0
    # Path to a local GGUF model file. Only used by LlamaCppProvider (the
    # embedded llama-cpp-python library, not the llama.cpp HTTP server).
    model_path: str = ""

    @property
    def resolved_api_key(self) -> str:
        return self.api_key or os.getenv(self.api_key_env, "")


@dataclass(frozen=True)
class LoopConfig:
    max_iterations: int = 10
    temperature: float = 0.2


@dataclass(frozen=True)
class ContextConfig:
    """Context-budget knobs.

    All fields are token-denominated except ``total_budget_chars`` which is
    a legacy hard cap retained for backward compatibility — it acts as a
    safety belt the assembled prompt cannot exceed even if the model's
    context window would in principle allow it. Set it to ``0`` to disable.

    The defaults sit in the empirically-validated **sweet spot**:

    * ``target_utilization = 0.50`` → assembled prompt sits at half the
      effective input budget, well below the ~60-70% ceiling where every
      frontier model's recall starts to rot (Chroma 2025).
    * ``buffer_pct = 9`` → 9% of the budget is reserved + never written
      to. Catches mid-loop tool-result expansion + tokenizer drift.
    * ``warn_threshold = 0.75`` → UI flips to orange when the assembled
      prompt exceeds 75% of the effective budget.
    * ``compact_threshold = 0.80`` → triggers dumb-zone compaction when
      headroom shrinks past 80%.
    """

    # Legacy hard cap (chars). Kept so existing tests + configs work; new
    # logic computes its budget in tokens off the model's context window.
    total_budget_chars: int = 24000
    # Tokens reserved for completion. Subtracted from the model context
    # window before allocation. 0 disables the reservation (use the full
    # window for input). Default mirrors Luna.
    max_output_tokens: int = 4096
    # Target fraction of the *effective* (window − max_output) budget to
    # actually fill. 0.50 keeps us in the U-shape sweet spot.
    target_utilization: float = 0.50
    # Buffer / safety headroom percentage (never allocated to any
    # section). Mirrors Luna's 9% buffer slot.
    buffer_pct: float = 9.0
    # UI / diagnostic thresholds (fractions of effective budget).
    warn_threshold: float = 0.75
    compact_threshold: float = 0.80
    # Per-section percentage overrides — keys map to entries in
    # augment.context.budget.DEFAULT_SLOTS. Empty dict = use defaults.
    budget_allocations: dict = field(default_factory=dict)
    # Zone overrides: {smart_top: [...], dumb_middle: [...], smart_bottom: [...]}
    # Empty dict = use augment.context.zones.DEFAULT_ZONE_MEMBERSHIP.
    zones: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AppConfig:
    server: ServerConfig
    provider: ProviderConfig
    loop: LoopConfig
    context: ContextConfig
    workspace_root: Path
    data_dir: Path
    scratch_root: Path
    discover_sources: tuple[Path, ...] = ()
    full_access: bool = False  # When True the agent may read/write any absolute path


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path) if path else ROOT / "config.yaml"
    raw: dict[str, Any] = {}
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    elif (ROOT / "config.example.yaml").exists():
        raw = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8")) or {}

    server = dict(raw.get("server") or {})
    provider = dict(raw.get("provider") or {})
    loop = dict(raw.get("loop") or {})
    context = dict(raw.get("context") or {})

    workspace_root = _resolve_path(os.getenv("AUGMENT_WORKSPACE_ROOT") or raw.get("workspace_root") or ".")
    data_dir = _resolve_path(os.getenv("AUGMENT_DATA_DIR") or raw.get("data_dir") or "data")
    scratch_root_raw = os.getenv("AUGMENT_SCRATCH_ROOT") or raw.get("scratch_root") or ""
    scratch_root = _resolve_path(scratch_root_raw) if scratch_root_raw else (workspace_root / "temp")
    _fa_env = os.getenv("AUGMENT_FULL_ACCESS", "")
    full_access = bool(raw.get("full_access")) if not _fa_env else _fa_env.lower() not in {"0", "false", "no", ""}

    discover_raw: list[str] = []
    raw_sources = raw.get("discover_sources")
    if isinstance(raw_sources, list):
        discover_raw.extend(str(item) for item in raw_sources if str(item).strip())
    env_sources = os.environ.get("AUGMENT_DISCOVER_SOURCES")
    explicit_env_choice = env_sources is not None
    if env_sources:
        discover_raw.extend(part.strip() for part in env_sources.replace(";", os.pathsep).split(os.pathsep) if part.strip())
    if not discover_raw and not explicit_env_choice:
        # Default: pick up FAIL's data dir if it sits next to this repo.
        candidate = (ROOT.parent / "fail" / "data").resolve()
        if candidate.exists():
            discover_raw.append(str(candidate))
    discover_sources = tuple(_resolve_path(item) for item in discover_raw)

    return AppConfig(
        server=ServerConfig(
            host=str(server.get("host") or os.getenv("AUGMENT_HOST") or "127.0.0.1"),
            port=int(server.get("port") or os.getenv("AUGMENT_PORT") or 8787),
        ),
        provider=ProviderConfig(
            id=str(provider.get("id") or "default"),
            name=str(provider.get("name") or "OpenAI Compatible"),
            endpoint=str(provider.get("endpoint") or os.getenv("AUGMENT_ENDPOINT") or "https://api.groq.com/openai/v1"),
            api_key_env=str(provider.get("api_key_env") or "AUGMENT_API_KEY"),
            api_key=str(provider.get("api_key") or ""),
            model=str(provider.get("model") or os.getenv("AUGMENT_MODEL") or "llama-3.1-8b-instant"),
            timeout_seconds=float(provider.get("timeout_seconds") or 120.0),
            context_window=int(provider.get("context_window") or 0),
        ),
        loop=LoopConfig(
            max_iterations=int(loop.get("max_iterations") or 10),
            temperature=float(loop.get("temperature") or 0.2),
        ),
        context=ContextConfig(
            total_budget_chars=int(context.get("total_budget_chars") or 24000),
            max_output_tokens=int(context.get("max_output_tokens") or 4096),
            target_utilization=float(context.get("target_utilization") or 0.50),
            buffer_pct=float(context.get("buffer_pct") or 9.0),
            warn_threshold=float(context.get("warn_threshold") or 0.75),
            compact_threshold=float(context.get("compact_threshold") or 0.80),
            budget_allocations=dict(context.get("budget_allocations") or {}),
            zones=dict(context.get("zones") or {}),
        ),
        workspace_root=workspace_root,
        data_dir=data_dir,
        scratch_root=scratch_root,
        discover_sources=discover_sources,
        full_access=full_access,
    )


def _resolve_path(value: Any) -> Path:
    path = Path(str(value or ".")).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()
