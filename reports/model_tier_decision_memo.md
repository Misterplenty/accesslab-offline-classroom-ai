# Model-tier decision memo (e4b vs e2b under constrained proxy)

**Date:** 2026-04-19
**Hardware:** MacBook Pro M4 Pro, 24 GB RAM, macOS 24.6.0, Apple Metal GPU
**Ollama:** 0.21.0 (older 0.11.10 build cannot load `gemma4` GGUF; see env note)
**Models:** `gemma4:e4b` (8.0 B, Q4_K_M), `gemma4:e2b` (5.1 B, Q4_K_M)
**Eval pack:** AccessLab Eval v0.1 — 20 tasks (8 worksheet/QA, 8 code, 4 accessibility), warm
**Defaults applied:** QA prompt = `baseline`, code-tutor prompt = `hybrid` (newly promoted)
**Sampling:** temperature 0.0, seed 7
**Proxy knobs:** `num_thread=4`, `num_gpu=0` (CPU-only), `num_ctx=2048`

---

## 1. Measured facts (full 20-task sweep)

| run        | model      |  pass  | parse | TTFT (s) | total (s) | prefill (s) | decode (s) | outTok |
|------------|------------|--------|-------|---------:|----------:|------------:|-----------:|-------:|
| e4b ref    | gemma4:e4b | 20/20  | 20/20 |   10.39  |   12.36   |     0.79    |    10.85   |  616.3 |
| e2b ref    | gemma4:e2b | 19/20  | 20/20 |    5.52  |    6.70   |     0.41    |     5.26   |  484.7 |
| e4b proxy  | gemma4:e4b | 19/20  | 20/20 |   20.76  |   24.36   |     3.28    |    20.30   |  611.4 |
| e2b proxy  | gemma4:e2b | 17/20  | 20/20 |    9.55  |   11.56   |     1.80    |     9.08   |  480.9 |

Per-category pass / parse:

| run        | worksheet/QA | code      | accessibility |
|------------|:------------:|:---------:|:-------------:|
| e4b ref    | 8/8 / 8/8    | 8/8 / 8/8 | 4/4 / 4/4     |
| e2b ref    | 7/8 / 8/8    | 8/8 / 8/8 | 4/4 / 4/4     |
| e4b proxy  | 8/8 / 8/8    | 7/8 / 8/8 | 4/4 / 4/4     |
| e2b proxy  | 7/8 / 8/8    | 8/8 / 8/8 | 2/4 / 4/4     |

Per-category latency (avg seconds, avg output tokens):

| run        | category                    | TTFT  | total | decode | outTok |
|------------|-----------------------------|------:|------:|-------:|-------:|
| e4b ref    | accessibility/output-format | 13.15 | 15.09 |  13.65 |  794   |
| e4b ref    | beginner-python-bug-fix     |  6.78 |  9.28 |   8.13 |  475   |
| e4b ref    | worksheet/local-doc         | 12.61 | 14.08 |  12.17 |  668   |
| e2b ref    | accessibility/output-format |  5.30 |  6.44 |   5.60 |  530   |
| e2b ref    | beginner-python-bug-fix     |  4.61 |  6.19 |   5.24 |  473   |
| e2b ref    | worksheet/local-doc         |  6.53 |  7.34 |   5.10 |  474   |
| e4b proxy  | accessibility/output-format | 28.90 | 32.74 |  28.14 |  836   |
| e4b proxy  | beginner-python-bug-fix     | 13.96 | 18.49 |  15.74 |  484   |
| e4b proxy  | worksheet/local-doc         | 23.49 | 26.02 |  20.94 |  626   |
| e2b proxy  | accessibility/output-format | 10.23 | 12.35 |   9.66 |  518   |
| e2b proxy  | beginner-python-bug-fix     |  8.45 | 10.82 |   8.99 |  472   |
| e2b proxy  | worksheet/local-doc         | 10.32 | 11.91 |   8.88 |  471   |

Specific task-level failures (only 4 across 80 task-runs):

