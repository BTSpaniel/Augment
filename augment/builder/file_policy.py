"""File policies — risk + sensitivity tagging for write/edit tools.

Ported from FAIL's ``server/builder/file_policy.py``. Used to flag risky
writes (secrets, dependency manifests) and required verifications.
"""
from __future__ import annotations

import fnmatch
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class FilePolicy:
    pattern: str
    file_type: str
    risk: str = "medium"
    allowed_writers: List[str] = field(default_factory=list)
    required_reviewers: List[str] = field(default_factory=list)
    required_verification: List[str] = field(default_factory=list)
    verification_profile: str = "default"
    approval_required: bool = False
    sensitive: bool = False
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_DEFAULT_POLICIES: List[FilePolicy] = [
    FilePolicy("**/.env*", "secrets.env", "critical", ["approval_coordinator"], ["security_reviewer"], [], "default", True, True, "environment secrets"),
    FilePolicy("**/*secret*", "secrets.generic", "critical", ["approval_coordinator"], ["security_reviewer"], [], "default", True, True, "secret path"),
    FilePolicy("**/*credential*", "secrets.generic", "critical", ["approval_coordinator"], ["security_reviewer"], [], "default", True, True, "credential path"),
    FilePolicy("**/*token*", "secrets.generic", "critical", ["approval_coordinator"], ["security_reviewer"], [], "default", True, True, "token path"),
    FilePolicy("**/package.json", "dependency.manifest", "high", ["dependency_writer"], ["dependency_reviewer"], ["json_parse"], "config.json", True, False, "dependency manifest"),
    FilePolicy("**/package-lock.json", "dependency.lockfile", "high", ["dependency_writer"], ["dependency_reviewer"], ["json_parse"], "config.json", True, False, "dependency lockfile"),
    FilePolicy("**/pnpm-lock.yaml", "dependency.lockfile", "high", ["dependency_writer"], ["dependency_reviewer"], [], "default", True, False, "dependency lockfile"),
    FilePolicy("**/yarn.lock", "dependency.lockfile", "high", ["dependency_writer"], ["dependency_reviewer"], [], "default", True, False, "dependency lockfile"),
    FilePolicy("**/requirements*.txt", "dependency.manifest", "high", ["dependency_writer"], ["dependency_reviewer"], [], "default", True, False, "Python dependency manifest"),
    FilePolicy("**/*.py", "backend.python", "medium", ["backend_writer"], ["backend_reviewer"], ["py_compile"], "backend.python", False, False, "Python source"),
    FilePolicy("**/*.js", "frontend.javascript", "medium", ["frontend_writer"], ["frontend_reviewer"], ["node_syntax"], "frontend.javascript", False, False, "JavaScript source"),
    FilePolicy("**/*.ts", "frontend.typescript", "medium", ["frontend_writer"], ["frontend_reviewer"], ["node_syntax"], "frontend.typescript", False, False, "TypeScript source"),
    FilePolicy("**/*.css", "frontend.css", "low", ["frontend_writer"], ["frontend_reviewer"], [], "frontend.css", False, False, "CSS stylesheet"),
    FilePolicy("**/*.html", "frontend.html", "medium", ["frontend_writer"], ["frontend_reviewer"], [], "frontend.html", False, False, "HTML document"),
    FilePolicy("**/*.json", "config.json", "medium", ["config_writer"], ["config_reviewer"], ["json_parse"], "config.json", False, False, "JSON config"),
    FilePolicy("**/*.md", "docs.markdown", "low", ["docs_writer"], ["docs_reviewer"], ["markdown_scan"], "docs.markdown", False, False, "Markdown docs"),
]


def default_file_policies() -> List[FilePolicy]:
    return list(_DEFAULT_POLICIES)


def resolve_file_policy(
    path: str,
    *,
    policies: List[FilePolicy] | None = None,
    content_hint: str = "",
) -> FilePolicy:
    normalized = _normalize_path(path)
    for policy in policies or _DEFAULT_POLICIES:
        if _matches(policy.pattern, normalized):
            return policy
    return _fallback_policy(normalized, content_hint)


def policy_registry_payload() -> List[Dict[str, Any]]:
    return [policy.to_dict() for policy in _DEFAULT_POLICIES]


def _matches(pattern: str, path: str) -> bool:
    pattern_norm = _normalize_path(pattern)
    return (
        fnmatch.fnmatch(path, pattern_norm)
        or fnmatch.fnmatch(f"/{path}", pattern_norm)
        or fnmatch.fnmatch(path, pattern_norm.replace("**/", ""))
    )


def _fallback_policy(path: str, content_hint: str = "") -> FilePolicy:
    suffix = Path(path).suffix.lower()
    if _is_sensitive_path(path):
        return FilePolicy(
            "<sensitive-fallback>",
            "secrets.generic",
            "critical",
            ["approval_coordinator"],
            ["security_reviewer"],
            [],
            "default",
            True,
            True,
            "sensitive fallback",
        )
    if suffix == ".py":
        return FilePolicy(
            "<fallback>",
            "backend.python",
            verification_profile="backend.python",
            required_verification=["py_compile"],
            allowed_writers=["backend_writer"],
            required_reviewers=["backend_reviewer"],
            reason="extension fallback",
        )
    if suffix in {".js", ".mjs", ".cjs"}:
        return FilePolicy(
            "<fallback>",
            "frontend.javascript",
            verification_profile="frontend.javascript",
            required_verification=["node_syntax"],
            allowed_writers=["frontend_writer"],
            required_reviewers=["frontend_reviewer"],
            reason="extension fallback",
        )
    if suffix == ".json":
        return FilePolicy(
            "<fallback>",
            "config.json",
            verification_profile="config.json",
            required_verification=["json_parse"],
            allowed_writers=["config_writer"],
            required_reviewers=["config_reviewer"],
            reason="extension fallback",
        )
    return FilePolicy(
        "<fallback>",
        "unknown",
        "medium",
        ["general_writer"],
        ["general_reviewer"],
        [],
        "default",
        False,
        False,
        "unknown fallback",
    )


def _is_sensitive_path(path: str) -> bool:
    lowered = path.lower()
    return any(
        part in lowered
        for part in (".env", ".ssh", "id_rsa", "id_ed25519", "credential", "secret", "token", ".aws", ".gcp")
    )


def _normalize_path(path: str) -> str:
    return str(path or "").replace("\\", "/").lstrip("/").lower()
