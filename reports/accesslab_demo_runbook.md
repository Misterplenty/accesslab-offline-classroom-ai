# AccessLab Demo Runbook

## Purpose

This runbook is for showing the strongest current AccessLab story without broadening scope.

The recommended demo path is:

1. Upload a local worksheet/text PDF
2. Ask a grounded question and show citations
3. Optionally show OCR-backed ingest on a scanned PDF
4. Run the Python code tutor on a known buggy example
5. Optionally inspect `/healthz`

## Prerequisites

- Python 3.14
- Ollama `>= 0.21`
- `gemma4:e4b` pulled locally
- `gemma4:e2b` pulled locally
- Recommended: `embeddinggemma` for hybrid retrieval
- Optional for OCR demo: `requirements-ocr.txt` installed and a scanned/image-based PDF available locally

## First-Time Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
make install
cp .env.example .env
```

Start Ollama:

```bash
ollama serve
```

Pull the models:

```bash
ollama pull gemma4:e4b
ollama pull gemma4:e2b
ollama pull embeddinggemma
```

Optional OCR extras:

```bash
.venv/bin/python -m pip install -r requirements-ocr.txt
```

## Strong-Profile Demo

Start the app on the strongest current path:

```bash
make run-strong
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### Happy Path Sequence

1. Upload `sample_data/worksheet_question3.md`.
2. Upload `sample_data/python_loops_notes.pdf` or `sample_data/python_loops_notes.txt`.
3. Upload `sample_data/algebra_notes.md`.
4. Open the Q&A view and ask:

```text
Explain question 3 in simple language.
```

What to show:

- The shared shell keeps the current profile, model, and primary flows visible across pages without a dashboard look
- The answer is grounded in local uploaded material
- Citations are visible
- Source snippets are shown and copyable
- Each evidence card now includes an `Open source` action for inspecting the underlying local file context

5. In the same Q&A view, ask:

```text
State the area formula from the notes. Use inline math notation like $A = l \times w$.
```

What to show:

- The answer renders math more cleanly than raw `$...$` text on supported browsers
- Citation chips in the answer are clickable
- Clicking a citation jumps to the matching local evidence card
- The evidence card shows the source file, chunk id, and page label if one exists
- The Q&A page lands on a stable `/qa?qa_id=...` URL after answering
- Clicking `Open source` opens the source inspection page in a new tab so the current Q&A answer/evidence state stays intact
- If the environment reuses the same tab, the source page keeps a `Back to Q&A` link to the same saved answer state
- PDFs can then open in the browser's native PDF view, while TXT and MD files stay in the lightweight local source page

6. Open the code-tutor view.
7. Paste `sample_code/buggy_sum.py` into the code box.
8. Paste `sample_code/test_buggy_sum.py` into the tests box.
9. Use this instruction:

```text
Explain what is wrong in simple language. Suggest the smallest fix. Patch the code and rerun the tests.
```

What to show:

- The code-tutor page uses the same shell and page structure as the rest of the app
- Diagnosis
- One minimal fix
- Patched code
- Local rerun result
- The page lands on a stable `/code?session_id=...` URL so the saved review can be reloaded

10. Optional operator view:

```bash
curl http://127.0.0.1:8000/healthz
```

What to show:

- `deployment_profile`
- `active_model`
- `qa_discipline_profile`
- OCR and semantic-retrieval status
- class-space, queue, and runtime-capability snapshots in the admin System view

## Weak-Profile Demo

Start the app on the weak-profile path:

```bash
make run-weak
```

Use the same browser flow as the strong-profile demo.

Reviewer framing:

- This path exists and is wired to `gemma4:e2b`.
- The weak profile includes the weak-tier QA discipline behavior on top of the baseline QA prompt.
- Current confidence for this profile is proxy-based until a real weak device is tested.

## Optional OCR Demo

Use this only if you have a real scanned or image-based PDF available locally.

1. Install the OCR extras if they are not already installed.
2. Start the app with either profile.
3. Upload the scanned PDF.
4. Ask a simple grounded question about the document.
5. Show the upload result and any OCR notes.

CLI smoke alternative:

```bash
make smoke-ocr PDF=/absolute/path/to/scanned.pdf
```

## Recommended Demo Framing

- Strong profile is the best current demo path.
- Weak profile is present and evidence-backed, but still proxy-validated.
- OCR and hybrid retrieval are part of the current prototype wedge, not separate products.
- Math rendering is local/offline-friendly and limited to common TeX-style answer fragments, not full scientific publishing.
- Citation links only point to grounded local evidence cards that AccessLab actually retrieved.
- Evidence cards now bridge to a real local source-inspection view rather than stopping at a snippet card.
- The source page is intentionally lightweight. It is not a full document browser, editor, or annotation system.
- The code runner is hardened for the local prototype but is not presented as a production secure sandbox.

## Smoke Path: Citation To Source

1. Upload `sample_data/worksheet_question3.md`.
2. Upload `sample_data/python_loops_notes.pdf` or `sample_data/python_loops_notes.txt`.
3. Ask `Explain question 3 in simple language.`
4. Confirm the Q&A page URL is now `/qa?qa_id=...`.
5. Click `[S1]` in the answer.
6. Confirm the page jumps to the matching evidence card.
7. Click `Open source`.
8. Confirm a new tab opens to the source inspection page and the original Q&A tab still shows the existing answer and evidence cards.
9. In the source tab, confirm the page shows the file name, file type, page number when present, chunk id, and cited snippet.
10. Copy or open the `Open source` target directly and confirm the `/sources/{chunk_id}?qa_id=...` route loads correctly.
11. If the source opened in the same tab, use `Back to Q&A` and confirm it returns to the same saved answer state.
12. For PDFs, click `Open original PDF` and verify the browser opens the local PDF at the cited page when supported.

## Frontend Smoke Checklist

1. Open `/` and confirm the sticky shell shows the `AccessLab` wordmark, the `Offline classroom assistant` subtitle, text navigation, and the quiet runtime status cluster.
2. Upload a local document and confirm the workspace keeps a clear two-column layout with a restrained upload surface and clean indexed-material rows.
3. Open `/qa`, ask a grounded question, and confirm the page URL becomes `/qa?qa_id=...`.
4. Verify the answer reads like editorial content rather than a boxed widget, while citations still jump to evidence items and math stays readable.
5. Confirm the evidence rail highlights the selected source item subtly and that `Open source` still loads the source inspection route.
6. Click `Open source` and confirm the source page shows the file name, file type, chunk id, and page or whole-file context with a `Back to Q&A` path.
7. Open `/code`, run the sample buggy program, and confirm the page URL becomes `/code?session_id=...`.
8. Verify the code page presents the diagnosis, minimal fix, explanation, and rerun result with clear hierarchy and quiet semantic feedback.
9. Confirm readable mode and disclosure toggles work as progressive enhancement, not as required functionality.
