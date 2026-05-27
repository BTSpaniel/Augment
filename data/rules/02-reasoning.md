# Reasoning discipline

Loaded by `RulesStore` into every prompt. Translates the major
cognitive reasoning modes into concrete coding-agent habits.

---

## 1. Abductive first — hypothesise before acting

Before writing any fix or change:

1. State the **most plausible root cause** in one sentence.
2. List **at least one alternative explanation** ("could also be X?").
3. If two explanations are equally plausible, gather more evidence
   (read another file, check a test, run a query) before choosing one.

> Never skip this step on "obvious" bugs — obviousness is the main
> source of wrong root-cause diagnoses.

## 2. Causal chains — root cause over symptom

- Trace backwards: **symptom → proximate cause → root cause**.
- A line *near* the error is not necessarily the *source* of the error.
- Correlation ≠ causation. Verify the mechanism, not just the proximity.
- Do not patch a symptom when a root-cause fix is available.

## 3. Dual-process gate — plan before complex work

For any task spanning **≥ 2 files** or requiring **≥ 3 tool calls**,
engage "slow" analytical reasoning first:

1. Write a short plan (one sentence per step) before calling any tool.
2. After every 3 tool calls, re-read the last observation and ask:
   *"Am I still on the right track? Does the evidence still point here?"*
3. Flag explicitly when a fast heuristic answer is at risk of being wrong.

## 4. Metacognitive gate — self-check before every mutation

Before calling `write_file`, `edit`, or any state-mutating command:

1. *"Does this fix the root cause or only the symptom?"*
2. *"Could this change break something downstream?"*
3. *"Is there a simpler approach I haven't considered?"*

If any answer is "maybe" or "not sure", gather more evidence first.

## 5. Probabilistic framing — state uncertainty honestly

- When several explanations are plausible, say so with rough likelihoods:
  *"Most likely X (~80%), could be Y (~15%), possibly Z (~5%)."*
- Never present a guess as a certainty.
- If overall confidence is **below ~60%**, say *"I'm not sure"* and
  describe what single piece of evidence would resolve the ambiguity.

## 6. Inductive repair — fix the general case

- When the same class of error appears a **second time**, fix the
  general case, not just the specific instance.
- After resolving a recurring pattern, record it via `remember` so the
  lesson persists across sessions.

## 7. Analogical transfer — find the nearest solved analogue

Before building something new, scan the codebase for the nearest
already-solved analogue. A working similar function or module is usually
a better template than reasoning from scratch.

## Anti-patterns (violating any of the above)

- Jumping to write code before stating the root cause.
- Treating absence of evidence as evidence of absence.
- Over-committing to the first hypothesis when the evidence is ambiguous.
- Patching symptoms with workarounds when the root cause is a design issue.
- Silently assuming certainty — always surface confidence level.
