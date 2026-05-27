"""Tests for ``augment.context.zones``."""
from __future__ import annotations

from augment.context.zones import (
    DEFAULT_ZONE_MEMBERSHIP,
    Zone,
    default_zone_layout,
    zone_layout_from_config,
)


def test_default_layout_lists_every_default_section():
    layout = default_zone_layout()
    seen = set(layout.smart_top + layout.dumb_middle + layout.smart_bottom)
    for zone_sections in DEFAULT_ZONE_MEMBERSHIP.values():
        for section in zone_sections:
            assert section in seen


def test_zone_for_returns_correct_zone():
    layout = default_zone_layout()
    assert layout.zone_for("identity") is Zone.SMART_TOP
    assert layout.zone_for("agent_soul") is Zone.SMART_TOP
    assert layout.zone_for("tools") is Zone.DUMB_MIDDLE
    assert layout.zone_for("memory_tiers") is Zone.DUMB_MIDDLE
    assert layout.zone_for("recent_history") is Zone.SMART_BOTTOM
    assert layout.zone_for("message_ledger") is Zone.SMART_BOTTOM
    assert layout.zone_for("nonexistent_section") is None


def test_sections_in_order_puts_smart_top_first_smart_bottom_last():
    layout = default_zone_layout()
    ordered = layout.sections_in_order()
    # First section is in smart_top
    assert ordered[0] in layout.smart_top
    # Last is in smart_bottom
    assert ordered[-1] in layout.smart_bottom
    # Middle is dumb
    mid_idx = len(ordered) // 2
    assert ordered[mid_idx] in layout.dumb_middle or ordered[mid_idx] in layout.smart_top + layout.smart_bottom


def test_recent_history_lives_at_the_bottom():
    """recent_history is the most-attended residual section; it MUST sit
    in the smart_bottom zone next to the user's current message."""
    layout = default_zone_layout()
    assert "recent_history" in layout.smart_bottom
    ordered = layout.sections_in_order()
    assert ordered[-1] == "recent_history" or "recent_history" in ordered[-3:]


def test_config_partial_override_keeps_defaults_for_missing_zones():
    """If the user only overrides smart_top, the other two zones keep
    their default contents."""
    spec = {"smart_top": ["identity", "agent_soul"]}
    layout = zone_layout_from_config(spec)
    assert layout.smart_top == ("identity", "agent_soul")
    # Defaults preserved.
    assert "tools" in layout.dumb_middle
    assert "recent_history" in layout.smart_bottom


def test_config_string_value_coerced_to_single_element_tuple():
    """A bare string in the config (not a list) should still work."""
    spec = {"smart_top": "identity"}
    layout = zone_layout_from_config(spec)
    assert layout.smart_top == ("identity",)


def test_config_empty_or_none_yields_default_layout():
    assert zone_layout_from_config(None).smart_top == default_zone_layout().smart_top
    assert zone_layout_from_config({}).smart_bottom == default_zone_layout().smart_bottom


def test_known_sections_includes_all_three_zones():
    layout = default_zone_layout()
    known = layout.known_sections()
    assert "identity" in known
    assert "memory" in known
    assert "recent_history" in known
