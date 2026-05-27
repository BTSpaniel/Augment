"""Multi-profile provider settings store — distilled from FAIL.

Single source of truth for provider profiles + their API keys + their loaded
model lists. Augment runs one ReAct loop at a time but can hold several
configured providers (Groq, OpenAI, Ollama, …) and switch the default the same
way FAIL does.

Persistence: ``data/settings.json``::

    {
      "profiles": {"groq": {...}, "lmstudio": {...}},
      "default_id": "groq",
      "updated_at": 1700000000.0
    }

Back-compat: an older single-provider file (``{"provider": {...}}``) is
migrated into one profile transparently.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from augment.config import AppConfig, ProviderConfig
from augment.providers.presets import (
    PRESETS,
    detect_provider_from_key,
    get_preset,
    list_presets,
    preset_is_local,
)


PROFILE_FIELDS = (
    "id",
    "name",
    "endpoint",
    "api_key_env",
    "api_key",
    "model",
    "timeout_seconds",
    "preset_id",
    # Optional explicit context-window override. ``0`` means "auto-resolve
    # via augment.providers.context_window" (preset → introspection →
    # static catalog → fallback).
    "context_window",
)


class SettingsStore:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        config.data_dir.mkdir(parents=True, exist_ok=True)
        self._path = config.data_dir / "settings.json"
        # Cache: (preset_id, model) → resolved context window in tokens.
        # Cleared whenever any profile is mutated so introspection re-runs
        # after a user changes provider/model.
        self._context_window_cache: dict[tuple[str, str], int] = {}

    # ── Persistence ─────────────────────────────────────────────────
    def _seed_state(self) -> dict[str, Any]:
        # Start with zero providers; users add them via the UI / API.
        return {"profiles": {}, "default_id": "", "removed_presets": [], "updated_at": 0.0}

    def _read_state(self) -> dict[str, Any]:
        if not self._path.exists():
            return self._seed_state()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return self._seed_state()
        if not isinstance(data, dict):
            return self._seed_state()
        if "profiles" in data:
            profiles = {}
            for pid, raw in (data.get("profiles") or {}).items():
                if not isinstance(raw, dict):
                    continue
                profile = self._normalise_profile(raw, preset_id=str(raw.get("preset_id") or pid))
                profile["id"] = str(pid)
                profile.setdefault("models", list(raw.get("models") or []))
                profiles[profile["id"]] = profile
            default_id = str(data.get("default_id") or next(iter(profiles), ""))
            if profiles and default_id not in profiles:
                default_id = next(iter(profiles))
            return {
                "profiles": profiles,
                "default_id": default_id if profiles else "",
                "removed_presets": [str(item) for item in (data.get("removed_presets") or []) if str(item).strip()],
                "updated_at": float(data.get("updated_at") or 0.0),
            }
        # Legacy single-provider migration.
        legacy = data.get("provider") or {}
        models = list(data.get("models") or [])
        merged = self._normalise_profile(legacy, preset_id=str(legacy.get("id") or "default"))
        merged["models"] = models
        return {"profiles": {merged["id"]: merged}, "default_id": merged["id"], "updated_at": float(data.get("updated_at") or 0.0)}

    def _write_state(self, state: dict[str, Any]) -> None:
        state = dict(state)
        state["updated_at"] = time.time()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Any persisted change can affect which preset/model is active —
        # invalidate the resolved-context-window cache so the next chat
        # build picks up the new value.
        self._context_window_cache.clear()
        self._path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

    # ── Profile normalisation ───────────────────────────────────────
    def _normalise_profile(self, values: dict[str, Any], *, preset_id: str = "") -> dict[str, Any]:
        preset_id = (preset_id or values.get("preset_id") or values.get("id") or "").strip().lower()
        preset = get_preset(preset_id) if preset_id in PRESETS else {}
        defaults = asdict(self._config.provider)
        merged = {
            "id": str(values.get("id") or preset_id or defaults["id"]),
            "preset_id": preset_id,
            "name": str(values.get("name") or preset.get("name") or defaults["name"]),
            "endpoint": str(values.get("endpoint") or preset.get("endpoint") or defaults["endpoint"]),
            "api_key_env": str(values.get("api_key_env") or preset.get("api_key_env") or defaults["api_key_env"]),
            "api_key": str(values.get("api_key") or ""),
            "model": str(values.get("model") or preset.get("default_model") or defaults["model"]),
            "timeout_seconds": float(values.get("timeout_seconds") or defaults["timeout_seconds"]),
            "models": list(values.get("models") or []),
            "source": str(values.get("source") or ""),
            # User override > preset default > 0 (= auto-resolve at lookup).
            "context_window": int(
                values.get("context_window")
                or preset.get("context_window")
                or 0
            ),
        }
        # Codex is a virtual provider routed through the local bridge — it has
        # no API endpoint and no API-key env var, so drop any defaults that
        # leaked through from the legacy single-provider config.
        if preset_id == "codex":
            merged["endpoint"] = ""
            merged["api_key_env"] = ""
        return merged

    # ── Profile listing ─────────────────────────────────────────────
    def list_profiles(self) -> list[dict[str, Any]]:
        state = self._read_state()
        return [self._public_profile(state, profile) for profile in state["profiles"].values()]

    def default_profile_id(self) -> str:
        return self._read_state()["default_id"]

    def default_profile(self) -> dict[str, Any]:
        state = self._read_state()
        pid = state["default_id"]
        return self._public_profile(state, state["profiles"].get(pid, {}))

    def has_default_profile(self) -> bool:
        state = self._read_state()
        return bool(state["default_id"] and state["profiles"].get(state["default_id"]))

    def provider_config(self, profile_id: str | None = None) -> ProviderConfig:
        state = self._read_state()
        pid = profile_id or state["default_id"]
        raw = state["profiles"].get(pid) if pid else None
        if not raw:
            # Empty store fallback so callers (registry, health probes) don't
            # crash before the user has configured a provider.
            return ProviderConfig(
                id="",
                name="",
                endpoint="",
                api_key_env="",
                api_key="",
                model="",
                timeout_seconds=float(self._config.provider.timeout_seconds),
            )
        return ProviderConfig(
            id=str(raw.get("id") or pid),
            name=str(raw.get("name") or pid),
            endpoint=str(raw.get("endpoint") or ""),
            api_key_env=str(raw.get("api_key_env") or ""),
            api_key=str(raw.get("api_key") or ""),
            model=str(raw.get("model") or ""),
            timeout_seconds=float(raw.get("timeout_seconds") or 120.0),
            context_window=int(raw.get("context_window") or 0),
        )

    def presets_catalog(self) -> list[dict[str, Any]]:
        return list_presets()

    def active_context_window(self, *, allow_introspection: bool = True) -> int:
        """Resolve the active profile's context window in tokens.

        Three-tier resolution (see :mod:`augment.providers.context_window`):

        1. Explicit ``profile["context_window"]`` override.
        2. Live introspection (OpenRouter / Groq / Ollama / LM Studio /
           llama.cpp / Mistral / Together / Fireworks).
        3. Static catalog by model id (OpenAI / Anthropic / Cerebras).

        Falls back to :data:`augment.providers.context_window.DEFAULT_FALLBACK`
        (32_768 tokens) when every tier misses or no profile is configured.

        Results are cached per ``(preset_id, model)`` for the process
        lifetime so the introspection HTTP calls don't re-fire on every
        chat turn. The cache is cleared whenever profiles are mutated.
        """
        from augment.providers.context_window import (  # local import to avoid cycle
            DEFAULT_FALLBACK,
            resolve_context_window,
        )

        state = self._read_state()
        pid = state.get("default_id")
        profile = state["profiles"].get(pid) if pid else None
        if not profile:
            return DEFAULT_FALLBACK

        cache_key = (
            str(profile.get("preset_id") or profile.get("id") or ""),
            str(profile.get("model") or ""),
        )
        cached = self._context_window_cache.get(cache_key)
        if cached:
            return cached

        resolved = resolve_context_window(profile, allow_introspection=allow_introspection)
        self._context_window_cache[cache_key] = int(resolved)
        return resolved

    # ── Auto-discovery (env vars + FAIL key_overrides.json) ─────────
    def discover_providers(self, sources: Iterable[Path] | None = None) -> dict[str, Any]:
        """Detect providers from env vars and external sources (e.g. FAIL data dir).

        - Adds a profile for every preset whose ``api_key_env`` is populated in
          ``os.environ`` and that isn't already configured / tombstoned.
        - For each source path, reads ``providers/key_overrides.json`` (and
          optionally ``providers/providers.json`` for endpoint/model hints) and
          adopts saved keys.
        - Skips anything the user has explicitly removed.
        """
        state = self._read_state()
        removed = set(state.get("removed_presets") or [])
        existing_presets = {str(profile.get("preset_id") or "").lower() for profile in state["profiles"].values()}
        added: list[dict[str, str]] = []

        # 1) Environment variables.
        for preset_id, preset in PRESETS.items():
            if preset_id == "custom":
                continue
            env_name = str(preset.get("api_key_env") or "").strip()
            if not env_name:
                continue
            value = (os.environ.get(env_name) or "").strip()
            if not value:
                continue
            if preset_id in existing_presets or preset_id in removed:
                continue
            self._add_discovered_profile(state, preset_id=preset_id, api_key="", source=f"env:{env_name}")
            existing_presets.add(preset_id)
            added.append({"preset_id": preset_id, "source": f"env:{env_name}"})

        # 2) External sources (FAIL data dir layout).
        for src in sources or []:
            try:
                src_path = Path(src)
            except TypeError:
                continue
            if not src_path.exists():
                continue
            key_file = src_path / "providers" / "key_overrides.json"
            providers_file = src_path / "providers" / "providers.json"
            external_keys: dict[str, str] = {}
            external_providers: dict[str, dict[str, Any]] = {}
            if key_file.exists():
                try:
                    parsed = json.loads(key_file.read_text(encoding="utf-8"))
                    for pid, spec in (parsed or {}).items():
                        if isinstance(spec, dict):
                            key_value = str(spec.get("api_key") or "").strip()
                        else:
                            key_value = str(spec or "").strip()
                        if key_value:
                            external_keys[str(pid).lower()] = key_value
                except Exception:
                    pass
            if providers_file.exists():
                try:
                    parsed_providers = json.loads(providers_file.read_text(encoding="utf-8"))
                    if isinstance(parsed_providers, dict):
                        external_providers = {str(k).lower(): v for k, v in parsed_providers.items() if isinstance(v, dict)}
                except Exception:
                    pass
            for raw_id, api_key in external_keys.items():
                preset_id = raw_id if raw_id in PRESETS else (detect_provider_from_key(api_key) or "custom")
                if preset_id == "custom" and raw_id not in PRESETS:
                    continue  # unknown preset, skip to avoid garbage cards
                if preset_id in existing_presets or preset_id in removed:
                    continue
                extra = external_providers.get(raw_id) or external_providers.get(preset_id) or {}
                self._add_discovered_profile(
                    state,
                    preset_id=preset_id,
                    api_key=api_key,
                    source=str(key_file),
                    endpoint=str(extra.get("endpoint") or ""),
                    model=str(extra.get("model") or ""),
                    name=str(extra.get("display_name") or ""),
                )
                existing_presets.add(preset_id)
                added.append({"preset_id": preset_id, "source": str(key_file)})

        # 3) Codex bridge — if the user is authenticated with ChatGPT/Codex,
        #    register a `codex` profile so it shows up in the Sessions
        #    provider dropdown without manual setup.
        if "codex" in PRESETS and "codex" not in existing_presets and "codex" not in removed:
            if self._codex_authenticated():
                self._add_discovered_profile(state, preset_id="codex", api_key="", source="codex_bridge")
                existing_presets.add("codex")
                added.append({"preset_id": "codex", "source": "codex_bridge"})

        if state["profiles"] and not state.get("default_id"):
            state["default_id"] = next(iter(state["profiles"]))

        if added:
            self._write_state(state)
        return {"added": added, "count": len(added)}

    @staticmethod
    def _codex_authenticated() -> bool:
        try:
            from augment.codex.bridge import codex_account_status
            return bool((codex_account_status() or {}).get("authenticated"))
        except Exception:
            return False

    def restore_preset(self, preset_id: str) -> bool:
        """Forget a tombstone so the next discovery can re-add the preset."""
        state = self._read_state()
        tombstones = set(state.get("removed_presets") or [])
        if preset_id.lower() not in tombstones:
            return False
        tombstones.discard(preset_id.lower())
        state["removed_presets"] = sorted(tombstones)
        self._write_state(state)
        return True

    def _add_discovered_profile(
        self,
        state: dict[str, Any],
        *,
        preset_id: str,
        api_key: str = "",
        source: str = "",
        endpoint: str = "",
        model: str = "",
        name: str = "",
    ) -> dict[str, Any]:
        values = {
            "preset_id": preset_id,
            "api_key": api_key,
            "endpoint": endpoint,
            "model": model,
            "name": name,
        }
        profile = self._normalise_profile(values, preset_id=preset_id)
        profile["id"] = self._unique_id(state["profiles"], preset_id)
        if source:
            profile["source"] = source
        state["profiles"][profile["id"]] = profile
        if not state.get("default_id"):
            state["default_id"] = profile["id"]
        return profile

    # ── Mutations ───────────────────────────────────────────────────
    def add_profile(self, values: dict[str, Any], *, make_default: bool = True) -> dict[str, Any]:
        state = self._read_state()
        preset_id = str(values.get("preset") or values.get("preset_id") or "").strip().lower()
        api_key = str(values.get("api_key") or "").strip()
        if not preset_id and api_key:
            preset_id = detect_provider_from_key(api_key)
        if preset_id not in PRESETS:
            preset_id = "custom"
        profile = self._normalise_profile({**values, "preset_id": preset_id, "id": preset_id, "api_key": api_key}, preset_id=preset_id)
        profile_id = self._unique_id(state["profiles"], preset_id)
        profile["id"] = profile_id
        state["profiles"][profile_id] = profile
        if make_default or not state.get("default_id"):
            state["default_id"] = profile_id
        self._write_state(state)
        return {"profile": self._public_profile(state, profile), "detected_preset": preset_id}

    def remove_profile(self, profile_id: str) -> bool:
        state = self._read_state()
        if profile_id not in state["profiles"]:
            return False
        removed_profile = state["profiles"].pop(profile_id)
        preset_id = str(removed_profile.get("preset_id") or "").lower()
        if preset_id and preset_id != "custom":
            tombstones = set(state.get("removed_presets") or [])
            tombstones.add(preset_id)
            state["removed_presets"] = sorted(tombstones)
        if state["default_id"] == profile_id:
            state["default_id"] = next(iter(state["profiles"]), "")
        self._write_state(state)
        return True

    def set_default(self, profile_id: str) -> bool:
        state = self._read_state()
        if profile_id not in state["profiles"]:
            return False
        state["default_id"] = profile_id
        self._write_state(state)
        return True

    def set_profile_key(self, profile_id: str, api_key: str) -> dict[str, Any]:
        state = self._read_state()
        profile = state["profiles"].get(profile_id)
        if not profile:
            return {}
        profile["api_key"] = str(api_key or "").strip()
        self._write_state(state)
        return self._public_profile(state, profile)

    def set_profile_model(self, profile_id: str, model: str) -> dict[str, Any]:
        state = self._read_state()
        profile = state["profiles"].get(profile_id)
        if not profile:
            return {}
        if model:
            profile["model"] = str(model).strip()
        self._write_state(state)
        return self._public_profile(state, profile)

    def save_profile_models(self, profile_id: str, models: Iterable[str]) -> dict[str, Any]:
        state = self._read_state()
        profile = state["profiles"].get(profile_id)
        if not profile:
            return {}
        unique = list(dict.fromkeys(str(m).strip() for m in models if str(m or "").strip()))
        profile["models"] = unique
        if not profile.get("model") and unique:
            profile["model"] = unique[0]
        self._write_state(state)
        return self._public_profile(state, profile)

    # FAIL-style "update default profile" — used by the back-compat
    # ``PUT /api/providers`` endpoint. With no profiles configured this
    # behaves like ``add_profile`` so the caller can bootstrap from scratch.
    def update_default(self, values: dict[str, Any]) -> dict[str, Any]:
        state = self._read_state()
        preset_id = str(values.get("preset") or values.get("preset_id") or "").strip().lower()
        api_key = str(values.get("api_key") or "").strip()
        if not preset_id and api_key:
            preset_id = detect_provider_from_key(api_key)

        if not state["profiles"]:
            outcome = self.add_profile({**values, "preset": preset_id or "custom", "api_key": api_key}, make_default=True)
            return {
                "provider": outcome["profile"],
                "detected_preset": outcome.get("detected_preset", preset_id),
                "default_id": outcome["profile"]["id"],
            }

        if preset_id and preset_id in PRESETS:
            target_id = self._find_profile_by_preset(state, preset_id) or self._unique_id(state["profiles"], preset_id)
            if target_id not in state["profiles"]:
                state["profiles"][target_id] = self._normalise_profile({"id": target_id, "preset_id": preset_id}, preset_id=preset_id)
            profile = state["profiles"][target_id]
            preset = get_preset(preset_id)
            profile["preset_id"] = preset_id
            profile["name"] = profile.get("name") or preset.get("name") or preset_id
            profile["endpoint"] = profile.get("endpoint") or preset.get("endpoint") or ""
            profile["api_key_env"] = preset.get("api_key_env") or profile.get("api_key_env") or ""
            if preset.get("default_model") and not (values.get("model") or "").strip():
                profile.setdefault("model", preset["default_model"])
            state["default_id"] = target_id
        else:
            target_id = state["default_id"]
            profile = state["profiles"][target_id]
        for key in PROFILE_FIELDS:
            if key in values and values[key] not in (None, ""):
                profile[key] = values[key]
        if api_key:
            profile["api_key"] = api_key
        self._write_state(state)
        return {
            "provider": self._public_profile(state, profile),
            "detected_preset": preset_id or "",
            "default_id": target_id,
        }

    # ── Snapshots (UI) ──────────────────────────────────────────────
    def _public_profile(self, state: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        if not profile:
            return {}
        preset_id = str(profile.get("preset_id") or profile.get("id") or "").lower()
        api_key_env = str(profile.get("api_key_env") or "")
        env_key = bool(self.provider_config(profile.get("id")).resolved_api_key) if profile.get("id") in state["profiles"] else False
        preset = PRESETS.get(preset_id, {})
        capabilities = list(preset.get("capabilities") or [])
        return {
            "id": str(profile.get("id") or preset_id),
            "preset_id": preset_id,
            "name": str(profile.get("name") or ""),
            "endpoint": str(profile.get("endpoint") or ""),
            "api_key_env": api_key_env,
            "model": str(profile.get("model") or ""),
            "models": list(profile.get("models") or []),
            "timeout_seconds": float(profile.get("timeout_seconds") or 120.0),
            "has_inline_key": bool(profile.get("api_key")),
            "has_env_key": env_key,
            "key_required": self._key_required(profile),
            "is_default": state.get("default_id") == profile.get("id"),
            "source": str(profile.get("source") or ""),
            "capabilities": capabilities,
            "vision": "vision" in capabilities,
            "presets": sorted(PRESETS),
        }

    def public_snapshot(self) -> dict[str, Any]:
        state = self._read_state()
        default = state["profiles"].get(state["default_id"], {})
        return {
            "profiles": [self._public_profile(state, profile) for profile in state["profiles"].values()],
            "default_id": state["default_id"],
            "provider": self._public_profile(state, default),
            "models": list(default.get("models") or []),
            "removed_presets": list(state.get("removed_presets") or []),
            "updated_at": state.get("updated_at") or 0.0,
        }

    # ── Helpers ─────────────────────────────────────────────────────
    def _unique_id(self, profiles: dict[str, Any], preset_id: str) -> str:
        base = preset_id or "profile"
        if base not in profiles:
            return base
        counter = 2
        while f"{base}_{counter}" in profiles:
            counter += 1
        return f"{base}_{counter}"

    def _find_profile_by_preset(self, state: dict[str, Any], preset_id: str) -> str:
        for pid, profile in state["profiles"].items():
            if str(profile.get("preset_id") or "").lower() == preset_id:
                return pid
        return ""

    def _key_required(self, profile: dict[str, Any]) -> bool:
        preset_id = str(profile.get("preset_id") or profile.get("id") or "").lower()
        if preset_id in PRESETS:
            return not preset_is_local(preset_id)
        endpoint = str(profile.get("endpoint") or "").lower()
        return not (endpoint.startswith("http://127.0.0.1") or endpoint.startswith("http://localhost"))
