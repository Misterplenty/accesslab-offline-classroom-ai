# AccessLab v0.1 Portable Agent Brief

This document is a self-contained transfer brief for another agent or reviewer who cannot access the underlying repository, source files, or local benchmark artifacts.

Everything important is embedded here in prose and tables.

## 1. Executive Summary

AccessLab is a local-first educational assistant prototype focused on one narrow and practical wedge:

It explains local worksheet materials with citations, helps beginners fix small Python bugs using local test execution, and presents results in a screen-reader-friendly format.

This is not a generic tutor.

This is not a cloud product.

This is not a training-first system.

This is a deliberately small end-to-end vertical slice intended to prove that a grounded classroom assistant can run locally with measurable behavior.

The current best measured runtime model is `gemma4:e4b`, and it should be treated as the default demo and runtime model for now.

The current best smaller comparison model inside the same Gemma 4 family is `gemma4:e2b`.

Current benchmark outcome on the measured host:

- `gemma4:e4b`: 19 of 20 tasks passed, 95% pass rate
- `gemma4:e2b`: 16 of 20 tasks passed, 80% pass rate

The main current weakness is not code patch correctness. The main weakness is explanation grounding in code mode and output verbosity on the smaller model tier.

The most important unresolved validation step is a real benchmark on a separate weak or aging machine.

## 2. Product Definition

### 2.1 One-sentence product definition

AccessLab is a local-first, offline-capable assistant that explains local worksheet materials and beginner Python bugs using grounded retrieval, local model inference, local test execution, and accessible output.

### 2.2 Primary user

The intended primary user is:

- a rural teacher
- a student using an older laptop
- a user with weak or unreliable internet

### 2.3 Product wedge

The prototype is intentionally limited to one wedge:

- ingest small local school materials
- answer questions from those materials only
- cite the local sources
- help fix beginner Python bugs by running code locally
- keep the output short and screen-reader-friendly

### 2.4 Why that wedge matters

This wedge proves several things at once:

- fully local workflow
- grounded educational answers
- inspectable citations
- real code execution rather than purely verbal tutoring
- usability on constrained deployment assumptions

## 3. What the Application Currently Does

### 3.1 Local document ingestion

The system can ingest:

- PDF
- TXT
- MD

For each uploaded document, the application:

- stores the file locally
- extracts readable text
- normalizes whitespace
- splits the text into overlapping chunks
- records document and chunk metadata in SQLite
- indexes the chunk text for local retrieval

Current chunking behavior:

- chunk size target: 140 words
- overlap target: 25 words

Each chunk carries enough metadata to support citations:

- source file name
- page number if available
- chunk ID
- chunk text

### 3.2 Grounded worksheet Q and A

The worksheet explanation flow is:

1. the user asks a question
2. the system searches the local chunk index
3. it selects the top matching chunks
4. it assigns source labels such as `S1`, `S2`, and so on
5. it prompts the local model to answer only from those retrieved sources
6. it formats the result as:
   - short answer
   - more detail
   - sources

The grounding rule is strict by prototype standards:

- if retrieval looks weak, the system should not guess
- instead, it should say it is unsure and show the closest snippets

This keeps the product closer to “source-first explainer” than “confident tutor.”

### 3.3 Beginner Python bug-fix flow

The beginner code flow is:

1. the user pastes Python code
2. the user optionally pastes tests
3. the system runs the code locally
4. it captures runtime or test output
5. it asks the local model for:
   - what failed
   - what evidence shows that
   - the smallest fix
   - a patched program
   - why the fix works
6. it reruns the patched code locally
7. it reports whether the patch passed

This flow matters because it measures a real tutoring behavior:

- diagnosis
- evidence grounding
- minimal repair
- validation by rerun

### 3.4 Accessible output behavior

The output is intentionally simple and structured.

Design goals:

- semantic headings
- labeled controls
- keyboard navigation
- visible focus states
- status updates for long-running operations
- short sections
- short paragraphs
- no markdown tables inside normal user-facing answers
- no emoji clutter

