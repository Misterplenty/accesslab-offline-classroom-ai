# AccessLab v0.1 Post-Patch Regression Check

Generated: 2026-04-14

## Question

Did the evidence-grounding patch turn the last major code-tutoring failure into a pass without hurting latency or brevity?

## Short Answer

Partially.

- Yes, the patch turned the last major code-tutoring failure into a pass.
- Yes, the rerun did not introduce a brevity failure.
- No, the rerun did not preserve the earlier latency profile.

## Before vs After

| Run | Model | Tasks Passed | Pass Rate | Avg TTFT | Avg Total | Avg Model Inference |
| --- | --- | --- | --- | --- | --- | --- |
| Pre-patch baseline | `gemma4:e4b` | 19 / 20 | 95% | 10.74s | 13.31s | 13.18s |
| Post-patch rerun | `gemma4:e4b` | 20 / 20 | 100% | 17.40s | 21.71s | 21.51s |

## Delta

- Pass count improved from 19 to 20
- Pass rate improved from 95% to 100%
- Average TTFT increased by 6.66s
- Average total response time increased by 8.40s
- Average model inference time increased by 8.33s

## Key Regression Test: `code-08`

### Before

- task pass: no
- grounded: no
- too verbose: no
- passed tests: yes
- TTFT: 11.58s
- total response time: 15.70s
- note: patch passed tests, but the explanation did not clearly reference runtime or test evidence

### After

- task pass: yes
- grounded: yes
- too verbose: no
- passed tests: yes
- TTFT: 17.40s
- total response time: 25.02s
- note: patched tests passed; pass

## Brevity Check

The post-patch rerun did not create a brevity regression in the benchmark scoring.

Important observations:

- `code-08` remained within the verbosity target
- the full rerun passed all four accessibility/output-format tasks
- the rerun did not add any `too_verbose` failures

## Latency Check

The post-patch rerun was materially slower than the earlier `gemma4:e4b` baseline.

### Category-level averages

| Category | Pre-patch Avg TTFT | Post-patch Avg TTFT | Pre-patch Avg Total | Post-patch Avg Total |
| --- | --- | --- | --- | --- |
| Worksheet/local-doc | 11.98s | 18.99s | 13.38s | 21.14s |
| Beginner Python bug-fix | 8.30s | 14.14s | 12.36s | 21.23s |
| Accessibility/output-format | 13.13s | 20.73s | 15.07s | 23.80s |

## Interpretation

The quality gain is real:

- the system now clears the full 20-task pack
- the major code-tutor explanation-grounding miss is fixed in the measured rerun

The latency increase is also real:

- the rerun is slower across the whole benchmark
- the slowdown is not isolated to code tasks
- worksheet and accessibility tasks also became slower

Because the slowdown affected all categories, the safe conclusion is:

The post-patch system improved correctness, but this rerun does not preserve the earlier latency profile, and the broader slowdown cannot be attributed with confidence to the code-tutor prompt change alone without another controlled rerun.

## Current Best Read

The evidence-grounding patch was worth it for quality.

However, the next technical question is now:

Can AccessLab keep the explanation-grounding win while recovering the earlier latency profile?

## Recommended Immediate Next Step

Run one more controlled `gemma4:e4b` rerun under the same host conditions to check whether the slowdown was transient or repeatable, then compare:

- overall TTFT
- total response time
- `code-08`
- verbosity outcomes
