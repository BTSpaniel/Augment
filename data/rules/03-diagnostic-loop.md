# Diagnostic loop discipline

Loaded by `RulesStore` into every prompt. Defines the ordered 7-step
diagnostic process for debugging, investigation, and root-cause work.
Complements `02-reasoning.md` (reasoning types); this file covers
*process order*, not reasoning mode.

---

## The 7-step loop

Apply this sequence for every bug, error, or unexpected behaviour:

### Step 1 — OBSERVE: preserve the scene first

Before touching *anything*:
- Capture the exact error message, stack trace, failing test output,
  or unexpected behaviour in a note or scratchpad.
- Record the current state: which version, which env, which inputs.
- Do **not** edit code or run mutations until you have this baseline.

> Analogy: investigators secure the crime scene before collecting
> evidence. A contaminated scene destroys the investigation.

### Step 2 — MODEL: state the expected behaviour explicitly

Write one sentence: *"Given [inputs / state], I expect [outcome]."*
This makes the contradiction visible in step 3.

### Step 3 — CONTRADICT: state "Expected X, got Y"

Explicitly write: *"Expected [X], got [Y]."*
Never skip this — the contradiction sentence is the anchor for the
hypothesis in step 4. If you can't state it precisely, go back to
step 1 and gather more observations.

### Step 4 — HYPOTHESISE: reproduce before hypothesising

1. **Reproduce the issue first.** A hypothesis about an unreproducible
   failure is speculation, not diagnosis.
2. Generate **at least two** candidate hypotheses; do not stop at the
   first plausible one (fixation / tunnel-vision trap).
3. State each as a testable prediction: *"If hypothesis H is true,
   then [observable X] should change when [action Y] is taken."*

### Step 5 — TEST: hypothesis must survive reality before fix

- Test the hypothesis with the *minimum* invasive action (read a
  log, add a temporary print, run an isolated test — not a code edit).
- "Never touch the fix until the hypothesis survives reality."
- If the test refutes the hypothesis, return to step 4.
  Do not patch forward from a refuted hypothesis.

### Step 6 — REVISE: fix the confirmed root cause only

- Fix the root cause identified in the surviving hypothesis.
- Do not fix adjacent symptoms unless they have their own confirmed
  hypotheses.
- Run the full test suite after the fix to verify no regression.

### Step 7 — DOCUMENT: close the loop

After resolving:
1. Record the root cause (one sentence).
2. Record the evidence path that confirmed it.
3. Record the fix and any regression risk.
4. If this is a recurring class of failure, add it to memory via
   `remember` (inductive repair from `02-reasoning.md`).

---

## Bias guards specific to diagnosis

| Bias | Symptom | Guard |
|---|---|---|
| **Recency** | "The last change must have caused it" | Verify with git log + bisect; don't assume |
| **Fixation** | Stuck on the first plausible cause | Mandate ≥2 hypotheses in step 4 |
| **Tunnel vision** | Ignoring evidence that contradicts the theory | Re-read *all* observations before step 6 |
| **Confirmation** | Seeking only evidence that confirms the chosen hypothesis | Actively try to *refute* each hypothesis in step 5 |
| **Guilt-presumptive** | Concluding before evidence is collected | No fix before step 5 passes |

---

## FMEA-style pre-mortem for new code

Before writing a new module or function, briefly enumerate failure modes:
- What happens on null / empty input?
- What happens at the boundary (off-by-one, overflow, underflow)?
- What if the downstream service is slow or unavailable?
- What if this is called concurrently?

This is not exhaustive analysis; it is a 2-minute mental sweep that
surfaces the most likely failure modes before they become bugs.

---

## Anti-patterns (diagnostic loop violations)

- Editing code before reproducing the failure.
- Jumping to a fix before the hypothesis survives a test.
- Stopping at the first hypothesis that "sounds right."
- Forgetting to re-run the full suite after a targeted fix.
- Closing a bug without documenting root cause and evidence.
- Losing the original error state before capturing it.