| run        | task    | category                    | parse | tests  | failure mode                                                |
|------------|---------|-----------------------------|-------|--------|-------------------------------------------------------------|
| e2b ref    | doc-06  | worksheet/local-doc         | yes   | n/a    | expected keywords missing (QA content miss, structure OK)   |
| e4b proxy  | code-06 | beginner-python-bug-fix     | yes   | passed | tests passed, but diagnosis lacked evidence vocabulary      |
| e2b proxy  | doc-06  | worksheet/local-doc         | yes   | n/a    | same QA keyword miss as e2b ref                             |
| e2b proxy  | a11y-01 | accessibility/output-format | yes   | n/a    | content correct but exceeded verbosity target               |
| e2b proxy  | a11y-02 | accessibility/output-format | yes   | n/a    | content correct but exceeded verbosity target               |

Parse OK held at **20/20 in every run**, including the smaller model under stress. The hybrid code-tutor structure (XML `<patched_code>` + `<diagnosis>` anchors) survived every condition tested.

---

## 2. Engineering judgment

**Q1: Does hybrid remain the correct default for code tutor after the full-pack run?**
Yes. With QA fixed on `baseline` and code on `hybrid` (the new defaults), the e4b warm full-pack scored 20/20 / 20/20 with no regression in any category. Hybrid did not destabilize QA; QA only lost a single task on e2b (a content-miss, not a structural fault). Recommend keeping the new defaults.

**Q2: How much quality does e2b lose vs e4b?**
- Reference (Metal GPU on): e2b loses **1 of 20** tasks (5 pp). The miss is a worksheet QA keyword match, not a structural failure.
- Constrained proxy (CPU-only, num_thread=4, num_ctx=2048): e2b loses **3 of 20** (15 pp). 1 QA content miss + 2 accessibility verbosity failures. **Code 8/8 stayed perfect on e2b in both conditions.**
- Quality degradation pattern: e2b's weakness under stress is **output-discipline / verbosity** in accessibility prompts, not bug-fixing. The accessibility tasks are the hardest because they have explicit per-paragraph length budgets the model has to honor.

**Q3: How much speed does e2b gain vs e4b?**
- Reference: e2b is **~2× faster** across the board: TTFT −47 % (10.39 → 5.52 s), total −46 %, decode −52 %, output tokens −21 %.
- Proxy: e2b is **~2.1× faster**: TTFT −54 % (20.76 → 9.55 s), total −53 %, decode −55 %, output tokens −21 %.
- The 2× ratio is consistent across reference and proxy, which suggests it reflects the model size rather than the constraint profile.

**Q4: Under constrained proxy conditions, is e2b the likely future weak-tier candidate?**
Yes — but with two qualifiers.
- *Yes* because: e2b is the only model whose proxy-condition latency stays in conversational range (avg total 11.56 s). e4b proxy averages 24.36 s and tops 32 s on accessibility, which is over a beginner's patience threshold. e2b's structural reliability (parse 20/20) and code quality (8/8) hold under the stress profile.
- *Qualifier 1*: The verbosity regression on accessibility under stress is real (-2 tasks) and would likely amplify on truly slow hardware. Future work should tighten the accessibility prompt to enforce shorter paragraphs deterministically, not via the model.
- *Qualifier 2*: This is a proxy on Apple silicon; see Section 4.

**Q5: Should e4b be treated as the stronger-device / local-hub candidate?**
Yes. e4b ref is the only configuration that scored 20/20. Its proxy run still hit 19/20 but at >20 s per task — too slow to be a primary user-facing path on any constrained device. e4b is a good fit when a teacher is running it on their own laptop or a classroom hub machine with GPU acceleration.

**Q6: Are there hidden regressions caused by the hybrid default flip?**
None observed in the data. The full-pack e4b ref run (the most comparable to the previous baseline study) scored 20/20 with hybrid on code + baseline on QA, and the previous baseline study also scored 20/20. Decode improved on the code subset (8/8 in both, but with lower decode and output tokens — see `reports/runs/20260419T124826Z*` for baseline-on-code). No QA regression was introduced because the QA path was not changed.

