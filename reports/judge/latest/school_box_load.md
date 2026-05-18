# AccessLab School-Box Load Snapshot

- Generated at: 2026-05-18T19:14:59.128812+00:00
- Scenario: school-box-shared-queued-load
- Scenario description: Synthetic local contention against the same in-process queue primitive used by uploads, grounded QA, code tutor, OCR, and embedding/indexing work.
- Submitted jobs: 12
- Completed jobs: 12
- Failed jobs: 0
- Completion rate: 100.0%
- Max concurrent jobs configured: 1
- Max observed active jobs: 1
- Max observed waiting jobs: 11
- Avg queue wait: 1.117s
- Median queue wait: 1.119s
- P95 queue wait: 2.031s
- Max queue wait: 2.234s

## Queue Behavior

Jobs are first-in, first-served by ticket and constrained by the local capacity budget. This synthetic run exercises the same queue primitive used by uploads, grounded QA, code repair, OCR, and indexing.

## What The Synthetic Test Does

- Submits multiple local jobs at nearly the same time.
- Measures queue wait distribution under the configured local concurrency budget.
- Confirms the in-process queue exposes active, waiting, completed, and failed job state.

## What The Synthetic Test Does Not Prove

- It does not call Gemma 4, OCR, or EmbeddingGemma for every synthetic job.
- It does not prove production multi-user serving or a distributed queue.
- It does not prove one host can satisfy a full classroom at once without wait time.

## Honest Limits

- This is local synthetic load, not internet-scale concurrency proof.
- School-box mode is intended for a classroom LAN and a conservative number of simultaneous learners.
- Queue pressure increases wait time; large OCR or embedding work should be avoided during live student use.
- Prefer teacher-laptop or classroom-local mode when one machine is driving the lesson for the room.
- Prefer school-box mode when several browsers need the same local materials and host.

## Job Rows

| Ticket | Kind | Outcome | Wait | Run |
| --- | --- | --- | --- | --- |
| 1 | code-tutor | complete | 0.0s | 0.205s |
| 2 | code-tutor | complete | 0.205s | 0.202s |
| 3 | grounded-qa | complete | 0.407s | 0.202s |
| 4 | grounded-qa | complete | 0.61s | 0.203s |
| 5 | code-tutor | complete | 0.813s | 0.205s |
| 6 | grounded-qa | complete | 1.018s | 0.201s |
| 7 | grounded-qa | complete | 1.219s | 0.203s |
| 8 | grounded-qa | complete | 1.422s | 0.202s |
| 9 | grounded-qa | complete | 1.624s | 0.203s |
| 10 | grounded-qa | complete | 1.827s | 0.203s |
| 11 | grounded-qa | complete | 2.031s | 0.203s |
| 12 | grounded-qa | complete | 2.234s | 0.205s |
