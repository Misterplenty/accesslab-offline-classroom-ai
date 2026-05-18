# AccessLab Benchmark Summary

## Eval runs

No eval summaries were provided.

## Comparison readouts

No directly comparable run pairs were found in the supplied summaries.


## Accessibility smoke

- http://127.0.0.1:57845: 13/13 checks passed

| Base URL | Check | Result | Detail |
| --- | --- | --- | --- |
| http://127.0.0.1:57845 | Heading and landmark structure | pass | The shell keeps a single page heading plus header, nav, main, and footer landmarks for screen-reader navigation. |
| http://127.0.0.1:57845 | Main navigation and skip link | pass | Skip link receives focus first and shows visible focus styling. |
| http://127.0.0.1:57845 | Inclusive Classroom toolbar | pass | Large text, high contrast, plain language, reduce motion, and keyboard modes are toggleable and persisted locally. |
| http://127.0.0.1:57845 | Role switch and teacher controls | pass | Teacher mode exposes upload controls without showing a separate admin shell. |
| http://127.0.0.1:57845 | Upload flow and redirect focus | pass | Teacher upload keeps the interaction in-page, restores focus to the status region, and updates the shared class collection. |
| http://127.0.0.1:57845 | Inclusive form preferences | pass | Plain-language mode feeds grounded QA, and the visible progress contract names the Gemma 4 answering stage. |
| http://127.0.0.1:57845 | QA flow and saved-answer focus | pass | Grounded QA lands on a saved URL and returns focus to the status region. |
| http://127.0.0.1:57845 | Citation jump flow | pass | Keyboard activation jumps to the evidence card, focuses it, and keeps it clear of the page header. |
| http://127.0.0.1:57845 | Disclosure open/close focus | pass | The detail disclosure toggles open and closed without losing keyboard focus. |
| http://127.0.0.1:57845 | Read-aloud transcript | pass | Generated answer audio is optional; the same content remains available as text. |
| http://127.0.0.1:57845 | Source inspection flow | pass | The cited source view opens with the cited excerpt visible first. |
| http://127.0.0.1:57845 | Code tutor flow | pass | Code tutor saves to a stable URL and keeps disclosure focus stable after opening evidence. |
| http://127.0.0.1:57845 | Admin system view | pass | Admin mode exposes runtime, retrieval, indexing, OCR, and queue diagnostics in one server-rendered page. |

## References

- Accessibility smoke: `reports/a11y_smoke_latest.json`
