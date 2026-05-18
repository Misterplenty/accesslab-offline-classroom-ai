from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.db import db_connection, init_db, list_documents
from app.services.document_ingest import (
    OCR_STATUS_APPLIED,
    OCR_STATUS_NOT_APPLICABLE,
    OCR_STATUS_NOT_NEEDED,
    OCR_STATUS_UNAVAILABLE,
    DocumentIngestService,
    build_chunk_id,
    extract_text_units,
    split_text_into_chunks,
)
from app.services.semantic import SQLiteSemanticIndex


SAMPLE_DATA_DIR = Path(__file__).resolve().parent.parent / "sample_data"


class StubOCRBackend:
    def __init__(
        self,
        *,
        available: bool = True,
        reason: str = "OCR dependencies missing",
        page_text: dict[int, str] | None = None,
    ) -> None:
        self.available = available
        self.reason = reason
        self.page_text = page_text or {}
        self.calls: list[int] = []

    def is_available(self) -> bool:
        return self.available

    def unavailable_reason(self) -> str:
        return self.reason

    def ocr_pdf_page(self, pdf_path: Path, page_number: int) -> str:
        self.calls.append(page_number)
        return self.page_text.get(page_number, "")

    def describe(self) -> str:
        return "stub-ocr"


class StubEmbeddingProvider:
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors
        self.model_name = "stub-semantic"

    def is_available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""

    def health_status(self) -> tuple[str, str]:
        return "ok", "ready"

    def describe(self) -> str:
        return "stub-semantic"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors[text] for text in texts]


def _write_blank_pdf(path: Path, *, pages: int = 1) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)


def test_split_text_into_chunks_creates_overlap():
    words = " ".join(f"word{i}" for i in range(220))
    chunks = split_text_into_chunks(words, max_words=80, overlap_words=20)

    assert len(chunks) == 4
    assert "word60" in chunks[1]
    assert chunks[0].startswith("word0")


def test_build_chunk_id_includes_page_marker():
    chunk_id = build_chunk_id("worksheet.md", 3, 1, "loop explanation")
    assert chunk_id.startswith("worksheet-p3-c1-")


def test_text_pdf_path_keeps_fast_path_without_ocr():
    backend = StubOCRBackend(page_text={1: "unused"})

    result = extract_text_units(
        SAMPLE_DATA_DIR / "python_loops_notes.pdf",
        ocr_backend=backend,
    )

    assert result.units
    assert result.ocr_status == OCR_STATUS_NOT_NEEDED
    assert result.pypdf_pages_with_text >= 1
    assert backend.calls == []


def test_scanned_pdf_pages_trigger_ocr_and_preserve_page_numbers(tmp_path):
    pdf_path = tmp_path / "scanned.pdf"
    _write_blank_pdf(pdf_path, pages=2)
    backend = StubOCRBackend(
        page_text={
            1: "Question 3 asks students to trace the loop output on this worksheet page.",
            2: "Page 2 says the answer should show each item being checked one by one.",
        }
    )

    result = extract_text_units(pdf_path, ocr_backend=backend)

    assert result.ocr_status == OCR_STATUS_APPLIED
    assert result.ocr_pages_attempted == 2
    assert result.ocr_pages_applied == 2
    assert backend.calls == [1, 2]
    assert result.units == [
        (1, "Question 3 asks students to trace the loop output on this worksheet page."),
        (2, "Page 2 says the answer should show each item being checked one by one."),
    ]