The system is designed to prefer:

- short answer first
- explanation second
- sources or test results after that

## 4. Current Technical Shape

### 4.1 Backend stack

The application currently uses:

- Python 3.11+
- FastAPI
- server-rendered HTML templates
- SQLite
- SQLite FTS5 for lexical retrieval
- local filesystem storage
- Ollama for local model inference

### 4.2 Data storage model

The local SQLite database stores four main kinds of information:

- uploaded documents
- document chunks
- question and answer history
- code tutoring sessions

At a logical level, the stored data includes:

#### Documents

- file name
- file type
- stored location
- creation timestamp

#### Document chunks

- source file
- page number when available
- chunk ID
- chunk text
- creation timestamp

#### Question and answer history

- question text
- retrieved chunk IDs
- answer text
- citation list
- creation timestamp

#### Code sessions

- original code
- test code
- execution output
- patched code
- patched test result
- creation timestamp

### 4.3 Retrieval design

Retrieval is intentionally simple.

Current approach:

- SQLite FTS5 lexical search
- BM25-based ranking
- snippet extraction from the retrieved chunk
- fallback to simple text matching if the FTS query does not return anything

Why this matters:

- it keeps the system fully local
- it avoids vector database complexity
- it is easy to inspect and debug

What it does not do:

- embedding search
- semantic search beyond lexical overlap
- reranking by a second model

### 4.4 LLM provider design

The application uses a local model provider abstraction with three conceptual capabilities:

- generate an answer
- stream an answer
- run a health check

The current implementation uses Ollama as the local model backend.

### 4.5 Runtime default

The runtime default is currently:

- `gemma4:e4b`

This should remain the default until a weaker-device benchmark proves otherwise.

The smaller comparison model currently used for evaluation is:

- `gemma4:e2b`

## 5. Why `gemma4:e4b` Should Stay the Default

The current evidence supports locking `gemma4:e4b` as the default runtime model for now.

Reasons:

- best measured pass rate
- best measured latency on the current host
- fewer accessibility failures
- only one benchmark miss
- that miss was an explanation-grounding miss, not a patch failure

This makes `gemma4:e4b` the best current default for demos and for the strongest version of the product story.

## 6. Code Execution and Safety Model

The code runner is a local prototype sandbox, not a production-grade hardened sandbox.

Current safety measures include:

- parsing submitted code with Python AST before execution
- blocking obviously dangerous imports
- blocking obviously dangerous calls
- running inside a temporary directory
- using a timeout
- isolating Python startup behavior
- capturing stdout and stderr

This is enough for a beginner-code prototype but not enough for hostile production workloads.

That limitation should be stated clearly whenever the project is presented.

## 7. Current Prompting Behavior

### 7.1 Grounded Q and A mode

Grounded Q and A prompting emphasizes:

- answer only from retrieved material
- admit uncertainty when evidence is weak
- use simple language
- keep the answer concise
- preserve requested structure when possible
- cite sources using local source labels
- avoid invented facts

### 7.2 Code tutor mode

The code tutor prompt now emphasizes:

- explain the bug in simple language
- base reasoning only on runtime or test evidence
- separate diagnosis from evidence
- quote a short concrete evidence line
- suggest the smallest next fix
- keep the patch minimal
- avoid unnecessary rewrites
- explain why the fix works by linking it back to the evidence

This change was made specifically because the benchmark exposed a shared failure pattern:

The patch was often correct, but the explanation was not evidence-grounded enough.

## 8. Current Output Structure

### 8.1 Q and A output

The worksheet answer format is:

- short answer
- more detail
- sources

### 8.2 Code tutor output

The code tutor answer format is:

- what failed
- what evidence shows that
- smallest fix
- why the fix works
- patched code
- initial local run result
- rerun result

This format exists to make the system:

- beginner-friendly
- accessible
- inspectable
- less likely to hide its reasoning behind a code dump

## 9. What the Application Does Not Try to Do

The prototype intentionally does not attempt to solve:

