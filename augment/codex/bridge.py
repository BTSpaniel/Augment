"""Local Codex CLI bridge for ChatGPT Codex login.

Distilled from FAIL's ``server.codex_bridge``. Augment only needs the login +
status surface — the heavy ``codex exec`` execution path lives in FAIL.

* :func:`codex_status` — locate the Codex CLI binary, probe ``--version`` and
  ``exec --help`` to confirm it is scriptable.
* :func:`codex_account_status` — call the ``openai_codex`` Python SDK's
  ``Codex.account()`` when available to confirm an authenticated session.
* :func:`start_codex_chatgpt_login` — kick off either the device-code or
  in-browser ChatGPT login flow and store the handle for later polling.
* :func:`codex_login_status` / :func:`cancel_codex_login` — peek at or abort
  the in-flight login.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


_DEFAULT_CODEX_MODELS = ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.2"]
_DEFAULT_REASONING_EFFORTS = ["low", "medium", "high", "xhigh"]
_LOGIN_LOCK = threading.Lock()
_LOGIN_STATE: Dict[str, Any] = {}


@dataclass
class CodexStatus:
    available: bool
    mode: str
    codex_bin: str
    python_sdk_available: bool
    executable_found: bool = False
    supports_exec: bool = False
    version: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "mode": self.mode,
            "codex_bin": self.codex_bin,
            "python_sdk_available": self.python_sdk_available,
            "executable_found": self.executable_found,
            "supports_exec": self.supports_exec,
            "version": self.version,
            "error": self.error,
            "setup": setup_instructions(),
        }


def setup_instructions() -> Dict[str, Any]:
    return {
        "summary": "Install or provide a scriptable local Codex CLI/app server, authenticate it once with ChatGPT, then Augment can call it from Python.",
        "python_sdk": [
            "Clone https://github.com/openai/codex",
            "From the repo root, run: python -m pip install -e sdk/python",
            "The SDK installs openai-codex-cli-bin, which includes a scriptable codex executable.",
            "If needed, set CODEX_BIN to the local codex executable path.",
        ],
        "cli_binary": [
            "Install Codex CLI by your preferred method.",
            "Run codex once and sign in with ChatGPT.",
            "Set CODEX_BIN if codex is not on PATH.",
        ],
    }


def codex_status(codex_bin: str = "") -> Dict[str, Any]:
    sdk_available = _python_sdk_available()
    resolved = _resolve_codex_bin(codex_bin)
    if not resolved:
        return CodexStatus(
            available=False,
            mode="python_sdk" if sdk_available else "missing",
            codex_bin="",
            python_sdk_available=sdk_available,
            executable_found=False,
            supports_exec=False,
            error="Codex CLI runtime not found. Install the Python SDK runtime, set CODEX_BIN to the scriptable CLI, or put codex on PATH.",
        ).to_dict()
    probe = _probe_codex_cli(resolved)
    supports_exec = bool(probe.get("supports_exec"))
    error = str(probe.get("error") or "")
    if not supports_exec and not error:
        error = "Codex executable found, but it does not appear to expose the non-interactive `codex exec` CLI."
    return CodexStatus(
        available=supports_exec,
        mode="codex_exec" if supports_exec else "codex_app",
        codex_bin=resolved,
        python_sdk_available=sdk_available,
        executable_found=True,
        supports_exec=supports_exec,
        version=str(probe.get("version") or ""),
        error=error,
    ).to_dict()


def codex_account_status() -> Dict[str, Any]:
    if not _python_sdk_available():
        return {"ok": False, "authenticated": False, "error": "openai_codex Python SDK is not installed"}
    try:
        from openai_codex import Codex  # type: ignore
        with Codex(config=_codex_app_server_config()) as codex:
            account = codex.account()
        return {"ok": True, "authenticated": True, "account": _model_to_dict(account)}
    except Exception as exc:
        return {"ok": False, "authenticated": False, "error": str(exc)}


def codex_available_models(include_hidden: bool = False) -> Dict[str, Any]:
    """Query the Codex SDK for the authenticated account's available models."""
    if not _python_sdk_available():
        return {"ok": False, "models": list(_DEFAULT_CODEX_MODELS), "error": "openai_codex Python SDK is not installed"}
    try:
        from openai_codex import Codex  # type: ignore
        with Codex(config=_codex_app_server_config()) as codex:
            response = codex.models(include_hidden=include_hidden)
        models: List[str] = []
        metadata: List[Dict[str, Any]] = []
        for item in response.data:
            raw = _model_to_dict(item) or {}
            if not isinstance(raw, dict):
                raw = {}
            model = str(
                getattr(item, "model", "")
                or getattr(item, "id", "")
                or raw.get("model", "")
                or raw.get("id", "")
                or ""
            ).strip()
            if model and model not in models:
                models.append(model)
            metadata.append({
                "id": raw.get("id", model),
                "model": model,
                "display_name": raw.get("displayName") or raw.get("display_name") or model,
                "description": raw.get("description", ""),
                "is_default": bool(raw.get("isDefault") or raw.get("is_default")),
                "hidden": bool(raw.get("hidden")),
                "default_reasoning_effort": raw.get("defaultReasoningEffort") or raw.get("default_reasoning_effort") or "",
                "supported_reasoning_efforts": raw.get("supportedReasoningEfforts") or raw.get("supported_reasoning_efforts") or [],
                "service_tiers": raw.get("serviceTiers") or raw.get("service_tiers") or [],
                "input_modalities": raw.get("inputModalities") or raw.get("input_modalities") or [],
                "supports_personality": bool(raw.get("supportsPersonality") or raw.get("supports_personality")),
            })
        return {"ok": True, "models": models or list(_DEFAULT_CODEX_MODELS), "metadata": metadata}
    except Exception as exc:
        return {"ok": False, "models": list(_DEFAULT_CODEX_MODELS), "metadata": [], "error": str(exc)}


