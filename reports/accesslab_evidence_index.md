# AccessLab Evidence Index

Use this file to find the shortest path from a claim to the evidence that supports it.

## Canonical Reviewer Docs

| Topic | Start here |
| --- | --- |
| What AccessLab is now | [`reports/accesslab_validated_prototype_status.md`](accesslab_validated_prototype_status.md) |
| How to demo it | [`reports/accesslab_demo_runbook.md`](accesslab_demo_runbook.md) |
| Minimum validation commands | [`reports/accesslab_core_validation_commands.md`](accesslab_core_validation_commands.md) |
| Release-readiness read | [`reports/accesslab_release_readiness_checklist.md`](accesslab_release_readiness_checklist.md) |

## Decision Memos And Primary Evidence

| Topic | Primary source | Supporting evidence |
| --- | --- | --- |
| Model-tier decision (`e4b` vs `e2b`) | [`reports/model_tier_decision_memo.md`](model_tier_decision_memo.md) | `reports/runs/20260419T130427Z-m4pro-gemma4-e4b-sweep-e4b-ref-20260419-150427/summary.json`, `reports/runs/20260419T130835Z-m4pro-gemma4-e2b-sweep-e2b-ref-20260419-150427/summary.json`, `reports/runs/20260419T131049Z-m4pro-gemma4-e4b-sweep-e4b-proxy-20260419-150427/summary.json`, `reports/runs/20260419T131856Z-m4pro-gemma4-e2b-sweep-e2b-proxy-20260419-150427/summary.json` |
| Deployment-profile defaults | [`reports/deployment_profiles_decision_memo.md`](deployment_profiles_decision_memo.md) | `app/config.py`, `app/main.py`, `Makefile`, `/healthz` |
| Weak-tier QA discipline behavior | [`reports/weak_tier_a11y_discipline_decision_memo.md`](weak_tier_a11y_discipline_decision_memo.md) | `reports/runs/20260419T140207Z-m4pro-gemma4-e2b-weak-fullpack-tightened-20260419/summary.json`, `reports/runs/20260419T140651Z-m4pro-accessibility-output-format-gemma4-e4b-strong-a11y-sanity-20260419/summary.json` |
| OCR fallback choice | [`reports/ocr_decision_memo.md`](ocr_decision_memo.md) | `scripts/run_ocr_smoke.py`, `tests/test_document_ingest.py`, `requirements-ocr.txt` |

## Retrieval Evidence

There is no standalone retrieval decision memo yet. Current retrieval evidence lives in:

- `app/services/retrieval.py`
- `app/services/semantic.py`
- `tests/test_retrieval.py`
- `scripts/run_retrieval_smoke.py`
- Historical architecture/background docs retained in [`reports/accesslab_current_state_2026_04_19.md`](accesslab_current_state_2026_04_19.md) and [`reports/accesslab_v0_1_detailed_report.md`](accesslab_v0_1_detailed_report.md)

What it supports:

- Retrieval remains SQLite-first
- FTS5 stays in the path
- Semantic assist is optional and local-only
- Hybrid retrieval can backfill embeddings into SQLite without a separate vector database

## Code-Runner Hardening Evidence

There is no standalone hardening decision memo yet. Current hardening evidence lives in:

- `app/services/code_runner.py`
- `app/services/code_runner_bootstrap.py`
- `tests/test_code_runner.py`
- `scripts/run_code_runner_hardening_smoke.py`
- Historical background retained in [`reports/accesslab_current_state_2026_04_19.md`](accesslab_current_state_2026_04_19.md) and [`reports/accesslab_v0_1_detailed_report.md`](accesslab_v0_1_detailed_report.md)

What it supports:

- Temp execution directories
- Env scrubbing
- Runtime denial of network access, child process creation, and writes outside the temp run directory
- Best-effort hardening only, not a production secure sandbox claim

## Legacy Status Reports

These remain useful for history but are no longer the primary entry points for new reviewers:

- [`reports/accesslab_current_state_2026_04_19.md`](accesslab_current_state_2026_04_19.md)
- [`reports/accesslab_v0_1_evaluation.md`](accesslab_v0_1_evaluation.md)
- [`reports/accesslab_v0_1_detailed_report.md`](accesslab_v0_1_detailed_report.md)
- [`reports/accesslab_v0_1_executive_summary.md`](accesslab_v0_1_executive_summary.md)
- [`reports/accesslab_v0_1_full_output.md`](accesslab_v0_1_full_output.md)
