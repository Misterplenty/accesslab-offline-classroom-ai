# AccessLab v0.1 Detailed Application and Benchmark Report

Generated: 2026-04-14

## Status Snapshot

- Application status: working local-first prototype
- Default runtime and demo model: `gemma4:e4b`
- Secondary measured comparison model: `gemma4:e2b`
- Benchmark status: full 20-task runs completed for both Gemma 4 tiers on the same host
- Hardware status: real separate weak-device benchmark is still pending
- Current code status: the code tutor has already been patched to make explanations more evidence-grounded after the benchmark run; the benchmark artifacts below therefore describe the measured system state from 2026-04-14, while the current codebase is slightly ahead of those artifacts

## 1. What AccessLab Is

AccessLab is a local-first, offline-capable proof of concept for one narrow educational wedge:

AccessLab explains local worksheets and beginner Python bugs on aging school hardware, with citations from local materials and screen-reader-friendly output.

This application is intentionally not a generic tutor. It is not a cloud architecture. It is not a training-first system. It is a small end-to-end vertical slice that proves a single user experience:

1. upload local school material
2. ask grounded questions about that material
3. paste buggy beginner Python code
4. run the code locally
5. get a concise explanation, a minimal patch, and a rerun result

## 2. Primary User and Product Wedge

Primary user:

- a rural teacher
- a student on an older laptop
- someone with weak or unreliable internet

The wedge is narrow by design:

- local materials only
- grounded answers only
- beginner Python bug fixing only
- accessible output by default

This keeps the product focused on reliability, inspectability, and deployment realism rather than breadth.

## 3. What the Application Does

### 3.1 Local document ingestion

AccessLab ingests:

- PDF
- TXT
- MD

For each document it:

- stores the uploaded file locally
- extracts readable text
- splits text into chunks
- assigns chunk IDs
- records file and chunk metadata in SQLite
- indexes chunk text with SQLite FTS5

Implementation details:

- PDF extraction uses `pypdf`
- TXT and MD are read directly from disk
- chunking uses normalized text with:
  - max chunk size: 140 words
  - overlap: 25 words
- chunk IDs include file stem, page marker, chunk index, and a short SHA1 digest

### 3.2 Grounded worksheet Q and A

The worksheet flow:

1. the user asks a question
2. AccessLab searches indexed chunks with SQLite FTS5
3. it builds a local source list and source labels such as `[S1]`
4. it calls the local Ollama model
5. the model is instructed to answer only from retrieved material
6. the UI shows:
   - short answer
   - optional more detail
   - visible sources
   - copyable source snippets

Grounding behavior:

- if retrieval is weak, AccessLab refuses to guess
- it falls back to an unsure answer and shows source snippets instead
- weak retrieval is currently detected with a simple lexical overlap heuristic
- if the best overlap ratio is below `0.3`, AccessLab treats retrieval as weak

### 3.3 Beginner Python bug-fix flow

The code tutor flow:

1. the user pastes Python code
2. the user optionally pastes tests
3. AccessLab runs the code locally in a temporary directory
4. it captures stdout, stderr, and failing test output
5. it asks the local model to explain and patch the code
6. it reruns the patched code
7. it shows:
   - what failed
   - what evidence shows that
   - smallest fix
   - why the fix works
   - patched code
   - initial local run output
   - rerun result

Current code-tutor prompt structure:

- `<what_failed>`
- `<evidence>`
- `<smallest_next_fix>`
- `<patched_code>`
- `<why_it_works>`

This structure exists specifically to fix the observed failure class where the patch is correct but the explanation is not grounded enough in the runtime or test evidence.

### 3.4 Accessible frontend behavior

The frontend is intentionally simple and semantic.

Key accessibility decisions:

- server-rendered HTML
- semantic headings
- labels for all form controls
- skip link
- keyboard-usable forms and buttons
- visible focus outlines
- live status region with `role="status"` and `aria-live="polite"`
- short paragraphs rather than dense blocks
- copyable source snippets in `textarea` elements
- no decorative animation burden

UI sections:

1. upload local materials
2. ask about the uploaded worksheet
3. fix a beginner Python bug
4. demo files

## 4. What the Application Explicitly Does Not Do

AccessLab v0.1 does not attempt to implement:

