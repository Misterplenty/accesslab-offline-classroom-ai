# AccessLab Demo Runbook

This runbook keeps the demo inside the product scope: local classroom materials, citation-backed Q&A, abstention on weak evidence, beginner Python repair, teacher/admin review, and proof artifacts.

## Before Recording

```bash
ollama serve
ollama pull gemma4:e4b
ollama pull embeddinggemma
make test
make smoke-code-runner
make preflight
make smoke-retrieval
make smoke-a11y
make school-box-demo-proof
make school-box-load
make judge-bundle
```

If a command fails because Ollama, Playwright, OCR extras, or a model is unavailable, record the exact failure and fix the dependency before using that proof in the submission.

## Seeded Judge Demo

```bash
make judge-demo
```

Open:

- `http://127.0.0.1:8000/judge-demo`
- `http://127.0.0.1:8000/proofs`

The judge demo target resets `data/judge-demo` before seeding, then creates a deterministic classroom state.

## Demo Flow

1. Open the judge demo page.
2. Use **Ask from local materials** to show a saved answer with citations.
3. Use **Inspect cited source** to show the cited chunk and source context.
4. Use **Fix beginner Python** to show the failing `add_numbers` example, minimal fix, and passing rerun.
5. Use **Review teacher/class summary** to show teacher-visible session history.
6. Use **View proof dashboard** to show what has been verified, what is missing, and what is stale.
7. Optionally open `/qa` and ask an unsupported question to show abstention.
8. Optionally select a non-English answer language and show that the saved question remains clean.


