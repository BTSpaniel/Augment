"""Matt Pocock-inspired skill packs: caveman, grill-me, handoff.

Adapted from https://github.com/mattpocock/skills to fit Augment's
``AdaptiveSkill`` + dormant-pack format. Each pack has:

- A regex trigger that auto-activates the skill on matching user messages.
- A persistent-mode prompt block (stays on for the conversation).
- An explicit deactivation phrase.
- A dormant-catalog entry so the UI can advertise it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional

from augment.skills.store import AdaptiveSkill

if TYPE_CHECKING:  # pragma: no cover
    from augment.service import AugmentApp


# ── Caveman: ultra-terse mode ───────────────────────────────────────


CAVEMAN_TRIGGER = re.compile(
    r"\b(caveman mode|talk like (?:a )?caveman|use caveman|less tokens?|be brief|terse mode)\b",
    re.IGNORECASE,
)
CAVEMAN_OFF = re.compile(r"\b(stop caveman|normal mode|verbose mode)\b", re.IGNORECASE)

CAVEMAN_PROMPT = """\
CAVEMAN MODE — terse output, ~75% token reduction.

All technical substance stays. Only fluff dies.

## Rules

Drop articles (a/an/the), filler (just/really/basically/actually), pleasantries
(sure/certainly/of course), hedging. Fragments OK. Short synonyms (big not
extensive, fix not "implement a solution for"). Abbreviate common terms
(DB/auth/config/req/res/fn/impl). Use arrows for causality (X -> Y). One word
when one word enough.

Technical terms stay exact. Code blocks unchanged. Errors quoted exact.

Pattern: `[thing] [action] [reason]. [next step].`

## Persistence

ACTIVE every response once triggered. No revert. Off only when user says
"stop caveman" or "normal mode".

## Auto-Clarity Exception

Drop caveman temporarily for: security warnings, irreversible action
confirmations, multi-step sequences where fragment order risks misread, user
asks to clarify. Resume after clear part done.

## Examples

User: "Why React component re-render?"
> Inline obj prop -> new ref -> re-render. `useMemo`.

User: "Explain database connection pooling."
> Pool = reuse DB conn. Skip handshake -> fast under load.\
"""

CAVEMAN_PACK = {
    "id": "caveman_mode",
    "name": "Caveman (Terse Mode)",
    "category": "Content",
    "description": (
        "Ultra-compressed communication: drops articles, filler, pleasantries "
        "while keeping full technical accuracy. ~75% fewer tokens. Activates on "
        "'caveman mode' / 'be brief' / 'less tokens'."
    ),
    "when_to_use": [
        "User asks for shorter / less verbose responses.",
        "Long tool outputs need terse interpretation.",
        "User invokes 'caveman' / 'brief' / 'less tokens'.",
    ],
    "when_not_to_use": [
        "Do not activate for safety warnings or destructive-action confirmations.",
        "Do not activate when the user explicitly asks for detailed explanations.",
    ],
    "inputs": ["current_task"],
    "outputs": ["terse fragments preserving technical accuracy"],
    "required_tools": [],
    "allowed_permissions": [],
    "risk_level": "low",
    "steps": [
        "Drop articles, filler, pleasantries.",
        "Use arrows for causality.",
        "Keep code blocks and error messages exact.",
        "Resume after safety / clarity exception.",
    ],
    "acceptance_check": (
        "Response is at least ~50% shorter than baseline yet preserves every "
        "technical claim, error message, and code block verbatim."
    ),
    "handoff_targets": [],
    "memory_write_policy": "Do not write memories — caveman is per-conversation styling.",
    "active_by_default": False,
}


# ── Grill-Me: interview the user about a plan ────────────────────────


GRILL_TRIGGER = re.compile(
    r"\b(grill me|stress[- ]test (?:my |this |the )?plan|interview me|"
    r"ask me (?:hard )?questions about|poke holes in|find the gaps in (?:my |the )?plan)\b",
    re.IGNORECASE,
)
GRILL_OFF = re.compile(
    r"\b(stop grilling|enough questions?|no more questions?|stop asking|"
    r"i'?m done|just (?:build|make|do|write|create) it|"
    r"build it|make it|implement it|write the code|create the)\b",
    re.IGNORECASE,
)

GRILL_PROMPT = """\
GRILL-ME MODE — collaborative design partner.

You are a thoughtful collaborator helping the user pressure-test their plan,
not an interrogator. The goal is to strengthen their idea together, working
through the open decisions one at a time until the plan feels solid. Stay warm,
curious, and on their side — every question is in service of their success.

