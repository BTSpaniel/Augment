from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from augment.config import AppConfig
from augment.context.budget import ContextBudgetAllocator
from augment.context.memory import ChatMessage, MemoryStore
from augment.context.tokens import (
    count_tokens,
    is_available as tiktoken_is_available,
    truncate_to_token_budget,
)
from augment.context.zones import (
    Zone,
    ZoneLayout,
    default_zone_layout,
    zone_layout_from_config,
)


@dataclass
class ContextStats:
    original_chars: int
    final_chars: int
    truncated: list[str]
    sections: list[dict] | None = None


class ContextBuilder:
    """Assemble the system prompt with model-aware budgeting + U-zones.

    The builder collects every named section (identity, agent_soul,
    memory, recent_history, …), measures their *actual* sizes, then asks
    :class:`augment.context.budget.ContextBudgetAllocator` to compute a
    final per-section token allowance. Sections are then truncated to fit
    and emitted in the order specified by :class:`ZoneLayout`:

    * :data:`Zone.SMART_TOP` → high-attention header.
    * :data:`Zone.DUMB_MIDDLE` → low-attention belly (bulk reference).
    * :data:`Zone.SMART_BOTTOM` → high-attention footer.

    The total input budget is derived from the active model's context
    window via the optional ``context_window_provider`` callback (set by
    :class:`augment.service.AugmentApp`). When no callback is configured
    the builder falls back to the legacy hard cap in
    ``config.context.total_budget_chars``.
    """

    # Approximate chars-per-token (Luna parity heuristic).
    _CHARS_PER_TOKEN = 4

    def __init__(
        self,
        config: AppConfig,
        memory: MemoryStore,
        *,
        context_window_provider: Optional[Callable[[], int]] = None,
        active_model_provider: Optional[Callable[[], str]] = None,
    ) -> None:
        """Construct a ContextBuilder.

        Args:
            config: The AppConfig.
            memory: MemoryStore for the episodic memory section.
            context_window_provider: Optional callback returning the
                active provider's context window in tokens. When given,
                the assembled prompt scales with the model
                (target_utilization * (window - max_output_tokens)).
            active_model_provider: Optional callback returning the
                active model id (e.g. "gpt-4o", "claude-sonnet-4-...").
                Used to pick the right tiktoken encoding for accurate
                token counting. When None, falls back to o200k_base.
        """
        self._config = config
        self._memory = memory
        self._context_window_provider = context_window_provider
        self._active_model_provider = active_model_provider
        self._zones: ZoneLayout = zone_layout_from_config(
            getattr(config.context, "zones", None) or {}
        ) if getattr(config.context, "zones", None) else default_zone_layout()
        self._last_stats = ContextStats(0, 0, [], [])
        self._last_prompt = ""
        self._last_budget_tokens = 0
        self._last_window_tokens = 0

    # ── Public API ───────────────────────────────────────────────────

    def build(
        self,
        *,
        message: str,
        history: list[ChatMessage],
        mailbox_context: str = "",
        skills_context: str = "",
        soul_context: str = "",
        identity_override: str = "",
        mind_context: str = "",
        plan_context: str = "",
        memory_tiers: str = "",
        scratchboard: str = "",
        turn_state: str = "",
        user_model: str = "",
        message_ledger: str = "",
        project_conventions: str = "",
        user_rules: str = "",
        coding_contract: str = "",
    ) -> str:
        # ── 1) Collect raw section content ───────────────────────────
        raw_sections: dict[str, str] = {
            "identity":             identity_override or self._identity(),
            "project_conventions":  project_conventions,
            "user_rules":           user_rules,
            "coding_contract":      coding_contract,
            "agent_soul":           soul_context,
            "active_plan":          plan_context,
            "tool_policy":          self._tool_policy(),
            "tools":            "",                         # caller doesn't pass yet
            "adaptive_skills":  skills_context,
            "memory":           self._memory.context_block(),
            "memory_tiers":     memory_tiers,
            "user_model":       user_model,
            "mind_state":       mind_context,
            "runtime":          self._runtime(),
            "workspace":        self._workspace(),
            "scratchboard":     scratchboard,
            "session_mailbox":  mailbox_context,
            "turn_state":       turn_state,
            "message_ledger":   message_ledger,
            "recent_history":   self._history(history),
        }

        # ── 2) Compress + measure ────────────────────────────────────
        # Real token counts via tiktoken (cached per content hash) when
        # available; falls back to chars/4 if tiktoken isn't installed.
        active_model = self._resolve_active_model()
        cleaned: dict[str, str] = {}
        actuals: dict[str, int] = {}
        original_chars = 0
        for name, value in raw_sections.items():
            clean = _compress(value)
            cleaned[name] = clean
            actuals[name] = count_tokens(clean, active_model)
            original_chars += len(clean)

        # ── 3) Allocate proportionally ───────────────────────────────
        total_budget_tokens = self._resolve_total_budget_tokens()
        self._last_budget_tokens = total_budget_tokens

        allocator = ContextBudgetAllocator(
            total_budget_tokens,
            overrides=self._config.context.budget_allocations or None,
        )
        result = allocator.finalize(actuals)

        # ── 4) Truncate each section to its final allocation ─────────
        # Token-accurate truncation via tiktoken when available — the
        # output lands on an exact token boundary so we never accidentally
        # cleave a multi-byte character or push the prompt past the
        # model's real context window.
        truncated: list[str] = []
        section_records: list[dict] = []
        rendered_in_zone: dict[Zone, list[str]] = {z: [] for z in Zone}

        for name in self._zones.sections_in_order():
            clean = cleaned.get(name, "")
            zone = self._zones.zone_for(name) or Zone.DUMB_MIDDLE
            if not clean:
                section_records.append(_section_record(name, zone))
                continue
            budget_tokens = result.tokens_for(name)
            actual_tokens = actuals.get(name, 0)
            original_len = len(clean)
            section_truncated = False
            if budget_tokens > 0 and actual_tokens > budget_tokens:
                # Reserve a few tokens for the truncation marker line.
                marker = f"\n[...truncated {name}]"
                marker_tokens = count_tokens(marker, active_model)
                slice_budget = max(1, budget_tokens - marker_tokens)
                clean = truncate_to_token_budget(clean, slice_budget, active_model).rstrip() + marker
                truncated.append(name)
                section_truncated = True
            elif budget_tokens == 0 and actual_tokens > 0:
                # Allocator gave this section zero — drop it entirely
                # rather than silently letting it through.
                truncated.append(name)
                section_truncated = True
                clean = ""
            if clean:
                rendered_in_zone[zone].append(clean)
            final_tokens = count_tokens(clean, active_model) if clean else 0
            section_records.append(_section_record(
                name, zone,
                budget_tokens=budget_tokens,
                original_tokens=actual_tokens,
                final_tokens=final_tokens,
                original_chars=original_len,
                final_chars=len(clean),
                truncated=section_truncated,
                preview=clean[:280],
            ))

        # ── 5) Emit zones in order ───────────────────────────────────
        # Smart-top first, dumb-middle next, smart-bottom last so the
        # U-shape attention curve picks up the right sections.
        rendered: list[str] = []
        for zone in (Zone.SMART_TOP, Zone.DUMB_MIDDLE, Zone.SMART_BOTTOM):
            rendered.extend(rendered_in_zone[zone])
        output = "\n\n".join(rendered)

        # ── 6) Legacy hard cap (safety belt) ─────────────────────────
        legacy_cap = int(self._config.context.total_budget_chars or 0)
        if legacy_cap and len(output) > legacy_cap:
            output = output[:legacy_cap].rstrip() + "\n[...truncated context]"
            truncated.append("global")

        self._last_stats = ContextStats(original_chars, len(output), truncated, section_records)
        self._last_prompt = output
        return output

    def stats(self) -> dict[str, object]:
        # The total_budget reported here is the *effective* budget in
        # characters (so it's directly comparable to ``final_chars``).
        # The legacy hard cap is also exposed for completeness.
        effective_chars = max(
            self._last_budget_tokens * self._CHARS_PER_TOKEN,
            int(self._config.context.total_budget_chars or 0),
        )
        active_model = self._resolve_active_model()
        # Avoid importing tokens.encoding_name_for_model at module load.
        from augment.context.tokens import encoding_name_for_model
        return {
            "original_chars": self._last_stats.original_chars,
            "final_chars": self._last_stats.final_chars,
            "truncated": list(self._last_stats.truncated),
            "sections": list(self._last_stats.sections or []),
            "total_budget": effective_chars,
            "total_budget_tokens": int(self._last_budget_tokens),
            "context_window_tokens": int(self._last_window_tokens),
            "target_utilization": float(self._config.context.target_utilization),
            "max_output_tokens": int(self._config.context.max_output_tokens),
            "buffer_pct": float(self._config.context.buffer_pct),
            "warn_threshold": float(self._config.context.warn_threshold),
            "compact_threshold": float(self._config.context.compact_threshold),
            # Tokenizer diagnostics — useful for the UI to confirm we are
            # counting tokens accurately for the active model rather than
            # falling back to the chars/4 heuristic.
            "tokenizer": {
                "available": bool(tiktoken_is_available()),
                "encoding": encoding_name_for_model(active_model),
                "active_model": active_model,
            },
        }

    def last_prompt(self) -> str:
        """Return the most-recently-built system prompt (or empty string)."""
        return self._last_prompt

    # ── Internals ────────────────────────────────────────────────────

    def _resolve_active_model(self) -> str:
        """Best-effort lookup of the active model id (for tokenizer choice).

        Returns an empty string when no callback is configured; downstream
        :func:`augment.context.tokens.count_tokens` then falls back to the
        DEFAULT_ENCODING (o200k_base) which is a sane universal default.
        """
        if not self._active_model_provider:
            return ""
        try:
            return str(self._active_model_provider() or "")
        except Exception:
            return ""

    def _resolve_total_budget_tokens(self) -> int:
        """Compute the effective input-token budget for one prompt build.

        Formula::

            effective = (window − max_output) × target_utilization

        Where ``window`` is the active provider's context window in
        tokens (auto-resolved by the settings store, or falling back to
        the legacy ``total_budget_chars`` cap converted to tokens).
        """
        window = 0
        if self._context_window_provider:
            try:
                window = int(self._context_window_provider() or 0)
            except Exception:
                window = 0
        self._last_window_tokens = window

        max_output = max(0, int(self._config.context.max_output_tokens or 0))
        target_util = float(self._config.context.target_utilization or 1.0)
        target_util = max(0.05, min(1.0, target_util))

        if window > 0:
            effective_input = max(0, window - max_output)
            return max(1024, int(effective_input * target_util))

        # Fallback: convert the legacy char cap to tokens.
        legacy_chars = int(self._config.context.total_budget_chars or 0)
        return max(1024, legacy_chars // self._CHARS_PER_TOKEN)

    def _identity(self) -> str:
        return """[AUGMENT]
You are Augment, a reasoning-first coding assistant.

Reasoning order every turn:
1. ABDUCTIVE — state the most plausible root cause (and one alternative) before
   acting. Never skip this on "obvious" bugs.
2. CAUSAL — trace symptom → proximate → root cause. Patch root, not symptom.
3. DUAL-PROCESS GATE — if the task spans ≥2 files or ≥3 tool calls, write a
   one-sentence-per-step plan first; re-check direction after every 3 calls.
4. METACOGNITIVE GATE — before any mutation: (a) root cause or symptom?
   (b) regression risk? (c) simpler approach?
5. INDUCTIVE — same error class twice? Fix the general case; record the lesson.
6. UNCERTAINTY — confidence < ~60%? Say "I'm not sure" and name the evidence
   that would resolve it. Never present a guess as a certainty.

Then act: use tools when they materially improve correctness; cite evidence by
file path + line range. Do not claim files were changed unless a write/edit tool
succeeded. One loop, no mesh, no dashboards."""

    def _runtime(self) -> str:
        return f"[RUNTIME]\nUnix time: {time.time():.0f}"

    def _workspace(self) -> str:
        return (
            f"[WORKSPACE]\n"
            f"Root: {self._config.workspace_root}\n"
            f"Scratch (default write dir): {self._config.scratch_root}\n"
            "Reads/edits resolve under Root. New `write_file` calls land under "
            "`<scratch>/<session_id>/` UNLESS the user explicitly directs "
            "output elsewhere — in which case call `set_output_dir(path)` once "
            "to record that directive, after which relative writes go to that dir."
        )

    def _history(self, history: list[ChatMessage]) -> str:
        """Emit the most-recent-first history block.

        We deliberately don't truncate here — the ``recent_history`` slot
        is a *residual* section in the allocator (absorbs leftover budget),
        so the budget itself decides how many turns survive. With a 200k
        context window the allocator gives this section ~98k tokens; on
        an 8k-window model the same section gets ~3k tokens. Hard-coded
        caps used to short-circuit that scaling.
        """
        if not history:
            return ""
        lines = ["[RECENT HISTORY]"]
        for item in history:
            lines.append(f"{item.role}: {item.content}")
        return "\n".join(lines)

    def _tool_policy(self) -> str:
        return """[TOOL POLICY]
Use tools only when useful. Prefer read-only tools before editing.
File paths are relative to the workspace root.
For multiple independent reads/searches, use a <tool_plan> JSON array.
Mutation tools run sequentially.
Final answers should summarise: actions taken, evidence found, and remaining risk.

Tool-use reasoning gates:
- SCENE FIRST: before any tool call on a live error, capture the exact
  error/trace/test output in your response. Never mutate before the scene is
  documented.
- Before the first tool call, state what you expect to find (and why). This is
  the abductive step — it makes wrong assumptions visible early.
- Use search_code / search_files before run_command for text search.
- REPRODUCE before hypothesising: if the failure cannot be reproduced, say so.
  Do not form a hypothesis about an unreproducible failure.
- Generate ≥2 candidate hypotheses; test the most specific one with a read-only
  action before writing any fix.
- HYPOTHESIS SURVIVAL: never write a fix until at least one test confirms the
  hypothesis. Refute rather than confirm — actively look for evidence against it.
- After reading evidence, re-evaluate: does it confirm the hypothesis or suggest
  a different root cause?
- On the last tool call before an edit, run the metacognitive check:
  root cause or symptom? regression risk? simpler approach?

[CODING DISCIPLINE HARD GATE]
Before calling write_file for any code file, include the required audit header,
section markers for files over 100 lines, and docs for public functions/classes
in the content itself. Non-compliant code writes are rejected; do not rely on a
later edit to add the comments."""


def _section_record(
    name: str,
    zone: Zone,
    budget_tokens: int = 0,
    original_tokens: int = 0,
    final_tokens: int = 0,
    *,
    original_chars: int = 0,
    final_chars: int = 0,
    truncated: bool = False,
    preview: str = "",
) -> dict:
    """Build the per-section diagnostic record.

    Exposes both tokens (the real budget unit) and chars (kept for
    backward compat with the existing UI/bleep panel). ``budget`` is
    kept as a char-denominated alias of ``budget_tokens * 4`` so older
    callers that read ``record["budget"]`` keep working.
    """
    return {
        "name": name,
        "zone": zone.value,
        "budget_tokens": int(budget_tokens),
        "original_tokens": int(original_tokens),
        "final_tokens": int(final_tokens),
        # Legacy char-denominated alias — UI bleep panel reads these.
        "budget": int(budget_tokens) * 4,
        "original_chars": int(original_chars),
        "final_chars": int(final_chars),
        "truncated": bool(truncated),
        "preview": preview,
    }


def _compress(text: str) -> str:
    lines: list[str] = []
    previous_empty = False
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            if not previous_empty:
                lines.append("")
            previous_empty = True
            continue
        lines.append(stripped)
        previous_empty = False
    return "\n".join(lines).strip()
