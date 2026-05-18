# Deployment profiles decision memo

**Date:** 2026-04-19
**Scope:** Codifying the model-tier evidence into an explicit application-level
deployment-profile concept and documenting the assumptions behind each
profile so a future maintainer can reproduce or revise them.
**Companion:** [`reports/model_tier_decision_memo.md`](model_tier_decision_memo.md)

---

## 1. What this branch did

Two evidence-based deployment profiles are now first-class in the code,
configuration, Makefile, README, and UI:

| Profile  | Default model | Selected because…                                      |
|----------|---------------|--------------------------------------------------------|
| `strong` | `gemma4:e4b`  | Only configuration that scored 20/20 on the warm full-pack reference run; appropriate for stronger laptops, teacher devices, and local-hub demos. |
| `weak`   | `gemma4:e2b`  | Only model whose constrained-proxy total latency stays in conversational range (avg 11.56 s) while keeping parse 20/20 and code 8/8; intended as the future weak-device candidate. |
| `custom` | (operator)    | Implicit label when `ACCESSLAB_MODEL` is set to a model outside the profile mapping. |

The two validated prompt defaults are now pinned in code constants:

- `DEFAULT_QA_PROMPT_VARIANT = "baseline"` (`app/services/qa.py`)
- `DEFAULT_CODE_TUTOR_PROMPT_VARIANT = "hybrid"` (`app/services/code_tutor.py`)

The harness still exposes both per-service variants
(`--qa-prompt-variant`, `--code-prompt-variant`) so regressions can be
benchmarked without touching the running app.

---

## 2. Why these defaults

### 2.1 Why `weak = gemma4:e2b`

From the model-tier sweep on the M4 Pro (warm, defaults: QA=baseline,
code-tutor=hybrid, temperature 0.0, seed 7):

| run        | model      | pass  | parse | TTFT (s) | total (s) | decode (s) |
|------------|------------|-------|-------|---------:|----------:|-----------:|
| e4b ref    | gemma4:e4b | 20/20 | 20/20 |   10.39  |   12.36   |    10.85   |
| e2b ref    | gemma4:e2b | 19/20 | 20/20 |    5.52  |    6.70   |     5.26   |
| e4b proxy  | gemma4:e4b | 19/20 | 20/20 |   20.76  |   24.36   |    20.30   |
| e2b proxy  | gemma4:e2b | 17/20 | 20/20 |    9.55  |   11.56   |     9.08   |

Under the proxy stress profile, `e2b` is the only candidate whose total
latency stays under ~12 s on average and keeps parse reliability at 20/20.
`e4b` proxy averages 24 s and tops 32 s on accessibility tasks, which is
over a beginner's patience threshold for an offline assistant. Among the
two models tested, `e2b` is therefore the better-evidence candidate for
constrained-device deployment.

### 2.2 Why `strong = gemma4:e4b`

`e4b` is the only model that scored 20/20 / 20/20 on the warm reference
run with the new defaults, with no per-category regression. The code path
is also more forgiving on `e4b` because the larger model holds the hybrid
structure cleanly even on edge cases. For a teacher running AccessLab on
their own laptop or a school-hub machine with GPU acceleration, `e4b` is
the safer default.

### 2.3 Why `code-tutor = hybrid`

Per the A/B/C benchmark on the 8 beginner-python-bug-fix tasks (warm,
gemma4:e4b):

| variant       | pass | parse | TTFT  | total  | decode  | outTok |
|---------------|------|-------|-------|--------|---------|--------|
| baseline      | 8/8  | 8/8   | 8.41s | 12.57s | 11.35s  | 657.8  |
| experimental  | 2/8  | 6/8   | 6.23s | 7.87s  | 6.79s   | 398.5  |
| hybrid        | 8/8  | 8/8   | 6.73s | 9.18s  | 8.08s   | 475.4  |

Hybrid restored full pass + parse (which experimental had broken) while
keeping ~28 % of the decode and token reduction. The hybrid prompt has
strong `<patched_code>` and `<diagnosis>` XML anchors plus explicit
evidence-vocabulary directives, which together survive every constrained
condition tested in the model-tier sweep (parse stayed 20/20 even on
e2b-proxy).

### 2.4 Why `qa = baseline`

The full XML-tag baseline prompt is the only QA variant validated end-to-end
across all 20 tasks. The experimental variant trades parse reliability for
output-token reduction; the hybrid variant only changes the code-tutor path.
Keeping QA on baseline isolates the hybrid promotion to the code path, which
is what the A/B/C work actually validated.