## Tone

- **Be a partner, not a prosecutor.** Curious and encouraging, never hostile,
  rapid-fire, or accusatory. This should feel like rubber-ducking with a sharp
  friend, not a deposition.
- **Affirm what's already good** before probing what's uncertain.
- **Frame questions as shared exploration:** "What do you think about…",
  "One thing worth deciding…", not "Why didn't you…".
- **Match their pace.** If they seem done deliberating, wrap up — don't drag it out.

## Rules

- **One question at a time.** Never bundle or overwhelm.
- **Recommend an answer** for each question so it's easy to say yes — then let the
  user accept or overrule. Always give them an easy default.
- **Resolve dependencies first** — a question whose answer makes other questions
  moot goes earlier, so you ask as few questions as possible.
- **Explore the codebase** instead of asking the user when an answer can be
  found by reading. Use `read_file` / `search_code` first — respect their time.
- **Track the tree.** State briefly what is now resolved and what remains.

## Persistence

ACTIVE until the user says "stop grilling", "enough", the tree is fully
resolved, OR the user issues a concrete build request. Do not silently revert
to flat answers mid-interview without one of those triggers.

## Build-Request Override — EXIT grilling and build

The interview exists to refine a plan, not to block work. The MOMENT the user
asks you to build, make, implement, write, create, or otherwise execute
something concrete, STOP asking questions immediately and DELIVER it with
sensible defaults. A build/execute request ENDS the interview — treat it as
"stop grilling". Never answer a build request with more questions, and never
repeat a question the user has already moved past.

## Auto-Clarity Exception

Pause grilling to: deliver a destructive-action warning, summarize where we
are, or honor an explicit user request for a non-question response. Resume
after the side trip.\
"""

GRILL_PACK = {
    "id": "grill_me",
    "name": "Grill Me (Design Partner)",
    "category": "Review",
    "description": (
        "Collaborative design review: a supportive partner walks the decision "
        "tree one friendly question at a time until the plan is stress-tested. "
        "Activates on 'grill me' / 'stress-test my plan' / 'poke holes in'."
    ),
    "when_to_use": [
        "User wants their plan or design stress-tested.",
        "Before committing to a non-trivial architecture choice.",
        "User explicitly asks 'grill me' / 'interview me'.",
    ],
    "when_not_to_use": [
        "Do not activate for simple factual questions or tiny edits.",
        "Do not activate when the user has already committed to a plan and asks for execution.",
        "Exit immediately when the user issues a concrete build/implement/create request.",
    ],
    "inputs": ["plan_or_design", "constraints", "available_codebase"],
    "outputs": [
        "ordered list of resolved decisions",
        "remaining open questions",
        "recommended answers per question",
    ],
    "required_tools": ["read_file", "search_code", "search_files"],
    "allowed_permissions": ["filesystem_read"],
    "risk_level": "low",
    "steps": [
        "Identify the top-level decision tree.",
        "Pick the question whose answer most constrains the rest.",
        "Explore the codebase before asking when possible.",
        "Ask one question with a recommended answer.",
        "Update the tree, repeat.",
    ],
    "acceptance_check": (
        "Every branch of the decision tree is either resolved or explicitly "
        "deferred with a reason. No bundled questions. Every question has a "
        "recommended answer."
    ),
    "handoff_targets": ["architect", "planner"],
    "memory_write_policy": (
        "Write resolved design decisions to semantic memory under "
        "category='design_decision' once the interview completes."
    ),
    "active_by_default": False,
}


# ── Handoff: compact the conversation into a handoff doc ─────────────


HANDOFF_TRIGGER = re.compile(
    r"\b(hand ?off|write (?:a )?handoff|continue in (?:a )?new session|"
    r"compact (?:this|the) conversation|prepare for (?:a )?fresh agent)\b",
    re.IGNORECASE,
)

HANDOFF_PROMPT = """\
HANDOFF MODE — write a compact continuation document.

Summarize the current conversation so a fresh agent (or future-you) can pick
up the work without re-reading the whole transcript.

## Required sections

1. **Goal.** One sentence: what the work is about.
2. **State so far.** Bullet list of decisions made, files changed, tests added.
3. **Open threads.** Bullet list of unresolved questions or pending tasks.
4. **Suggested next step.** The single highest-value next action.
5. **Suggested skills.** Which Augment skill packs the next session should
   invoke (e.g. `code_investigator`, `caveman_mode`, `grill_me`).
