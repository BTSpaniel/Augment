# Augment — Agent Conventions

This file is auto-loaded by Augment's `ConventionsLoader` into every
prompt's `[PROJECT CONVENTIONS]` section. Keep it terse and durable —
hard rules that apply to **every** action you take in this workspace.

If you want one-session rules (e.g., "all new code in TypeScript for the
next 20 minutes"), use the per-session coding contract API:
`PUT /api/sessions/{sid}/coding-contract`.

## Stack

- Python 3.12+, FastAPI, uvicorn, asyncio
- Vanilla HTML/CSS/JS (no frameworks; no build step)
- pytest for tests
- Provider-agnostic LLM layer (OpenAI-compatible + Codex bridge)

## Architecture

- `augment/` — Python backend (FastAPI service, providers, loop, mind, skills, tools)
- `ui/` — Frontend (vanilla HTML/CSS/JS, no React/Vue)
- `data/` — Runtime data (gitignored; settings, memory, scratchpads)
- `tests/` — pytest, mirrors the module path under `augment/`

## Hard rules

1. **Comment every new file**: a 4-12 line header banner that names the
   file's purpose + the major sections inside.
2. **Section comments**: split files >100 lines into commented sections
   (`# ── Section ──`, `<!-- Section -->`, `/* === Section === */`).
3. **Docstrings on every public function/class**: first line = one-line
   summary; longer functions get a doc block explaining intent + args.
4. **Inline comments explain WHY, never WHAT**. The code already shows
   what; comment the non-obvious *reason* it does it that way.
5. **No new dependencies** without explicit approval. Vanilla stdlib +
   FastAPI + httpx + pyyaml + pydantic + tiktoken are the baseline.
6. **Tests required** for every non-trivial Python change — mirror the
   module under `tests/test_<module>.py`.
7. **Never rewrite a whole file** unless the user explicitly approves;
   the edit-receipt gate will block you. Use small surgical edits.
8. **No 24k-char context cap**. Budget scales with the model window
   automatically via `augment/context/budget.py`.

## Style anchors

- Python: 4-space indents, type hints on every public signature, PEP 8.
- JS: 2-space indents, single quotes, semicolons; ES2020+ OK.
- CSS: 2-space indents, BEM-ish (`.lab-section__element--modifier`).
- HTML: 2-space indents, lowercase tags, attribute order: id, class, data-*, the rest.

## Output style (chat replies)

- Lead with the answer / outcome, then the supporting detail.
- Use bullet lists when ≥3 items; otherwise use prose.
- Cite tool evidence by file path with line ranges, e.g.
  `augment/context/budget.py:45-170`.
- For long answers (>15 lines), end with a one-paragraph summary.

## Reasoning

- **Abductive first**: before any fix, state the most plausible root
  cause and one alternative. Gather evidence before committing to one.
- **Causal chains**: trace symptom → proximate cause → root cause.
  Don't patch symptoms when a root-cause fix is available.
- **Dual-process gate**: tasks spanning ≥ 2 files require a written
  plan first; re-check direction after every 3 tool calls.
- **Metacognitive gate**: before any mutation ask — (1) root cause or
  symptom? (2) regression risk? (3) simpler approach?
- **Inductive repair**: same class of error twice → fix the general
  case and record the lesson via `remember`.
- **State uncertainty**: if confidence is below ~60%, say
  "I'm not sure" and describe what evidence would resolve it.
- **Analogical transfer**: scan the codebase for the nearest solved
  analogue before building something from scratch.

## Anti-patterns

- Dumping raw tool output without a short framing sentence.
- "Sure!" / "Great idea!" / "I'll help with that" preambles.
- Claiming a file was changed when no write/edit tool succeeded.
- Re-stating user intent verbatim before answering.
- Jumping to write code before stating the root cause.
- Presenting a guess as a certainty (always surface confidence level).
