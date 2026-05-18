from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from app.config import Settings
from app.db import db_connection, init_db
from app.services.document_ingest import DocumentIngestService
from app.services.llm import OllamaProvider
from app.services.ocr import create_ocr_backend
from app.services.qa import GroundedQAService
from app.services.retrieval import HybridSQLiteRetrieval
from app.services.semantic import SQLiteSemanticIndex, create_embedding_provider


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproducible smoke path for scanned-PDF OCR ingest and grounded QA."
    )
    parser.add_argument(
        "--pdf",
        required=True,
        type=Path,
        help="Path to a scanned or image-based PDF to ingest.",
    )
    parser.add_argument(
        "--question",
        default="What does this worksheet ask the student to do?",
        help="Grounded question to ask after ingest succeeds.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPO_ROOT / "data" / "ocr-smoke",
        help="Isolated data directory for the smoke run.",
    )
    parser.add_argument(
        "--keep-data-dir",
        action="store_true",
        help="Keep the smoke data directory instead of clearing it before each run.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the local Ollama model. Defaults to the AccessLab env/profile resolution.",
    )
    parser.add_argument(
        "--ollama-url",
        default=None,
        help="Override the Ollama base URL. Defaults to ACCESSLAB_OLLAMA_URL or the app default.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    pdf_path = args.pdf.expanduser().resolve()
    if not pdf_path.exists():
        print(f"Smoke check failed: PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    settings = Settings()
    data_dir = args.data_dir.expanduser().resolve()
    if data_dir.exists() and not args.keep_data_dir:
        shutil.rmtree(data_dir, ignore_errors=True)
    uploads_dir = data_dir / "uploads"
    db_path = data_dir / "accesslab.db"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    init_db(db_path)

    ocr_backend = create_ocr_backend(enabled=settings.ocr_enabled, dpi=settings.ocr_dpi)
    semantic_index = SQLiteSemanticIndex(
        db_path=db_path,
        embedding_provider=create_embedding_provider(
            enabled=settings.semantic_enabled,
            base_url=args.ollama_url or settings.accesslab_ollama_url,
            model_name=settings.semantic_embedding_model,
        ),
    )
    ingest_service = DocumentIngestService(
        uploads_dir=uploads_dir,
        db_path=db_path,
        ocr_backend=ocr_backend,
        semantic_index=semantic_index,
        ocr_min_chars_per_page=settings.ocr_min_chars_per_page,
    )

    try:
        summary = ingest_service.ingest_upload(
            file_name=pdf_path.name,
            content=pdf_path.read_bytes(),
        )
    except Exception as exc:
        print(f"Smoke check failed during ingest: {exc}", file=sys.stderr)
        return 2

    print("OCR ingest summary")
    print(f"  data_dir: {data_dir}")
    print(f"  db_path: {db_path}")
    print(f"  file: {summary.file_name}")
    print(f"  chunks_created: {summary.chunks_created}")
    print(f"  ocr_status: {summary.ocr_status}")
    print(f"  ocr_pages_applied: {summary.ocr_pages_applied}")
    for note in summary.notes:
        print(f"  note: {note}")

    with db_connection(db_path) as connection:
        chunk_rows = connection.execute(
            """
            SELECT page_number, chunk_id, substr(chunk_text, 1, 160) AS preview
            FROM document_chunks
            ORDER BY page_number, id
            LIMIT 3
            """
        ).fetchall()
        indexed_chunk_count = connection.execute(
            "SELECT COUNT(*) FROM document_chunks"
        ).fetchone()[0]

    if indexed_chunk_count == 0:
        print("Smoke check failed: ingest finished but no chunks were indexed.", file=sys.stderr)
        return 3

    print("Indexed chunk preview")
    print(f"  indexed_chunks: {indexed_chunk_count}")
    for row in chunk_rows:
        print(
            f"  page {row['page_number']}: {row['chunk_id']} :: {row['preview']}"
        )

    retrieval = HybridSQLiteRetrieval(db_path, semantic_index=semantic_index)
    llm_provider = OllamaProvider(
        base_url=args.ollama_url or settings.accesslab_ollama_url,
        model_name=args.model or settings.accesslab_model,
    )
    llm_ready, llm_message = llm_provider.health_check()
    if not llm_ready:
        print(
            f"Smoke check stopped before QA: local Ollama is not ready ({llm_message}).",
            file=sys.stderr,
        )
        return 4

    qa_service = GroundedQAService(
        db_path=db_path,
        retrieval_backend=retrieval,
        llm_provider=llm_provider,
        qa_discipline_profile=settings.qa_discipline_profile,
    )
    result = qa_service.answer(args.question)

    print("Grounded QA")
    print(f"  question: {args.question}")
    print(f"  short_answer: {result.short_answer}")
    print(f"  more_detail: {result.more_detail}")
    if not result.citations:
        print("Smoke check failed: QA returned no citations.", file=sys.stderr)
        return 5
    for citation in result.citations:
        print(f"  citation: {citation.display}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
