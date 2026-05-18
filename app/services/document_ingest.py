"""Document ingest pipeline for AccessLab.

This module is intentionally small. The happy path is unchanged: PyPDF
extracts embedded text from a PDF, the text is chunked, and each chunk is
written to both ``document_chunks`` and the FTS5 shadow table with the
page number preserved for citations.

The only new responsibility here is a *per-page OCR fallback* for scanned
PDFs. When PyPDF returns no meaningful text for a page (the page looks
like a rasterised scan of a worksheet), the ingest service asks the
injected :class:`~app.services.ocr.OCRBackend` to OCR that specific page
locally. The OCR'd text then flows through exactly the same chunking /
indexing path as normal extracted text, which keeps page-based citations
working for scanned material.

The fallback is strictly optional:
    * If no backend is injected (`ocr_backend=None`) -> we behave exactly
      like the pre-OCR implementation. Scanned pages drop out quietly.
    * If a backend is injected but reports unavailable -> scanned pages
      are reported as "OCR unavailable" so operators know why the
      document looks empty, instead of silently indexing nothing.
    * If OCR raises mid-page -> that page is skipped with a note; other
      pages still get indexed.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

from app.db import db_connection, utc_now_iso
from app.models.schemas import IngestSummary
from app.services.ocr import OCRBackend, OCRUnavailableError
from app.services.semantic import SQLiteSemanticIndex


logger = logging.getLogger(__name__)


SUPPORTED_FILE_TYPES = {
    ".pdf": "pdf",
    ".txt": "txt",
    ".md": "md",
}


# A PDF page whose PyPDF-extracted text (after whitespace normalisation) is
# shorter than this threshold is considered "scan-like" and eligible for
# OCR fallback. 20 characters is intentionally low — normal worksheet
# pages have dozens to hundreds of characters, while scanned pages
# typically produce 0–5 characters of junk (page numbers, stray glyphs).
# Operators can tune this via ``ACCESSLAB_OCR_MIN_CHARS_PER_PAGE`` without
# touching code.
DEFAULT_OCR_MIN_CHARS_PER_PAGE = 20


# OCR status strings used by :class:`IngestSummary.ocr_status`. These are
# deliberately operator-readable rather than numeric codes so the upload
# panel can show them directly.
OCR_STATUS_NOT_NEEDED = "not_needed"
OCR_STATUS_NOT_APPLICABLE = "not_applicable"
OCR_STATUS_UNAVAILABLE = "unavailable"
OCR_STATUS_APPLIED = "applied"
OCR_STATUS_NO_TEXT = "applied_no_text"
OCR_STATUS_ERROR = "error"


@dataclass(slots=True)
class ExtractionResult:
    """What ``extract_text_units`` returns after (possibly) running OCR.

    ``units`` keeps the legacy ``(page_number, text)`` shape so the
    downstream chunker/indexer stays untouched. The remaining fields are
    diagnostic: they let the service surface "OCR ran on N pages" or
    "OCR was unavailable" to operators and to the upload UI.
    """

    units: list[tuple[int | None, str]] = field(default_factory=list)
    total_pages: int = 0
    pypdf_pages_with_text: int = 0
    ocr_pages_attempted: int = 0
    ocr_pages_applied: int = 0
    ocr_status: str = OCR_STATUS_NOT_APPLICABLE
    notes: list[str] = field(default_factory=list)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_text_into_chunks(text: str, *, max_words: int = 140, overlap_words: int = 25) -> list[str]:
    cleaned = normalize_text(text)
    if not cleaned:
        return []

    words = cleaned.split()
    if len(words) <= max_words:
        return [cleaned]

    chunks: list[str] = []
    step = max(max_words - overlap_words, 1)
    for start in range(0, len(words), step):
        chunk_words = words[start : start + max_words]
        if not chunk_words:
            continue
        chunks.append(" ".join(chunk_words))
        if start + max_words >= len(words):
            break
    return chunks


def extract_text_units(
    file_path: Path,
    *,
    ocr_backend: OCRBackend | None = None,
    min_chars_per_page: int = DEFAULT_OCR_MIN_CHARS_PER_PAGE,
) -> ExtractionResult:
    """Extract text units from a PDF/TXT/MD file, OCR'ing scanned pages.

    Behaviour by file type:
        * **.pdf** — PyPDF is tried first for every page. Pages whose
          normalised extracted text is shorter than ``min_chars_per_page``
          are considered scan-like and, if an OCR backend is available,
          are OCR'd. Pages keep their 1-based page numbers so citations
          still point at the right page in the original document.
        * **.txt / .md** — single unit with ``page_number=None``, exactly
          as before. OCR is not applicable.

    This function never raises for a scanned PDF: if OCR is unavailable,
    the page simply drops out of ``units`` and a human-readable note
    records the reason. The caller decides whether an empty ``units``
    list is an error (``DocumentIngestService`` does this once).
    """
    suffix = file_path.suffix.lower()
    result = ExtractionResult()

    if suffix == ".pdf":
        reader = PdfReader(str(file_path))
        pages_needing_ocr: list[int] = []
        for page_number, page in enumerate(reader.pages, start=1):
            result.total_pages += 1
            try:
                raw_page_text = page.extract_text() or ""
            except Exception as exc:  # pragma: no cover - pypdf edge cases
                logger.warning("PyPDF failed on page %d of %s: %s", page_number, file_path, exc)
                raw_page_text = ""
            page_text = normalize_text(raw_page_text)

            if len(page_text) >= min_chars_per_page:
                result.units.append((page_number, page_text))
                result.pypdf_pages_with_text += 1
            else:
                pages_needing_ocr.append(page_number)

        if not pages_needing_ocr:
            result.ocr_status = OCR_STATUS_NOT_NEEDED
        else:
            result.ocr_status, notes, ocr_units, applied = _run_ocr_on_pages(
                file_path=file_path,
                pages=pages_needing_ocr,
                ocr_backend=ocr_backend,
                min_chars_per_page=min_chars_per_page,
            )
            result.ocr_pages_attempted = len(pages_needing_ocr)
            result.ocr_pages_applied = applied
            result.notes.extend(notes)
            result.units.extend(ocr_units)

        # Keep the downstream indexer's expectation that units appear in
        # page order. Units with ``page_number is None`` (not applicable
        # to PDFs, but kept defensively) sort to the end.
        result.units.sort(key=lambda item: (item[0] is None, item[0] or 0))
        return result

    if suffix in {".txt", ".md"}:
        text = normalize_text(file_path.read_text(encoding="utf-8", errors="ignore"))
        if text:
            result.units.append((None, text))
        result.ocr_status = OCR_STATUS_NOT_APPLICABLE
        return result

    raise ValueError(f"Unsupported file type: {suffix}")


def _run_ocr_on_pages(
    *,
    file_path: Path,
    pages: list[int],
    ocr_backend: OCRBackend | None,
    min_chars_per_page: int,
) -> tuple[str, list[str], list[tuple[int | None, str]], int]:
    """Run OCR on the given page numbers.

    Returns ``(ocr_status, notes, units, applied_count)``. The function
    never raises: any per-page error is recorded in ``notes`` and the
    affected page is simply missing from ``units``.
    """
    notes: list[str] = []
    units: list[tuple[int | None, str]] = []

    page_count = len(pages)
    if ocr_backend is None:
        notes.append(
            f"{page_count} page(s) looked scanned but no OCR backend was configured; "
            "those pages were skipped. Install OCR support with `pip install -r "
            "requirements-ocr.txt` and set ACCESSLAB_OCR_ENABLED=auto."
        )
        return OCR_STATUS_UNAVAILABLE, notes, units, 0

    if not ocr_backend.is_available():
        notes.append(
            f"{page_count} page(s) looked scanned but OCR is unavailable: "
            f"{ocr_backend.unavailable_reason()}"
        )
        return OCR_STATUS_UNAVAILABLE, notes, units, 0

    notes.append(
        f"Running local OCR on {page_count} page(s) that had little or no extracted text."
    )
    applied = 0
    errors = 0
    for page_number in pages:
        try:
            raw_text = ocr_backend.ocr_pdf_page(file_path, page_number)
        except OCRUnavailableError as exc:
            notes.append(f"OCR unavailable on page {page_number}: {exc}")
            errors += 1
            continue
        except Exception as exc:  # pragma: no cover - depends on runtime OCR stack
            logger.warning("OCR failed on page %d of %s: %s", page_number, file_path, exc)
            notes.append(f"OCR failed on page {page_number}: {exc}")
            errors += 1
            continue

        normalised = normalize_text(raw_text)
        if len(normalised) >= min_chars_per_page:
            units.append((page_number, normalised))
            applied += 1
        else:
            notes.append(
                f"OCR produced no usable text for page {page_number} "
                f"(got {len(normalised)} characters)."
            )

    if applied == 0 and errors == 0:
        status = OCR_STATUS_NO_TEXT
        notes.append(f"OCR ran on {page_count} page(s) but recovered no usable text.")
    elif errors and applied == 0:
        status = OCR_STATUS_ERROR
    else:
        status = OCR_STATUS_APPLIED
        notes.append(f"OCR recovered usable text on {applied}/{page_count} page(s).")
    return status, notes, units, applied


def build_chunk_id(source_name: str, page_number: int | None, index: int, chunk_text: str) -> str:
    digest = hashlib.sha1(f"{source_name}|{page_number}|{index}|{chunk_text[:80]}".encode("utf-8")).hexdigest()[:10]
    page_part = f"p{page_number}" if page_number is not None else "p0"
    return f"{Path(source_name).stem}-{page_part}-c{index}-{digest}"


def sanitize_file_name(file_name: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", file_name.strip())
    return safe_name or "upload"


class DocumentIngestService:
    """Ingest uploaded documents into SQLite (both ``document_chunks`` and FTS5).

    The OCR fallback is injected rather than imported directly so that:
      * tests can pass a stub backend without touching the real ONNX models;
      * production can swap the RapidOCR implementation for a different
        lightweight OCR path in one place without rewriting the pipeline;
      * AccessLab still ingests text PDFs normally when the OCR extras
        are not installed (``ocr_backend`` defaults to ``None``).
    """

    def __init__(
        self,
        *,
        uploads_dir: Path,
        db_path: Path,
        ocr_backend: OCRBackend | None = None,
        semantic_index: SQLiteSemanticIndex | None = None,
        ocr_min_chars_per_page: int = DEFAULT_OCR_MIN_CHARS_PER_PAGE,
    ) -> None:
        self.uploads_dir = uploads_dir
        self.db_path = db_path
        self.ocr_backend = ocr_backend
        self.semantic_index = semantic_index
        self.ocr_min_chars_per_page = max(1, int(ocr_min_chars_per_page))

    def ingest_upload(
        self,
        *,
        file_name: str,
        content: bytes,
        uploader_role: str = "teacher",
        visibility_scope: str = "class",
        class_space: str = "default-classroom",
    ) -> IngestSummary:
        extension = Path(file_name).suffix.lower()
        if extension not in SUPPORTED_FILE_TYPES:
            supported = ", ".join(sorted(SUPPORTED_FILE_TYPES))
            raise ValueError(f"Unsupported file type. Upload one of: {supported}")

        stored_name = f"{utc_now_iso().replace(':', '-')}-{sanitize_file_name(file_name)}"
        stored_path = self.uploads_dir / stored_name
        stored_path.write_bytes(content)
        return self.ingest_file(
            stored_path=stored_path,
            original_name=file_name,
            uploader_role=uploader_role,
            visibility_scope=visibility_scope,
            class_space=class_space,
        )

    def ingest_file(
        self,
        *,
        stored_path: Path,
        original_name: str | None = None,
        uploader_role: str = "teacher",
        visibility_scope: str = "class",
        class_space: str = "default-classroom",
    ) -> IngestSummary:
        source_name = original_name or stored_path.name
        file_type = SUPPORTED_FILE_TYPES[stored_path.suffix.lower()]

        extraction = extract_text_units(
            stored_path,
            ocr_backend=self.ocr_backend,
            min_chars_per_page=self.ocr_min_chars_per_page,
        )

        if not extraction.units:
            reason = "No readable text was found in that file."
            if extraction.notes:
                reason = f"{reason} {' '.join(extraction.notes)}"
            raise ValueError(reason)

        created_at = utc_now_iso()
        chunks_created = 0
        chunk_rows_for_semantic: list[tuple[str, str, str | None]] = []
        with db_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO documents (
                    file_name,
                    file_type,
                    stored_path,
                    visibility_scope,
                    uploader_role,
                    class_space,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_name,
                    file_type,
                    str(stored_path),
                    visibility_scope,
                    uploader_role,
                    class_space,
                    created_at,
                ),
            )
            document_id = int(cursor.lastrowid)

            for page_number, unit_text in extraction.units:
                for index, chunk_text in enumerate(split_text_into_chunks(unit_text), start=1):
                    chunk_id = build_chunk_id(source_name, page_number, index, chunk_text)
                    connection.execute(
                        """
                        INSERT INTO document_chunks (
                            document_id,
                            source_file,
                            page_number,
                            chunk_id,
                            chunk_text,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (document_id, source_name, page_number, chunk_id, chunk_text, created_at),
                    )
                    connection.execute(
                        """
                        INSERT INTO document_chunks_fts (
                            chunk_id,
                            document_id,
                            source_file,
                            page_number,
                            chunk_text
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (chunk_id, document_id, source_name, page_number, chunk_text),
                    )
                    chunks_created += 1
                    chunk_rows_for_semantic.append((chunk_id, chunk_text, source_name))

        if self.semantic_index is not None and chunk_rows_for_semantic:
            try:
                self.semantic_index.index_chunk_rows(chunk_rows_for_semantic)
            except Exception as exc:  # pragma: no cover - defensive logging only
                logger.warning(
                    "Semantic indexing failed for %s; continuing with FTS-only retrieval: %s",
                    source_name,
                    exc,
                )

        return IngestSummary(
            document_id=document_id,
            file_name=source_name,
            file_type=file_type,
            chunks_created=chunks_created,
            stored_path=str(stored_path),
            ocr_pages_applied=extraction.ocr_pages_applied,
            ocr_status=extraction.ocr_status,
            notes=list(extraction.notes),
        )
