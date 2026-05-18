# Accessibility Contract

AccessLab is trying to be predictably usable for keyboard users, screen-reader users, and mixed teacher/learner classroom setups without turning the product into a custom-widget maze.

## Required product behavior

### Keyboard operability

These flows must work without a mouse:

- main navigation
- local role switch
- teacher upload flow
- heading and landmark structure
- grounded QA submission
- citation jump from answer to evidence card
- source inspection from evidence card to source page
- beginner Python tutor flow
- admin/system view navigation
- Inclusive Classroom Mode toggles: large text, high contrast, plain language, reduce motion, and keyboard mode
- read-aloud controls with visible transcript text

### Focus policy

AccessLab should keep focus deliberate and obvious:

- skip link reaches the main content region
- saved QA and saved code redirects return focus to the status region
- citation jumps focus the target evidence card
- disclosure open/close keeps focus stable on the controlling button
- focus styling remains visible on native controls and important links
- sticky UI must not visually cover the newly focused target

### Reading order and structure

- use semantic landmarks: `header`, `nav`, `main`, `aside`, `footer`
- keep headings in a sensible order
- keep the answer before the evidence list
- keep cited snippet, source metadata, and open-source action together on source pages
- keep role-specific pages understandable in linear reading order

### Live regions

- use polite status announcements for meaningful state changes only
- do not turn every surface into a live region
- degraded states should say what happened in plain language
- long-running QA/code submissions should show visible text progress, including the local model or Python stage

### Inclusive classroom support

- high-contrast and large-text modes must be available from the shared shell
- plain-language mode should influence grounded QA and Code Assist prompts
- read-aloud must remain optional and paired with transcript text
- status updates must be visible as text, not audio-only
- forms must keep large click targets and submit without drag-and-drop-only paths
- avoid outdated disability language in product copy

## Role-specific expectations

### Learner pages

- learner mode should not bury the first screen in teacher/admin controls
- recent sessions should be scoped to the current browser actor
- shared class materials should still be visible for grounded QA

### Teacher pages

- shared-material management should be reachable from the first screen
- recent classroom activity should be visible without a dashboard-style overload
- saved learner sessions should stay linkable and readable

### Admin pages

- runtime, retrieval, OCR, and queue state should be readable as plain HTML
- EmbeddingGemma health and index lifecycle should be visible without reading logs

## What the repo validates now

- server-rendered shell keeps landmarks and skip link intact
- server-rendered shell keeps a single page `h1` and stable landmark structure
- focus targets exist after saved QA/code redirects
- evidence cards are keyboard-focusable citation targets
- disclosure buttons expose `aria-controls`
- Inclusive Classroom Mode toggles persist in local storage
- read-aloud controls expose text transcripts
- admin view renders retrieval/index/system sections
- learner history stays scoped by browser actor in shared deployments
- Playwright smoke checks cover keyboard/focus paths across the primary flows

