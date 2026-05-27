"""File claims — track which paths a tool is about to read/write.

Single-loop slice of FAIL's ``server/builder/claims.py``. Augment has only one
running loop so we don't need owner/lock semantics; we keep just the *path
normalisation* + ``claim_paths_for_tool`` helper so the read-gate can resolve
which files an edit tool intends to touch.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def claim_paths_for_tool(tool_name: str, args: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    """Return the workspace-relative path keys a tool is about to touch."""
    workspace_root = context.get("workspace_root") or context.get("execution_root")
    target_root = context.get("target_root") or workspace_root
    if tool_name in {"write_file", "edit_file", "delete_file"}:
        values = [str(args.get("path") or args.get("file_path") or args.get("target_file") or "")]
        return _normalised_claim_paths(values, workspace_root)
    if tool_name == "apply_workspace_file":
        values = [str(args.get("target_path") or args.get("path") or "")]
        return _normalised_claim_paths(values, target_root)
    if tool_name == "apply_workspace_files":
        subdir = str(args.get("target_subdir") or "").replace("\\", "/").rstrip("/")
        values = [
            f"{subdir}/{item}" if subdir else str(item)
            for item in (args.get("paths") or [])
            if item
        ]
        return _normalised_claim_paths(values, target_root)
    return []


def normalize_workspace_path(root: Path, value: str) -> str:
    raw = str(value or ".").strip()
    if not raw:
        return "."
    path = Path(raw).expanduser()
    if path.is_absolute():
        return raw
    normalized = raw.replace("\\", "/").lstrip("/")
    lowered = normalized.lower()
    if lowered.startswith("workspace/"):
        return normalized[len("workspace/"):] or "."
    return raw


def _normalised_claim_paths(paths: List[str], root_value: Any) -> List[str]:
    if not root_value:
        return []
    try:
        root = Path(str(root_value)).resolve()
    except Exception:
        return []
    keys: List[str] = []
    for value in paths:
        if not value:
            continue
        try:
            path = Path(normalize_workspace_path(root, str(value)))
            resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
            resolved.relative_to(root)
            keys.append(str(resolved).replace("\\", "/").lower())
        except Exception:
            continue
    return keys
