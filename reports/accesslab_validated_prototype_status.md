# AccessLab Validated Prototype Status

## Scope

AccessLab is a local-first, offline-capable Python application for one narrow educational use case:

1. Upload a local school document (`PDF`, `TXT`, `MD`)
2. Ask a grounded question and get an answer with visible source citations
3. Paste buggy Python code and get a diagnosis, one minimal fix, and a local test result

This is the current prototype wedge. It is not a general-purpose tutor, a cloud product, or a production security boundary.

## Current Validated Configuration

| Area | Current status |
| --- | --- |
| Strong profile | `strong -> gemma4:e4b` |
| Weak profile | `weak -> gemma4:e2b` |
| QA default | `baseline` |
| Code tutor default | `hybrid` |
| Retrieval | SQLite-first hybrid retrieval: FTS5 stays primary, local semantic assist is optional and stays in SQLite |
| OCR | Local fallback exists for scanned/image-based PDFs when the optional OCR extras are installed |
| Code runner | Hardened local runner with timeouts, env scrubbing, runtime policy checks, and temp execution dirs |

The strong-profile path is the strongest validated demo configuration today.

## What AccessLab Includes Right Now

- Local document upload and indexing for `PDF`, `TXT`, and `MD`
- Grounded question answering with visible citations and source snippets
- OCR fallback for scan-like PDFs without changing the normal text-PDF path
- SQLite-first retrieval with optional local semantic backfill in the same SQLite database
- Beginner Python diagnosis, one minimal fix, patched code, and rerun result
- A local `/healthz` endpoint that reports the active profile, model, OCR state, and semantic-retrieval state

## What Is Measured vs Inferred

### Measured on the current host

- Strong profile (`gemma4:e4b`, QA `baseline`, code `hybrid`) completed the current full evaluation pack at `20/20` on the reference run.
- Weak-profile behavior (`gemma4:e2b` with weak-tier QA discipline on top of the baseline QA prompt) completed the current full evaluation pack at `20/20` under the constrained-proxy configuration on the same host.
- OCR fallback is implemented, covered by tests, and exposed through a dedicated smoke path.
- Hybrid retrieval is implemented, covered by tests, and exposed through a dedicated smoke path.
- Code-runner hardening is implemented, covered by tests, and exposed through a dedicated smoke path.

### Inferred or proxy-based

- Weak-profile viability on actual low-spec hardware is still inferred from constrained-proxy evidence on a stronger Apple-silicon host.
- Weak-profile cold-start behavior on slow storage is not yet measured on real weak hardware.
- Phone-class and SBC-class deployment claims are not supported by the current evidence.

## Current Evidence Read

- `strong = gemma4:e4b` is the current best validated demo/profile default.
- `weak = gemma4:e2b` is the current best weak-tier candidate, but only with honest proxy-based framing.
- QA should remain on `baseline`.
- Code tutor should remain on `hybrid`.
- OCR fallback and SQLite-first hybrid retrieval are part of the current prototype package.
- The code runner is meaningfully hardened for the local prototype but is not a production secure sandbox.

## Known Limitations

- Weak-device deployment is not yet proven on real hardware.
- OCR remains best-effort on faint scans, handwriting, and complex layouts.
- Hybrid retrieval depends on a local embedding model (`all-minilm`) for its semantic assist; without it, AccessLab falls back to lexical retrieval.
- The local code runner blocks more dangerous behavior than before, but it does not claim protection against determined malicious code or host compromise.
- Ollama must be running locally for grounded QA and code-tutor generation paths.

## What Remains Unproven

- Real weak-device latency and usability for the weak profile
- Real low-spec storage cold-start behavior
- Phone viability
- SBC viability
- Any claim stronger than "validated prototype" for sandbox isolation

## Canonical Next Docs

- Demo/runbook: [`reports/accesslab_demo_runbook.md`](accesslab_demo_runbook.md)
- Minimum confidence commands: [`reports/accesslab_core_validation_commands.md`](accesslab_core_validation_commands.md)
- Release-readiness checklist: [`reports/accesslab_release_readiness_checklist.md`](accesslab_release_readiness_checklist.md)
- Evidence map: [`reports/accesslab_evidence_index.md`](accesslab_evidence_index.md)
