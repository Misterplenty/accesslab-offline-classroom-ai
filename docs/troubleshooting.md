# Troubleshooting

## Gemma 4 not ready

Symptoms:

- preflight shows Gemma 4 blocked
- `/healthz` reports `llm_ready=false`

Checks:

- is `ollama serve` running?
- did you pull the configured model?
- is `ACCESSLAB_MODEL` pinned to `gemma4:e4b` or `gemma4:e2b` only?

## EmbeddingGemma missing

Symptoms:

- hybrid retrieval degrades to lexical only
- admin view shows `Model not installed`

Fix:

```bash
ollama pull embeddinggemma
```

## OCR unavailable

Symptoms:

- scanned PDFs index with warnings
- admin view shows OCR optional / unavailable

Fix:

```bash
python -m pip install -r requirements-ocr.txt
```

## Wrong class space

Symptoms:

- uploaded materials do not appear in the current deployment
- saved session URLs stop reopening in the expected scope

Fix:

- confirm `ACCESSLAB_CLASS_SPACE`
- preview migration:

```bash
python scripts/manage_class_space.py --from old-space --to new-space --include-sessions
```

- apply only after checking the dry run:

```bash
python scripts/manage_class_space.py --from old-space --to new-space --include-sessions --apply
```

## Optimizing School-Box Performance

Symptoms:

- Queue wait grows during peak usage
- Slower response times

Response:

- Tune `ACCESSLAB_MAX_CONCURRENT_JOBS` according to the host device's RAM and CPU capabilities.
- Pre-upload and index materials (OCR) before class rather than during live Q&A sessions.
- Ensure the host device is adequately cooled and plugged into power for maximum local inference speed.

## Training export looks sparse

Symptoms:

- export JSONL has sessions but no capture records
- admin System view shows `Opt-in local capture off`

Response:

- normal saved-session export still works without capture
- turn on `ACCESSLAB_TRAINING_CAPTURE_ENABLED=on` only if you want structured future-tuning capture records as well
- use teacher/admin labels on saved QA/code URLs before exporting if you want a smaller review subset
