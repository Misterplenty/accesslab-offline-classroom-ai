# Accessibility Release Gate

Use this before calling an AccessLab build classroom-ready.

## Required checks

1. Run the server-rendered test suite:

```bash
make test
```

2. Run the Playwright smoke:

```bash
playwright install chromium
make smoke-a11y
```

3. Review the generated artifacts:

- `reports/a11y_smoke_latest.json`
- `reports/a11y_smoke_latest.md`

## What the smoke covers

- keyboard-first main navigation
- role switch into teacher controls
- upload flow
- landmark and heading structure
- grounded QA submission and saved redirect focus
- citation jump focus and sticky-header clearance
- source inspection flow
- code tutor saved redirect focus
- disclosure focus stability
- Inclusive Classroom Mode toggles
- read-aloud transcript presence
- visible progress contract for QA/code submissions
- admin system view reachability

## Manual validation checklist

The latest smoke artifact now carries the checklist below with a status for each item:

- keyboard-only upload
- keyboard-only QA
- keyboard-only citation/source navigation
- keyboard-only code tutor
- inclusive classroom toolbar
- read-aloud transcript
- visible progress states
- focus restoration after saved session redirect
- role switching
- admin navigation

## Screen-reader notes

The smoke is browser automation, not speech-output automation. Treat these as manual follow-up gates:

- NVDA / Windows: not validated unless a Windows/NVDA host is actually used
- VoiceOver / macOS: recommended manual rotor and form-control spot check on this Mac host
- TalkBack / Android: not validated unless an Android/TalkBack device is actually used

## Release decision rule

Do not mark a build release-ready if:

- any accessibility smoke check fails
- learner pages regress into teacher/admin overload
- focus return after saved redirects is broken
- citation targets stop being keyboard-focusable
- system or degraded states become screen-reader-hostile or vague

## Known gaps

- this is a validated smoke gate, not WCAG certification
- no exhaustive browser/screen-reader matrix yet
- no automated speech-output verification
- no axe integration yet
- OCR quality affects document accessibility and citation usefulness
- code editing still uses a textarea rather than a specialized accessible editor
