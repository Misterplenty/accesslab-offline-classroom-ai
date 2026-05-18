# AccessLab Judge Proof Bundle

- Generated at: 2026-05-18T22:25:03.467520+00:00
- Commit hash: `366e930a9a2046b1383f8d395ca54b515786e1dd`
- Hardware: macOS-15.7.4-arm64-arm-64bit-Mach-O / arm64
- Artifact summary: 18 included, 0 missing
- Scope: local-first grounded QA, verified beginner Python repair, Ollama runtime proof, school-box load, and accessibility artifacts.
- Product thesis: Gemma 4 answers from local classroom materials with visible citations and repairs beginner Python through local run, minimal patch, and rerun.
- Architecture summary: server-rendered FastAPI UI, local SQLite/FTS5 storage, optional EmbeddingGemma semantic index via local Ollama, Gemma 4 generation via local Ollama, local Python execution for the narrow repair loop, and local proof scripts.
- Gemma 4 centrality: `gemma4:e4b` and `gemma4:e2b` are the only accepted user-facing generation models.
- EmbeddingGemma centrality: `embeddinggemma` is the default semantic retrieval model; lexical fallback is reported when it is unavailable.

## Included Artifacts

| Artifact | Status | Stable File |
| --- | --- | --- |
| readme | included | `reports/judge/latest/readme.md` |
| benchmark_summary | included | `reports/judge/latest/benchmark_summary.md` |
| benchmark_bundle | included | `reports/judge/latest/benchmark_bundle.json` |
| accessibility_smoke | included | `reports/judge/latest/accessibility_smoke.md` |
| accessibility_smoke_json | included | `reports/judge/latest/accessibility_smoke_json.json` |
| operator_preflight | included | `reports/judge/latest/operator_preflight.md` |
| system_snapshot | included | `reports/judge/latest/system_snapshot.json` |
| deployment_snapshot | included | `reports/judge/latest/deployment_snapshot.md` |
| embeddinggemma_setup | included | `reports/judge/latest/embeddinggemma_setup.md` |
| embeddinggemma_setup_json | included | `reports/judge/latest/embeddinggemma_setup_json.json` |
| semantic_retrieval_proof | included | `reports/judge/latest/semantic_retrieval_proof.md` |
| semantic_retrieval_proof_json | included | `reports/judge/latest/semantic_retrieval_proof_json.json` |
| school_box_load | included | `reports/judge/latest/school_box_load.md` |
| school_box_load_json | included | `reports/judge/latest/school_box_load_json.json` |
| school_box_demo_proof | included | `reports/judge/latest/school_box_demo_proof.md` |
| school_box_demo_proof_json | included | `reports/judge/latest/school_box_demo_proof_json.json` |
| semantic_retrieval | included | `reports/judge/latest/semantic_retrieval.md` |
| demo_runbook | included | `reports/judge/latest/demo_runbook.md` |

## Five-Minute Review Path

1. Read `readme.md` for the product shape and limitations.
2. Read `semantic_retrieval_proof.md` and `embeddinggemma_setup.md` for retrieval evidence.
3. Read `benchmark_summary.md` for measured runtime claims.
4. Read `school_box_demo_proof.md` and `school_box_load.md` for the classroom/shared-host story.
5. Read `accessibility_smoke.md` for the keyboard/focus/accessibility release-gate boundary.

## Honest Limits

- Gemma 4 remains the only user-facing reasoning model.
- EmbeddingGemma remains the default semantic retrieval model.
- No cloud fallback is included or claimed.
- School-box load is local synthetic proof, not a production distributed queue claim.
- Benchmark evidence applies only to the hardware and model setup actually recorded in local artifacts.
- The beginner Python runner is a local demo runner, not a production secure sandbox.
