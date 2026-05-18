# Weak-tier QA accessibility discipline decision memo

**Date:** 2026-04-19
**Scope:** Tightening weak-tier (`gemma4:e2b`) accessibility/output-format
discipline without broadening into retrieval, OCR, sandboxing, or model-tier
configuration.
**Companion:** [`reports/model_tier_decision_memo.md`](model_tier_decision_memo.md),
[`reports/deployment_profiles_decision_memo.md`](deployment_profiles_decision_memo.md)

---

## 1. The narrow problem

The model-tier sweep ([`reports/model_tier_decision_memo.md`](model_tier_decision_memo.md))
showed `gemma4:e2b` as the only candidate whose constrained-proxy total
latency on the M4 Pro stayed in conversational range (avg 11.56 s) while
keeping parse 20/20 and code 8/8. The same sweep also flagged the one
remaining failure mode: **e2b under proxy stress fails the
`accessibility/output-format` category** (2/4) even though grounding,
parse, and citation correctness are all intact.

Inspecting the per-task outputs from the proxy run
(`reports/runs/20260419T131856Z-m4pro-gemma4-e2b-sweep-e2b-proxy-…`)
isolated two distinct micro-failures:

| Task     | Failure mode (default discipline) | Mechanism                                                                                                                              |
|----------|-----------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| a11y-01  | `more_detail` exceeded 120 words and used bullet lists across multiple paragraphs. | The baseline prompt's "keep paragraphs short" instruction is too soft for e2b under constrained knobs; the model defaults to "explain everything I know". |
| a11y-02  | `short_answer` parsed as 2+ sentences. | The model placed citations as a *trailing* token group: `"...one item at a time. [S1] [S2]"`. The parser counts that as a second sentence, even though the prose is a single sentence. |

Both `a11y-03` and `a11y-04` already passed under the default discipline,
so the failure mode is genuinely about discipline / formatting, not about
content quality.

The strong tier (`gemma4:e4b`) hits 4/4 on the same category under both
reference and proxy knobs, so the fix needs to be **weak-tier-only**.

---

## 2. The narrow fix

A single new constant in `app/services/qa.py`:

```python
WEAK_TIER_QA_DISCIPLINE_SUFFIX = """
Output discipline (this device runs a small model; brevity is required):
- Keep <short_answer> to ONE simple sentence.
- Place every citation inside the sentence it supports, before the final
  period. For example: "...goes through the list one item at a time [S1]."
- Do NOT add a separate trailing line of citation tags after the sentence.
- Keep <more_detail> to AT MOST two short sentences in ONE paragraph. Leave
  it empty if <short_answer> already answers the question.
- Do NOT add bullet lists, numbered steps, headings, or extra examples.
- Prefer the shortest correct answer. Stop as soon as the question is
  answered.
""".rstrip()
```

The suffix is appended to `GROUNDED_QA_SYSTEM_PROMPT` only when a new
service-level knob `qa_discipline_profile` is set to `"weak"`. The
existing baseline prompt is otherwise untouched. The `experimental`
prompt variant intentionally bypasses the suffix because its purpose is
to be a clean prefill A/B target.

Wiring (deliberately small):

| Layer                | Behavior                                                                                                                                                                                |
|----------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `app/services/qa.py` | New `qa_discipline_profile` constructor arg; new `_resolve_system_prompt` helper.                                                                                                       |
| `app/config.py`      | New `resolve_qa_discipline_profile` + `Settings.qa_discipline_profile`. Defaults to `auto` (binds to deployment profile). `ACCESSLAB_QA_DISCIPLINE_PROFILE` overrides for triage/experiments. |
| `app/main.py`        | Passes `settings.qa_discipline_profile` straight through to `GroundedQAService`. `/healthz` now reports the resolved value.                                                              |
| Eval harness         | New `--qa-discipline-profile {auto,default,weak}` flag (defaults to `auto`, infers from active model). Reported in `summary.json` and per-row CSV.                                        |
| Makefile             | `eval-weak-a11y-default`, `eval-weak-a11y-tightened`, `eval-weak-a11y-ab`, `eval-weak-fullpack-tightened` for focused A/B and full-pack confirmation runs.                                |

Reverting at the operator level requires no code change:
`ACCESSLAB_QA_DISCIPLINE_PROFILE=default` turns the suffix off while
keeping the weak deployment profile and the e2b model.

---

## 3. Measured A/B results

All runs on M4 Pro, warm, proxy knobs (`num_thread=4`, `num_gpu=0`,
`num_ctx=2048`), `temperature=0.0`, `seed=7`, defaults
(QA=baseline, code-tutor=hybrid).