def parse_codex_model_choice(value: str) -> Dict[str, str]:
    """Parse labels like ``gpt-5.5 (medium)`` → ``{"model": "gpt-5.5", "reasoning_effort": "medium"}``."""
    raw = str(value or "").strip()
    match = re.match(r"^(?P<model>.+?)\s*\((?P<effort>low|medium|high|xhigh)\)\s*$", raw, flags=re.IGNORECASE)
    if match:
        return {"model": match.group("model").strip(), "reasoning_effort": match.group("effort").lower()}
    return {"model": raw or _DEFAULT_CODEX_MODELS[0], "reasoning_effort": "medium"}


def codex_available_model_choices(include_hidden: bool = False) -> List[Dict[str, Any]]:
    """Expand each Codex model into ``model (effort)`` choices used by the UI dropdown."""
    payload = codex_available_models(include_hidden=include_hidden)
    metadata = payload.get("metadata") or []
    choices: List[Dict[str, Any]] = []
    if metadata:
        for item in metadata:
            model = str(item.get("model") or item.get("id") or "").strip()
            if not model:
                continue
            efforts_raw = item.get("supported_reasoning_efforts") or []
            efforts: List[str] = []
            for effort_item in efforts_raw:
                if isinstance(effort_item, dict):
                    effort = str(effort_item.get("reasoningEffort") or effort_item.get("reasoning_effort") or "").strip().lower()
                else:
                    effort = str(effort_item or "").strip().lower()
                if effort and effort not in efforts:
                    efforts.append(effort)
            if not efforts:
                efforts = [str(item.get("default_reasoning_effort") or "medium").strip().lower()]
            default_effort = str(item.get("default_reasoning_effort") or "medium").strip().lower()
            for effort in efforts:
                choices.append({
                    "label": f"{model} ({effort})",
                    "model": model,
                    "reasoning_effort": effort,
                    "display_name": item.get("display_name") or model,
                    "description": item.get("description", ""),
                    "is_default": bool(item.get("is_default") and effort == default_effort),
                    "service_tiers": item.get("service_tiers") or [],
                    "input_modalities": item.get("input_modalities") or [],
                    "supports_personality": bool(item.get("supports_personality")),
                })
    if choices:
        choices.sort(key=lambda entry: 0 if entry.get("is_default") else 1)
        return choices
    return [
        {"label": f"{model} ({effort})", "model": model, "reasoning_effort": effort}
        for model in _DEFAULT_CODEX_MODELS
        for effort in _DEFAULT_REASONING_EFFORTS
    ]


def start_codex_chatgpt_login(method: str = "device_code") -> Dict[str, Any]:
    if not _python_sdk_available():
        return {"ok": False, "error": "openai_codex Python SDK is not installed. Run `pip install -e sdk/python` from the openai/codex repo."}
    method = str(method or "device_code").strip().lower()
    if method not in {"device_code", "browser"}:
        method = "device_code"
    try:
        from openai_codex import Codex  # type: ignore
        codex = Codex(config=_codex_app_server_config())
        if method == "browser":
            handle = codex.login_chatgpt()
            payload: Dict[str, Any] = {"auth_url": getattr(handle, "auth_url", "")}
        else:
            handle = codex.login_chatgpt_device_code()
            payload = {
                "verification_url": getattr(handle, "verification_url", ""),
                "user_code": getattr(handle, "user_code", ""),
            }
        login_id = uuid.uuid4().hex[:12]
        state = {
            "ok": True,
            "login_id": login_id,
            "method": method,
            "status": "pending",
            "started_at": time.time(),
            "completed_at": 0.0,
            "error": "",
            **payload,
        }
        with _LOGIN_LOCK:
            old_codex = _LOGIN_STATE.get("_codex")
            _LOGIN_STATE.clear()
            _LOGIN_STATE.update({**state, "_codex": codex, "_handle": handle})
        try:
            if old_codex is not None:
                old_codex.close()
        except Exception:
            pass
        thread = threading.Thread(target=_wait_for_login_completion, args=(login_id,), daemon=True)
        thread.start()
        return state
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def codex_login_status() -> Dict[str, Any]:
    with _LOGIN_LOCK:
        state = {key: value for key, value in _LOGIN_STATE.items() if not key.startswith("_")}
    if not state:
        return {"ok": True, "status": "idle"}
    return state


