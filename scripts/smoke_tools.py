"""Smoke test: confirm all FAIL-ported tools are wired into the registry."""
from __future__ import annotations

from augment.config import load_config
from augment.service import AugmentApp


def main() -> None:
    app = AugmentApp(load_config())
    names = app.tools.all_names()
    print(f"Total tools: {len(names)}")
    packs = app.tool_packs()
    print(f"Tool packs: {len(packs['packs'])} (total {packs['tool_count']})")
    for pack in packs["packs"]:
        tool_names = ", ".join(t["name"] for t in pack["tools"])
        print(f"  - {pack['id']} ({pack['count']}): {tool_names}")


if __name__ == "__main__":
    main()
