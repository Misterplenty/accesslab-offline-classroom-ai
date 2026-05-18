# Local Data Capture and Export

AccessLab does not require training to work. This guide exists for future lightweight tuning work only.

## What stays local

- grounded QA sessions
- beginner Python repair sessions
- local quality labels
- exported JSONL artifacts

No cloud logging or remote sync is added in this phase.

## Opt-in structured capture

Set:

```bash
ACCESSLAB_TRAINING_CAPTURE_ENABLED=on
```

This keeps the normal saved-session history and also stores structured local capture records for QA/code sessions. Leave it off if you only want the normal product history.

## Local labels

Use lightweight labels such as:

- `good`
- `bad`
- `overlong`
- `over-disclosing`
- `unclear`
- `screen-reader-friendly`
- `needs-review`

Example:

```bash
python scripts/label_local_data.py --source-type qa --id 12 --label screen-reader-friendly
```

Teacher/admin users can also add these labels directly from the saved QA or saved code review page.

## Exporting data

Example full export:

```bash
python scripts/export_local_data.py --output reports/training_export_latest.jsonl
```

Named export profiles:

```bash
python scripts/export_local_data.py --profile labeled-good --output reports/training_export_good.jsonl
python scripts/export_local_data.py --profile labeled-bad --output reports/training_export_bad.jsonl
python scripts/export_local_data.py --profile qa --output reports/training_export_qa.jsonl
python scripts/export_local_data.py --profile code --output reports/training_export_code.jsonl
python scripts/export_local_data.py --profile weak-retrieval --output reports/training_export_weak_retrieval.jsonl
python scripts/export_local_data.py --profile screen-reader-friendly --output reports/training_export_screen_reader.jsonl
python scripts/export_local_data.py --profile teacher-reviewed --output reports/training_export_teacher_reviewed.jsonl
```

Only labeled examples:

```bash
python scripts/export_local_data.py --only-labeled --output reports/training_export_labeled.jsonl
```

Filter by class space or label:

```bash
python scripts/export_local_data.py --class-space biology-lab --label needs-review
```

Export specific saved sessions:

```bash
python scripts/export_local_data.py --qa-ids 12,14 --code-ids 3
```

## Included metadata

QA rows can include:

- role
- class-space
- runtime backend
- model tier
- requested retrieval mode
- effective retrieval mode
- semantic availability when observable
- weak retrieval status
- citations
- retrieved evidence IDs
- retrieved evidence snippets
- prompt variant
- discipline profile
- runtime backend
- model name
- opt-in capture records when present

Code rows can include:

- original code
- test harness
- execution evidence / error
- suggested fix / patch
- rerun success
- prompt variant
- runtime backend
- model name
- opt-in capture records when present

## Dataset Assembly Scaffold

After export, assemble a narrow SFT or preference-candidate JSONL:

```bash
python scripts/assemble_tuning_dataset.py \
  --input reports/training_export_good.jsonl \
  --output reports/tuning_sft_accesslab_behavior.jsonl \
  --task-profile mixed-product-behavior
```

Use `--task-profile qa-citation-abstention`, `code-minimal-fix`, or `accessibility-style` to keep the tuning task narrow.

Do not mix unreviewed, labeled-bad, or retrieval-broken rows into SFT. Weak-retrieval rows are useful only when the explicit target is abstention behavior.

## Intended future use

These exports are shaped to support later:

- LoRA / QLoRA style supervised tuning
- small preference or rejection-sampling sets
- targeted accessibility-format examples

Current product function does not depend on any of this.

See [tuning_readiness.md](tuning_readiness.md) for the one-cycle tuning plan and rollback criteria.
