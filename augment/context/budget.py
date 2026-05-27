"""Proportional, model-aware context budget allocator.

Faithful port of Luna's ``ContextBudgetAllocator``
(see ``C:/Coding/Luna/server/core/context_compiler.py:45-170``) with the
allocation table re-laid out for Augment's section names and our
"Smart / Dumb / Buffer" zone model (see :mod:`augment.context.zones`).

Algorithm (two-phase, identical to Luna):

* **Phase 1 — Targets.** Each section is given a *target* allocation equal
  to ``pct%`` of the total budget, clamped between ``min_pct%`` and
  ``max_pct%``.
* **Phase 2 — Surplus redistribution.** Sections that used *less* than
  their target donate the unused slack to a shared pool. Sections that
  *exceeded* their target draw from the pool, proportionally to their
  overage and capped at their personal ``max_pct%`` ceiling.
* **Residual sections.** A small set of sections (by default just
  ``recent_history``) get whatever remains after every other section
  plus the buffer is accounted for. This mirrors Luna's behaviour where
  conversation messages absorb the leftover input budget.

Everything is denominated in **tokens** (Luna's convention). Callers that
work in characters can convert via ``ContextBudgetAllocator.tokens_to_chars``
which uses the standard 4-chars-per-token heuristic.

Empirical sources guiding the default percentages:

* Liu et al. 2024, *Lost in the Middle* (arXiv:2307.03172) — U-shaped
  attention. Smart sections sit at the top/bottom of the prompt; bulk
  reference material lives in the middle where attention naturally
  weakens.
* Chroma's *Context Rot* study (2025) — every frontier model degrades
  past ~60-70% of advertised window. We default ``target_utilization``
  to ``0.50`` so the assembled prompt sits comfortably below that cliff.
* Anthropic's *Effective Context Engineering for AI Agents* — "find the
  smallest possible set of high-signal tokens".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional


# Default per-section allocation table.
#
# Each entry is ``(default_pct, min_pct, max_pct)`` — percentages of the
# total input budget. Sums to 100. Tweakable via the ``overrides`` arg
# to the allocator or via ``config.context.budget_allocations`` in YAML.
#
# Section names match the keys produced by ``ContextBuilder.build()``.
DEFAULT_SLOTS: Dict[str, tuple[float, float, float]] = {
    # ── smart_top ──────────────────────────────────────────────────
    "identity":             (5.0,  3.0, 12.0),   # AGENT IDENTITY block
    "agent_soul":           (6.0,  3.0, 12.0),   # SOUL / personality
    "project_conventions":  (5.0,  0.0, 10.0),   # AGENTS.md / CONVENTIONS.md / RULES.md
    "user_rules":           (3.0,  0.0,  8.0),   # data/rules/*.md + .augment/rules/*.md
    "coding_contract":      (3.0,  0.0,  8.0),   # per-session pinned rules
    "active_plan":          (3.0,  0.0,  8.0),   # current plan, if any
    "tool_policy":          (3.0,  1.0,  6.0),   # mutation/exploration policy
    # ── dumb_middle ────────────────────────────────────────────────
    "tools":            (5.0,  2.0, 12.0),   # tool descriptions catalog
    "adaptive_skills":  (4.0,  0.0, 10.0),   # skill packs
    "memory":           (4.0,  1.0,  8.0),   # MemoryStore episodic block
    "memory_tiers":     (4.0,  1.0, 10.0),   # MemorySystem semantic dump
    "user_model":       (2.0,  0.0,  4.0),
    "mind_state":       (2.0,  0.0,  4.0),
    "runtime":          (1.0,  0.0,  2.0),
    "workspace":        (1.0,  0.0,  3.0),
    "scratchboard":     (3.0,  0.0,  6.0),
    "session_mailbox":  (3.0,  0.0,  6.0),
    # ── smart_bottom ───────────────────────────────────────────────
    "turn_state":       (3.0,  0.0,  6.0),
    "message_ledger":   (5.0,  2.0, 10.0),
    "recent_history":  (26.0, 18.0, 55.0),   # residual section
    # ── buffer (never allocated) ───────────────────────────────────
    "buffer":           (9.0,  5.0, 15.0),
}


# Sections that are *always* loaded last and absorb the residual budget.
# Mirrors Luna's pattern where ``messages`` is the residual slot.
DEFAULT_RESIDUAL_SECTIONS: frozenset[str] = frozenset({"recent_history"})


@dataclass(frozen=True)
class AllocationResult:
    """Outcome of one ``finalize`` pass.

    Attributes:
        targets: Phase-1 token budget per section.
        finals: Phase-2 (post-redistribution) token budget per section.
        actuals: Caller-supplied actual token sizes (for diagnostics).
        total_budget: Total input budget the allocator was working with.
        chars_per_token: Conversion factor used by ``tokens_to_chars``.
    """

    targets: Dict[str, int]
    finals: Dict[str, int]
    actuals: Dict[str, int] = field(default_factory=dict)
    total_budget: int = 0
    chars_per_token: int = 4

    def chars_for(self, section: str) -> int:
        """Return the section's final budget in *characters* (tokens × 4)."""
        return int(self.finals.get(section, 0)) * int(self.chars_per_token)

    def tokens_for(self, section: str) -> int:
        return int(self.finals.get(section, 0))


