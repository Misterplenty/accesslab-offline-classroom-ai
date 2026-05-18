# Operator Preflight

Run this before a classroom demo or a school-box session:

```bash
python scripts/run_operator_preflight.py
```

Artifacts:

- `reports/operator_preflight_latest.json`
- `reports/operator_preflight_latest.md`
- `reports/system_status_snapshot_latest.json`
- `reports/deployment_mode_snapshot_latest.md`

## What it checks

- Gemma 4 runtime readiness
- EmbeddingGemma model availability
- effective semantic retrieval state
- OCR fallback availability
- writable local storage
- SQLite quick-check status
- current deployment mode
- current class-space label
- queue guardrail and current queue depth
- training-capture mode
- runtime capability report for the active backend

## How to read the result

- `Ready`: core runtime, storage, and database checks passed
- `Needs attention`: the app can still run, but an operator-facing subsystem is degraded
- `Blocked`: at least one critical check failed and the box should be fixed before class

## Common follow-up

- Missing Gemma 4 model:
  run `ollama pull gemma4:e4b` or `ollama pull gemma4:e2b`
- Missing EmbeddingGemma:
  run `ollama pull embeddinggemma`
- OCR unavailable:
  install `requirements-ocr.txt`
- Wrong deployment framing:
  set `ACCESSLAB_DEPLOYMENT_MODE` and `ACCESSLAB_CLASS_SPACE` explicitly
- Wrong class-space assignment:
  use the admin System view migration form or `scripts/manage_class_space.py`
