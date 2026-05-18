# Benchmarking

AccessLab keeps benchmarking small, explicit, and reproducible.

## Device tiers

Run summaries now record a reporting tier for the host:

- `teacher-laptop`
- `standard-laptop`
- `school-box-host`
- `edge-validation-device`
- `constrained-proxy`
- `other`

These are reporting categories, not claims that all devices in a category will behave identically.

`standard-local-laptop` is accepted as an alias for `standard-laptop`. Unknown tiers resolve to `other` in generated artifacts rather than silently pretending support.

## Preset Matrix

The reproducible preset manifest is `evals/benchmark_presets.json`.

Run one preset:

```bash
python scripts/run_benchmark_preset.py --preset grounded-qa-hybrid-e4b --device-label teacher-m2
```

Available deployment-oriented presets:

- `grounded-qa-lexical-e2b`
- `grounded-qa-hybrid-e2b`
- `grounded-qa-hybrid-e4b`
- `grounded-qa-semantic-e4b`
- `python-repair-e2b`
- `python-repair-e4b`
- `school-box-shared-queued-load`
- `accessibility-smoke`
- `semantic-unavailable-fallback`

## Core comparisons

### Retrieval

Compare lexical-only against hybrid retrieval:

- lexical baseline: SQLite FTS5 only
- semantic diagnostic: EmbeddingGemma-only retrieval when installed
- hybrid path: SQLite FTS5 plus EmbeddingGemma when operational

Recommended command:

```bash
make eval-retrieval-compare DEVICE_LABEL=local-machine MODEL=gemma4:e4b
python scripts/run_retrieval_smoke.py
```

Each run now records:

- deployment mode
- requested retrieval mode
- effective retrieval mode
- runtime backend
- model tier (`E2B` / `E4B`)
- inferred deployment profile label
- device tier label
- semantic status code and label
- semantic index lifecycle status
- chunk coverage counts
- queue wait when observable
- peak memory when observable
- JSON summary and Markdown summary
- combined benchmark bundle JSON
- concise summary brief
- comparison readouts for E2B/E4B, lexical/hybrid, runtime/backend, and school-box queue runs when matching summaries are supplied
- stable device-tier comparison artifacts:
  - `reports/device_tier_comparison_latest.md`
  - `reports/device_tier_comparison_latest.json`

### Gemma 4 model tiers

Compare the two supported user-facing models:

- `gemma4:e4b`
- `gemma4:e2b`

Recommended commands:

```bash
make eval-fullpack-strong DEVICE_LABEL=local-machine
make eval-fullpack-weak DEVICE_LABEL=local-machine
make eval-preset-school-box DEVICE_LABEL=school-box-host
python scripts/run_model_tier_sweep.py --device-label local-machine
```

### Accessibility

Run the browser-flow smoke:

```bash
make smoke-a11y
```

This produces:

- `reports/a11y_smoke_latest.json`
- `reports/a11y_smoke_latest.md`

Preset:

```bash
make eval-preset-a11y-smoke
```

## Key metrics exposed in run summaries

- task pass rate
- answer support rate
- citation presence rate
- citation precision
- weak-retrieval abstention quality
- code pass rate
- wall-clock latency
- queue wait time when observable
- peak memory when observable
- prefill/decode timing when available
- prompt/output token counts when available
- Ollama-native prefill/decode timing when available

## Human-readable summary

Combine eval and accessibility artifacts into one Markdown summary:

```bash
python scripts/build_benchmark_summary.py \
  --summary reports/runs/<run-a>/summary.json \
  --summary reports/runs/<run-b>/summary.json \
  --a11y reports/a11y_smoke_latest.json
```

This also writes:

- `reports/accesslab_benchmark_summary.md`
- `reports/accesslab_benchmark_highlights.md`
- `reports/accesslab_benchmark_bundle.json`

## Operator snapshot pairing

For a judge or deployment packet, pair the benchmark summary with:

```bash
python scripts/run_operator_preflight.py
python scripts/build_device_tier_comparison.py --summary reports/runs/<run>/summary.json
python scripts/run_school_box_load.py --jobs 12 --max-concurrent-jobs 1
python scripts/build_judge_bundle.py
```

