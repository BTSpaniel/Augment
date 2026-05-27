"""Builder layer — safety policies, environment detection, snapshots, receipts.

Single-loop slice of FAIL's ``server/builder`` package. Mesh-only pieces
(routing, role contracts, approval coordinators) are intentionally omitted.
"""
from __future__ import annotations

from augment.builder.claims import claim_paths_for_tool, normalize_workspace_path
from augment.builder.edit_receipts import (
    EditReceiptDraft,
    EditReceiptTarget,
    finalize_edit_receipt,
    get_receipt,
    is_mutation_tool,
    list_receipts,
    prepare_edit_receipt,
)
from augment.builder.environment import EnvironmentSnapshot, EnvironmentTool, detect_environment
from augment.builder.file_policy import (
    FilePolicy,
    default_file_policies,
    policy_registry_payload,
    resolve_file_policy,
)
from augment.builder.patterns import PatternSnapshot, snapshot_file
from augment.builder.read_gate import check_read_before_edit, file_hash
from augment.builder.verification_profiles import (
    VerificationCheck,
    VerificationReceipt,
    profile_for_files,
    run_verification_profile,
    verification_profile_registry,
)

__all__ = [
    "EditReceiptDraft",
    "EditReceiptTarget",
    "EnvironmentSnapshot",
    "EnvironmentTool",
    "FilePolicy",
    "PatternSnapshot",
    "VerificationCheck",
    "VerificationReceipt",
    "check_read_before_edit",
    "claim_paths_for_tool",
    "default_file_policies",
    "detect_environment",
    "file_hash",
    "finalize_edit_receipt",
    "get_receipt",
    "is_mutation_tool",
    "list_receipts",
    "normalize_workspace_path",
    "policy_registry_payload",
    "prepare_edit_receipt",
    "profile_for_files",
    "resolve_file_policy",
    "run_verification_profile",
    "snapshot_file",
    "verification_profile_registry",
]