- cloud APIs
- training or fine-tuning
- LoRA
- authentication
- analytics
- multi-tenant deployment
- vector database infrastructure
- mobile app support
- multimodal camera workflows
- school hub distributed systems
- fancy visual polish

That restraint is intentional. The prototype is optimized for inspectable end-to-end behavior rather than feature breadth.

## 5. Runtime Default and Configuration

Runtime default:

- `ACCESSLAB_MODEL=gemma4:e4b`

Current environment variables:

| Variable | Purpose | Default |
| --- | --- | --- |
| `ACCESSLAB_MODEL` | local Ollama model name | `gemma4:e4b` |
| `ACCESSLAB_OLLAMA_URL` | Ollama base URL | `http://127.0.0.1:11434` |
| `ACCESSLAB_DATA_DIR` | local data directory | `./data` |
| `ACCESSLAB_SECRET_KEY` | optional app secret | `change-me-if-needed` in `.env.example` |

Why `gemma4:e4b` is locked as the default:

- highest measured pass rate
- better measured latency on the current host
- fewer accessibility failures
- only one benchmark miss
- that one miss was explanation grounding, not patch correctness

`gemma4:e2b` remains useful as:

- a fallback candidate
- a comparison baseline
- a future real weak-device benchmark target

## 6. Stack and Dependencies

Core stack:

- Python 3.11+
- FastAPI
- Jinja2 templates
- SQLite with FTS5
- local filesystem storage
- Ollama for local inference

Pinned Python dependencies:

| Package | Version |
| --- | --- |
| `fastapi` | `0.116.1` |
| `uvicorn[standard]` | `0.35.0` |
| `jinja2` | `3.1.6` |
| `python-multipart` | `0.0.20` |
| `requests` | `2.32.4` |
| `PyPDF` | `5.9.0` |
| `python-dotenv` | `1.1.1` |
| `pytest` | `8.4.1` |
| `httpx` | `0.28.1` |

## 7. Repository Layout

Primary code and artifact layout:

```text
app/
  config.py
  db.py
  main.py
  models/schemas.py
  routes/web.py
  services/
    code_runner.py
    code_tutor.py
    document_ingest.py
    llm.py
    qa.py
    retrieval.py
  static/styles.css
  templates/
    base.html
    index.html
evals/
  accesslab_eval_v0_1_tasks.json
  accesslab_eval_v0_1_sheet.csv
  code_tasks/
sample_data/
sample_code/
scripts/
  run_accesslab_eval.py
  build_accesslab_report.py
tests/
reports/
```

## 8. Application Architecture

### 8.1 App startup

`app/main.py` wires the app together at startup:

- loads settings
- ensures directories exist
- initializes SQLite schema
- constructs:
  - retrieval backend
  - Ollama provider
  - code execution backend
  - document ingest service
  - grounded QA service
  - code tutor service

Health endpoint:

- `GET /healthz`

HTML routes:

- `GET /`
- `POST /upload`
- `POST /qa`
- `POST /code`

### 8.2 Settings

`app/config.py` resolves:

- base directory
- data directory
- uploads directory
- SQLite path
- template directory
- static directory
- sample data directory
- sample code directory

### 8.3 Persistence model

SQLite schema includes:

#### `documents`

- `id`
- `file_name`
- `file_type`
- `stored_path`
- `created_at`

#### `document_chunks`

- `id`
- `document_id`
- `source_file`
- `page_number`
- `chunk_id`
- `chunk_text`
- `created_at`

#### `qa_history`

- `id`
- `question`
- `retrieved_chunk_ids`
- `answer_text`
- `citation_list`
- `created_at`

#### `code_sessions`

- `id`
- `original_code`
- `test_code`
- `execution_output`
- `patched_code`
- `patched_test_result`
- `created_at`

#### `document_chunks_fts`

SQLite FTS5 virtual table for lexical retrieval across chunk text.

### 8.4 Retrieval design

Retrieval is intentionally simple:

- primary method: SQLite FTS5
- ranking: `bm25(document_chunks_fts)`
- snippet generation: SQLite `snippet(...)`
- fallback: `LIKE` matching if FTS returns nothing

Important detail:

This is lexical retrieval, not embeddings. The system is designed so embeddings can be added later, but v0 intentionally stays with the simplest local option.

### 8.5 Grounded QA design

Grounded QA service behavior:

- retrieves top 4 chunks
- creates citations `[S1]`, `[S2]`, and so on
- builds a prompt that includes source labels and chunk text
- asks the local model to answer only from those sources
- appends citation labels to the short answer if the model omitted them
- detects uncertainty language
- stores the question and answer history

QA system prompt rules emphasize:

- answer only from retrieved material
- admit uncertainty
- keep the answer concise
- support short quotes when requested
- avoid markdown formatting inside answer content

### 8.6 Code execution design

The code runner is a best-effort local prototype sandbox, not hardened isolation.

Safety behavior:

- parses code with `ast`
- blocks imports:
  - `ctypes`
  - `os`
  - `pathlib`
  - `resource`
  - `shutil`
  - `socket`
  - `subprocess`
- blocks calls:
  - `__import__`
  - `compile`
  - `eval`
  - `exec`
  - `open`

Execution behavior:

- writes files into a temporary directory
- runs with timeout
- uses isolated Python mode `-I`
- suppresses user site packages
- returns stdout and stderr

If tests are not provided:

- AccessLab tries to generate a minimal smoke-test harness
- it only does that when the submission contains exactly one top-level function definition

### 8.7 Code tutor design

The code tutor service:

- runs the original code first
- records execution evidence
- checks local model health
- builds a structured prompt
- asks for:
  - what failed
  - evidence
  - smallest next fix
  - full patched code
  - why the fix works
- reruns the patched code
- stores the full session in SQLite

This is the most important product behavior beyond Q and A because it turns the local model from a text explainer into a measurable debugging assistant.

### 8.8 LLM provider abstraction

The LLM interface supports:

- `generate_answer(...)`
- `stream_answer(...)`
- `health_check()`

Current implementation:

- `OllamaProvider`

It uses:

- `POST /api/generate`
- `GET /api/tags`

It also measures:

- TTFT
- total generation time

### 8.9 Response profiling

The app tracks response-level profiling data through `ResponseProfile`.

Tracked fields include:

- TTFT
- retrieval time
- prompt build time
- model inference time
- post-processing time
- code execution time
- patched execution time
- total time
- prompt size
- context size
- response size
- number of retrieved chunks

## 9. Current User-Facing Output Structure

### 9.1 QA output

QA answers are structured as:

- Short answer
- More detail
- Sources

### 9.2 Code tutor output

Code tutor answers are structured as:

- What failed
- What evidence shows that
- Smallest fix
- Why the fix works
- Patched code
- Initial local run
- Test result after rerun

This is intentionally screen-reader-friendly and maps directly to the product need for concise, inspectable help.

## 10. Testing Status

Current local test suite status:

- `10 passed`

Test coverage currently includes:

- document chunking
- retrieval
- code runner success
- code runner timeout
- citation formatting
- QA uncertainty handling
- code tutor evidence parsing
- code tutor evidence fallback behavior

Test files:

- `tests/test_citations.py`
- `tests/test_code_runner.py`
- `tests/test_code_tutor.py`
- `tests/test_document_ingest.py`
- `tests/test_qa_service.py`
- `tests/test_retrieval.py`

## 11. Benchmark Methodology

### 11.1 Evaluation pack

AccessLab Eval v0.1 contains 20 tasks:

- 8 worksheet/local-doc tasks
- 8 beginner Python bug-fix tasks
- 4 accessibility/output-format tasks

Evaluation artifacts:

- task pack: `evals/accesslab_eval_v0_1_tasks.json`
- blank/manual sheet: `evals/accesslab_eval_v0_1_sheet.csv`

### 11.2 Metrics collected per task

For each task the eval runner logs:

- TTFT
- total response time
- grounded yes/no
- citation correct yes/no
- helpful yes/no
- too verbose yes/no
- passed tests yes/no for code
- notes

### 11.3 Scoring logic

QA task pass requires:

- grounded
- helpful
- not too verbose
- citation correctness not false when citation is required

Code task pass requires:

- patched tests passed
- grounded explanation
- helpful output
- not too verbose

This scoring rule is why `code-08` fails even though the patch passes tests. The patch is right, but the explanation is not sufficiently evidence-grounded.

