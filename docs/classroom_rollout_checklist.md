# Classroom Rollout Checklist

Use this for teacher-laptop or school-box deployment.

## Before class

1. Pull the local models:
   `ollama pull gemma4:e4b`
   `ollama pull gemma4:e2b`
   `ollama pull embeddinggemma`
2. Start Ollama:
   `ollama serve`
3. Run the operator preflight:
   `python scripts/run_operator_preflight.py`
4. Run the accessibility smoke:
   `python scripts/run_accesslab_a11y_smoke.py`
5. Upload the demo or class materials once.
6. If class-space labels changed since the last session, preview the reassignment in the admin System view or with `scripts/manage_class_space.py` before class begins.

## Choose the right mode

- `single-user-local`:
  personal workstation or solo prep
- `classroom-local`:
  one teacher device driving the room
- `school-box-shared`:
  one stronger LAN host serving many browsers

## Demo flow

1. Teacher uploads one worksheet or notes file.
2. Learner asks one grounded question from shared materials.
3. Learner runs one beginner Python repair example.
4. Teacher reopens the saved learner session.
5. Admin opens the system view and shows runtime, retrieval, queue, and deployment mode.

## Judge bundle

Keep these artifacts ready:

- `reports/operator_preflight_latest.md`
- `reports/system_status_snapshot_latest.json`
- `reports/deployment_mode_snapshot_latest.md`
- `reports/a11y_smoke_latest.md`
- one or more `reports/runs/<id>/summary.md`
- `reports/accesslab_benchmark_summary.md`
- `reports/accesslab_benchmark_highlights.md`
