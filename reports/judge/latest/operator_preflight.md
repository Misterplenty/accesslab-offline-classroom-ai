# AccessLab Operator Preflight

- Generated at: 2026-05-18T20:51:46.315554+00:00
- Overall status: Ready

## Deployment snapshot

- Mode: School AI box
- Profile: Strong
- Class space: judge demo class
- Training capture: Opt-in local capture on
- Summary: one stronger LAN machine serving many classroom browsers

## Runtime snapshot

- Backend: Ollama local runtime
- Model: gemma4:e4b
- Runtime: Ollama local runtime (gemma4:e4b)
- Validation only: False
- Supported profiles: grounded-qa, beginner-python-repair, accessibility-smoke

## Retrieval snapshot

- Requested mode: Hybrid
- Effective mode: Hybrid
- Semantic status: Ready (ok)
- Semantic index: Indexed
- Semantic chunks backfilled during preflight: 0
- Semantic counts: 5/5/5/0

## Queue snapshot

- Max concurrent jobs: 1
- Queue depth: 0
- Active jobs: 0
- Waiting jobs: 0
- Active mix: None
- Waiting mix: None

## Preflight checks

- Gemma 4 runtime: pass — Ready with `gemma4:e4b`. Ollama local runtime (gemma4:e4b)
- EmbeddingGemma model: pass — EmbeddingGemma is ready and the shared embedding index is usable. Ready with `embeddinggemma`.
- Semantic retrieval: pass — Hybrid active. Ready with `embeddinggemma`.
- OCR fallback: pass — OCR extras are available locally. rapidocr (ready, dpi=200)
- Writable local storage: pass — Storage is writable in <workspace>/data/judge-demo. <workspace>/data/judge-demo/accesslab-preflight-p8e8dvgp.tmp
- Database state: pass — SQLite quick_check passed for <workspace>/data/judge-demo/accesslab.db. 5 document(s), 2 QA session(s), 1 code session(s), 2 label(s), and 0 captured example(s) in judge demo class.
- Deployment mode: info — School AI box one stronger LAN machine serving many classroom browsers
- Class space: info — judge demo class Shared material and saved-session scope for this deployment.
- Concurrent job limit: info — 1 capacity slot(s) Queue depth 0 with 0 active, 0 waiting, and 1 slot(s) currently free.
- Training-data capture: info — Opt-in local capture on Structured QA/code examples are being captured locally for future tuning export.
