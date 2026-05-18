# AccessLab Core Validation Commands

This is the smallest command set that gives an operator minimum confidence that the current prototype package is healthy.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
make install
cp .env.example .env
ollama serve
ollama pull gemma4:e4b
ollama pull gemma4:e2b
ollama pull all-minilm
```

Optional for OCR:

```bash
.venv/bin/python -m pip install -r requirements-ocr.txt
```

## Run The App

Strong profile:

```bash
make run-strong
```

Weak profile:

```bash
make run-weak
```

Check runtime status:

```bash
curl http://127.0.0.1:8000/healthz
```

## Minimum Confidence Checks

Full test suite:

```bash
make test
```

Retrieval smoke:

```bash
make smoke-retrieval
```

Code-runner hardening smoke:

```bash
make smoke-code-runner
```

OCR smoke:

```bash
make smoke-ocr PDF=/absolute/path/to/scanned.pdf
```

Notes:

- `smoke-retrieval` exercises the SQLite-first lexical-vs-hybrid comparison.
- `smoke-code-runner` proves safe code still runs and runtime network access is blocked clearly.
- `smoke-ocr` requires OCR extras and a real scanned/image-based PDF.

## Key Evidence Reproduction

Strong-profile full-pack confirmation:

```bash
make eval-fullpack-strong DEVICE_LABEL=reviewer-machine
```

Weak-profile default behavior under proxy validation:

```bash
make eval-weak-fullpack-tightened DEVICE_LABEL=reviewer-machine
```

Full model-tier sweep:

```bash
make eval-tier-sweep DEVICE_LABEL=reviewer-machine
```

Use the evidence index to find the existing summary JSON files and decision memos that correspond to these commands:

- [`reports/accesslab_evidence_index.md`](accesslab_evidence_index.md)
