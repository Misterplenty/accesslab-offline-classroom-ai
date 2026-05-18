# School AI Box Mode

School AI box mode is AccessLab's local shared-service deployment concept.

## What it means

- one stronger local machine runs the app
- the host is reachable over the school LAN
- teacher uploads materials once
- learners connect from browser clients
- retrieval and Gemma 4 inference stay on the host machine

## When to choose it

- choose `classroom-local` when one teacher machine is driving the room
- choose `school-box-shared` when many student browsers need the same local service over LAN


## Recommended operator setup

1. Put the host on the same LAN as the classroom devices.
2. Pull the local models:

```bash
ollama pull gemma4:e4b
ollama pull embeddinggemma
```

3. Start AccessLab in school-box mode:

```bash
ACCESSLAB_DEPLOYMENT_MODE=school-box-shared make run-school-box
```

4. Give the class the LAN URL for that machine.
5. Keep teacher/admin use on a trusted browser session.
6. Use a named class-space, for example `ACCESSLAB_CLASS_SPACE=period-3-python`.
7. Keep `ACCESSLAB_MAX_CONCURRENT_JOBS=1` for the most predictable live demo.
8. Run `python scripts/run_operator_preflight.py` before the session starts.
9. Run the canonical demo proof before a judged demo:

```bash
python scripts/run_school_box_demo_proof.py --max-concurrent-jobs 1
```

10. Run the synthetic queue proof before a judged demo or deployment dry run:

```bash
python scripts/run_school_box_load.py --jobs 12 --max-concurrent-jobs 1
```

## Recommended host class

- stronger teacher laptop
- mini-PC
- small desktop acting as the classroom host

Use `classroom-local` when one teacher machine is driving the room and learners are mostly looking at the same screen. Use `school-box-shared` when multiple student browsers need the same host over LAN.

## Current guardrails

- teacher/admin controls stay role-gated in the UI and server routes
- learner recent-session history is scoped per browser actor cookie
- saved learner session URLs only reopen for the same browser actor unless a teacher/admin is intentionally reviewing them
- uploads, QA, and code-tutor runs go through a simple local queue guardrail
- upload/index jobs can consume more host capacity than a normal QA/code run when the concurrent-job budget is above `1`
- shared materials are scoped to the configured class-space label
- admin view exposes queue depth, last completed/failed job timestamps, and effective retrieval mode
- admin view exposes a dry-run class-space migration form for operators who are not using the CLI


## Common recovery steps

- if Gemma 4 is unavailable: verify `ollama serve` and the configured model
- if hybrid retrieval falls back: verify `embeddinggemma`
- if a class-space label was set incorrectly: preview a reassignment with `scripts/manage_class_space.py`
- if the host is overloaded: keep `ACCESSLAB_MAX_CONCURRENT_JOBS` conservative and avoid large OCR batches during class
- if a label or export workflow is needed after class: reopen the saved QA/code URL, apply a local quality label, and export later from the same box

## Judge artifacts

- `reports/school_box_demo_proof_latest.md`
- `reports/school_box_load_latest.md`
- `reports/operator_preflight_latest.md`
- `reports/device_tier_comparison_latest.md`
