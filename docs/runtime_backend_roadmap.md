# Runtime Backend Roadmap

## Current truth

- AccessLab runs on Ollama today.
- Gemma 4 remains the only user-facing reasoning model.
- EmbeddingGemma remains the default semantic retrieval model.
- The working product claim is local laptops and school-box hosts, not universal low-end devices.

## Why a runtime abstraction exists

The generation runtime boundary is now explicit so AccessLab can compare:

- current Ollama runtime behavior
- future LiteRT-LM validation work
- later local runtimes if they become relevant

without rewriting the product shell or pretending all backends are equally ready.

## LiteRT-LM in this phase

This repo now exposes a non-default `litert-lm-validation` backend option.

What it means:

- config and factory wiring exist
- runtime capabilities report it honestly as experimental and validation-only
- health checks fail closed unless an executable validation command is configured
- `scripts/run_litert_validation.py` exercises the provider contract without changing the default product runtime
- Ollama remains the only working backend

Executable validation contract:

```bash
ACCESSLAB_LITERT_LM_COMMAND="/path/to/local/litert_adapter" \
python scripts/run_litert_validation.py --profile grounded-qa-smoke
```

The command receives JSON on stdin:

```json
{
  "model": "gemma4:e4b",
  "profile": "grounded-qa-smoke",
  "prompt": "...",
  "context": "...",
  "settings": {"temperature": 0.0}
}
```

It may return plain text or JSON with `response`, `text`, or `answer`.

What it does not mean:

- no claim of integrated LiteRT inference
- no claim of streaming support or token timings from LiteRT
- no claim of phone-ready deployment
- no claim that semantic retrieval has already moved off the current local embedding path

## Capability reporting

The admin view and `/healthz` now distinguish:

- generation available / unavailable
- streaming support
- token timing availability
- model listing availability
- health probe support
- supported validation profiles
- validation-only versus working runtime
- health probe shape
- semantic retrieval dependency shape

## Realistic future validation classes

The next honest validation targets are likely to be:

- stronger phones or tablets with enough RAM for a LiteRT-LM experiment
- edge-validation mini-PCs
- constrained teacher-laptop tiers used as stand-ins before any phone claim

This repo is still not claiming universal low-end phone support.

This keeps backend differences legible instead of hiding them behind one generic status line.
