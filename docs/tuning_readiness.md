# AccessLab Lightweight Tuning Readiness

AccessLab does not require tuning to work. This path exists only for narrow product-behavior improvement after local review.

## Target Task

One candidate tuning cycle should target product discipline, not generic intelligence:

- answer-first grounded QA
- citation discipline
- abstention under weak retrieval
- smallest-next-fix behavior for beginner Python repair
- screen-reader-friendly formatting when requested
- teacher versus learner tone control through existing role context

## Model Target

- Base target: Gemma 4 profile model already used by the product (`gemma4:e4b` or `gemma4:e2b`)
- Method: LoRA or QLoRA adapter in an offline local training environment
- Initial dataset size: start with tens to low hundreds of teacher-reviewed AccessLab examples, then expand only after review
- Expected improvement: output discipline, citation behavior, abstention, and smallest-next-fix consistency
- Product default: unchanged until a tuned adapter beats baseline on the comparison contract

## Data Sources

Use explicit exports only:

```bash
python scripts/export_local_data.py --profile labeled-good --output reports/training_export_good.jsonl
python scripts/export_local_data.py --profile teacher-reviewed --output reports/training_export_teacher_reviewed.jsonl
python scripts/export_local_data.py --profile weak-retrieval --output reports/training_export_weak_retrieval_latest.jsonl
python scripts/export_local_data.py --profile screen-reader-friendly --output reports/training_export_accessibility_candidates_latest.jsonl
```

Then assemble a task-specific JSONL:

```bash
python scripts/assemble_tuning_dataset.py \
  --input reports/training_export_good.jsonl \
  --output reports/tuning_sft_accesslab_behavior.jsonl \
  --task-profile mixed-product-behavior

python scripts/assemble_tuning_dataset.py \
  --input reports/training_export_good.jsonl \
  --output reports/tuning_preference_candidates.jsonl \
  --task-profile mixed-product-behavior \
  --format preference-candidates
```

Current stable starter artifacts:

- `reports/training_export_latest.jsonl`
- `reports/training_export_labeled_good_latest.jsonl`
- `reports/training_export_weak_retrieval_latest.jsonl`
- `reports/training_export_accessibility_candidates_latest.jsonl`
- `reports/tuning_sft_accesslab_behavior_latest.jsonl`
- `reports/tuning_preference_candidates_latest.jsonl`

## Suitable Fields

SFT candidates:

- QA question
- retrieved evidence snippets and evidence IDs
- short answer and more detail
- citations
- weak-retrieval flag
- code, error, diagnosis, evidence, patch, rerun result
- role and class-space metadata for filtering

Preference candidates:

- labels and review flags
- good/bad examples
- overlong or unclear flags
- screen-reader-friendly labels
- weak-retrieval abstention outcomes

Exclude from training text:

- actor keys
- raw local paths
- unreviewed private student notes unless explicitly approved
- low-quality rows
- retrieval-broken rows unless the target behavior is abstention
- broad open-chat examples, which are outside the AccessLab wedge

## Evaluation Plan

Compare tuned adapter versus baseline Gemma 4 on:

- grounded QA support rate
- citation presence and citation precision
- weak-retrieval abstention quality
- beginner Python rerun success and minimal patch behavior
- verbosity and answer-first formatting
- screen-reader-friendly paragraph length

Use the existing benchmark presets:

```bash
python scripts/run_benchmark_preset.py --preset grounded-qa-hybrid-e4b --device-label tuned-host
python scripts/run_benchmark_preset.py --preset python-repair-e4b --device-label tuned-host
python scripts/run_benchmark_preset.py --preset semantic-unavailable-fallback --device-label tuned-host
```

## Rollback Criteria

Do not ship or demo a tuned adapter if it:

- reduces citation precision
- guesses under weak retrieval
- widens into open chat or generic tutoring
- lowers code rerun success
- creates longer or less accessible answers
- needs cloud runtime, cloud storage, or remote logging

The baseline Gemma 4 runtime remains the rollback.

## Current claim

The repo has reproducible export and assembly artifacts. It does not claim that any tuned adapter has been trained or outperformed baseline Gemma 4.
