# Accessibility Submission Notes

AccessLab is built as a server-rendered classroom tool with semantic forms, visible evidence cards, and keyboard-operable flows.

## Implemented Accessibility Supports

- Skip link to the main content.
- Visible focus styling through `:focus-visible`.
- Keyboard-operable navigation, upload, Q&A, source inspection, code tutor, and role switch controls.
- Upload can be used through the file input; drag-and-drop is not the only path.
- Source cards and cited evidence include accessible labels.
- Accessibility toolbar controls for large text, high contrast, plain language, reduced motion, keyboard mode, and read aloud.
- Plain-language mode is stored as request metadata and does not alter the learner's saved question.
- Read-aloud uses local browser speech synthesis when available and keeps the source text visible.

## Verification

Run:

```bash
make smoke-a11y
```

Expected artifact paths:

- `reports/a11y_smoke_latest.md`
- `reports/a11y_smoke_latest.json`

If the smoke test is missing, stale, or failing, describe that honestly in the submission and rerun it before recording final media.

## Owner Video Tasks

The final video should include captions or a transcript. That is a human-owner submission task, not something this repo currently generates automatically.
