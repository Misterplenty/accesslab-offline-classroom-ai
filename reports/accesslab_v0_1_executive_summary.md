# AccessLab v0.1 Executive Summary

## What AccessLab Is

AccessLab is a local-first classroom assistant designed for unreliable internet and aging school hardware. It focuses on one narrow job: explain local worksheet materials with citations, and help beginners fix small Python bugs with local test execution and screen-reader-friendly output.

## What Was Tested

AccessLab v0.1 was evaluated on a 20-task pack:

- 8 worksheet and local-document grounded Q&A tasks
- 8 beginner Python bug-fix tasks
- 4 accessibility and output-format tasks

Both Gemma 4 tiers were run end to end:

- `gemma4:e4b`
- `gemma4:e2b`

## Which Model Tier Won

`gemma4:e4b` is the current default runtime and demo model.

Results on the current host:

- `gemma4:e4b`: 19/20 passed, 95%, average TTFT 10.74s, average total response time 13.31s
- `gemma4:e2b`: 16/20 passed, 80%, average TTFT 17.66s, average total response time 22.29s

Why `gemma4:e4b` is the right default now:

- better pass rate
- better latency on the measured host
- fewer accessibility and formatting failures
- only one miss, and it was an explanation-grounding issue rather than a code patch failure

## What Is Already Working

- grounded worksheet Q&A is consistently working
- citations are consistently visible
- beginner Python patches are usually correct when judged by rerun test results
- the product already behaves like a real vertical slice rather than an idea

## What Still Needs Proof

The current benchmark proves the Gemma 4 model-tier tradeoff on the same machine. It does not yet prove performance on a separate aging laptop or clearly weaker CPU-only device.

That means the main unresolved competition question is:

What is the best quality and latency tradeoff on real school hardware?

## Top Current Issue

The main shared failure is not patch correctness. It is explanation grounding.

In the current misses, the patch can be right while the explanation does not clearly cite the runtime or test evidence strongly enough.

## Next 3 Fixes

- force the code explanation to separate what failed from the concrete evidence
- reduce output length by default so accessible answers stay short
- tighten retrieved context so the strongest source chunk dominates the QA prompt

## Recommended Next Step

Run the same 20-task evaluation pack on a real weaker machine, then compare `gemma4:e4b` and `gemma4:e2b` on pass rate, TTFT, and total response time.

## One-Sentence Conclusion

AccessLab v0.1 shows that a grounded, local-first classroom and coding assistant is already viable with Gemma 4; the main remaining work is reducing inference cost on weaker hardware and tightening evidence-grounded explanations.