---

## 3. Recommendations

1. **Keep the new defaults.** `code = hybrid`, `qa = baseline`. Changing one of these would either lose the structural reliability (going back to experimental on code) or risk QA regressions (flipping QA to anything else).
2. **Treat e2b as the prospective weak-tier candidate** for a real-device sweep. It is the only model whose constrained-proxy latency on this machine remains in a usable range, and it carries the structural reliability of the hybrid prompt cleanly.
3. **Treat e4b as the local-hub / stronger-device candidate.** Document this in the demo material so a teacher running on a school server uses e4b, while the field-device build defaults to e2b.
4. **Before any deployment claim**, run the same eval pack on a real weak device. Until then, the e2b candidacy is *evidence-based engineering judgment*, not deployment proof.
5. **Targeted next prompt-work** (only if Section 4 weak-device runs show the same pattern): tighten the `accessibility/output-format` prompt to enforce per-paragraph length budgets explicitly. Two of the three e2b-proxy failures were verbosity, not content. This is a prompt-discipline fix, not a model fix, and is reversible.

---

## 4. What remains unproven (deployment claims this memo does NOT support)

This sweep was run on a MacBook Pro M4 Pro with 24 GB RAM. The proxy knobs (`num_thread=4`, `num_gpu=0`, `num_ctx=2048`) only stress-test the model **relative to itself on this hardware**.

The following are explicitly *not* proven by these numbers:

- That e2b is fast enough on a real low-spec laptop (8 GB RAM, slow SATA SSD, no GPU).
- That e2b is usable on a Raspberry Pi 5 4 GB or similar SBC.
- That e2b is usable on any phone-class CPU.
- That cold-start `load_duration_sec` on a slow disk will stay reasonable (the e4b GGUF is 9.6 GB, e2b is 7.2 GB; loading those off a slow eMMC dominates first-request latency).
- That accessibility-format quality holds when CPU memory bandwidth is genuinely constrained (vs the M4's 273 GB/s LPDDR5X).

A real weak-device benchmark is still required to upgrade any of these from "engineering judgment" to "measured deployment evidence."

---

## 5. Reproduction commands

```bash
# Confirm Ollama >= 0.21 and both models present
curl -s http://127.0.0.1:11434/api/version
ollama list | grep gemma4

# Full-pack confirmation (defaults: qa=baseline, code=hybrid)
make eval-fullpack DEVICE_LABEL=m4pro

# Single-model proxy runs
make eval-proxy-e4b DEVICE_LABEL=m4pro
make eval-proxy-e2b DEVICE_LABEL=m4pro

# One-shot four-run sweep used to produce this memo
make eval-tier-sweep DEVICE_LABEL=m4pro

# Or call the script directly
python scripts/run_model_tier_sweep.py --device-label m4pro
```

Per-run summaries from the sweep underlying this memo:

- e4b ref:    `reports/runs/20260419T130427Z-m4pro-gemma4-e4b-sweep-e4b-ref-20260419-150427/summary.json`
- e2b ref:    `reports/runs/20260419T130835Z-m4pro-gemma4-e2b-sweep-e2b-ref-20260419-150427/summary.json`
- e4b proxy:  `reports/runs/20260419T131049Z-m4pro-gemma4-e4b-sweep-e4b-proxy-20260419-150427/summary.json`
- e2b proxy:  `reports/runs/20260419T131856Z-m4pro-gemma4-e2b-sweep-e2b-proxy-20260419-150427/summary.json`

---

## 6. Environment note

The host previously had Ollama 0.11.10 installed via a stale DMG; it returned HTTP 500 for `gemma4` with `error loading model architecture: unknown model architecture: 'gemma4'`. Upgrading to **Ollama 0.21.0** (`https://ollama.com/download/Ollama-darwin.tgz`) made both models load correctly using the existing blobs in `~/.ollama/models/`. The README's "Known limitations" section now requires Ollama ≥ 0.21 for the `gemma4` family.
