from __future__ import annotations

from app.config import Settings
from app.db import (
    db_connection,
    init_db,
    mark_semantic_index_failed,
    utc_now_iso,
)
from app.services.semantic import (
    SEMANTIC_STATUS_MODEL_NOT_INSTALLED,
    SQLiteSemanticIndex,
)
from app.services.system_status import build_retrieval_diagnostics


class StubEmbeddingProvider:
    def __init__(
        self,
        *,
        available: bool = True,
        code: str = "ok",
        message: str = "Ready with `embeddinggemma`.",
    ) -> None:
        self.available = available
        self.code = code
        self.message = message
        self.model_name = "embeddinggemma"

    def is_available(self) -> bool:
        return self.available

    def unavailable_reason(self) -> str:
        return "" if self.available else self.message

    def health_status(self) -> tuple[str, str]:
        return self.code, self.message

    def describe(self) -> str:
        return "stub-semantic"

    def embed_texts(self, texts):
        return [[1.0, 0.0] for _ in texts]


def _insert_chunk(db_path, *, chunk_id: str = "chunk-1", text: str = "Question 3 explains loops.") -> None:
    created_at = utc_now_iso()
    with db_connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO documents (file_name, file_type, stored_path, class_space, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("worksheet.md", "md", "/tmp/worksheet.md", "default-classroom", created_at),
        )
        document_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO document_chunks (document_id, source_file, page_number, chunk_id, chunk_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (document_id, "worksheet.md", None, chunk_id, text, created_at),
        )


def _insert_chunk_in_space(
    db_path,
    *,
    file_name: str,
    class_space: str,
    chunk_id: str,
    text: str,
) -> None:
    created_at = utc_now_iso()
    with db_connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO documents (file_name, file_type, stored_path, class_space, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (file_name, "md", f"/tmp/{file_name}", class_space, created_at),
        )
        document_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO document_chunks (document_id, source_file, page_number, chunk_id, chunk_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (document_id, file_name, None, chunk_id, text, created_at),
        )


def test_retrieval_diagnostics_report_missing_embedding_model(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", retrieval_mode="hybrid")
    settings.ensure_directories()
    init_db(settings.db_path)
    semantic_index = SQLiteSemanticIndex(
        db_path=settings.db_path,
        embedding_provider=StubEmbeddingProvider(
            available=False,
            code=SEMANTIC_STATUS_MODEL_NOT_INSTALLED,
            message="embeddinggemma is not installed",
        ),
    )

    diagnostics = build_retrieval_diagnostics(settings, semantic_index)

    assert diagnostics.actual_mode == "lexical"
    assert diagnostics.semantic.code == "model_not_installed"
    assert diagnostics.semantic.label == "Model not installed"


def test_retrieval_diagnostics_report_index_failure(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", retrieval_mode="hybrid")
    settings.ensure_directories()
    init_db(settings.db_path)
    _insert_chunk(settings.db_path)
    mark_semantic_index_failed(
        settings.db_path,
        model_name="embeddinggemma",
        error_code="embedding_generation_error",
        error_message="Embedding request failed during indexing.",
    )
    semantic_index = SQLiteSemanticIndex(
        db_path=settings.db_path,
        embedding_provider=StubEmbeddingProvider(),
    )

    diagnostics = build_retrieval_diagnostics(settings, semantic_index)

    assert diagnostics.index_status.status == "indexing_failed"
    assert diagnostics.semantic.code == "embedding_generation_error"
    assert diagnostics.actual_mode == "lexical"


def test_retrieval_diagnostics_report_hybrid_ready_when_embeddings_exist(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", retrieval_mode="hybrid")
    settings.ensure_directories()
    init_db(settings.db_path)
    _insert_chunk(settings.db_path, text="Question 3 explains loops.")
    semantic_index = SQLiteSemanticIndex(
        db_path=settings.db_path,
        embedding_provider=StubEmbeddingProvider(),
    )
    semantic_index.index_chunk_rows([("chunk-1", "Question 3 explains loops.", "worksheet.md")])

    diagnostics = build_retrieval_diagnostics(settings, semantic_index)

    assert diagnostics.actual_mode == "hybrid"
    assert diagnostics.semantic.retrieval_ready is True
    assert diagnostics.index_status.status == "indexed"


def test_retrieval_diagnostics_counts_only_current_class_space(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        retrieval_mode="hybrid",
        class_space="biology-lab",
    )
    settings.ensure_directories()
    init_db(settings.db_path)
    _insert_chunk_in_space(
        settings.db_path,
        file_name="biology.md",
        class_space="biology-lab",
        chunk_id="bio-1",
        text="Cells use mitochondria to make energy.",
    )
    _insert_chunk_in_space(
        settings.db_path,
        file_name="history.md",
        class_space="history-lab",
        chunk_id="hist-1",
        text="History class discusses timelines.",
    )
    semantic_index = SQLiteSemanticIndex(
        db_path=settings.db_path,
        embedding_provider=StubEmbeddingProvider(),
        class_space="biology-lab",
    )
    semantic_index.index_chunk_rows([("bio-1", "Cells use mitochondria to make energy.", "biology.md")])

    diagnostics = build_retrieval_diagnostics(settings, semantic_index)

    assert diagnostics.index_status.document_count == 1
    assert diagnostics.index_status.chunk_count == 1
    assert diagnostics.index_status.embedded_chunk_count == 1
