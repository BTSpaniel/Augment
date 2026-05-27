"""Read-before-edit gate — block edits to files the agent hasn't read first.

Single-loop distillation of FAIL's ``server/builder/read_gate.py``. The agent
must have emitted a ``read_provenance`` entry (file path + content hash) for a
file before any write/edit/delete tool can touch it. Snapshot of file shape is
recorded once per file to make later diffs explainable.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List

from augment.builder.claims import claim_paths_for_tool, normalize_workspace_path
from augment.builder.patterns import snapshot_file


_READ_GATED_TOOLS = {"write_file", "edit_file", "delete_file", "apply_workspace_file", "apply_workspace_files"}


def file_hash(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def check_read_before_edit(tool_name: str, args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Return an empty string if the edit is allowed, otherwise a violation code."""
    if tool_name not in _READ_GATED_TOOLS:
        return ""
    # Gate only runs when the caller has opted in by providing a read log.
    if not isinstance(context.get("read_provenance"), list):
        return ""
    targets = _target_files(tool_name, args, context)
    reads = context["read_provenance"]
    for target in targets:
        if not target.exists():
            continue
        snapshot_error = _ensure_pattern_snapshot(target, context)
        if snapshot_error:
            return snapshot_error
        receipt = _matching_read(target, reads, context)
        if not receipt:
            return f"builder_gate_no_read_receipt:{_display_target(target, context)}"
        scope_error = _check_read_scope(tool_name, args, target, receipt, context)
        if scope_error:
            return scope_error
        expected_hash = str(receipt.get("content_hash") or "")
        current_hash = file_hash(target)
        if expected_hash and expected_hash != current_hash:
            return f"builder_gate_hash_changed:{_display_target(target, context)}"
        if not expected_hash:
            return f"builder_gate_no_read_hash:{_display_target(target, context)}"
    return ""


def _ensure_pattern_snapshot(target: Path, context: Dict[str, Any]) -> str:
    try:
        keys = _target_keys(target, context)
        snapshots = context.get("pattern_snapshots")
        if isinstance(snapshots, list):
            for snapshot in snapshots:
                if not isinstance(snapshot, dict):
                    continue
                snap_path = str(snapshot.get("path") or "").replace("\\", "/").lower()
                if snap_path in keys:
                    return ""
        snapshot = snapshot_file(target, display_path=_display_target(target, context))
        snapshots = context.setdefault("pattern_snapshots", [])
        if isinstance(snapshots, list):
            snapshots.append(snapshot.to_dict())
            if len(snapshots) > 80:
                del snapshots[:-80]
        return ""
    except Exception as exc:
        return f"builder_gate_pattern_missing:{_display_target(target, context)}:{exc}"


def _target_files(tool_name: str, args: Dict[str, Any], context: Dict[str, Any]) -> List[Path]:
    if tool_name == "apply_workspace_files":
        root = context.get("target_root") or context.get("workspace_root") or context.get("execution_root")
        return [Path(path) for path in claim_paths_for_tool(tool_name, args, context)]
    if tool_name == "apply_workspace_file":
        root = context.get("target_root") or context.get("workspace_root") or context.get("execution_root")
        path = str(args.get("target_path") or args.get("path") or "")
        return [_resolve_under(root, path)] if root and path else []
    if tool_name in {"write_file", "edit_file", "delete_file"}:
        root = context.get("workspace_root") or context.get("execution_root")
        path = str(args.get("path") or args.get("file_path") or args.get("target_file") or "")
        return [_resolve_under(root, path)] if root and path else []
    return []


def _resolve_under(root_value: Any, value: str) -> Path:
    root = Path(str(root_value)).resolve()
    normalized = normalize_workspace_path(root, value)
    path = Path(normalized)
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    resolved.relative_to(root)
    return resolved


def _matching_read(target: Path, reads: List[Any], context: Dict[str, Any]) -> Dict[str, Any] | None:
    keys = _target_keys(target, context)
    for item in reversed(reads):
        if not isinstance(item, dict):
            continue
        read_path = str(item.get("path") or "")
        if read_path.replace("\\", "/").lower() in keys:
            return item
    return None


def _check_read_scope(
    tool_name: str,
    args: Dict[str, Any],
    target: Path,
    receipt: Dict[str, Any],
    context: Dict[str, Any],
) -> str:
    if tool_name != "edit_file":
        return ""
    start = int(receipt.get("start_line") or 0)
    end = int(receipt.get("end_line") or 0)
    total = int(receipt.get("total_lines") or 0)
    if not start or not end or (total and start <= 1 and end >= total):
        return ""
    old_string = str(args.get("old_string") or "")
    if not old_string:
        return ""
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if old_string not in text:
        return ""
    before = text.split(old_string, 1)[0]
    edit_start = before.count("\n") + 1
    edit_end = edit_start + old_string.count("\n")
    if edit_start < start or edit_end > end:
        return (
            f"builder_gate_read_scope_mismatch:{_display_target(target, context)}:"
            f"{edit_start}-{edit_end}:read={start}-{end}"
        )
    return ""


def _target_keys(target: Path, context: Dict[str, Any]) -> List[str]:
    keys = {str(target).replace("\\", "/").lower()}
    for root_key in ("workspace_root", "target_root", "execution_root"):
        root_value = context.get(root_key)
        if not root_value:
            continue
        try:
            root = Path(str(root_value)).resolve()
            keys.add(target.relative_to(root).as_posix().lower())
        except Exception:
            continue
    return sorted(keys)


def _display_target(target: Path, context: Dict[str, Any]) -> str:
    for root_key in ("workspace_root", "target_root", "execution_root"):
        root_value = context.get(root_key)
        if not root_value:
            continue
        try:
            return target.relative_to(Path(str(root_value)).resolve()).as_posix()
        except Exception:
            continue
    return str(target)