def test_ocr_text_flows_into_chunking_and_indexing_pipeline(tmp_path):
    db_path = tmp_path / "accesslab.db"
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    init_db(db_path)

    pdf_path = tmp_path / "scan.pdf"
    _write_blank_pdf(pdf_path, pages=2)
    backend = StubOCRBackend(
        page_text={
            1: "Question 3 asks students to explain what the loop prints after each item.",
            2: "The teacher note says a for loop checks one value at a time and then stops.",
        }
    )
    service = DocumentIngestService(
        uploads_dir=uploads_dir,
        db_path=db_path,
        ocr_backend=backend,
    )

    summary = service.ingest_file(stored_path=pdf_path, original_name="scan.pdf")

    assert summary.file_type == "pdf"
    assert summary.ocr_status == OCR_STATUS_APPLIED
    assert summary.ocr_pages_applied == 2
    assert summary.chunks_created >= 2

    documents = list_documents(db_path)
    assert len(documents) == 1
    assert documents[0]["chunk_count"] == summary.chunks_created

    with db_connection(db_path) as connection:
        chunk_rows = connection.execute(
            """
            SELECT source_file, page_number, chunk_id, chunk_text
            FROM document_chunks
            ORDER BY page_number, id
            """
        ).fetchall()
        fts_count = connection.execute("SELECT COUNT(*) FROM document_chunks_fts").fetchone()[0]

    assert fts_count == summary.chunks_created
    assert {row["page_number"] for row in chunk_rows} == {1, 2}
    assert chunk_rows[0]["source_file"] == "scan.pdf"
    assert chunk_rows[0]["chunk_id"].startswith("scan-p1-c1-")
    assert chunk_rows[1]["chunk_id"].startswith("scan-p2-c1-")
    assert "Question 3 asks students" in chunk_rows[0]["chunk_text"]


def test_scanned_pdf_without_available_ocr_fails_cleanly(tmp_path):
    db_path = tmp_path / "accesslab.db"
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    init_db(db_path)

    pdf_path = tmp_path / "scan.pdf"
    _write_blank_pdf(pdf_path)
    backend = StubOCRBackend(available=False, reason="RapidOCR extras are not installed")
    service = DocumentIngestService(
        uploads_dir=uploads_dir,
        db_path=db_path,
        ocr_backend=backend,
    )

    with pytest.raises(ValueError) as excinfo:
        service.ingest_file(stored_path=pdf_path, original_name="scan.pdf")

    message = str(excinfo.value)
    assert "No readable text was found in that file." in message
    assert "OCR is unavailable" in message
    assert "RapidOCR extras are not installed" in message
    assert list_documents(db_path) == []


def test_txt_ingest_remains_non_ocr_path(tmp_path):
    db_path = tmp_path / "accesslab.db"
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    init_db(db_path)

    txt_path = tmp_path / "notes.txt"
    txt_path.write_text("A loop checks each number one by one.", encoding="utf-8")
    backend = StubOCRBackend(page_text={1: "unused"})
    service = DocumentIngestService(
        uploads_dir=uploads_dir,
        db_path=db_path,
        ocr_backend=backend,
    )

    summary = service.ingest_file(stored_path=txt_path, original_name="notes.txt")

    assert summary.file_type == "txt"
    assert summary.ocr_status == OCR_STATUS_NOT_APPLICABLE
    assert summary.chunks_created == 1
    assert backend.calls == []


def test_ingest_indexes_semantic_rows_when_embedding_support_is_available(tmp_path):
    db_path = tmp_path / "accesslab.db"
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    init_db(db_path)

    txt_path = tmp_path / "notes.txt"
    text = "A loop checks each number one by one."
    txt_path.write_text(text, encoding="utf-8")
    semantic_index = SQLiteSemanticIndex(
        db_path=db_path,
        embedding_provider=StubEmbeddingProvider({text: [1.0, 0.0]}),
    )
    service = DocumentIngestService(
        uploads_dir=uploads_dir,
        db_path=db_path,
        semantic_index=semantic_index,
    )

    summary = service.ingest_file(stored_path=txt_path, original_name="notes.txt")

    assert summary.chunks_created == 1
    with db_connection(db_path) as connection:
        row = connection.execute(
            "SELECT chunk_id, embedding_model, vector_dim FROM chunk_embeddings"
        ).fetchone()
    assert row["chunk_id"].startswith("notes-p0-c1-")
    assert row["embedding_model"] == "stub-semantic"
    assert row["vector_dim"] == 2
