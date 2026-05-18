# Role Model

AccessLab uses local role shaping, not cloud identity.

## Roles

### Learner

- ask from shared materials
- use the beginner Python helper
- reopen only this browser's recent sessions
- avoid teacher/admin clutter

### Teacher / Coach

- upload class-shared materials
- remove outdated materials
- inspect saved learner QA and code sessions
- scan recent classroom activity without a heavy analytics layer

### Admin

- review runtime/backend state
- review Gemma 4 and EmbeddingGemma readiness
- inspect semantic index lifecycle
- inspect OCR state and queue guardrails
- review deployment framing for local or school-box use

## Identity model

- role is stored in a local cookie
- browser actor identity is stored in a second local cookie
- learner session history is scoped by browser actor
- this is a classroom UX boundary, not a full auth system

## Non-goals

- no email auth
- no roster sync
- no grading
- no messaging
- no parent accounts
