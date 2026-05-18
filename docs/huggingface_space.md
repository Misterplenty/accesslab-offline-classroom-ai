# Hugging Face Space Deployment

This setup runs AccessLab as a Docker Space with local Ollama inside the
container. It defaults to `gemma4:e2b` for viable demo speed on free CPU Basic
hardware. (The `e4b` model took ~300 seconds per query on CPU Basic.)

## Space Settings

Create a new Hugging Face Space with:

- Space SDK: Docker
- Hardware: CPU Basic
- Visibility: Public, unless the hackathon allows private links

The top of `README.md` already contains the Docker Space metadata:

```yaml
sdk: docker
app_port: 7860
```

## Default Runtime

The Docker image defaults are:

```bash
ACCESSLAB_MODEL=gemma4:e2b
ACCESSLAB_DEPLOYMENT_PROFILE=weak
ACCESSLAB_DEPLOYMENT_MODE=school-box-shared
ACCESSLAB_CLASS_SPACE=judge-demo-class
ACCESSLAB_SEMANTIC_ENABLED=off
ACCESSLAB_OCR_ENABLED=off
```

`gemma4:e2b` is baked during the Docker build so the Space can restart without
redownloading the model. If the build fails because the model name changes in
Ollama, update `ACCESSLAB_BAKE_MODEL` in the Dockerfile and `ACCESSLAB_MODEL`
in `space_start.sh`.

## Upload With The CLI

After creating the Space on Hugging Face, install the CLI if needed:

```bash
python3 -m pip install --upgrade huggingface_hub
huggingface-cli login
```

Then upload from the repo root:

```bash
huggingface-cli upload MrInference/accesslab-gemma4 . --repo-type=space
```

## URLs To Submit

After the Space builds, use:

- Live demo: `https://mrinference-accesslab-gemma4.hf.space/judge-demo`
- Health check: `https://mrinference-accesslab-gemma4.hf.space/healthz`
- Proof dashboard: `https://mrinference-accesslab-gemma4.hf.space/proofs`

`/judge-demo` reseeds deterministic demo data on each visit, so it is safe if
the Space restarts before judging.

## Stronger Model Override

To use `gemma4:e4b` instead (much slower on free CPU), change both places:

```dockerfile
ARG ACCESSLAB_BAKE_MODEL=gemma4:e4b
```

```bash
ACCESSLAB_MODEL=gemma4:e4b
ACCESSLAB_DEPLOYMENT_PROFILE=strong
```

Keep in mind that `gemma4:e4b` took ~300 seconds per query on CPU Basic.

## Known HF Proxy Behaviour

Hugging Face Spaces' reverse proxy does not reliably forward cookies on
cross-origin 303 redirects. The `/judge-demo` route now only checks the
`?ready=1` query parameter (not cookies) to decide whether to redirect,
preventing infinite redirect loops.
