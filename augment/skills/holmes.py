"""Holmes investigation skill — iterative read → think → read loop.

Inspired by Anthropic / Matt Pocock skill-pack patterns (``grill-me`` /
``handoff`` / ``caveman``). The Holmes skill nudges the loop to:

1. Read multiple files **in parallel** before reasoning (3-6 at a time).
2. Pause and **think** between batches — record findings to the inner monologue.
3. Identify gaps explicitly before the next batch.
4. Only conclude after the file map and call graph are stable.

The skill activates automatically when the user message contains exploration
verbs (investigate / understand / explore / map / audit) or when the active
metacognition strategy is ``explore_first``. It can also be invoked manually
from the UI via the dormant ``code_investigator`` pack.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, List

from augment.skills.store import AdaptiveSkill

if TYPE_CHECKING:  # pragma: no cover
    from augment.service import AugmentApp


_TRIGGERS = re.compile(
    r"\b(investigate|understand|explore|map\s+(?:the\s+)?code|audit|"
    r"how\s+does\s+[\w\s]{1,40}?\s+work|trace|find\s+(?:out|where)|figure\s+out|"
    r"walk\s+(?:me\s+)?through|reverse[- ]engineer)\b",
    re.IGNORECASE,
)


HOLMES_PROMPT = """\
INVESTIGATION MODE (Holmes) — read first, conclude last.

The loop you are in works best when:
1. **Batch reads.** Call `read_file` / `search_code` / `list_dir` for 3-6 likely
   targets in a single turn before reasoning. Parallel evidence beats sequential
   guessing.
2. **Think out loud.** Between batches, write one or two sentences naming what
   you now know and the *single* biggest remaining unknown. Use the inner
   monologue / scratchpad if available.
3. **Name the gap.** Each round explicitly identifies the next files to open.
   No reading without a reason; no reasoning without enough reads.
4. **Cite as you go.** When stating a fact about the code, cite the file + line
   range that justifies it.
5. **Conclude only when stable.** Stop investigating once a second batch would
   not change the conclusion. Then state the answer concisely.

## Persistence

ACTIVE for the whole investigation, not just one turn. Do not silently revert
to flat answers. If the user asks a different question mid-flow, finish naming
your current finding first (one sentence) then pivot. Off only when the user
says "stop Holmes" or "I have enough" — or when the conclusion is stable.

## Auto-Clarity Exception

Drop Holmes mode temporarily when:
- The user asks for a single, factual lookup ("what's the path of X?").
- The user requests an action that requires no investigation ("rename Y to Z").
- A safety / destructive confirmation is required.
Resume Holmes after the clarification.

## Anti-patterns to avoid

- Reading one file, then writing a long opinion.
- Asking the user a question that a `search_code` would answer.
- Restating the same finding in different words instead of testing it.

## Example

User: "How does the chat loop call tools?"

Bad (anti-pattern):
> Looking at react.py, it seems like ReActLoop.run iterates and calls tools.

Good (Holmes):
> Batch 1: read augment/loop/react.py, augment/tools/registry.py,
> augment/service.py. Finding: tool execution flows through
> `ReActLoop._execute_tool_calls` (@C:/.../react.py:120-178), which dispatches
> via the ToolRegistry. Remaining unknown: how tool *context* (memory, session)
> is injected.
> Batch 2: read augment/service.py:120-160. Finding: `tool_context` dict is
> assembled in `AugmentApp.chat` and passed to `ReActLoop.run`. Conclusion is
> now stable.

Match the pattern of a careful human investigator: scan, batch-read,
note, batch-read, note, conclude.\
"""


def matches_investigation_intent(message: str) -> bool:
    """True when the user's message looks like an investigation request."""
    return bool(_TRIGGERS.search(message or ""))


def holmes_skill(app: "AugmentApp", *, objective: str = "", explicit: bool = False) -> AdaptiveSkill | None:
    """Build the Holmes adaptive skill for ``objective`` if relevant.

    Returns ``None`` when the objective doesn't look like an investigation and
    metacognition hasn't picked ``explore_first``. Set ``explicit=True`` to
    force-activate (e.g. from a UI toggle).
    """
    is_explore_strategy = False
    try:
        is_explore_strategy = (
            getattr(app, "mind", None) is not None
            and app.mind.metacognition.current_strategy == "explore_first"
        )
    except Exception:
        pass

    if not (explicit or is_explore_strategy or matches_investigation_intent(objective)):
        return None

    signals: List[str] = []
    if objective:
        signals.append(f"objective: {objective[:200]}")
    signals.extend([
        "mode: investigation (batch read → think → batch read)",
        "minimum batch size before reasoning: 3 files",
        "cite file + line range for every claim about code",
    ])
    if is_explore_strategy:
        signals.append("metacognition.strategy = explore_first")

    return AdaptiveSkill(
        id="adaptive_holmes_investigation",
        kind="holmes_investigation",
        title="Holmes Investigation Loop",
        priority=0.95,  # higher than current_build (0.9) so it lands first
        signals=signals,
        instructions=HOLMES_PROMPT,
        metadata={
            "explicit": explicit,
            "intent_matched": matches_investigation_intent(objective),
            "strategy": "explore_first" if is_explore_strategy else "",
        },
    )


# ── Dormant pack registration ───────────────────────────────────────


HOLMES_DORMANT_PACK = {
    "id": "code_investigator",
    "name": "Code Investigator (Holmes)",
    "category": "Architecture",
    "description": (
        "Iterative investigation pattern: batch-read 3-6 related files, then "
        "think, then batch-read again. Avoids the 'read-one-then-opine' "
        "anti-pattern. Activates on investigate / explore / audit / how-does-X-work."
    ),
    "when_to_use": [
        "The user wants to understand an unfamiliar codebase or subsystem.",
        "There is a bug whose root cause spans multiple files.",
        "A refactor or feature requires mapping ownership and call paths first.",
    ],
    "when_not_to_use": [
        "Do not activate for tiny, single-file edits.",
        "Do not activate when the user has already named the exact file to change.",
        "Do not write any file under this pack — handoff to builder once mapped.",
    ],
    "inputs": ["work_order", "objective", "available_files"],
    "outputs": [
        "file map + responsibility per file",
        "call graph notes for the affected paths",
        "list of remaining unknowns",
        "concrete next step (target file, target function)",
    ],
    "required_tools": ["read_file", "search_code", "search_files", "list_dir"],
    "allowed_permissions": ["filesystem_read"],
    "risk_level": "low",
    "steps": [
        "Scan the workspace to identify likely entry points (3-6 files).",
        "Read them in a single batched turn.",
        "Write one or two sentences naming what is now known and the single "
        "biggest remaining unknown. Use inner monologue when available.",
        "Identify the next batch of files based on the gap.",
        "Repeat until a second batch would not change the conclusion.",
        "Hand off to builder/debugger with: file map, citations, next step.",
    ],
    "acceptance_check": (
        "Every claim about the code cites a file + line range. The conclusion "
        "names the exact file and function to change. A second exploration "
        "would not move the conclusion."
    ),
    "handoff_targets": ["builder", "debugger", "refactorer"],
    "memory_write_policy": (
        "Record the final file map and call-graph notes as procedural memory "
        "if the pattern is likely to recur. Avoid dumping raw read output."
    ),
    "active_by_default": False,
}
