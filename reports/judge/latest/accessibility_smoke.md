# AccessLab Accessibility Smoke

- Generated at: 2026-05-18T19:14:53.443394+00:00
- Base URL: http://127.0.0.1:60981
- Passed: 13/13
- Claim level: automated smoke gate, not WCAG certification

| Check | Result | Detail |
| --- | --- | --- |
| Heading and landmark structure | pass | The shell keeps a single page heading plus header, nav, main, and footer landmarks for screen-reader navigation. |
| Main navigation and skip link | pass | Skip link receives focus first and shows visible focus styling. |
| Inclusive Classroom toolbar | pass | Large text, high contrast, plain language, reduce motion, and keyboard modes are toggleable and persisted locally. |
| Role switch and teacher controls | pass | Teacher mode exposes upload controls without showing a separate admin shell. |
| Upload flow and redirect focus | pass | Teacher upload keeps the interaction in-page, restores focus to the status region, and updates the shared class collection. |
| Inclusive form preferences | pass | Plain-language mode feeds grounded QA, and the visible progress contract names the Gemma 4 answering stage. |
| QA flow and saved-answer focus | pass | Grounded QA lands on a saved URL and returns focus to the status region. |
| Citation jump flow | pass | Keyboard activation jumps to the evidence card, focuses it, and keeps it clear of the page header. |
| Disclosure open/close focus | pass | The detail disclosure toggles open and closed without losing keyboard focus. |
| Read-aloud transcript | pass | Generated answer audio is optional; the same content remains available as text. |
| Source inspection flow | pass | The cited source view opens with the cited excerpt visible first. |
| Code tutor flow | pass | Code tutor saves to a stable URL and keeps disclosure focus stable after opening evidence. |
| Admin system view | pass | Admin mode exposes runtime, retrieval, indexing, OCR, and queue diagnostics in one server-rendered page. |

## Manual Validation Checklist

- [covered-by-smoke] Inclusive Classroom Mode: Large text, high contrast, plain language, reduce motion, and keyboard mode toggles are exercised.
- [covered-by-smoke] Read-aloud transcript: Answer read-aloud controls are paired with visible transcript text.
- [covered-by-smoke] Keyboard-only upload: Teacher role switch, file input, submit button, redirect, and status-region focus are exercised.
- [covered-by-smoke] Keyboard-only QA: Question entry, submit activation, saved URL, and status-region focus are exercised.
- [covered-by-smoke] Keyboard-only citation/source navigation: Citation jump focus and source inspection popup are exercised.
- [covered-by-smoke] Keyboard-only code tutor: Textarea entry, submit activation, saved URL, and evidence disclosure focus are exercised.
- [covered-by-smoke] Focus restoration after saved session redirect: QA and code saved redirects wait for focus on the status region.
- [covered-by-smoke] Visible progress states: QA and code forms expose text progress stages instead of relying on audio or a static spinner.
- [covered-by-smoke] Role switching: Teacher, learner, and admin role transitions are exercised in one browser session.
- [covered-by-smoke] Admin navigation: Admin system view reachability and diagnostics section visibility are exercised.

## Screen-Reader Validation Notes

- NVDA / Windows: not-run-on-this-host - No Windows/NVDA environment was available in this run; keep this as a manual release check before a Windows classroom claim.
- VoiceOver / macOS: manual-spot-check-recommended - The current host is macOS, but this smoke does not automate speech output; use VoiceOver rotor checks for landmarks, forms, citations, and saved redirects.
- TalkBack / Android: not-run-on-this-host - No Android/TalkBack device was available in this run; do not claim Android screen-reader validation from this artifact.

## Known Accessibility Limits

- The smoke gate is not WCAG certification.
- The browser and screen-reader matrix may be incomplete.
- OCR quality affects document accessibility and source usefulness.
- Code editor fields are simple textareas, not full IDE accessibility surfaces.
- Speech-output quality still needs manual assistive-technology review.
