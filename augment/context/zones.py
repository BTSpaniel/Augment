"""Smart-zone / Dumb-zone / Buffer layout for the assembled context.

The "Lost in the Middle" effect (Liu et al. 2024, arXiv:2307.03172) means
LLM attention follows a U-shaped curve: high at the start of the prompt,
high at the end, and **30%+ degradation** in the middle. Reproduced
across every frontier model in Chroma's 2025 *Context Rot* study.

To play to the architecture instead of fighting it, Augment partitions
the assembled prompt into three named zones, ordered top-to-bottom:

* :data:`Zone.SMART_TOP` — high-attention header. Holds anything the
  agent **must** read every turn: identity, soul/persona, active plan,
  hard tool policy.
* :data:`Zone.DUMB_MIDDLE` — low-attention belly. Holds bulky reference
  material the agent only needs to *have access to* — tool catalog,
  skill packs, memory dumps, workspace metadata, scratchboard. Truncates
  more aggressively under pressure.
* :data:`Zone.SMART_BOTTOM` — high-attention footer adjacent to the
  user's current message. Holds the most recent N turns, last tool
  results, message ledger, turn state.

A separate **buffer** allocation (default 9% of the budget) is reserved
and never written to. It absorbs mid-loop tool-result expansion and
covers tokenizer-drift fudge between our 4-chars-per-token estimator and
the provider's actual count.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Mapping, Sequence


class Zone(str, Enum):
    """Where a section sits in the assembled prompt."""

    SMART_TOP = "smart_top"
    DUMB_MIDDLE = "dumb_middle"
    SMART_BOTTOM = "smart_bottom"


# Default mapping from section name → zone. Section names match the
# keys produced by :class:`augment.context.builder.ContextBuilder`.
DEFAULT_ZONE_MEMBERSHIP: Dict[Zone, List[str]] = {
    Zone.SMART_TOP: [
        # Order matters — emitted top-to-bottom inside the smart_top zone.
        # Identity first establishes "who", then the durable rules the
        # agent must abide by every turn (project conventions, user
        # rules, per-session coding contract), then the live agent soul
        # and active plan that shape voice and current focus.
        "identity",
        "project_conventions",
        "user_rules",
        "coding_contract",
        "agent_soul",
        "active_plan",
        "tool_policy",
        "environment",
    ],
    Zone.DUMB_MIDDLE: [
        # Bulk reference material — the agent uses these as a lookup
        # surface but rarely needs every line. Sits in the low-attention
        # middle of the prompt where attention naturally dilutes.
        "runtime",
        "workspace",
        "tools",
        "adaptive_skills",
        "memory",
        "memory_tiers",
        "wiki_knowledge",
        "user_model",
        "mind_state",
        "scratchboard",
        "session_mailbox",
    ],
    Zone.SMART_BOTTOM: [
        # Smart-bottom sits adjacent to the user's current message and
        # benefits from the recency primacy of the U-shape.
        "turn_state",
        "message_ledger",
        "evidence",
        "learning_signals",
        "recent_history",
    ],
}


@dataclass(frozen=True)
class ZoneLayout:
    """Resolved layout: which sections live in which zone, in order.

    Use :func:`zone_layout_from_config` to build one from a YAML config
    block, or :func:`default_zone_layout` for the baked-in default.
    """

    smart_top: tuple[str, ...]
    dumb_middle: tuple[str, ...]
    smart_bottom: tuple[str, ...]

    def zone_for(self, section: str) -> Zone | None:
        if section in self.smart_top:
            return Zone.SMART_TOP
        if section in self.dumb_middle:
            return Zone.DUMB_MIDDLE
        if section in self.smart_bottom:
            return Zone.SMART_BOTTOM
        return None

    def sections_in_order(self) -> tuple[str, ...]:
        """Return all sections in their final assembled order."""
        return self.smart_top + self.dumb_middle + self.smart_bottom

    def known_sections(self) -> frozenset[str]:
        return frozenset(self.smart_top + self.dumb_middle + self.smart_bottom)


def default_zone_layout() -> ZoneLayout:
    return ZoneLayout(
        smart_top=tuple(DEFAULT_ZONE_MEMBERSHIP[Zone.SMART_TOP]),
        dumb_middle=tuple(DEFAULT_ZONE_MEMBERSHIP[Zone.DUMB_MIDDLE]),
        smart_bottom=tuple(DEFAULT_ZONE_MEMBERSHIP[Zone.SMART_BOTTOM]),
    )



def zone_layout_from_config(spec: Mapping[str, Sequence[str]] | None) -> ZoneLayout:
    """Build a :class:`ZoneLayout` from a config block.

    Accepts a mapping like::

        {
            "smart_top":    ["identity", "agent_soul", ...],
            "dumb_middle":  ["tools", "memory_tiers", ...],
            "smart_bottom": ["recent_history", ...],
        }

    Missing zones fall back to defaults so partial overrides are OK.
    """
    if not spec:
        return default_zone_layout()

    base = DEFAULT_ZONE_MEMBERSHIP

    def _coerce(zone: Zone) -> tuple[str, ...]:
        value = spec.get(zone.value)
        if value is None:
            return tuple(base[zone])
        if isinstance(value, str):
            value = [value]
        return tuple(str(v) for v in value if str(v).strip())

    return ZoneLayout(
        smart_top=_coerce(Zone.SMART_TOP),
        dumb_middle=_coerce(Zone.DUMB_MIDDLE),
        smart_bottom=_coerce(Zone.SMART_BOTTOM),
    )
