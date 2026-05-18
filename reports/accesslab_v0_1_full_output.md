# AccessLab v0.1 Full Benchmark Output

Generated: 2026-04-14 08:30 UTC

## Scope

- Full 20-task evaluation completed for `gemma4:e4b`
- Full 20-task evaluation completed for `gemma4:e2b`
- Both runs executed on the same host: Apple M4 Pro, 24 GB RAM, 14 logical cores
- This proves the Gemma 4 model-tier quality/latency tradeoff on the current machine
- This does not yet prove behavior on a separate aging laptop

## Run Artifacts

- Report: `reports/accesslab_v0_1_evaluation.md`
- `gemma4:e4b` summary: `reports/runs/20260414T081122Z-primary-benchmark-2026-04-14-gemma4-e4b/summary.json`
- `gemma4:e4b` results: `reports/runs/20260414T081122Z-primary-benchmark-2026-04-14-gemma4-e4b/results.csv`
- `gemma4:e2b` summary: `reports/runs/20260414T082126Z-weak-gemma4-e2-2026-04-14-gemma4-e2b/summary.json`
- `gemma4:e2b` results: `reports/runs/20260414T082126Z-weak-gemma4-e2-2026-04-14-gemma4-e2b/results.csv`

## Headline Comparison

| Model | Tasks Passed | Pass Rate | Avg TTFT | Avg Total | Avg Model Inference |
| --- | --- | --- | --- | --- | --- |
| `gemma4:e4b` | 19 / 20 | 95% | 10.74s | 13.31s | 13.18s |
| `gemma4:e2b` | 16 / 20 | 80% | 17.66s | 22.29s | 22.16s |

## Delta

- `gemma4:e4b` beat `gemma4:e2b` by 3 tasks
- `gemma4:e4b` was faster by 6.92s on average TTFT
- `gemma4:e4b` was faster by 8.98s on average total response time
- On both runs, latency was dominated by model inference rather than retrieval or code execution

## Category Breakdown

| Model | Docs | Code | Accessibility |
| --- | --- | --- | --- |
| `gemma4:e4b` | 8 / 8 | 7 / 8 | 4 / 4 |
| `gemma4:e2b` | 7 / 8 | 7 / 8 | 2 / 4 |

## Failed Tasks

### `gemma4:e4b`

| Task | Result | Notes |
| --- | --- | --- |
| `code-08` | fail | Patch passed tests, but the explanation did not clearly reference runtime or test evidence |

### `gemma4:e2b`

| Task | Result | Notes |
| --- | --- | --- |
| `doc-06` | fail | Expected quoted evidence/content was missing |
| `code-08` | fail | Patch passed tests, but the explanation did not clearly reference runtime or test evidence |
| `a11y-01` | fail | Helpful and grounded, but too verbose for the output target |
| `a11y-02` | fail | Helpful and grounded, but too verbose for the output target |

## Latency Breakdown

| Model | Avg TTFT | Median TTFT | Avg Total | Retrieval | Prompt Build | Model Inference | Post-Processing | Code Execution |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `gemma4:e4b` | 10.74s | 10.34s | 13.31s | 0.00s | 0.00s | 13.18s | 0.00s | 0.06s |
| `gemma4:e2b` | 17.66s | 16.99s | 22.29s | 0.00s | 0.00s | 22.16s | 0.00s | 0.07s |

## Shared Failure Taxonomy

- `missed_expected_content`: 3 task(s)
- `weak_evidence_reference`: 2 task(s)
- `verbosity`: 2 task(s)

## What The Benchmark Shows

- Grounded worksheet Q&A is working reliably
- Citation behavior is working reliably
- Beginner code repair is strong on both Gemma 4 tiers when judged by patched test outcomes
- The main visible gap is not correctness first; it is latency and evidence/verbosity discipline

## Next 3 Fixes

- Tighten retrieved context size so the strongest chunk dominates the prompt
- Make the code-tutor prompt quote failing test or runtime lines explicitly before proposing a fix
- Reduce default output length and cap extra detail unless the user explicitly asks for more

## Bottom Line

- Best quality on this host: `gemma4:e4b`
- Best current fully measured fallback in the Gemma 4 family: `gemma4:e2b`
- Remaining benchmark gap: rerun the same 20-task pack on a separate weak device to validate the aging-hardware claim
