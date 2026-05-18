# AccessLab Current State Report

Generated: 2026-04-19

## 1. What This Application Is

AccessLab is a local-first educational assistant prototype built around one narrow product wedge:

It explains local worksheet materials with citations, helps beginners fix small Python bugs using local test execution, and presents the output in a concise, screen-reader-friendly structure.

This is intentionally not:

- a generic tutor
- a cloud product
- a many-feature learning platform
- a training-first system

It is intentionally:

- local-first
- offline-capable in its core workflow
- grounded in local materials
- small enough to inspect end to end
- narrow enough to benchmark meaningfully

The product idea is that a student or teacher on older school hardware should be able to upload a local worksheet, ask a grounded question about it, paste a small buggy Python program, and get a useful local answer without needing cloud inference.

## 2. Core Product Promise

The core promise of AccessLab is:

“AccessLab explains local worksheets and beginner Python bugs on old school hardware, with citations from local materials and screen-reader-friendly output.”

That promise breaks into three practical behaviors:

1. local document explanation
2. local beginner code tutoring
3. accessible, compact presentation

## 3. Who It Is For

The primary target user is:

- a rural teacher
- a student using an older laptop
- someone with weak or unreliable internet

The point is not broad capability. The point is dependable local usefulness under constrained conditions.

## 4. What the Application Does Right Now

### 4.1 Local document ingestion

AccessLab accepts:

- PDF
- TXT
- MD

For each uploaded document, it:

- stores the file locally
- extracts text
- normalizes whitespace
- splits the text into chunks
- stores chunk text and metadata in SQLite
- builds a local lexical search index with SQLite FTS5

Chunking is intentionally simple and local:

- target chunk size: 140 words
- overlap: 25 words

Stored chunk metadata includes:

- source file name
- page number when available
- chunk ID
- chunk text

### 4.2 Grounded worksheet Q and A

The worksheet Q and A flow works like this:

1. the user asks a question
2. AccessLab retrieves the most relevant local chunks
3. it labels those chunks as sources such as `S1`, `S2`, and so on
4. it prompts the local model to answer only from those sources
5. it displays:
   - short answer
   - more detail
   - source list
   - copyable source snippets

Important behavior:

- if retrieval looks weak, the system should not guess
- instead, it says it is unsure and shows the closest matching snippets

That grounding behavior is central to the product identity.

### 4.3 Beginner Python code tutoring

The code tutoring flow works like this:

1. the user pastes Python code
2. the user optionally provides tests
3. AccessLab runs the code locally in a temporary working directory
4. it captures stdout, stderr, and failing test output
5. it asks the local model to produce:
   - what failed
   - what evidence shows that
   - the smallest fix
   - patched code
   - why the fix works
6. it reruns the patched code
7. it reports whether the patch passed

This is important because AccessLab is not just “explaining code.” It is testing, patching, and validating locally.

### 4.4 Accessible output structure

The app is intentionally simple in presentation.

The output is designed to be:

- semantically structured
- keyboard usable
- screen-reader friendly
- concise by default

Normal answer structure is:

- short answer first
- explanation second
- sources or test results after that

The interface includes:

- semantic headings
- proper labels
- visible focus states
- a live status region
- copyable text areas for sources and outputs

## 5. Current Technical Shape

The application currently uses:

- Python
- FastAPI
- server-rendered HTML templates
- SQLite
- SQLite FTS5
- local filesystem storage
- Ollama for local model inference

The architecture is intentionally shallow.

Major logical components:

- document ingestion
- retrieval
- LLM provider
- grounded Q and A service
- code runner
- code tutor service
- minimal accessible UI

The model provider is local. There is no cloud dependency in the core workflow.

## 6. Current Runtime Default

The current default demo and runtime model is:

- `gemma4:e4b`

The current smaller comparison model inside the same family is:

- `gemma4:e2b`

Why `gemma4:e4b` is the default:

- best measured pass rate
- best measured latency on the measured host
- fewer accessibility failures
- only one major benchmark miss before the latest patch
- stronger benchmark story overall

`gemma4:e2b` is still important as:

- a smaller comparison profile
- a fallback candidate
- the preferred weak-tier Gemma 4 comparison model

## 7. Where We Are Right Now

AccessLab is no longer in the “idea” phase.

It is now in the “working prototype with measurable behavior” phase.

That is a big project transition.

It means the main work is no longer invention. The main work is now:

- optimization
- validation
- latency control
- deployment realism
- failure cleanup

Current status in one sentence:

AccessLab already works as a local grounded classroom and beginner-code assistant, but it still needs better latency discipline and a real weak-device benchmark.

## 8. What We Have Already Tested

### 8.1 Functional product behavior

The prototype already exercises these end-to-end behaviors:

- upload local worksheet material
- answer grounded questions from local material
- display visible citations
- show source snippets instead of guessing when retrieval is weak
- accept buggy beginner Python code
- run code locally
- explain the bug
- propose a minimal patch
- rerun the patched code
- show pass or fail after rerun

### 8.2 Automated tests

Current test suite status as of 2026-04-19:

- 10 tests passing

The automated tests currently cover:

- document chunking
- retrieval behavior
- code runner success
- code runner timeout
- citation formatting
- Q and A uncertainty handling
- code tutor evidence parsing
- code tutor evidence fallback behavior

This is still a lightweight suite, but it is meaningful for a prototype at this stage.

### 8.3 Evaluation pack

AccessLab Eval v0.1 contains 20 tasks:

- 8 worksheet/local-doc tasks
- 8 beginner Python bug-fix tasks
- 4 accessibility/output-format tasks

For each task, the evaluation logs:

- TTFT
- total response time
- grounded yes or no
- citation correct yes or no
- helpful yes or no
- too verbose yes or no
- passed tests yes or no for code tasks
- notes

### 8.4 Benchmark runs already completed

The key benchmark runs were completed on April 14, 2026.

Measured host:

- Apple M4 Pro
- 24 GB RAM
- 14 logical cores

Completed model-tier runs:

- `gemma4:e4b`
- `gemma4:e2b`

Important benchmark caveat:

These runs were performed on the same host.

That means the benchmark does prove the Gemma 4 model-tier tradeoff on the measured machine.

It does not yet prove behavior on a separate aging laptop or clearly weaker CPU-only device.

## 9. Benchmark Results Before the Code-Tutor Evidence Patch

### 9.1 Baseline `gemma4:e4b` run

Date:

- 2026-04-14

Results:

- 19 of 20 tasks passed
- 95% pass rate
- average TTFT: 10.74s
- average total response time: 13.31s
- average model inference time: 13.18s

Category breakdown:

- worksheet/local-doc: 8 of 8
- beginner Python bug-fix: 7 of 8
- accessibility/output-format: 4 of 4

The only failure in that run was:

- `code-08`

And that failure was not a patch failure.

It was an explanation-grounding failure:

- the patch passed tests
- but the explanation did not clearly reference runtime or test evidence

### 9.2 `gemma4:e2b` comparison run

Date:

- 2026-04-14

Results:

- 16 of 20 tasks passed
- 80% pass rate
- average TTFT: 17.66s
- average total response time: 22.29s
- average model inference time: 22.16s

Category breakdown:

- worksheet/local-doc: 7 of 8
- beginner Python bug-fix: 7 of 8
- accessibility/output-format: 2 of 4

Notable failures:

- one document-grounding/content miss
- one code explanation-grounding miss
- two verbosity failures in accessibility mode

### 9.3 Main conclusion from the original benchmark

On the measured host:

- `gemma4:e4b` was better than `gemma4:e2b`
- `gemma4:e4b` was also faster than `gemma4:e2b`
- the dominant latency cost was model inference, not retrieval or code execution

At that point, the main problem was not “does AccessLab work?”

The main problem was:

How good is the quality/latency tradeoff, and how well will it hold on weaker hardware?

## 10. The Most Important Failure We Found

The most important shared failure pattern was:

The patch is correct, but the explanation is not sufficiently evidence-grounded.

This matters because the product is not only supposed to fix code. It is supposed to teach and explain.

If the explanation is weakly grounded, the tutoring experience becomes less trustworthy even when the patch succeeds.

This is why `code-08` became the most important regression target in the whole eval pack.

## 11. What We Changed After the Benchmark

After the April 14 benchmark, the code tutor was tightened to directly address the explanation-grounding problem.

The current code-tutor structure now explicitly separates:

- what failed
- what evidence shows that
- smallest fix
- why the fix works

The evidence section is intended to force the model to quote or point to concrete runtime or test output instead of hand-waving.

This was the right change because it targeted the highest-value failure mode directly.

## 12. Post-Patch Full Rerun

After the code-tutor evidence patch, the full 20-task benchmark was rerun on:

- 2026-04-14
- using `gemma4:e4b`
- on the post-patch system

### 12.1 Post-patch results

Results:

