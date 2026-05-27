"""Verification profiles — syntax / parse checks per file type.

Distilled from FAIL's ``server/builder/verification_profiles.py``. Drops the
FAIL receipt-writer dependency; callers consume the :class:`VerificationReceipt`
directly (e.g. attach it to an edit receipt or surface it in the chat UI).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from augment.builder.environment import EnvironmentSnapshot, detect_environment


@dataclass
class VerificationCheck:
    name: str
    status: str
    reason: str = ""
    command: str = ""
    evidence: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationReceipt:
    verification_receipt_id: str
    profile: str
    checks: List[VerificationCheck] = field(default_factory=list)
    overall: str = "skipped"
    risk_left: List[str] = field(default_factory=list)
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verification_receipt_id": self.verification_receipt_id,
            "profile": self.profile,
            "checks": [c.to_dict() for c in self.checks],
            "overall": self.overall,
            "risk_left": self.risk_left,
            "created_at": self.created_at,
        }


_PROFILES: Dict[str, List[str]] = {
    "frontend.single_file_game": ["node_syntax", "browser_smoke"],
    "frontend.javascript": ["node_syntax"],
    "frontend.typescript": ["node_syntax"],
    "backend.python": ["py_compile"],
    "config.json": ["json_parse"],
    "docs.markdown": ["markdown_scan"],
    "default": ["file_exists"],
}


def profile_for_files(files: List[str]) -> str:
    files = [str(p) for p in files or []]
    if any(path.endswith(".py") for path in files):
        return "backend.python"
    if any(path.endswith(".json") for path in files):
        return "config.json"
    if any(path.endswith((".md", ".markdown")) for path in files):
        return "docs.markdown"
    if any(path.endswith((".js", ".mjs", ".cjs")) for path in files):
        return "frontend.javascript"
    return "default"


def verification_profile_registry() -> Dict[str, List[str]]:
    return {key: list(value) for key, value in _PROFILES.items()}


def run_verification_profile(
    root: str | Path,
    files: List[str],
    *,
    profile: str = "",
) -> VerificationReceipt:
    root_path = Path(root).resolve()
    selected = profile or profile_for_files(files)
    env = detect_environment()
    checks = [_run_check(name, root_path, files, env) for name in _PROFILES.get(selected, _PROFILES["default"])]
    overall = _overall(checks)
    return VerificationReceipt(
        verification_receipt_id=f"vr_{int(time.time() * 1000)}",
        profile=selected,
        checks=checks,
        overall=overall,
        risk_left=[c.reason for c in checks if c.status == "skipped" and c.reason],
        created_at=time.time(),
    )


def _run_check(name: str, root: Path, files: List[str], env: EnvironmentSnapshot) -> VerificationCheck:
    if name == "file_exists":
        missing = [path for path in files if not (root / path).exists()]
        return VerificationCheck(
            name=name,
            status="failed" if missing else "passed",
            reason=", ".join(missing) if missing else "all files exist",
        )
    if name == "py_compile":
        return _py_compile(root, [p for p in files if p.endswith(".py")])
    if name == "node_syntax":
        node_tool = env.tools.get("node")
        if not node_tool or not node_tool.available:
            return VerificationCheck(name=name, status="skipped", reason="node unavailable")
        return _node_syntax(root, [p for p in files if p.endswith((".js", ".mjs", ".cjs", ".ts"))])
    if name == "json_parse":
        return _json_parse(root, [p for p in files if p.endswith(".json")])
    if name == "markdown_scan":
        return VerificationCheck(
            name=name,
            status="passed",
            reason="markdown syntax scan not required",
            evidence=f"{len(files)} files considered",
        )
    if name == "browser_smoke":
        return VerificationCheck(name=name, status="skipped", reason="browser runner unavailable")
    return VerificationCheck(name=name, status="skipped", reason=f"unknown check: {name}")


def _py_compile(root: Path, files: List[str]) -> VerificationCheck:
    if not files:
        return VerificationCheck(name="py_compile", status="skipped", reason="no Python files")
    t0 = time.time()
    command = f"{sys.executable} -m py_compile " + " ".join(files)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", *files],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as exc:
        return VerificationCheck(
            name="py_compile",
            status="failed",
            command=command,
            evidence=str(exc)[:1000],
            duration_ms=(time.time() - t0) * 1000,
        )
    return VerificationCheck(
        name="py_compile",
        status="passed" if result.returncode == 0 else "failed",
        command=command,
        evidence=(result.stdout or result.stderr).strip()[:1000],
        duration_ms=(time.time() - t0) * 1000,
    )


def _node_syntax(root: Path, files: List[str]) -> VerificationCheck:
    if not files:
        return VerificationCheck(name="node_syntax", status="skipped", reason="no JavaScript files")
    t0 = time.time()
    failures: List[str] = []
    for path in files[:10]:
        try:
            result = subprocess.run(
                ["node", "--check", path],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                failures.append((result.stderr or result.stdout).strip()[:400])
        except Exception as exc:
            failures.append(f"{path}: {exc}")
    return VerificationCheck(
        name="node_syntax",
        status="failed" if failures else "passed",
        command="node --check",
        evidence="\n".join(failures) if failures else f"{len(files[:10])} files OK",
        duration_ms=(time.time() - t0) * 1000,
    )


def _json_parse(root: Path, files: List[str]) -> VerificationCheck:
    if not files:
        return VerificationCheck(name="json_parse", status="skipped", reason="no JSON files")
    errors: List[str] = []
    for path in files[:20]:
        try:
            json.loads((root / path).read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    return VerificationCheck(
        name="json_parse",
        status="failed" if errors else "passed",
        evidence="\n".join(errors) if errors else f"{len(files[:20])} files OK",
    )


def _overall(checks: List[VerificationCheck]) -> str:
    if any(check.status == "failed" for check in checks):
        return "failed"
    if checks and all(check.status == "passed" for check in checks):
        return "passed"
    if any(check.status == "passed" for check in checks):
        return "partial"
    return "skipped"