def cancel_codex_login() -> Dict[str, Any]:
    with _LOGIN_LOCK:
        handle = _LOGIN_STATE.get("_handle")
        codex = _LOGIN_STATE.get("_codex")
    try:
        if handle is not None:
            handle.cancel()
    except Exception:
        pass
    try:
        if codex is not None:
            codex.close()
    except Exception:
        pass
    with _LOGIN_LOCK:
        _LOGIN_STATE.clear()
    return {"ok": True, "status": "cancelled"}


def _wait_for_login_completion(login_id: str) -> None:
    with _LOGIN_LOCK:
        handle = _LOGIN_STATE.get("_handle")
        codex = _LOGIN_STATE.get("_codex")
    try:
        completed = handle.wait() if handle is not None else None
        payload = _model_to_dict(completed)
        with _LOGIN_LOCK:
            if _LOGIN_STATE.get("login_id") == login_id:
                _LOGIN_STATE["status"] = "completed"
                _LOGIN_STATE["completed_at"] = time.time()
                _LOGIN_STATE["result"] = payload
    except Exception as exc:
        with _LOGIN_LOCK:
            if _LOGIN_STATE.get("login_id") == login_id:
                _LOGIN_STATE["status"] = "error"
                _LOGIN_STATE["completed_at"] = time.time()
                _LOGIN_STATE["error"] = str(exc)
    finally:
        try:
            if codex is not None:
                codex.close()
        except Exception:
            pass


def _probe_codex_cli(codex_bin: str) -> Dict[str, Any]:
    version = ""
    error = ""
    supports_exec = False
    try:
        result = subprocess.run([codex_bin, "--version"], capture_output=True, text=True, timeout=10)
        version = (result.stdout or result.stderr or "").strip()[:500]
        if result.returncode != 0:
            error = f"codex --version exited {result.returncode}"
    except Exception as exc:
        error = str(exc)
    try:
        help_result = subprocess.run([codex_bin, "exec", "--help"], capture_output=True, text=True, timeout=10)
        help_text = (help_result.stdout or help_result.stderr or "").strip().lower()
        supports_exec = help_result.returncode == 0 and any(token in help_text for token in ("codex exec", "--sandbox", "--json", "usage"))
    except Exception as exc:
        if not error:
            error = str(exc)
    return {"version": version, "supports_exec": supports_exec, "error": error}


def _model_to_dict(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json", by_alias=True)
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return dict(value.__dict__)
        except Exception:
            pass
    return str(value)


def _python_sdk_available() -> bool:
    try:
        import openai_codex  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def _codex_app_server_config() -> Any:
    from openai_codex import AppServerConfig  # type: ignore
    resolved = _resolve_codex_bin()
    return AppServerConfig(codex_bin=resolved or None)


def _resolve_codex_bin(codex_bin: str = "") -> str:
    explicit = str(codex_bin or os.environ.get("CODEX_BIN") or "").strip().strip('"')
    if explicit:
        path = Path(explicit).expanduser()
        if path.exists() and path.is_file():
            return str(path.resolve())
        if path.exists() and path.is_dir():
            found_in_dir = _find_codex_exe_in_dir(path)
            if found_in_dir:
                return found_in_dir
        found = shutil.which(explicit)
        return found or ""
    found = _find_python_codex_cli_bin()
    if found:
        return found
    found = _find_scriptable_path_codex()
    if found:
        return found
    return ""


def _find_scriptable_path_codex() -> str:
    for name in ("codex", "codex.exe"):
        found = shutil.which(name)
        if not found:
            continue
        normalized = found.replace("\\", "/").lower()
        if "/microsoft/windowsapps/" in normalized or "/program files/windowsapps/" in normalized:
            # Windows Store stub launchers are not scriptable.
            continue
        return found
    return ""


def _find_python_codex_cli_bin() -> str:
    try:
        import codex_cli_bin  # type: ignore
        root = Path(codex_cli_bin.__file__).resolve().parent
    except Exception:
        return ""
    return _find_codex_exe_in_dir(root / "bin")


def _find_codex_exe_in_dir(directory: Path) -> str:
    names = ("codex.exe", "Codex.exe", "OpenAI.Codex.exe", "codex", "Codex")
    for name in names:
        candidate = directory / name
        try:
            if candidate.exists() and candidate.is_file():
                return str(candidate.resolve())
        except Exception:
            continue
    try:
        for candidate in directory.glob("*.exe"):
            if "codex" in candidate.name.lower() and candidate.is_file():
                return str(candidate.resolve())
    except Exception:
        return ""
    return ""


def _reset_login_state_for_tests() -> None:
    """Test-only helper: drop any in-flight login handle."""
    with _LOGIN_LOCK:
        _LOGIN_STATE.clear()