6. **References.** Paths or URLs to existing PRDs, ADRs, plans, diffs. Do NOT
   duplicate content — reference by path.

## Rules

- **Redact** API keys, passwords, PII.
- **Do not duplicate** content already captured in other artifacts.
- **Reference, don't copy.** Use file paths and line ranges.
- If the user passed an argument (e.g. "for the memory tier work"), tailor the
  doc to that scope.

## Output destination

Write the handoff document to the user's OS temporary directory, not the
current workspace. Use a name like `augment_handoff_<short_topic>_<utc>.md`.\
"""

HANDOFF_PACK = {
    "id": "handoff_writer",
    "name": "Handoff Writer",
    "category": "Operations",
    "description": (
        "Compacts the current conversation into a handoff document so a fresh "
        "agent can continue the work. Includes goal, state, open threads, "
        "suggested next step, suggested skills, and references."
    ),
    "when_to_use": [
        "End of a long session.",
        "User wants to continue work in a new session or context.",
        "Conversation is approaching context-window limits.",
        "User invokes 'handoff' / 'compact this' / 'write handoff'.",
    ],
    "when_not_to_use": [
        "Do not activate for short conversations where a handoff adds no value.",
        "Do not duplicate existing artifacts — reference them by path instead.",
    ],
    "inputs": ["conversation_history", "session_memory", "active_skills"],
    "outputs": [
        "handoff markdown file in OS temp dir",
        "goal / state / open threads / next step / references",
    ],
    "required_tools": ["write_file"],
    "allowed_permissions": ["filesystem_write"],
    "risk_level": "low",
    "steps": [
        "Read the recent conversation history and session memory.",
        "Extract goal, state, open threads, and references.",
        "Pick the single highest-value next action.",
        "Redact secrets / PII.",
        "Write the doc to the OS temp directory.",
    ],
    "acceptance_check": (
        "The doc is < 2 pages, has every required section, contains no "
        "duplicate content from referenced artifacts, and is saved outside "
        "the workspace."
    ),
    "handoff_targets": ["any"],
    "memory_write_policy": (
        "Optionally record the handoff path as a procedural-memory entry under "
        "category='handoff'."
    ),
    "active_by_default": False,
}


# ── Builder helpers ──────────────────────────────────────────────────


@dataclass
class _PocockSkill:
    pack_id: str
    title: str
    prompt: str
    trigger: re.Pattern
    off_trigger: Optional[re.Pattern] = None


_POCOCK_SKILLS: List[_PocockSkill] = [
    _PocockSkill("caveman_mode", "Caveman (Terse Mode)", CAVEMAN_PROMPT, CAVEMAN_TRIGGER, CAVEMAN_OFF),
    _PocockSkill("grill_me", "Grill Me (Design Partner)", GRILL_PROMPT, GRILL_TRIGGER, GRILL_OFF),
    _PocockSkill("handoff_writer", "Handoff Writer", HANDOFF_PROMPT, HANDOFF_TRIGGER, None),
]


def pocock_skills_for(message: str, *, explicit_ids: Optional[List[str]] = None) -> List[AdaptiveSkill]:
    """Return AdaptiveSkill records for any Pocock-style skill triggered by ``message``.

    Pass ``explicit_ids`` to force-activate one or more skills regardless of the
    message text (e.g. from a UI toggle).
    """
    explicit = {s for s in (explicit_ids or [])}
    skills: List[AdaptiveSkill] = []
    for spec in _POCOCK_SKILLS:
        active = spec.pack_id in explicit
        if not active and spec.trigger.search(message or ""):
            active = True
        # An explicit off-trigger in the same message wins.
        if active and spec.off_trigger and spec.off_trigger.search(message or ""):
            continue
        if not active:
            continue
        skills.append(
            AdaptiveSkill(
                id=f"adaptive_{spec.pack_id}",
                kind=spec.pack_id,
                title=spec.title,
                priority=0.92,  # below Holmes (0.95) but above current_build (0.9)
                signals=[f"trigger: {spec.pack_id}", f"explicit: {spec.pack_id in explicit}"],
                instructions=spec.prompt,
                metadata={"pack_id": spec.pack_id, "explicit": spec.pack_id in explicit},
            )
        )
    return skills


POCOCK_DORMANT_PACKS = [CAVEMAN_PACK, GRILL_PACK, HANDOFF_PACK]
