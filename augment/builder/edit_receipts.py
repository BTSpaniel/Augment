"""Edit receipts — per-mutation diff trail with full-rewrite guard.

Single-loop slice of FAIL's ``server/builder/edit_receipts.py``. Drops the
FAIL receipt-writer dependency; instead persists each receipt as a JSON file
under ``<data_dir>/edit_receipts/<edit_receipt_id>.json`` so the chat loop
can show diffs in the artifact strip and the user can audit changes.
"""
from __future__ import annotations

import difflib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from augment.builder.claims import normalize_workspace_path
from augment.builder.patterns import snapshot_file
from augment.builder.read_gate import file_hash


_MUTATION_TOOLS = {
    "write_file",
    "edit_file",
    "delete_file",
    "apply_workspace_file",
    "apply_workspace_files",
}


@dataclass
class EditReceiptTarget:
    path: str
    existed_before: bool
    exists_after: bool = False
    before_hash: str = ""
    after_hash: str = ""
    changed_ranges: List[Dict[str, int]] = field(default_factory=list)
    changed_sections: List[str] = field(default_factory=list)
    pattern_preserved: bool = True
    full_rewrite: bool = False
    diff_preview: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EditReceiptDraft:
    edit_receipt_id: str
    tool: str
    targets: List[EditReceiptTarget]
    before_text: Dict[str, str] = field(default_factory=dict)
    before_patterns: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def is_mutation_tool(tool_name: str) -> bool:
    return tool_name in _MUTATION_TOOLS


def prepare_edit_receipt(
    tool_name: str,
    args: Dict[str, Any],
    context: Dict[str, Any],
) -> Optional[EditReceiptDraft]:
    """Snapshot every target file's hash / text / structure before a mutation runs."""
    if tool_name not in _MUTATION_TOOLS:
        return None
    targets: List[EditReceiptTarget] = []
    before_text: Dict[str, str] = {}
    before_patterns: Dict[str, Dict[str, Any]] = {}
    for path in _target_files(tool_name, args, context):
        display = _display_target(path, context)
        existed = path.exists() and path.is_file()
        target = EditReceiptTarget(path=display, existed_before=existed)
        if existed:
            try:
                target.before_hash = file_hash(path)
                text = path.read_text(encoding="utf-8", errors="replace")
                before_text[display] = text
                before_patterns[display] = snapshot_file(path, display_path=display).to_dict()
            except Exception:
                pass
        targets.append(target)
    if not targets:
        return None
    return EditReceiptDraft(
        edit_receipt_id=f"er_{uuid.uuid4().hex[:12]}",
        tool=tool_name,
        targets=targets,
        before_text=before_text,
        before_patterns=before_patterns,
    )


def finalize_edit_receipt(
    draft: Optional[EditReceiptDraft],
    tool_name: str,
    args: Dict[str, Any],
    context: Dict[str, Any],
    *,
    success: bool,
    output: str,
    error: str = "",
) -> Dict[str, Any]:
    """Capture the after-state, compute diff metrics, optionally block full rewrites."""
    if draft is None:
        return {"blocked": False, "error": "", "output_suffix": "", "receipt_id": "", "receipt": None}
    target_paths = {
        _display_target(path, context): path
        for path in _target_files(tool_name, args, context)
    }
    blocked = False
    block_error = ""
    for target in draft.targets:
        path = target_paths.get(target.path)
        if path is None:
            continue
        target.exists_after = path.exists() and path.is_file()
        if target.exists_after:
            try:
                target.after_hash = file_hash(path)
            except Exception:
                target.after_hash = ""
        if success:
            _analyze_target(target, path, draft)
            if target.full_rewrite and not _full_rewrite_allowed(context):
                _restore_target(path, target, draft)
                target.exists_after = path.exists() and path.is_file()
                target.after_hash = (
                    file_hash(path) if target.exists_after else ""
                )
                blocked = True
                block_error = f"builder_gate_full_rewrite_blocked:{target.path}"
            elif (
                not target.pattern_preserved
                and not _full_rewrite_allowed(context)
                and not _pattern_break_allowed(context)
            ):
                # FAIL-parity hard gate (mirrors fail/server/builder/edit
                # receipts pattern-preservation check): mutations that
                # disturb the file's structural pattern — re-ordered
                # imports, swapped class/section order, etc. — get rolled
                # back unless the caller passes ``allow_pattern_break`` /
                # ``refactor_mode`` in the tool context.
                _restore_target(path, target, draft)
                target.exists_after = path.exists() and path.is_file()
                target.after_hash = (
                    file_hash(path) if target.exists_after else ""
                )
                blocked = True
                block_error = f"builder_gate_pattern_disturbed:{target.path}"
    status = "blocked" if blocked else ("recorded" if success else "failed")
    receipt = _persist(draft, context, status=status, output=output, error=block_error or error)
    return {
        "blocked": blocked,
        "error": block_error,
        "output_suffix": f"\n[builder] edit_receipt={draft.edit_receipt_id}",
        "receipt_id": draft.edit_receipt_id,
        "receipt": receipt,
    }


