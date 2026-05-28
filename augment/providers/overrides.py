"""Provider overrides — persisted key/model per profile.

Sections: load_keys/save_key/delete_key, load_model_overrides/
save_model_override, apply_overrides_to_profiles,
load_provider_configs/save_provider_config/delete_provider_config.

Keys are stored in data/providers/key_overrides.json.
Model overrides are stored in data/providers/model_overrides.json.
Extra provider configs (dynamically added) are stored in
data/providers/providers.json.

API keys are NOT stored inside providers.json — they go to
key_overrides.json so they can be chmod-protected and isolated.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Internal write helper ─────────────────────────────────────────────

def _write_json_atomic(path: Path, data: Any) -> None:
    """Write JSON to path atomically (temp file + rename, Windows-compat)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        if path.exists():
            path.unlink()
        os.rename(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


# ── Key overrides ─────────────────────────────────────────────────────

def _key_path(data_root: Path) -> Path:
    return Path(data_root) / "providers" / "key_overrides.json"


def load_keys(data_root: Path) -> Dict[str, str]:
    """Return {profile_id: api_key} from disk."""
    p = _key_path(data_root)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        out: Dict[str, str] = {}
        for pid, spec in data.items():
            value = str(spec.get("api_key") if isinstance(spec, dict) else spec or "").strip()
            if value:
                out[str(pid)] = value
        return out
    except Exception:
        return {}


def save_key(data_root: Path, profile_id: str, value: str) -> None:
    """Persist an inline API key for *profile_id*."""
    p = _key_path(data_root)
    current: Dict[str, Any] = {}
    if p.exists():
        try:
            parsed = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                current = parsed
        except Exception:
            pass
    current[str(profile_id)] = {"api_key": str(value or "").strip()}
    _write_json_atomic(p, current)
    try:
        if os.name != "nt":
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass


def delete_key(data_root: Path, profile_id: str) -> bool:
    """Remove the stored key for *profile_id*. Returns True if anything was removed."""
    p = _key_path(data_root)
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or str(profile_id) not in data:
            return False
        del data[str(profile_id)]
        if data:
            _write_json_atomic(p, data)
        else:
            p.unlink(missing_ok=True)
        return True
    except Exception:
        return False


# ── Model overrides ───────────────────────────────────────────────────

def _model_override_path(data_root: Path) -> Path:
    return Path(data_root) / "providers" / "model_overrides.json"


def load_model_overrides(data_root: Path) -> Dict[str, Dict[str, Any]]:
    """Return {profile_id: {model: str, models: [...]}} from disk."""
    p = _model_override_path(data_root)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for pid, spec in data.items():
            if not isinstance(spec, dict):
                continue
            clean: Dict[str, Any] = {}
            model = str(spec.get("model") or "").strip()
            models = [str(m).strip() for m in (spec.get("models") or []) if str(m).strip()]
            if model:
                clean["model"] = model
            if models:
                clean["models"] = models
            if clean:
                out[str(pid)] = clean
        return out
    except Exception:
        return {}


def save_model_override(
    data_root: Path,
    profile_id: str,
    *,
    model: str = "",
    models: Optional[List[str]] = None,
) -> None:
    """Persist model + models list for *profile_id*."""
    p = _model_override_path(data_root)
    current = load_model_overrides(data_root)
    entry = dict(current.get(str(profile_id)) or {})
    if model:
        entry["model"] = str(model).strip()
    if models is not None:
        entry["models"] = [str(m).strip() for m in models if str(m).strip()]
    current[str(profile_id)] = entry
    _write_json_atomic(p, current)


# ── Dynamic provider configs ──────────────────────────────────────────

def _providers_config_path(data_root: Path) -> Path:
    return Path(data_root) / "providers" / "providers.json"


def load_provider_configs(data_root: Path) -> Dict[str, Dict[str, Any]]:
    """Load dynamically-added provider configs from disk."""
    p = _providers_config_path(data_root)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(v, dict)}
    except Exception:
        return {}


def save_provider_config(data_root: Path, profile_id: str, config: Dict[str, Any]) -> None:
    """Persist a dynamically-added provider config (api_key stored separately)."""
    p = _providers_config_path(data_root)
    current = load_provider_configs(data_root)
    safe_config = {k: v for k, v in config.items() if k != "api_key"}
    current[str(profile_id)] = safe_config
    _write_json_atomic(p, current)
    if config.get("api_key"):
        save_key(data_root, profile_id, config["api_key"])


def delete_provider_config(data_root: Path, profile_id: str) -> None:
    """Remove a provider config from disk."""
    p = _providers_config_path(data_root)
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and str(profile_id) in data:
            del data[str(profile_id)]
            if data:
                _write_json_atomic(p, data)
            else:
                p.unlink(missing_ok=True)
    except Exception:
        pass


# ── Apply overrides ───────────────────────────────────────────────────

def apply_overrides_to_profiles(
    profiles: Dict[str, Any],
    data_root: Path,
) -> Dict[str, Any]:
    """Merge key + model overrides + dynamic providers into profile dicts.

    Called at settings load time so that any persisted overrides are
    transparently layered on top of the YAML/static config without
    requiring a server restart.
    """
    out: Dict[str, Any] = {pid: dict(p or {}) for pid, p in (profiles or {}).items()}
    for pid, config in load_provider_configs(data_root).items():
        if pid not in out:
            out[pid] = config
    for pid, key in load_keys(data_root).items():
        if pid in out:
            out[pid]["api_key"] = key
    for pid, spec in load_model_overrides(data_root).items():
        if pid not in out:
            continue
        if spec.get("model"):
            out[pid]["model"] = spec["model"]
        if spec.get("models"):
            out[pid]["models"] = list(spec["models"])
    return out