---

## 3. What this memo does NOT prove

These limitations matter; they are deliberately not papered over by the
profile mechanism.

1. **The weak profile is proxy-validated, not real-device-validated.** All
   of the constrained measurements were taken on a MacBook Pro M4 Pro with
   24 GB RAM. The proxy knobs (`num_thread=4`, `num_gpu=0`, `num_ctx=2048`)
   stress the model relative to itself on this hardware; they do not turn
   an Apple-silicon laptop into a Chromebook, a Raspberry Pi, or a phone.
2. **Cold-start `load_duration_sec` on slow storage is unmeasured.** The
   e4b GGUF is ~9.6 GB and e2b is ~7.2 GB. On a slow eMMC or SATA SSD,
   cold-start latency could dominate the first request and is not captured
   by the proxy sweep.
3. **Accessibility-format quality on genuinely memory-bandwidth-limited
   hardware is unmeasured.** Two of the three e2b-proxy failures were
   accessibility verbosity regressions; this would likely amplify on a
   real weak device with much lower memory bandwidth than M4 LPDDR5X.
4. **No claim is made about phone-class CPUs or single-board computers.**
5. **The "custom" profile is exactly that** — when an operator sets
   `ACCESSLAB_MODEL` to anything outside the profile mapping, AccessLab
   makes no quality or latency claims about the resulting configuration.

A real weak-device sweep against the same eval pack is required to upgrade
any of these from "engineering judgment" to "measured deployment evidence."

---

## 4. How profile selection is implemented

The mechanism is intentionally small and explicit (see `app/config.py`):

1. Read `ACCESSLAB_MODEL` from the environment. If set, it always wins as
   the active model.
2. Read `ACCESSLAB_DEPLOYMENT_PROFILE`. If set to `strong`, `weak`, or
   `custom`, use it as the profile label. When `ACCESSLAB_MODEL` is unset,
   the profile picks the model from `PROFILE_MODELS`.
3. If neither is set, default to the strong profile and `gemma4:e4b`.
4. If `ACCESSLAB_MODEL` is set but `ACCESSLAB_DEPLOYMENT_PROFILE` is not,
   the profile is inferred from the model: `gemma4:e4b → strong`,
   `gemma4:e2b → weak`, anything else → `custom`.

The active profile and active model are surfaced in three places:

- **Home page status panel** (`app/templates/home.html`) — visible to any
  operator who opens the app.
- **`/healthz` JSON response** (`app/main.py`) — for ops scripting.
- **Per-run summary JSON** — already capable via the existing `--model`
  knob; profile-pinned Makefile targets (`eval-fullpack-strong`,
  `eval-fullpack-weak`, `eval-proxy-strong`, `eval-proxy-weak`) keep the
  benchmark workflow honest.

---

## 5. Reproduction

```bash
# Run the app in either profile
make run-strong          # gemma4:e4b
make run-weak            # gemma4:e2b

# Or pin in .env
echo "ACCESSLAB_DEPLOYMENT_PROFILE=weak" >> .env
make run

# Override the model explicitly (badge will show "custom" if outside the map)
ACCESSLAB_MODEL=mistral:7b-instruct make run

# Profile-pinned full-pack benchmarks
make eval-fullpack-strong DEVICE_LABEL=my-machine
make eval-fullpack-weak   DEVICE_LABEL=my-machine

# Profile-pinned constrained-proxy runs (M4 Pro proxy knobs apply)
make eval-proxy-strong DEVICE_LABEL=my-machine
make eval-proxy-weak   DEVICE_LABEL=my-machine

# Inspect what the running app thinks it is
curl http://127.0.0.1:8000/healthz
```

---

## 6. When to revise this memo

Revise when **any** of the following becomes available:

- A real weak-device sweep (e.g. low-RAM Chromebook, Raspberry Pi 5 4 GB,
  or a phone-class device) using the same eval pack.
- A new gemma4 variant that lands between e2b and e4b on the size/quality
  curve.
- A retrieval or prompt change that materially shifts the per-category
  failure pattern that informed the e2b weak-tier candidacy (currently:
  accessibility verbosity is the failure mode under stress, not
  bug-fixing).
- An Ollama runtime change that changes prefill or decode characteristics
  enough to invalidate the latency ratios used here.

The profile mechanism is intentionally reversible: changing the
`PROFILE_MODELS` map in `app/config.py` is a one-line edit, and explicit
overrides via `ACCESSLAB_MODEL` continue to work regardless.