- cloud deployment
- advanced training or fine-tuning
- generic tutoring across all subjects
- authentication
- analytics
- multi-tenant architecture
- mobile application support
- distributed school hub workflows
- large vector infrastructure
- highly polished visual UI

This restraint is part of the product strategy.

The goal is a small, believable, measurable local-first slice.

## 10. Test Coverage Status

Current automated tests are passing.

Current suite status:

- 10 tests passing

The tests cover:

- document chunking
- retrieval behavior
- code runner success
- code runner timeout
- citation formatting
- Q and A uncertainty handling
- code tutor evidence parsing
- code tutor evidence fallback behavior

This is still a lightweight test suite, but it is enough to support the prototype stage.

## 11. Evaluation Design

### 11.1 Eval pack size and categories

The evaluation pack contains 20 tasks:

- 8 worksheet and local-document tasks
- 8 beginner Python bug-fix tasks
- 4 accessibility and output-format tasks

### 11.2 Metrics logged per task

Each task records:

- TTFT
- total response time
- grounded yes or no
- citation correct yes or no
- helpful yes or no
- too verbose yes or no
- passed tests yes or no for code tasks
- notes

### 11.3 Pass logic

Q and A tasks pass when they are:

- grounded
- helpful
- not too verbose
- correctly cited when citations are required

Code tasks pass when they:

- produce a passing patch
- give a grounded explanation
- remain helpful
- stay within the verbosity target

This is important because it means a patch can pass the tests and still fail the evaluation if the explanation quality is weak.

That exact thing happened in the benchmark.

## 12. Benchmark Environment and Caveat

Both full Gemma 4 benchmark runs were executed on the same host.

Measured host:

- Apple M4 Pro
- 24 GB RAM
- 14 logical cores
- macOS arm64
- Python 3.14.0

Important benchmark caveat:

The current benchmark is complete for the Gemma 4 model-tier comparison, but it is not a true two-machine weak-hardware benchmark.

This matters because:

- both runs used the same machine
- the smaller tier run used constrained settings to simulate a weaker profile
- that is useful for comparison
- but it is not the same as testing on a separate older or weaker device

Therefore:

- the model-tier comparison is real
- the aging-hardware claim is still provisional

## 13. Full Benchmark Summary

### 13.1 Headline results

| Model | Tasks Passed | Failed | Pass Rate | Avg TTFT | Median TTFT | Avg Total | Avg Model Inference |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `gemma4:e4b` | 19 | 1 | 95% | 10.74s | 10.34s | 13.31s | 13.18s |
| `gemma4:e2b` | 16 | 4 | 80% | 17.66s | 16.99s | 22.29s | 22.16s |

### 13.2 Delta

Compared with `gemma4:e2b`, the `gemma4:e4b` run was:

- 3 tasks better in pass count
- 6.92 seconds faster on average TTFT
- 8.98 seconds faster on average total response time

### 13.3 Core interpretation

On the measured host:

- `gemma4:e4b` is better
- `gemma4:e4b` is faster
- `gemma4:e4b` is more stable on accessibility/output discipline

## 14. Category-Level Benchmark Results

| Model | Worksheet/Local Doc | Beginner Python Code | Accessibility/Output Format |
| --- | --- | --- | --- |
| `gemma4:e4b` | 8 / 8 | 7 / 8 | 4 / 4 |
| `gemma4:e2b` | 7 / 8 | 7 / 8 | 2 / 4 |

What this means:

- both models are strong on code patch correctness
- the smaller tier drops most visibly on document quoting/detail discipline and on accessible compact output
- the strongest measured version of the product today is clearly the `e4b` tier

## 15. Full Task-by-Task Benchmark Table

