# AccessLab Frontend Architecture Memo

## Goals

Rebuild the AccessLab frontend as a calm, server-rendered interface that:

- preserves the current FastAPI + Jinja product logic
- keeps the trust trail clear across upload, grounded Q&A, code repair, and source inspection
- uses shared layout rules instead of page-by-page visual improvisation
- stays offline-capable and easy to maintain

## Shell

- `app/templates/base.html` is the single app shell.
- The shell owns:
  - sticky top bar
  - wordmark and subtitle
  - primary navigation
  - quiet runtime status cluster
  - shared content width and responsive padding
  - a single live status region for progressive enhancement feedback
- The shell does not own page-specific cards or widget layouts.

## Page Layout System

Each page follows the same high-level skeleton:

1. page header
2. main content layout
3. optional secondary rail
4. optional contextual status/help content only when useful

Shared layout primitives:

- `page-header`: title, one-line description, optional meta/actions
- `page-layout`: responsive page grid
- `page-main`: primary task content
- `page-rail`: secondary trust/status/context content
- `section-block`: reusable section wrapper with consistent heading, spacing, and dividers

Page-specific intent:

- Workspace: two-column landing view with upload/materials on the left and actions/system status on the right
- Explain Materials: question + answer in the main column, evidence/source trail in the rail
- Fix Python Code: code entry in the main column, structured repair result in the rail
- Source View: cited excerpt/context in the main column, metadata/actions in the rail

## Component System

Reusable Jinja macros live in `app/templates/_ui.html`.

Core components:

- page header block
- section header
- status metric
- inline notice
- empty state
- upload surface
- material row
- action row
- field group
- answer content wrapper
- evidence item
- source action row
- code result block

Rules:

- use spacing and dividers before borders
- use subtle surfaces only for functional grouping
- keep metadata styling consistent across pages
- keep evidence/source markup stable so citations and tests continue to work

## JS Loading Model

- One global script: `app/static/app.js`
- No framework runtime
- No client-side state store
- Enhancements are attached through stable `data-*` hooks

Progressive enhancement responsibilities:

- form submit status messaging
- readable mode toggle
- disclosure toggles
- citation jump + evidence highlight
- upload dropzone polish

Without JavaScript:

- forms still submit
- pages still render answers and saved sessions
- citations still link to evidence anchors
- evidence still links to source routes

## Navigation And State Model

- Workspace, Explain Materials, Fix Python Code, and Source View are server-rendered routes
- POST actions redirect to stable saved GET routes where already implemented:
  - `/qa?qa_id=...`
  - `/code?session_id=...`
- citation links target same-page evidence anchors
- evidence items link to `/sources/{chunk_id}` with `qa_id` preserved when available
- source pages keep the return path back to the saved Q&A state
- runtime/profile/model state is rendered from server context, not recreated in JS

## Compatibility Constraints

The rewrite must preserve:

- grounded answer rendering
- inline citations and evidence anchors
- math rendering and readable fallback
- saved QA and code-session URLs
- source inspection routes and raw-file opening
- offline-friendly local asset delivery
- current backend service boundaries