- 20 of 20 tasks passed
- 100% pass rate
- average TTFT: 17.40s
- average total response time: 21.71s
- average model inference time: 21.51s

### 12.2 What changed

The important quality win:

- `code-08` turned from a fail into a pass

Specifically:

- before the patch, `code-08` passed tests but failed the evaluation because the explanation was not grounded enough
- after the patch, `code-08` passed tests and also passed the grounding criterion

### 12.3 What did not regress

The post-patch rerun did not introduce a verbosity failure.

That matters because one of the risks was:

If we force a stronger evidence explanation, do we make the answer too long?

In the measured rerun, the answer stayed within the benchmark verbosity target.

### 12.4 What did regress

The post-patch rerun did not preserve the earlier latency profile.

Compared with the earlier `gemma4:e4b` baseline:

- pass rate improved from 95% to 100%
- average TTFT increased by 6.66s
- average total response time increased by 8.40s
- average model inference time increased by 8.33s

### 12.5 Important nuance about the slowdown

The slowdown was broad.

It did not affect only code tasks.

Category-level averages also increased across:

- worksheet/local-doc tasks
- beginner Python bug-fix tasks
- accessibility/output-format tasks

That means the safe conclusion is:

The quality improvement is real, but the latency increase cannot be confidently blamed on the code-tutor prompt change alone without another controlled rerun.

## 13. Where We Are Now, Technically

Current state of the project:

- the product wedge is real
- the local workflow works
- grounded worksheet explanation works
- citation behavior works
- code patching works
- explanation grounding in code mode improved enough to clear the full pack
- latency remains the main visible system cost
- weak-device proof is still incomplete

So the project is strong in correctness relative to prototype scope, but still incomplete in deployment validation.

## 14. What the Current Evidence Proves

The evidence now does prove:

- a grounded local-first classroom assistant is viable
- local worksheet Q and A can be made citation-aware
- beginner code tutoring can work with local execution and patch validation
- Gemma 4 can support this use case locally
- a small, inspectable vertical slice is already in place

The evidence does not yet prove:

- final performance on a separate aging laptop
- production-grade code sandbox safety
- large-scale semantic retrieval quality
- that the latest quality win comes without a stable latency cost

## 15. Current Risks and Open Questions

### 15.1 Biggest product risk

The biggest remaining product risk is:

Can AccessLab keep strong evidence-grounded explanations while also keeping latency low enough for real constrained hardware?

### 15.2 Biggest benchmark gap

The biggest benchmark gap is:

A real weak-device run on a separate machine.

That is still unresolved.

### 15.3 Biggest measurement question

The biggest immediate measurement question is:

Was the post-patch latency increase a real repeatable regression, or was it a broader rerun effect on that host?

That requires another controlled rerun.

## 16. What Is Strong Right Now

Strong points:

- narrow, credible product wedge
- local-first architecture
- grounded Q and A
- visible citations
- reliable local code reruns
- patch correctness
- improved code explanation grounding
- passing automated tests
- full eval pack already built

This is more than a concept. It is already a measurable prototype.

## 17. What Is Weak or Incomplete Right Now

Weak or incomplete points:

- latency is still heavy
- weak-device story is not fully proven
- post-patch latency behavior needs a controlled confirmation rerun
- retrieval is lexical, not semantic
- sandboxing is prototype-grade, not hardened

## 18. What We Should Do Next

Recommended next sequence:

1. run one more controlled `gemma4:e4b` full 20-task rerun on the same host
2. compare it against:
   - the original `e4b` baseline
   - the post-patch `e4b` rerun
3. determine whether the latency jump is repeatable
4. run the same eval pack on a real weaker machine
5. compare `gemma4:e4b` and `gemma4:e2b` there on:
   - pass rate
   - TTFT
   - total response time
6. tighten prompt compactness and output length if needed
7. tighten retrieved context size if latency or grounding still needs help

Only after that should the project seriously decide whether it needs:

- smaller-model routing
- different local deployment modes
- or training

## 19. Best Current Strategic Read

Right now, AccessLab looks real enough that the strategic question is no longer:

“Does it work?”

The strategic question is now:

“What is the best quality and latency tradeoff for real school hardware?”

That is a much better place for the project to be.

## 20. One-Sentence Conclusion

AccessLab v0.1 is now a working local-first classroom and beginner-code assistant with measurable grounded behavior; the next phase is validating the quality/latency tradeoff on weaker hardware and confirming that the explanation-grounding win can be retained without unacceptable latency cost.
