# AccessLab Device-Tier Comparison

- Generated at: 2026-05-18T10:06:49.343213+00:00
- Runs included: 1
- Real hardware runs: 1
- Constrained-proxy runs: 0
- Device tiers: Teacher laptop / mini-PC

## Run Table

| Run | Device Tier | CPU/RAM | Runtime | Model | Mode | Retrieval | Semantic | OCR | Pass | Code | Support | TTFT | Total | Tokens In/Out | Queue | Peak MB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full-proof-20260518 | Teacher laptop / mini-PC | Apple M4 Pro / 24.0 GB | ollama | gemma4:e4b (E4B) | School AI box | hybrid -> Hybrid | ok | False | 100% | 100% | 100% | 11.33s | 13.52s | 824.0/609.0 | 0.00s | 54.1 |

## What This Proves

- The listed benchmark rows ran on the recorded local hardware and runtime backend.
- Gemma 4 task pass, citation, code repair, latency, token, queue, OCR, and semantic fields are taken from run artifacts.
- Rows marked teacher-laptop, standard-laptop, school-box-host, or edge-validation-device are hardware evidence for that recorded host only.

## What This Does Not Prove

- It does not prove performance on lowest-end phones or untested devices.
- It does not prove production multi-user serving.
- It does not prove secure code sandboxing.
- Constrained-proxy rows are stress comparisons on the same host, not separate hardware tiers.

## Source Summaries

- `reports/runs/20260518T100128Z-judge-demo-host-gemma4-e4b-full-proof-20260518/summary.json`
