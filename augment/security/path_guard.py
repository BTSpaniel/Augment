"""Path guard — prevent file access outside allowed roots and to known-sensitive paths."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List, Optional, Set


logger = logging.getLogger("augment.security.path_guard")


_FORBIDDEN_PATTERNS = {
    ".env", ".git/config", ".ssh", "id_rsa", "id_ed25519",
    "authorized_keys", "known_hosts", "shadow", "passwd",
    "credentials", "secrets", "token", ".aws/credentials",
}
_FORBIDDEN_EXTENSIONS = {".pem", ".key", ".p12", ".pfx", ".keystore"}


class PathGuard:
    """Guards file system access. Configurable allowed roots and dotfile policy."""

    def __init__(
        self,
        *,
        allowed_roots: Optional[Iterable[str]] = None,
        deny_dotfiles: bool = False,
    ) -> None:
        self._allowed_roots: List[Path] = [Path(r).resolve() for r in (allowed_roots or [])]
        self._deny_dotfiles = deny_dotfiles
        self._denied: Set[str] = set()

    def is_safe(self, path: str) -> bool:
        try:
            resolved = Path(path).resolve()
        except Exception:
            return False
        path_str = str(resolved).replace("\\", "/").lower()
        name = resolved.name.lower()

        for pattern in _FORBIDDEN_PATTERNS:
            if pattern.lower() in path_str:
                self._denied.add(path)
                logger.warning("blocked forbidden pattern: %s", path)
                return False

        if resolved.suffix.lower() in _FORBIDDEN_EXTENSIONS:
            self._denied.add(path)
            logger.warning("blocked forbidden extension: %s", path)
            return False

        if self._deny_dotfiles:
            parts = resolved.parts
            if any(p.startswith(".") and p not in (".", "..") for p in parts):
                self._denied.add(path)
                return False

        if self._allowed_roots:
            if not any(self._is_under(resolved, root) for root in self._allowed_roots):
                self._denied.add(path)
                logger.warning("blocked outside allowed roots: %s", path)
                return False

        return True

    def guard(self, path: str) -> str:
        """Return ``path`` unchanged if safe, else raise ``ValueError``."""
        if not self.is_safe(path):
            raise ValueError(f"Access denied: {path}")
        return path

    @staticmethod
    def _is_under(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    @property
    def denied_count(self) -> int:
        return len(self._denied)

    @property
    def denied_paths(self) -> List[str]:
        return sorted(self._denied)
