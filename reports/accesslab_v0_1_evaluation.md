# AccessLab v0.1 Evaluation — Model-Tier Complete (e4b and e2b), Real Weak-Device Benchmark Pending

Generated: 2026-04-14 08:30 UTC

This report summarizes the current AccessLab evaluation pack, timing profile, device comparison, and the next fixes to prioritize before any training work.

## Summary Status

> Status: model-tier complete, hardware-tier provisional
> Complete for: gemma4:e4b and gemma4:e2b on the current host (Apple M4 Pro)
> Pending: a real weak-device benchmark on separate aging hardware
> Do not treat hardware-tier conclusions as final until the same task pack is run on a separate weak machine

## Pass/Fail Table

| Task | Category | Pass | TTFT | Total | Grounded | Citation | Helpful | Too Verbose | Passed Tests |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| doc-01 | worksheet/local-doc | yes | 17.39s | 19.41s | yes | yes | yes | no | n/a |
| doc-02 | worksheet/local-doc | yes | 14.62s | 16.58s | yes | yes | yes | no | n/a |
| doc-03 | worksheet/local-doc | yes | 11.52s | 12.49s | yes | yes | yes | no | n/a |
| doc-04 | worksheet/local-doc | yes | 9.53s | 10.82s | yes | yes | yes | no | n/a |
| doc-05 | worksheet/local-doc | yes | 10.12s | 11.24s | yes | yes | yes | no | n/a |
| doc-06 | worksheet/local-doc | yes | 13.51s | 15.01s | yes | yes | yes | no | n/a |
| doc-07 | worksheet/local-doc | yes | 12.35s | 14.12s | yes | yes | yes | no | n/a |
| doc-08 | worksheet/local-doc | yes | 6.76s | 7.36s | yes | yes | yes | no | n/a |
| code-01 | beginner-python-bug-fix | yes | 8.86s | 12.86s | yes | n/a | yes | no | yes |
| code-02 | beginner-python-bug-fix | yes | 7.77s | 11.91s | yes | n/a | yes | no | yes |
| code-03 | beginner-python-bug-fix | yes | 6.66s | 10.47s | yes | n/a | yes | no | yes |
| code-04 | beginner-python-bug-fix | yes | 9.48s | 13.47s | yes | n/a | yes | no | yes |
| code-05 | beginner-python-bug-fix | yes | 8.02s | 12.38s | yes | n/a | yes | no | yes |
| code-06 | beginner-python-bug-fix | yes | 8.51s | 12.99s | yes | n/a | yes | no | yes |
| code-07 | beginner-python-bug-fix | yes | 5.53s | 9.11s | yes | n/a | yes | no | yes |
| code-08 | beginner-python-bug-fix | no | 11.58s | 15.70s | no | n/a | yes | no | yes |
| a11y-01 | accessibility/output-format | yes | 14.03s | 16.74s | yes | yes | yes | no | n/a |
| a11y-02 | accessibility/output-format | yes | 13.82s | 15.98s | yes | yes | yes | no | n/a |
| a11y-03 | accessibility/output-format | yes | 10.55s | 11.77s | yes | yes | yes | no | n/a |
| a11y-04 | accessibility/output-format | yes | 14.13s | 15.79s | yes | yes | yes | no | n/a |

## Device Table

| Device | Tier | Model | CPU | Memory | Cores | Avg TTFT | Avg Total | Pass Rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| primary-benchmark-2026-04-14 | decent | gemma4:e4b | Apple M4 Pro | 24.0 GB | 14 | 10.74s | 13.31s | 95% |
| weak-gemma4-e2-2026-04-14 | weak | gemma4:e2b | Apple M4 Pro | 24.0 GB | 14 | 17.66s | 22.29s | 80% |

Current device table includes the weak-tier gemma4:e2b comparison, but both runs were executed on the same host. Treat this as a Gemma 4 model-tier comparison, not a true two-machine hardware benchmark.

## TTFT Table

| Device | Avg TTFT | Median TTFT | Avg Total | Retrieval | Prompt Build | Model Inference | Post-Processing | Code Execution |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| primary-benchmark-2026-04-14 | 10.74s | 10.34s | 13.31s | 0.00s | 0.00s | 13.18s | 0.00s | 0.06s |
| weak-gemma4-e2-2026-04-14 | 17.66s | 16.99s | 22.29s | 0.00s | 0.00s | 22.16s | 0.00s | 0.07s |

## Top 3 Failure Modes

- `missed_expected_content`: 3 task(s)
- `weak_evidence_reference`: 2 task(s)
- `verbosity`: 2 task(s)

## Next 3 Fixes

- Tighten retrieved context size so the strongest chunk dominates the prompt.
- Make the code-tutor prompt quote failing test or runtime lines explicitly before proposing a fix.
- Reduce default output length and cap extra detail unless the user explicitly asks for more.

## Conclusion Note

Current conclusions include both Gemma 4 model tiers on the current host. Hardware-tier conclusions remain provisional until a separate weak machine is benchmarked with the same 20-task pack.

## Notes

- Primary run: `reports/runs/20260414T081122Z-primary-benchmark-2026-04-14-gemma4-e4b/summary.json`
- Comparison run: `reports/runs/20260414T082126Z-weak-gemma4-e2-2026-04-14-gemma4-e2b/summary.json`
- The preferred weak-tier comparison for this project is `gemma4:e2b`.
- Both runs in this report were executed on the same Apple M4 Pro host on 2026-04-14.
- This report now proves the Gemma 4 quality/latency tradeoff across `gemma4:e4b` and `gemma4:e2b`, but it does not yet prove behavior on a separate aging laptop.