| Task | Category | `gemma4:e4b` Pass | `gemma4:e4b` TTFT | `gemma4:e4b` Total | `gemma4:e4b` Notes | `gemma4:e2b` Pass | `gemma4:e2b` TTFT | `gemma4:e2b` Total | `gemma4:e2b` Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| doc-01 | worksheet/local-doc | yes | 17.393s | 19.413s | matched keywords: one item at a time, stack; pass | yes | 20.095s | 25.234s | matched keywords: one item at a time, stack; pass |
| doc-02 | worksheet/local-doc | yes | 14.625s | 16.577s | matched keywords: list, one item at a time; pass | yes | 18.029s | 22.222s | matched keywords: list, one item at a time; pass |
| doc-03 | worksheet/local-doc | yes | 11.517s | 12.488s | matched keywords: shows, screen; pass | yes | 13.121s | 14.477s | matched keywords: shows, screen; pass |
| doc-04 | worksheet/local-doc | yes | 9.525s | 10.816s | matched keywords: 3, 5, 8; pass | yes | 16.230s | 18.785s | matched keywords: 3, 5, 8; pass |
| doc-05 | worksheet/local-doc | yes | 10.122s | 11.242s | matched keywords: visit each value, group; pass | yes | 15.383s | 17.676s | matched keywords: visit each value, group; pass |
| doc-06 | worksheet/local-doc | yes | 13.507s | 15.011s | matched keywords: one item at a time; pass | no | 18.197s | 20.224s | expected keywords missing |
| doc-07 | worksheet/local-doc | yes | 12.352s | 14.120s | matched keywords: worksheet_question3.md; pass | yes | 14.494s | 17.169s | matched keywords: worksheet_question3.md; pass |
| doc-08 | worksheet/local-doc | yes | 6.759s | 7.362s | expected keywords missing; pass | yes | 13.433s | 15.057s | expected keywords missing; pass |
| code-01 | beginner-python-bug-fix | yes | 8.856s | 12.857s | patched tests passed; pass | yes | 12.687s | 19.492s | patched tests passed; pass |
| code-02 | beginner-python-bug-fix | yes | 7.774s | 11.912s | patched tests passed; pass | yes | 20.205s | 27.712s | patched tests passed; pass |
| code-03 | beginner-python-bug-fix | yes | 6.662s | 10.467s | patched tests passed; pass | yes | 15.212s | 21.863s | patched tests passed; pass |
| code-04 | beginner-python-bug-fix | yes | 9.478s | 13.474s | patched tests passed; pass | yes | 24.143s | 30.831s | patched tests passed; pass |
| code-05 | beginner-python-bug-fix | yes | 8.024s | 12.385s | patched tests passed; pass | yes | 19.737s | 26.549s | patched tests passed; pass |
| code-06 | beginner-python-bug-fix | yes | 8.511s | 12.992s | patched tests passed; pass | yes | 24.952s | 33.336s | patched tests passed; pass |
| code-07 | beginner-python-bug-fix | yes | 5.530s | 9.110s | patched tests passed; pass | yes | 14.966s | 20.867s | patched tests passed; pass |
| code-08 | beginner-python-bug-fix | no | 11.579s | 15.703s | patched tests passed; diagnosis did not clearly reference runtime or test evidence | no | 25.312s | 33.109s | patched tests passed; diagnosis did not clearly reference runtime or test evidence |
| a11y-01 | accessibility/output-format | yes | 14.030s | 16.744s | matched keywords: one item at a time, stack; pass | no | 18.069s | 24.605s | matched keywords: one item at a time, stack; response exceeded verbosity target |
| a11y-02 | accessibility/output-format | yes | 13.823s | 15.976s | matched keywords: next value, list; pass | no | 17.570s | 20.795s | matched keywords: next value, list; response exceeded verbosity target |
| a11y-03 | accessibility/output-format | yes | 10.551s | 11.768s | matched keywords: shows, screen; pass | yes | 14.858s | 17.078s | matched keywords: shows, screen; pass |
| a11y-04 | accessibility/output-format | yes | 14.127s | 15.786s | matched keywords: group; pass | yes | 16.412s | 18.767s | matched keywords: visit each value, group; pass |

## 16. Latency Interpretation

Measured latency profile:

- retrieval time was negligible
- prompt-build time was negligible
- code execution time was negligible
- model inference dominated response time

