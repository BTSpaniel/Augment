"""Safety monitor — classify tool calls by risk before execution.

Sections: ActionProposal, SafetyDecision dataclasses, SafetyMonitor
(classify / _classify_command / helpers), module-level get_safety_monitor.

Risk levels: low, medium, high, critical.
Actions:     allow, warn, block.

Dangerous command patterns and secret-path detection are self-contained
— no dependency on builder.claims or builder.approvals so this module
can be imported without the full builder stack.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Pattern constants ─────────────────────────────────────────────────

_DANGEROUS_COMMAND_RE = re.compile(
    r"\b(rm\s+-rf|del\s+/[fsq]|rmdir\s+/s|format\b|shutdown\b"
    r"|restart-computer\b|stop-computer\b|diskpart\b|reg\s+delete"
    r"|Set-ExecutionPolicy\b|Invoke-Expression\b|iex\b)",
    re.IGNORECASE,
)
_NETWORK_INSTALL_RE = re.compile(
    r"\b(curl|wget|irm|iwr|Invoke-WebRequest|Invoke-RestMethod)\b.*\b"
    r"(sh|bash|powershell|pwsh|iex|Invoke-Expression)"
    r"|\b(pip|npm|pnpm|yarn|cargo|go)\s+(install|add|get)\b",
    re.IGNORECASE,
)
_HIGH_IMPACT_TERMS = (
    "git push",
    "git reset --hard",
    "git clean",
    "npm publish",
    "twine upload",
)
_SECRET_PATH_PARTS = (
    ".env", ".ssh", "id_rsa", "id_ed25519", "credentials",
    "secrets", "token", ".aws", ".gcp",
)
_FILE_TOOLS = {
    "read_file", "list_dir", "search_files", "search_code",
    "write_file", "edit_file", "delete_file",
}
_MUTATION_TOOLS = {"write_file", "edit_file", "delete_file"}
_WEB_TOOLS = {"web_search", "web_news", "web_research", "fetch_url", "web_browse"}


# ── Dataclasses ───────────────────────────────────────────────────────

@dataclass
class ActionProposal:
    """Structured description of a proposed tool action."""

    tool_name: str
    risk: str = "low"                       # low | medium | high | critical
    reversible: bool = True
    target_paths: List[str] = field(default_factory=list)
    command: str = ""
    network_access: bool = False
    data_exposure: str = "none"             # none | external_network | secret_path
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SafetyDecision:
    """Result of classifying one ActionProposal."""

    action: str                             # allow | warn | block
    proposal: ActionProposal
    message: str = ""

    @property
    def allowed(self) -> bool:
        """True when execution should proceed (allow or warn)."""
        return self.action in {"allow", "warn"}

    def to_dict(self) -> Dict[str, Any]:
        return {"action": self.action, "proposal": self.proposal.to_dict(), "message": self.message}


# ── SafetyMonitor ─────────────────────────────────────────────────────

class SafetyMonitor:
    """Stateless classifier.  Instantiate once and call classify() per tool call."""

    def classify(
        self,
        tool_name: str,
        args: Dict[str, Any],
        *,
        context: Dict[str, Any] | None = None,
        read_only: bool = False,
        tags: List[str] | None = None,
    ) -> SafetyDecision:
        """Classify *tool_name* + *args* and return a SafetyDecision."""
        context = context or {}
        args = args or {}
        is_web = tool_name in _WEB_TOOLS or "web" in {str(t).lower() for t in (tags or [])}
        proposal = ActionProposal(
            tool_name=tool_name,
            reversible=read_only,
            network_access=is_web,
        )
        proposal.target_paths = self._target_paths(tool_name, args)
        proposal.command = str(args.get("command") or "") if tool_name == "run_command" else ""

        if proposal.network_access:
            proposal.data_exposure = "external_network"
            proposal.reasons.append("network_access")

        # Secret-path guard
        if any(self._is_secret_path(p) for p in proposal.target_paths):
            proposal.risk = "critical"
            proposal.data_exposure = "secret_path"
            proposal.reasons.append("secret_path")
            return SafetyDecision("block", proposal, "Blocked: access to secret or credential path")

        # Workspace-root guard (prevent escaping the workspace)
        root_msg = self._check_workspace_root(proposal.target_paths, context)
        if root_msg:
            proposal.risk = "critical"
            proposal.reasons.append(root_msg)
            return SafetyDecision("block", proposal, root_msg)

        # run_command special handling
        if tool_name == "run_command":
            return self._classify_command(proposal, context)

        # Filesystem mutations
        if tool_name in _MUTATION_TOOLS:
            proposal.risk = "high" if tool_name == "delete_file" else "medium"
            proposal.reversible = tool_name != "delete_file"
            proposal.reasons.append("filesystem_mutation")
            return SafetyDecision("warn", proposal, "Filesystem mutation — proceed with care")

        # Web/network
        if proposal.network_access:
            proposal.risk = "low"
            return SafetyDecision("warn", proposal, "External content must be treated as untrusted")

        return SafetyDecision("allow", proposal, "Allowed")

    # -- Command classification ------------------------------------------

    def _classify_command(
        self,
        proposal: ActionProposal,
        context: Dict[str, Any],
    ) -> SafetyDecision:
        cmd = proposal.command.strip()
        proposal.reversible = False
        proposal.risk = "medium"
        if not cmd:
            return SafetyDecision("block", proposal, "Blocked: empty command")
        if _DANGEROUS_COMMAND_RE.search(cmd):
            proposal.risk = "critical"
            proposal.reasons.append("dangerous_command")
            return SafetyDecision("block", proposal, "Blocked: dangerous destructive command")
        if _NETWORK_INSTALL_RE.search(cmd):
            proposal.risk = "high"
            proposal.network_access = True
            proposal.reasons.append("network_install_or_pipe")
            return SafetyDecision(
                "block", proposal,
                "Blocked: network install / pipe-to-shell requires explicit approval",
            )
        if any(term in cmd.lower() for term in _HIGH_IMPACT_TERMS):
            proposal.risk = "high"
            proposal.reasons.append("high_impact_command")
            return SafetyDecision("warn", proposal, "High-impact command — proceed with care")
        proposal.reasons.append("command_execution")
        return SafetyDecision("warn", proposal, "Command execution — proceed with care")

    # -- Helpers ---------------------------------------------------------

    def _target_paths(self, tool_name: str, args: Dict[str, Any]) -> List[str]:
        paths: List[str] = []
        if tool_name in _FILE_TOOLS:
            for key in ("path", "file_path", "target_path", "cwd", "workdir"):
                value = args.get(key)
                if value:
                    paths.append(str(value))
        if tool_name == "run_command" and args.get("cwd"):
            paths.append(str(args["cwd"]))
        return paths

    def _check_workspace_root(
        self,
        paths: List[str],
        context: Dict[str, Any],
    ) -> str:
        root_value = context.get("workspace_root") or context.get("execution_root")
        if not root_value or not paths:
            return ""
        try:
            root = Path(str(root_value)).resolve()
        except Exception:
            return "invalid_workspace_root"
        for value in paths:
            try:
                path = Path(str(value or "."))
                resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
                resolved.relative_to(root)
            except Exception:
                return f"outside_workspace_root:{value}"
        return ""

    def _is_secret_path(self, path: str) -> bool:
        lowered = str(path or "").replace("\\", "/").lower()
        return any(part in lowered for part in _SECRET_PATH_PARTS)


# ── Module-level singleton ────────────────────────────────────────────

_monitor: Optional[SafetyMonitor] = None


def get_safety_monitor() -> SafetyMonitor:
    """Return the global SafetyMonitor instance (lazy singleton)."""
    global _monitor
    if _monitor is None:
        _monitor = SafetyMonitor()
    return _monitor