def _analyze_target(target: EditReceiptTarget, path: Path, draft: EditReceiptDraft) -> None:
    before = draft.before_text.get(target.path, "")
    after = (
        path.read_text(encoding="utf-8", errors="replace")
        if path.exists() and path.is_file()
        else ""
    )
    target.diff_preview = _diff_preview(target.path, before, after)
    target.changed_ranges = _changed_ranges(before, after)
    after_pattern = (
        snapshot_file(path, display_path=target.path).to_dict()
        if path.exists() and path.is_file()
        else {}
    )
    before_pattern = draft.before_patterns.get(target.path, {})
    target.changed_sections = _changed_sections(target.changed_ranges, before_pattern)
    target.full_rewrite = _is_full_rewrite(before, after, before_pattern, after_pattern)
    target.pattern_preserved = not target.full_rewrite and _section_order_preserved(
        before_pattern, after_pattern
    )


def _persist(
    draft: EditReceiptDraft,
    context: Dict[str, Any],
    *,
    status: str,
    output: str,
    error: str,
) -> Dict[str, Any]:
    receipt = {
        "edit_receipt_id": draft.edit_receipt_id,
        "tool": draft.tool,
        "status": status,
        "targets": [target.to_dict() for target in draft.targets],
        "success": status == "recorded",
        "error": error,
        "output_preview": (output or "")[:800],
        "created_at": time.time(),
    }
    data_root = context.get("data_dir") or context.get("temporal_data_root")
    if data_root:
        try:
            root = Path(str(data_root)) / "edit_receipts"
            root.mkdir(parents=True, exist_ok=True)
            (root / f"{draft.edit_receipt_id}.json").write_text(
                json.dumps(receipt, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            pass
    # Mirror the receipt into the tool_context so the loop can surface it
    # in artifact events without re-reading from disk.
    log = context.setdefault("edit_receipts", [])
    if isinstance(log, list):
        log.append(receipt)
        if len(log) > 200:
            del log[: len(log) - 200]
    return receipt


def list_receipts(data_dir: str | Path, *, limit: int = 50) -> List[Dict[str, Any]]:
    root = Path(data_dir) / "edit_receipts"
    if not root.exists():
        return []
    files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: List[Dict[str, Any]] = []
    for path in files[: max(1, limit)]:
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def get_receipt(data_dir: str | Path, receipt_id: str) -> Optional[Dict[str, Any]]:
    path = Path(data_dir) / "edit_receipts" / f"{receipt_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _target_files(tool_name: str, args: Dict[str, Any], context: Dict[str, Any]) -> List[Path]:
    if tool_name == "apply_workspace_files":
        root = context.get("target_root") or context.get("workspace_root") or context.get("execution_root")
        subdir = str(args.get("target_subdir") or "").replace("\\", "/").rstrip("/")
        values = [
            f"{subdir}/{item}" if subdir else str(item)
            for item in (args.get("paths") or [])
            if item
        ]
        return [_resolve_under(root, value) for value in values if root]
    if tool_name == "apply_workspace_file":
        root = context.get("target_root") or context.get("workspace_root") or context.get("execution_root")
        value = str(args.get("target_path") or args.get("path") or "")
        return [_resolve_under(root, value)] if root and value else []
    if tool_name in {"write_file", "edit_file", "delete_file"}:
        root = context.get("workspace_root") or context.get("execution_root")
        value = str(args.get("path") or args.get("file_path") or args.get("target_file") or "")
        return [_resolve_under(root, value)] if root and value else []
    return []


def _resolve_under(root_value: Any, value: str) -> Path:
    root = Path(str(root_value)).resolve()
    normalized = normalize_workspace_path(root, value)
    path = Path(normalized)
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        # Outside the workspace; refuse by returning the workspace root, which
        # later checks will treat as "no target".
        return root
    return resolved


def _display_target(target: Path, context: Dict[str, Any]) -> str:
    for key in ("workspace_root", "target_root", "execution_root"):
        root_value = context.get(key)
        if not root_value:
            continue
        try:
            return target.relative_to(Path(str(root_value)).resolve()).as_posix()
        except Exception:
            continue
    return str(target).replace("\\", "/")


def _diff_preview(path: str, before: str, after: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"before/{path}",
        tofile=f"after/{path}",
        lineterm="",
    )
    return "\n".join(list(diff)[:240])[:12000]


def _changed_ranges(before: str, after: str) -> List[Dict[str, int]]:
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    ranges: List[Dict[str, int]] = []
    matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        ranges.append(
            {
                "before_start": i1 + 1,
                "before_end": i2,
                "after_start": j1 + 1,
                "after_end": j2,
            }
        )
    return ranges[:80]


def _changed_sections(ranges: List[Dict[str, int]], before_pattern: Dict[str, Any]) -> List[str]:
    sections = list(before_pattern.get("section_order") or [])
    if not sections or not ranges:
        return []
    if len(ranges) >= max(3, len(sections) // 2):
        return sections
    return sections[: min(len(sections), max(1, len(ranges)))]


def _is_full_rewrite(
    before: str,
    after: str,
    before_pattern: Dict[str, Any],
    after_pattern: Dict[str, Any],
) -> bool:
    if not before or not after:
        return False
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    if len(before_lines) < 20:
        return False
    similarity = difflib.SequenceMatcher(None, before, after).ratio()
    before_symbols = set(before_pattern.get("symbols") or [])
    after_symbols = set(after_pattern.get("symbols") or [])
    lost_ratio = (
        len(before_symbols - after_symbols) / len(before_symbols)
        if before_symbols
        else 0.0
    )
    churn = 1.0 - difflib.SequenceMatcher(None, before_lines, after_lines).ratio()
    return similarity < 0.45 or churn > 0.65 or lost_ratio > 0.30


def _section_order_preserved(
    before_pattern: Dict[str, Any], after_pattern: Dict[str, Any]
) -> bool:
    before = list(before_pattern.get("section_order") or [])
    after = list(after_pattern.get("section_order") or [])
    if not before or not after:
        return True
    filtered_after = [section for section in after if section in before]
    return filtered_after == before[: len(filtered_after)]


def _restore_target(path: Path, target: EditReceiptTarget, draft: EditReceiptDraft) -> None:
    before = draft.before_text.get(target.path, "")
    if target.existed_before:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(before, encoding="utf-8")
    elif path.exists() and path.is_file():
        path.unlink()


def _full_rewrite_allowed(context: Dict[str, Any]) -> bool:
    return bool(
        context.get("allow_full_rewrite")
        or context.get("refactor_mode")
        or context.get("builder_refactor_mode")
    )


def _pattern_break_allowed(context: Dict[str, Any]) -> bool:
    """Escape hatch for the pattern-preservation hard gate.

    Set ``allow_pattern_break=True`` in the tool context when the agent
    intentionally needs to re-order sections, swap imports around, or
    otherwise touch the file's structural skeleton. The default is to
    block — small, surgical edits should pass through untouched.
    """
    return bool(
        context.get("allow_pattern_break")
        or context.get("refactor_mode")
        or context.get("builder_refactor_mode")
    )