This means:

- the current latency problem is primarily inference cost
- the benchmark does not support the claim that retrieval is the main bottleneck
- the benchmark does not support the claim that code execution is the main bottleneck

Current strategic implication:

optimize inference path and output discipline before jumping to training

## 17. Failure Analysis

### 17.1 Most important shared failure

The most important failure is:

The patch is correct, but the explanation is not sufficiently evidence-grounded.

This appeared most clearly in `code-08`.

Why it matters:

- the system looks technically capable
- but the tutoring quality is weakened if the explanation does not clearly point to the failing test or runtime evidence

This is a prompt and product-structure problem before it is a training problem.

### 17.2 Shared failure taxonomy

Top recurring failure tags:

- `missed_expected_content`: 3 tasks
- `weak_evidence_reference`: 2 tasks
- `verbosity`: 2 tasks

Interpretation:

- some answers still miss specific expected content
- code explanations sometimes under-cite concrete evidence
- output length control weakens on the smaller tier

### 17.3 `gemma4:e4b` failure profile

`gemma4:e4b` failed only:

- `code-08`

Nature of failure:

- patch passed tests
- explanation quality failed the grounding criterion

### 17.4 `gemma4:e2b` failure profile

`gemma4:e2b` failed:

- `doc-06`
- `code-08`
- `a11y-01`
- `a11y-02`

Nature of failures:

- one content/quote miss
- one evidence-grounding miss
- two verbosity failures

## 18. What Has Already Been Improved Since the Benchmark

After the benchmark, the code tutor was tightened to directly target the explanation-grounding problem.

The current implementation now:

- keeps `gemma4:e4b` as the default runtime model
- requires a separate evidence section in code explanations
- asks the model to quote short concrete lines from runtime or test output
- separates diagnosis from evidence
- keeps the “smallest fix” concept explicit
- includes test coverage for evidence parsing and evidence fallback behavior

This means:

- the current codebase is ahead of the benchmark artifacts
- the benchmark should be treated as the measured baseline
- the explanation-grounding patch still needs its own benchmark rerun

## 19. What the Current Evidence Proves

The current evidence does prove:

- a local-first classroom assistant is viable
- grounded worksheet explanation works
- local citation display works
- local beginner-code patching works
- semantic accessible output is achievable
- Gemma 4 can support this use case locally

The current evidence does not yet prove:

- production-grade security
- general-purpose tutoring quality
- semantic retrieval at scale
- final performance on true aging hardware

## 20. Known Limitations

- the local code runner is a prototype safety layer, not a hardened sandbox
- retrieval is lexical, not embedding-based
- scanned PDFs without embedded text are not OCRed
- the model provider depends on a local Ollama runtime
- the generated code harness is intentionally minimal
- the weak-device claim still lacks a separate-machine benchmark
- the latest evidence-grounding improvements have not yet been benchmark-rerun

## 21. Recommended Next Sequence

Recommended next work in order:

1. keep `gemma4:e4b` as the default runtime model
2. rerun the full 20-task benchmark after the evidence-grounding patch
3. run the same 20-task pack on a real weaker or older machine
4. compare `gemma4:e4b` and `gemma4:e2b` there on:
   - pass rate
   - TTFT
   - total response time
5. tighten retrieved context size
6. reduce default output length
7. only after that, decide whether routing or training is worth it

## 22. Plain-Language Bottom Line

AccessLab is no longer just an idea.

It is already a working local prototype with measurable behavior.

The strongest current version uses `gemma4:e4b`.

The biggest remaining product problem is not “can it patch the code?” but “can it explain the bug using clear evidence while staying concise?”

The biggest remaining validation problem is not “does it run locally?” but “how well does it run on a truly weak machine?”

## 23. One-Sentence Conclusion

AccessLab v0.1 shows that a grounded, local-first classroom and coding assistant is already viable with Gemma 4; the main remaining work is reducing inference cost on weaker hardware and tightening evidence-grounded explanations.
