# AccessLab School-Box Demo Proof

- Generated at: 2026-05-18T19:15:25.559904+00:00
- Overall status: pass
- Runtime backend: ollama
- Deployment mode: School AI box
- Class space: judge-demo-class
- Model: gemma4:e4b (E4B)
- Retrieval: hybrid -> Hybrid
- Semantic: ok / ready=True
- OCR available: True
- Total demo script seconds: 23.273

## Story

- Teacher uploaded 2 local material file(s).
- Learner asked: What does `for item in numbers:` mean?
- QA saved URL: `/qa?qa_id=1` with 2 citation(s).
- Code repair saved URL: `/code?session_id=1`; patched tests passed: True.
- Teacher/admin review found saved QA: True; saved code: True.

## Live Demo Checklist

- Start with ACCESSLAB_DEPLOYMENT_MODE=school-box-shared.
- Use class-space judge-demo-class unless the judge asks for a different class.
- Pull gemma4:e4b and embeddinggemma before the demo.
- Keep ACCESSLAB_MAX_CONCURRENT_JOBS=1 for the safest live demo.
- Show local URL http://127.0.0.1:8000 and LAN URL from the host network settings.
- Expected failures: missing Gemma 4 model, missing EmbeddingGemma, OCR extras unavailable, or long queue wait during embedding/generation.

## Classroom Limitations

- One host bottlenecks under simultaneous generation, OCR, and embedding work.
- The queue is local/in-process in this prototype.
- School-box mode is intended for supervised local classroom deployment.
- This is not production multi-user serving or a production secure sandbox.

## Uploaded Materials

- `worksheet_question3.md`: 1 chunk(s), OCR=not_applicable
- `python_loops_notes.txt`: 1 chunk(s), OCR=not_applicable

## QA Evidence

It means the program goes through the list one item at a time [S1], [S2].

- [S1] `worksheet_question3.md` chunk `worksheet_question3-p0-c1-013585d640`
- [S2] `python_loops_notes.txt` chunk `python_loops_notes-p0-c1-5940939291`

## Code Repair

- Diagnosis: The function incorrectly subtracts the two numbers, causing the assertion `assert -1 == 5` to fail when called with (2, 3).
- Evidence: The function incorrectly subtracts the two numbers, causing the assertion `assert -1 == 5` to fail when called with (2, 3).
- Next fix: Change the subtraction operator to an addition operator.