### 11.4 Commands used

Primary benchmark command:

```bash
.venv/bin/python scripts/run_accesslab_eval.py \
  --device-label "primary-benchmark-2026-04-14" \
  --device-tier decent \
  --model gemma4:e4b
```

Weak-tier comparison command:

```bash
.venv/bin/python scripts/run_accesslab_eval.py \
  --device-label "weak-gemma4-e2-2026-04-14" \
  --device-tier weak \
  --model gemma4:e2b \
  --num-thread 2 \
  --num-gpu 0
```

Combined report command:

```bash
.venv/bin/python scripts/build_accesslab_report.py \
  reports/runs/20260414T081122Z-primary-benchmark-2026-04-14-gemma4-e4b/summary.json \
  reports/runs/20260414T082126Z-weak-gemma4-e2-2026-04-14-gemma4-e2b/summary.json
```

### 11.5 Benchmark environment

Both benchmark runs were executed on the same machine:

| Field | Value |
| --- | --- |
| Date | 2026-04-14 |
| CPU | Apple M4 Pro |
| Memory | 24.0 GB |
| Logical cores | 14 |
| Python | 3.14.0 |
| Platform | macOS 15.7.4 arm64 |

### 11.6 Critical benchmark caveat

The current benchmark is complete for both Gemma 4 model tiers, but it is not yet a true two-machine hardware benchmark.

Important details:

- both runs used the same Apple M4 Pro host
- the `gemma4:e2b` run used constrained settings: `--num-thread 2 --num-gpu 0`
- this means the benchmark proves the currently chosen Gemma 4 runtime profiles
- it does not yet prove the application on a separate older laptop or clearly weaker CPU-only machine

That distinction matters because AccessLab's deployment story depends on constrained hardware, not just local execution.

## 12. Benchmark Headline Results

| Model | Run label | Tasks passed | Failed | Pass rate | Avg TTFT | Median TTFT | Avg total | Avg model inference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `gemma4:e4b` | `primary-benchmark-2026-04-14` | 19 | 1 | 95% | 10.74s | 10.34s | 13.31s | 13.18s |
| `gemma4:e2b` | `weak-gemma4-e2-2026-04-14` | 16 | 4 | 80% | 17.66s | 16.99s | 22.29s | 22.16s |

Headline interpretation:

- `gemma4:e4b` is the current winner on the measured setup
- `gemma4:e4b` beat `gemma4:e2b` by 3 tasks
- `gemma4:e4b` was 6.92s faster on average TTFT
- `gemma4:e4b` was 8.98s faster on average total response time

## 13. Category Breakdown

| Model | Worksheet/local-doc | Beginner Python bug-fix | Accessibility/output-format |
| --- | --- | --- | --- |
| `gemma4:e4b` | 8 / 8 | 7 / 8 | 4 / 4 |
| `gemma4:e2b` | 7 / 8 | 7 / 8 | 2 / 4 |

Interpretation:

- both models were strong on code patch correctness
- `gemma4:e4b` was stronger on document quoting/grounding and accessibility formatting
- the biggest quality drop for `gemma4:e2b` appeared in output discipline rather than raw code repair

## 14. Latency Breakdown

| Model | Avg TTFT | Median TTFT | Avg total | Retrieval | Prompt build | Model inference | Post-processing | Code execution |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `gemma4:e4b` | 10.74s | 10.34s | 13.31s | 0.00s | 0.00s | 13.18s | 0.00s | 0.06s |
| `gemma4:e2b` | 17.66s | 16.99s | 22.29s | 0.00s | 0.00s | 22.16s | 0.00s | 0.07s |

The main latency conclusion is straightforward:

- model inference dominates
- retrieval is currently negligible
- prompt-build overhead is negligible in the current profiling
- code execution is also negligible compared with inference

This means the current pain is not primarily SQLite retrieval or subprocess execution. It is model-side runtime behavior.

## 15. Full Task-by-Task Benchmark Table