### 3.1 Focused weak-proxy accessibility A/B (4 tasks)

| Run                                               | Discipline | Pass     | Parse  | TTFT (s) | Total (s) | Decode (s) | Avg prompt tok | Avg output tok |
|---------------------------------------------------|------------|----------|--------|---------:|----------:|-----------:|---------------:|---------------:|
| `weak-a11y-default-20260419` (baseline reproduce) | default    | **2/4**  | 4/4    |  10.814  |   12.867  |     9.537  |          869.5 |          518.0 |
| `weak-a11y-tightened-20260419`                    | weak       | **4/4**  | 4/4    |  11.720  |   13.197  |    10.441  |         1018.5 |          565.8 |

- **Pass rate +50 pp** on the targeted category.
- Parse holds at 4/4. Grounding and citation correctness hold at yes/yes
  on every task in both runs.
- Latency cost: **+0.3 s avg total**.
- Token cost: **+149 prompt tokens** (the suffix itself, ~17 % of the
  baseline prompt) and **+48 output tokens** on average. Per-task
  output tokens actually went **down** on a11y-01 (637 → 596); the
  +48 average is driven by a11y-02 (535 → 648), where the previously
  truncated short_answer + bullet list was replaced by a clean
  one-sentence short answer plus a compliant two-sentence more_detail.

### 3.2 Per-task transcript for the two previously-failing tasks

a11y-01 (`Explain question 3 in screen-reader-friendly output…`):

| Field          | Default (FAIL)                                                                                                              | Tightened (PASS)                                                                                                            |
|----------------|------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------|
| `short_answer` | `"The command for a for loop, for example, ‘for item in numbers:’, means the program goes through the list one item at a time [S1]."` | `"The command for a for loop means the program goes through the list one item at a time [S1]."`                              |
| `more_detail`  | 4 paragraphs incl. a bullet list (~125 words). Triggered `too_verbose`.                                                      | 2 sentences in 1 paragraph (~36 words). Compliant.                                                                            |

a11y-02 (`Explain what 'item' means…`):

| Field          | Default (FAIL)                                                                                                                                                              | Tightened (PASS)                                                                                                                |
|----------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------|
| `short_answer` | `"The variable item represents the next value from the list during the loop. The program goes through the list one item at a time. [S1] [S2]"` — trailing `[S1] [S2]` parsed as a 2nd "sentence". | `"The variable item represents the next value from the list as the program goes through it one item at a time [S1]."` — single sentence with the citation inside it. |
| `more_detail`  | One sentence + an example. OK.                                                                                                                                              | Two short sentences in one paragraph. OK.                                                                                      |

The tightened output is exactly what the suffix asked for, and it is
exactly what the eval pack's accessibility constraints accept.

### 3.3 Full-pack weak-proxy confirmation (20 tasks)

`weak-fullpack-tightened-20260419`, e2b proxy, `qa_discipline_profile=weak`:

| Category                       | Prior baseline (default) | Tightened     | Δ pass  | Avg output tok Δ |
|--------------------------------|--------------------------|---------------|--------:|-----------------:|
| accessibility/output-format    | 2/4                      | **4/4**       |  +2     |             +48  |
| beginner-python-bug-fix        | 8/8                      | 8/8           |   0     |              +0  |
| worksheet/local-doc            | 7/8                      | **8/8**       |  +1     |              +1  |
| **Total**                      | **17/20** (85 %)         | **20/20** (100 %) |  +3 |                  |

Latency on the full pack:

| Metric                    | Prior baseline (e2b proxy) | Tightened (e2b proxy + weak discipline) | Δ      |
|---------------------------|---------------------------:|----------------------------------------:|-------:|
| avg TTFT (s)              |                       9.55 |                                  9.692  |  +0.14 |
| avg total (s)             |                      11.56 |                                 11.329  |  −0.23 |
| avg decode (s)            |                       9.08 |                                  9.016  |  −0.06 |
| avg prompt tokens         |                          — |                                  811.4  |        |
| avg output tokens         |                          — |                                  490.8  |        |

The full pack is *slightly faster* with the discipline suffix, because
the +149-token prompt overhead on QA tasks is offset by shorter, more
disciplined outputs (decode is the dominant latency contributor under
proxy knobs). The suffix is not active on the code-tutor path
(`prompt_variant=hybrid`), so code latency is unchanged.

The single `missed_expected_content` flag in `top_failure_modes` is on
`doc-08`, where the answer is correct and grounded but the keyword check
prefers a different exact phrase. It is not a regression — the same
softer flag appears in the baseline run too — and the task still passes.

### 3.4 Strong-tier sanity check

