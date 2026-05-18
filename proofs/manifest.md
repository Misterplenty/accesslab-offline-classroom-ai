# AccessLab Proof Manifest

Use `/proofs` in the running app for the live read-only dashboard. That page derives status from actual artifacts and preflight state, and marks missing or stale items instead of assuming a pass.

| Proof | Artifact | Status rule | Regenerate | What it proves |
| --- | --- | --- | --- | --- |
| Operator preflight | `reports/operator_preflight_latest.md` | Present and recent, or Missing/Stale | `make preflight` | Local runtime, storage, database, retrieval, OCR, queue, and model readiness snapshot |
| Semantic retrieval | `reports/semantic_retrieval_proof_latest.md` | Present and recent, or Missing/Stale | `make smoke-retrieval` | Retrieval ranking over local classroom fixture |
| Code runner boundary | `reports/code_runner_hardening_smoke_latest.md` | Present and recent, or Missing/Stale | `make smoke-code-runner` | Safe beginner code runs; blocked runtime/network attempt is denied clearly |
| Accessibility smoke | `reports/a11y_smoke_latest.md` | Present and recent, or Missing/Stale | `make smoke-a11y` | Keyboard/focus/accessibility toolbar smoke coverage |
| School-box demo proof | `reports/school_box_demo_proof_latest.md` | Present and recent, or Missing/Stale | `make school-box-demo-proof` | Canonical local teacher/learner/admin flow with grounded QA and code repair |
| School-box load proof | `reports/school_box_load_latest.md` | Present and recent, or Missing/Stale | `make school-box-load` | Local synthetic queue/load behavior for shared classroom host framing |
| Benchmark summary | `reports/accesslab_benchmark_summary.md` | Present and recent, or Missing/Stale | `make benchmark-summary` | Summary of local benchmark outputs that exist on this machine |
| Judge bundle | `reports/judge/latest/proof_index.md` | Present and recent, or Missing/Stale | `make judge-bundle` | Stable judge-facing proof bundle index |

## Notes

- Do not claim a proof passes unless the corresponding command has completed successfully in the final environment.
- Artifacts may contain machine-specific runtime facts when generated locally; review them before committing or presenting.
- The dashboard intentionally shows Missing, Stale, Attention, or Blocked states when evidence is absent or dependencies are unavailable.
