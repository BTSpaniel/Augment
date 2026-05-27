"""Kernel utilities — small, framework-free helpers.

Ported from FAIL's ``server/kernel`` package, trimmed to single-loop needs.
"""
from __future__ import annotations

from augment.kernel.atomic_files import write_text_atomically

__all__ = ["write_text_atomically"]
