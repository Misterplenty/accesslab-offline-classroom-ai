# OCR Decision Memo

## Decision

AccessLab uses a narrow, local OCR fallback for scanned / image-based PDFs:

- `rapidocr-onnxruntime==1.2.3` for CPU OCR inference
- `pypdfium2==5.7.0` to rasterize individual PDF pages locally

The integration stays page-based and optional. PyPDF remains the default
path for normal text PDFs. OCR only runs when a PDF page yields less than
`ACCESSLAB_OCR_MIN_CHARS_PER_PAGE` characters after whitespace
normalization.

## Why This Fits AccessLab

- Local only: no cloud OCR service, no network dependency at ingest time.
- Lightweight relative to multimodal stacks: ONNX Runtime instead of
  PyTorch, and pdfium wheels instead of a larger document AI platform.
- CPU-friendly and reversible: the ingest service depends on a tiny
  `OCRBackend` protocol, so the backend can be swapped later without
  rewriting chunking, retrieval, or citations.
- Fast path preserved: text PDFs still use PyPDF directly, and scan-like
  pages are OCR'd one page at a time only when needed.
- Citation continuity: OCR text is injected back into the existing
  `(page_number, text)` units, so chunk IDs, page numbers, and source-file
  citations keep the current shape.

## Why Not Heavier OCR Stacks

- No PyTorch-first OCR stack: too heavy for the current local-first wedge
  and harder to justify on older classroom hardware.
- No cloud OCR API: violates the offline/local-first requirement.
- No layout reconstruction platform: this branch only needs recovered text
  for the existing ingest/index path, not table rebuilding or multimodal
  page understanding.
- No Tesseract-first path by default: it would add an external OS-level
  binary requirement and more setup friction than the current pip-only
  fallback path.

## Install and Runtime Tradeoffs

- OCR support is optional and stays outside `requirements.txt`. Operators
  must run `pip install -r requirements-ocr.txt` to enable scanned-PDF
  fallback.
- The OCR extras pull in ONNX Runtime and OpenCV, so OCR-enabled installs
  are heavier than the baseline text-only app.
- OCR quality depends on scan quality. Faint scans, handwriting, dense
  tables, and unusual layouts will still be imperfect.
- When OCR extras are missing or OCR produces no usable text, AccessLab
  fails clearly for scan-only PDFs instead of silently indexing empty
  content.
