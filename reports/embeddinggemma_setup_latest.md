# EmbeddingGemma Setup Verification

- Generated at: 2026-05-18T10:14:10.882421+00:00
- Model: `embeddinggemma`
- Setup command: `ollama pull embeddinggemma`
- Overall status: pass
- Present in active Ollama store: True
- `/healthz` reachable: True
- `/healthz` semantic provider ready: True
- `/healthz` semantic retrieval ready: False
- `/healthz` semantic status: indexing_unavailable

## Remediation

- Run `ollama pull embeddinggemma`.
- Run `ollama list` from the same account that runs AccessLab.
- If the model exists in another store, restart Ollama with the correct OLLAMA_MODELS/HOME.
- Restart AccessLab if it was already running.
- Open `/healthz` and confirm semantic_provider_ready is true; semantic_retrieval_ready becomes true after materials are indexed.

## Honest Limits

- Model installation only proves the provider can be found in the active Ollama store.
- Semantic retrieval also requires indexed class materials.
- SQLite FTS5 remains the fallback when EmbeddingGemma is unavailable.