`strong-a11y-sanity-20260419`, e4b reference knobs, `--qa-discipline-profile=auto`:

| Field                        | Value                                  |
|------------------------------|----------------------------------------|
| Resolved discipline          | `default` (auto resolved correctly)    |
| Pass / parse                 | 4/4 / 4/4                              |
| Avg prompt tokens            | 869.5 (**identical** to prior e4b ref) |
| Avg output tokens            | 793.8                                  |

The prompt token count is byte-identical to the original e4b reference
run, confirming the strong-tier prompt is unchanged. The `auto` →
`default` resolution rule fires correctly for the strong profile.

---

## 4. Trade-offs we accepted

- **+149 prompt tokens per QA call when the suffix is active.** This is
  the cost of an explicit rule list in plain English, and it adds about
  +0.3 s avg latency on accessibility-heavy turns under proxy stress
  (decode dominates, so prompt overhead is small). On the full pack the
  overhead is more than recovered by shorter outputs.
- **The suffix only attaches to the baseline QA prompt.** The
  experimental prompt deliberately stays minimal so it remains a clean
  A/B target; an operator who switches to the experimental variant on
  a weak install would lose the discipline. This is documented in the
  `_resolve_system_prompt` docstring.
- **The discipline profile is decoupled from the deployment profile.**
  In day-to-day operation `auto` makes them move together, but
  `ACCESSLAB_QA_DISCIPLINE_PROFILE` exists so an operator can disable
  the suffix for triage without changing the active model.

We deliberately did **not**:

- change the retrieval backend, OCR, sandboxing, or any model knob
  (`num_thread`, `num_ctx`, etc.) — out of scope for this branch.
- change the strong-tier prompt or its defaults.
- change the parsing / scoring rules. The fix targets the model's
  output, not the eval pack's checks.
- introduce a hard-coded post-processing rewrite that would silently
  reshape model output. The existing `enforce_accessible_layout`
  helper is unchanged.

---

## 5. Reverting

Three layers, in increasing scope:

1. **Per-run (eval harness):** add `--qa-discipline-profile default`.
2. **Per-process (running app):** set
   `ACCESSLAB_QA_DISCIPLINE_PROFILE=default` before starting `uvicorn`.
   The active value is reflected in `/healthz`
   (`qa_discipline_profile` and `qa_discipline_explicitly_set`).
3. **Code-level:** delete `WEAK_TIER_QA_DISCIPLINE_SUFFIX` and the
   `qa_discipline_profile` plumbing. The unit tests in
   `tests/test_qa_service.py` and `tests/test_deployment_profile.py`
   would fail in a way that points exactly at the deletion site.

---

## 6. Recommendation

Adopt the auto-binding default (`weak` deployment profile → `weak`
discipline). The measured trade-off is:

- +50 pp pass rate on the previously-failing accessibility category
  under the weak-tier proxy stress profile;
- +12.5 pp incidental gain on `worksheet/local-doc` (the same brevity
  rules also help the worksheet QA path);
- 0 regression on `beginner-python-bug-fix` (the suffix is not
  attached to the code-tutor path);
- prompt-tokens cost confined to the e2b path;
- strong-tier path byte-identical to the validated baseline.

This brings the weak-tier full-pack score from **17/20 (85 %) → 20/20
(100 %)** under proxy knobs, matching the strong-tier full-pack score
under reference knobs, while leaving the strong-tier path and all other
subsystems untouched.

---

## 7. Run inventory

| Purpose                              | Run id                                                                                          | Pass         | Parse |
|--------------------------------------|-------------------------------------------------------------------------------------------------|-------------:|------:|
| Weak-proxy a11y baseline (reproduce) | `20260419T135912Z-m4pro-accessibility-output-format-gemma4-e2b-weak-a11y-default-20260419`      | 2/4 (50 %)   | 4/4   |
| Weak-proxy a11y tightened            | `20260419T140008Z-m4pro-accessibility-output-format-gemma4-e2b-weak-a11y-tightened-20260419`    | 4/4 (100 %)  | 4/4   |
| Weak-proxy full-pack tightened       | `20260419T140207Z-m4pro-gemma4-e2b-weak-fullpack-tightened-20260419`                            | 20/20 (100 %) | 20/20 |
| Strong-tier a11y sanity (auto)       | `20260419T140651Z-m4pro-accessibility-output-format-gemma4-e4b-strong-a11y-sanity-20260419`     | 4/4 (100 %)  | 4/4   |

All four are in `reports/runs/`. Re-run any of them with the matching
Makefile target listed in `Makefile` (`eval-weak-a11y-default`,
`eval-weak-a11y-tightened`, `eval-weak-fullpack-tightened`, etc.).
