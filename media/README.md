# AccessLab Media Shot List

Final screenshots and video are owner-managed. Do not add placeholder screenshots to the Kaggle submission as if they are final assets.

| File name | Route/page | Viewport | Seeded state | Caption | Hide before sharing | Use |
| --- | --- | --- | --- | --- | --- | --- |
| `accesslab-cover-hero.png` | `/judge-demo` | Desktop 1440x1000 | `make judge-demo` | AccessLab guided local classroom demo | Browser chrome if distracting | Kaggle cover/gallery |
| `accesslab-judge-demo.png` | `/judge-demo` | Desktop 1440x1000 | `make judge-demo` | Guided judge flow with Q&A, sources, Python repair, teacher summary, and proofs | Local host URL optional | README/Kaggle gallery |
| `accesslab-grounded-qa.png` | `/qa?qa_id=<seeded>` | Desktop 1440x1000 | Seeded answered QA | Citation-backed answer from local materials | Any personal path or local username | Kaggle gallery |
| `accesslab-source-inspection.png` | `/sources/<seeded-chunk>?qa_id=<seeded>` | Desktop 1440x1000 | Seeded cited source | Inspect cited classroom source context | Any local file-system detail | Kaggle gallery |
| `accesslab-abstention.png` | `/qa?qa_id=<seeded-weak>` | Desktop 1440x1000 | Seeded no-match QA | Abstention when evidence is weak | None expected | Kaggle gallery |
| `accesslab-python-repair.png` | `/code?session_id=<seeded>` | Desktop 1440x1000 | Seeded code repair | Beginner Python bug, minimal fix, and passing rerun | None expected | Kaggle gallery |
| `accesslab-teacher-summary.png` | `/` as Teacher/Admin | Desktop 1440x1000 | Seeded demo class | Teacher-visible class summary and review labels | Any non-demo learner names | README/Kaggle gallery |
| `accesslab-proof-dashboard.png` | `/proofs` | Desktop 1440x1000 | After smoke/proof commands | Honest proof dashboard with ready/missing/stale states | Local paths, if any artifact text is open | README/Kaggle gallery |
| `accesslab-accessibility.png` | Any main page with toolbar open | Desktop or mobile | App running | Accessibility toolbar and readable controls | None expected | Kaggle gallery |
| `accesslab-architecture-local-flow.png` | Diagram or README-rendered image | Desktop 1440x1000 | N/A | Local flow: teacher materials -> retrieval -> Gemma 4/Ollama -> cited answer/code repair | No private paths | README/Kaggle gallery |

Before uploading, verify each image in an incognito/private window and check that no `/Users/...`, secrets, raw DB paths, or unrelated local files are visible.
