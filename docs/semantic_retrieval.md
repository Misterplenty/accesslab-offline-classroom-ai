# Semantic Retrieval Operations

AccessLab keeps SQLite FTS5 as the grounded lexical baseline and uses EmbeddingGemma as the default semantic retrieval model.

## Operational states

### Provider states

- ready
- model not installed
- provider connection failed
- embedding generation error
- disabled by configuration

### Index states

- not indexed
- indexing pending
- indexed
- indexing failed

## Where these surfaces appear

- `/healthz`
- admin system view
- workspace notices
- benchmark summaries

## Current retrieval framing

- requested retrieval mode can be `lexical`, `semantic`, or `hybrid`
- effective retrieval mode degrades honestly to lexical-only when semantic retrieval is not ready
- lexical fallback is preserved even when semantic retrieval is unavailable

## EmbeddingGemma preparation

First-class setup command:

```bash
ollama pull embeddinggemma
python scripts/setup_embeddinggemma.py --healthz-url http://127.0.0.1:8000/healthz
```

If AccessLab is not running yet, use the setup script with an empty health URL to verify the active Ollama store only:

```bash
python scripts/setup_embeddinggemma.py --skip-pull --healthz-url ""
```

Expected readiness signs:

- `ollama list` includes `embeddinggemma` or `embeddinggemma:latest`
- `/healthz` reports `semantic_provider_ready: true`
- `/healthz` reports `semantic_retrieval_ready: true` after class materials are indexed
- the admin view reports requested versus effective retrieval mode

AccessLab now formats semantic inputs differently for retrieval use:

- query embeddings use a retrieval-style query wrapper
- document embeddings use a title plus chunk-text wrapper

This keeps the EmbeddingGemma path aligned with retrieval-specific use rather than treating embeddings as generic opaque vectors.

## Operational notes

- existing documents are backfilled for embeddings at startup when possible
- new uploads try to embed during ingest
- semantic failures do not remove lexical search
- indexing state is persisted in SQLite so degraded status remains visible after a restart
- retrieval and index counts stay scoped to the current class space in shared deployments

## Retrieval proof command

Run the semantic proof before a judged demo:

```bash
python scripts/run_retrieval_smoke.py
```

Stable artifacts:

- `reports/semantic_retrieval_proof_latest.json`
- `reports/semantic_retrieval_proof_latest.md`

The proof runs lexical-only, EmbeddingGemma-only, and hybrid retrieval over the same local fixture. It records whether semantic retrieval changed retrieved chunks, whether hybrid improved expected evidence support, and where semantic retrieval was neutral or unavailable.

## Honest limits

- Semantic-only is a diagnostic path, not the default product path.
- Hybrid can be neutral when lexical retrieval already ranks the best evidence first.
- A retrieval proof is not a generation-quality proof by itself.
- If EmbeddingGemma is unavailable, AccessLab must report lexical fallback rather than claiming hybrid retrieval.