class ContextBudgetAllocator:
    """Proportional token-budget allocation with surplus redistribution.

    Example::

        alloc = ContextBudgetAllocator(total_input_tokens=64_000)
        result = alloc.finalize({
            "identity":       1200,
            "agent_soul":     6500,
            "tools":          2400,
            "recent_history":    0,  # filled later
            ...
        })
        identity_chars = result.chars_for("identity")
    """

    DEFAULT_SLOTS = DEFAULT_SLOTS  # re-export for callers

    def __init__(
        self,
        total_input_tokens: int,
        overrides: Optional[Dict[str, object]] = None,
        *,
        residual_sections: Optional[Iterable[str]] = None,
    ) -> None:
        if total_input_tokens < 0:
            raise ValueError("total_input_tokens must be non-negative")
        self._total = int(total_input_tokens)
        self._slots: Dict[str, tuple[float, float, float]] = dict(DEFAULT_SLOTS)
        if overrides:
            for key, val in overrides.items():
                if key not in self._slots:
                    # Allow callers to add brand-new sections at runtime.
                    self._slots[key] = self._coerce_slot(val, defaults=(0.0, 0.0, 100.0))
                    continue
                _, mn, mx = self._slots[key]
                self._slots[key] = self._coerce_slot(val, defaults=(0.0, mn, mx))

        # Normalise: if percentages don't sum to 100 (e.g. user added a
        # section without tweaking others), scale proportionally so we
        # never silently allocate >100% of the budget.
        total_pct = sum(s[0] for s in self._slots.values())
        if total_pct > 0 and abs(total_pct - 100.0) > 0.5:
            scale = 100.0 / total_pct
            self._slots = {
                k: (v[0] * scale, v[1], v[2])
                for k, v in self._slots.items()
            }

        self._residual_sections = frozenset(
            residual_sections if residual_sections is not None else DEFAULT_RESIDUAL_SECTIONS
        )

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _coerce_slot(
        value: object, *, defaults: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        """Accept either a bare number (override default_pct) or a 3-tuple."""
        d_pct, d_min, d_max = defaults
        if isinstance(value, (int, float)):
            return (float(value), d_min, d_max)
        if isinstance(value, (list, tuple)) and len(value) == 3:
            return (float(value[0]), float(value[1]), float(value[2]))
        return defaults

    @staticmethod
    def tokens_to_chars(tokens: int, *, chars_per_token: int = 4) -> int:
        """Standard ``chars ≈ tokens × 4`` heuristic (Luna parity)."""
        return max(0, int(tokens)) * int(chars_per_token)

    @staticmethod
    def chars_to_tokens(chars: int, *, chars_per_token: int = 4) -> int:
        return max(0, int(chars)) // max(1, int(chars_per_token))

    # ── Public API ──────────────────────────────────────────────────

    @property
    def total_budget(self) -> int:
        return self._total

    @property
    def slots(self) -> Dict[str, tuple[float, float, float]]:
        return dict(self._slots)

    def get_targets(self) -> Dict[str, int]:
        """Phase 1 — proportional target per section, clamped to floor/ceiling."""
        targets: Dict[str, int] = {}
        for name, (pct, min_pct, max_pct) in self._slots.items():
            target = int(self._total * pct / 100)
            floor = int(self._total * min_pct / 100)
            ceiling = int(self._total * max_pct / 100)
            targets[name] = max(floor, min(target, ceiling))
        return targets

    def finalize(self, actual_sizes: Dict[str, int]) -> AllocationResult:
        """Phase 2 — redistribute surplus from under-used sections.

        Non-residual, non-buffer sections donate unused allocation to a
        shared pool. Over-budget sections draw from the pool, proportional
        to their overage and capped at their per-section ceiling. Residual
        sections (default: ``recent_history``) absorb whatever remains.

        Args:
            actual_sizes: ``{section: actual_tokens_used}``. Sections not
                present default to ``0``.

        Returns:
            An :class:`AllocationResult` with per-section targets and
            finals (post-redistribution).
        """
        targets = self.get_targets()
        ceilings: Dict[str, int] = {
            name: int(self._total * slot[2] / 100)
            for name, slot in self._slots.items()
        }
        floors: Dict[str, int] = {
            name: int(self._total * slot[1] / 100)
            for name, slot in self._slots.items()
        }

        # ── Collect surplus + needs ───────────────────────────────
        surplus = 0
        needs: Dict[str, int] = {}
        for name, target in targets.items():
            if name == "buffer" or name in self._residual_sections:
                continue
            actual = int(actual_sizes.get(name, 0))
            if actual < target:
                surplus += (target - actual)
            elif actual > target:
                room = ceilings[name] - target
                if room > 0:
                    needs[name] = min(actual - target, room)

        total_need = sum(needs.values())
        finals: Dict[str, int] = {}
        non_residual_total = 0

        for name, target in targets.items():
            if name == "buffer":
                # Buffer is reserved as-is — never re-distributed away.
                finals[name] = target
                continue
            if name in self._residual_sections:
                continue  # handled below

            actual = int(actual_sizes.get(name, 0))
            if name in needs and total_need > 0 and surplus > 0:
                share = int(surplus * needs[name] / total_need)
                finals[name] = min(target + share, ceilings[name])
            else:
                # Section came in under target: keep its actual size, but
                # respect its floor (so a 0-byte section that has a
                # non-zero floor still gets that floor, in case it
                # arrives later in the loop).
                finals[name] = max(actual, floors[name])
                finals[name] = min(finals[name], target)
            non_residual_total += finals[name]

        # ── Residual pool ─────────────────────────────────────────
        buffer_tokens = finals.get("buffer", targets.get("buffer", 0))
        residual_pool = max(0, self._total - non_residual_total - buffer_tokens)
        for name in self._residual_sections:
            ceiling = ceilings.get(name, residual_pool)
            floor = floors.get(name, 0)
            finals[name] = max(floor, min(residual_pool, ceiling))

        return AllocationResult(
            targets=targets,
            finals=finals,
            actuals=dict(actual_sizes),
            total_budget=self._total,
        )

    # ── Diagnostics ─────────────────────────────────────────────────

    def log_summary(self, finals: Dict[str, int], actuals: Dict[str, int]) -> str:
        """Compact one-line diagnostic — used by the bleep SSE event."""
        rows = []
        for name in self._slots:
            f = int(finals.get(name, 0))
            a = int(actuals.get(name, 0))
            if f == 0 and a == 0:
                continue
            pct = (a / f * 100.0) if f else 0.0
            rows.append(f"{name}={a}/{f}({pct:.0f}%)")
        return " ".join(rows)