| Task | Category | e4b Pass | e4b TTFT | e4b Total | e4b Notes | e2b Pass | e2b TTFT | e2b Total | e2b Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| doc-01 | worksheet/local-doc | yes | 17.393s | 19.413s | matched keywords: one item at a time, stack; pass | yes | 20.095s | 25.234s | matched keywords: one item at a time, stack; pass |
| doc-02 | worksheet/local-doc | yes | 14.625s | 16.577s | matched keywords: list, one item at a time; pass | yes | 18.029s | 22.222s | matched keywords: list, one item at a time; pass |
| doc-03 | worksheet/local-doc | yes | 11.517s | 12.488s | matched keywords: shows, screen; pass | yes | 13.121s | 14.477s | matched keywords: shows, screen; pass |
| doc-04 | worksheet/local-doc | yes | 9.525s | 10.816s | matched keywords: 3, 5, 8; pass | yes | 16.23s | 18.785s | matched keywords: 3, 5, 8; pass |
| doc-05 | worksheet/local-doc | yes | 10.122s | 11.242s | matched keywords: visit each value, group; pass | yes | 15.383s | 17.676s | matched keywords: visit each value, group; pass |
| doc-06 | worksheet/local-doc | yes | 13.507s | 15.011s | matched keywords: one item at a time; pass | no | 18.197s | 20.224s | expected keywords missing |
| doc-07 | worksheet/local-doc | yes | 12.352s | 14.12s | matched keywords: worksheet_question3.md; pass | yes | 14.494s | 17.169s | matched keywords: worksheet_question3.md; pass |
| doc-08 | worksheet/local-doc | yes | 6.759s | 7.362s | expected keywords missing; pass | yes | 13.433s | 15.057s | expected keywords missing; pass |
| code-01 | beginner-python-bug-fix | yes | 8.856s | 12.857s | patched tests passed; pass | yes | 12.687s | 19.492s | patched tests passed; pass |
| code-02 | beginner-python-bug-fix | yes | 7.774s | 11.912s | patched tests passed; pass | yes | 20.205s | 27.712s | patched tests passed; pass |
| code-03 | beginner-python-bug-fix | yes | 6.662s | 10.467s | patched tests passed; pass | yes | 15.212s | 21.863s | patched tests passed; pass |
| code-04 | beginner-python-bug-fix | yes | 9.478s | 13.474s | patched tests passed; pass | yes | 24.143s | 30.831s | patched tests passed; pass |
| code-05 | beginner-python-bug-fix | yes | 8.024s | 12.385s | patched tests passed; pass | yes | 19.737s | 26.549s | patched tests passed; pass |
| code-06 | beginner-python-bug-fix | yes | 8.511s | 12.992s | patched tests passed; pass | yes | 24.952s | 33.336s | patched tests passed; pass |
| code-07 | beginner-python-bug-fix | yes | 5.53s | 9.11s | patched tests passed; pass | yes | 14.966s | 20.867s | patched tests passed; pass |
| code-08 | beginner-python-bug-fix | no | 11.579s | 15.703s | patched tests passed; diagnosis did not clearly reference runtime or test evidence | no | 25.312s | 33.109s | patched tests passed; diagnosis did not clearly reference runtime or test evidence |
| a11y-01 | accessibility/output-format | yes | 14.03s | 16.744s | matched keywords: one item at a time, stack; pass | no | 18.069s | 24.605s | matched keywords: one item at a time, stack; response exceeded verbosity target |
| a11y-02 | accessibility/output-format | yes | 13.823s | 15.976s | matched keywords: next value, list; pass | no | 17.57s | 20.795s | matched keywords: next value, list; response exceeded verbosity target |
| a11y-03 | accessibility/output-format | yes | 10.551s | 11.768s | matched keywords: shows, screen; pass | yes | 14.858s | 17.078s | matched keywords: shows, screen; pass |
| a11y-04 | accessibility/output-format | yes | 14.127s | 15.786s | matched keywords: group; pass | yes | 16.412s | 18.767s | matched keywords: visit each value, group; pass |

## 16. Failed Task Analysis

### 16.1 `gemma4:e4b` failed tasks

`gemma4:e4b` failed only one task:

- `code-08`

Why it failed:

- the patch passed tests
- the explanation did not clearly reference runtime or test evidence
- this is an explanation-grounding failure, not a code execution failure

### 16.2 `gemma4:e2b` failed tasks

`gemma4:e2b` failed four tasks:

- `doc-06`
- `code-08`
- `a11y-01`
- `a11y-02`

Failure types:

- one document-grounding/content miss
- one explanation-grounding miss in code mode
- two verbosity failures in accessibility mode

## 17. Shared Failure Taxonomy

Top recurring failure tags across the measured runs:

- `missed_expected_content`: 3 tasks
- `weak_evidence_reference`: 2 tasks
- `verbosity`: 2 tasks

Interpretation:

- content misses still happen occasionally, especially when quote-style behavior is expected
- evidence grounding in code explanations was the most important code-side weakness
- verbosity control is still fragile on the weaker profile

## 18. What the Benchmark Actually Proves

The benchmark does prove:

- grounded worksheet Q and A works end to end
- visible citations work
- local code execution works
- local patch-and-rerun works
- the product has measurable behavior
- `gemma4:e4b` is the strongest currently measured default

The benchmark does not yet prove:

- behavior on a separate older laptop
- a real CPU-only weak-machine deployment story
- final hardware-tier conclusions

That means AccessLab has crossed from invention into optimization and validation, but the constrained hardware claim still needs one more real experiment.

## 19. Post-Benchmark Code Changes Already Applied

After the benchmark runs, the code tutor was tightened to address the main shared failure class.

The current codebase now:

- locks `gemma4:e4b` as the default runtime model
- adds an explicit `evidence` field to code tutor results
- requires the model to separate:
  - what failed
  - what evidence shows that
  - smallest fix
  - why the fix works
- surfaces that structure in the UI
- adds tests for evidence parsing and evidence fallback behavior

Why this matters:

- the measured failure on `code-08` is now directly targeted by the prompt and output structure
- however, the benchmark has not yet been rerun after this patch
- therefore the current benchmark numbers should be read as the measured baseline before validating the new explanation-grounding fix

## 20. Operational Commands

Install dependencies:

```bash
make install
```

Run the app:

```bash
make run
```

Run tests:

```bash
make test
```

Primary benchmark:

```bash
make eval DEVICE_LABEL=primary-benchmark DEVICE_TIER=decent MODEL=gemma4:e4b
```

Constrained weaker-tier comparison:

```bash
make eval DEVICE_LABEL=weak-gemma4-e2 DEVICE_TIER=weak MODEL=gemma4:e2b NUM_THREAD=2 NUM_GPU=0
```

Build combined report:

```bash
make report SUMMARIES="reports/runs/<primary-run>/summary.json reports/runs/<weak-run>/summary.json"
```

## 21. Sample Demo Assets

Included local materials:

- `sample_data/worksheet_question3.md`
- `sample_data/python_loops_notes.txt`
- `sample_data/python_loops_notes.pdf`

Included code sample:

- `sample_code/buggy_sum.py`
- `sample_code/test_buggy_sum.py`

Eval code tasks:

- `evals/code_tasks/*.py`

## 22. Known Limitations

- the code runner is not a hardened sandbox
- retrieval is lexical rather than semantic
- scanned PDFs without embedded text are not OCRed
- Ollama must be running locally for full functionality
- the automatically generated test harness is intentionally minimal
- the real weak-device benchmark is still missing
- the most recent evidence-grounding patch has not yet been benchmark-rerun

## 23. Recommended Next Steps

Highest-value next steps:

1. rerun the full 20-task benchmark after the evidence-grounding patch
2. run the same 20-task pack on a separate weak machine
3. compare `gemma4:e4b` and `gemma4:e2b` there on:
   - pass rate
   - TTFT
   - total response time

Then optimize in this order:

1. explanation grounding in code mode
2. output compactness and verbosity control
3. retrieval context tightening
4. only after that, consider routing or training decisions

## 24. Final Assessment

AccessLab is no longer just an idea. It is already a working prototype with measurable behavior.

What is already strong:

- grounded QA
- citation behavior
- local code execution
- patch correctness
- semantic accessible output structure

What remains unresolved:

- real aging-hardware validation
- stricter evidence-grounded explanations
- latency cost under constrained deployment

Current one-sentence conclusion:

AccessLab v0.1 shows that a grounded, local-first classroom and coding assistant is already viable with Gemma 4; the main remaining work is reducing inference cost on weaker hardware and tightening evidence-grounded explanations.
