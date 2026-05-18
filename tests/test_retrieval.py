from app.db import db_connection, init_db, utc_now_iso
from app.models.schemas import SearchResult
from app.services.qa import build_citations
from app.services.retrieval import HybridSQLiteRetrieval, SQLiteFTSRetrieval, is_weak_retrieval
from app.services.semantic import SQLiteSemanticIndex


class StubEmbeddingProvider:
    def __init__(
        self,
        vectors: dict[str, list[float]],
        *,
        available: bool = True,
        reason: str = "embedding model unavailable",
    ) -> None:
        self.vectors = vectors
        self.available = available
        self.reason = reason
        self.model_name = "stub-semantic"

    def is_available(self) -> bool:
        return self.available

    def unavailable_reason(self) -> str:
        return self.reason

    def health_status(self) -> tuple[str, str]:
        return ("ok", "ready") if self.available else ("disabled", self.reason)

    def describe(self) -> str:
        return "stub-semantic"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors[text] for text in texts]


def _insert_chunk(
    db_path,
    *,
    document_id: int,
    source_file: str,
    chunk_id: str,
    chunk_text: str,
    page_number: int | None = None,
):
    with db_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO document_chunks (document_id, source_file, page_number, chunk_id, chunk_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (document_id, source_file, page_number, chunk_id, chunk_text, utc_now_iso()),
        )
        connection.execute(
            """
            INSERT INTO document_chunks_fts (chunk_id, document_id, source_file, page_number, chunk_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chunk_id, document_id, source_file, page_number, chunk_text),
        )


def _insert_document(db_path, *, file_name: str = "worksheet.md") -> int:
    with db_connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO documents (file_name, file_type, stored_path, class_space, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (file_name, "md", f"/tmp/{file_name}", "default-classroom", utc_now_iso()),
        )
        return int(cursor.lastrowid)


def _insert_document_in_space(
    db_path,
    *,
    file_name: str,
    class_space: str,
) -> int:
    with db_connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO documents (file_name, file_type, stored_path, class_space, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (file_name, "md", f"/tmp/{file_name}", class_space, utc_now_iso()),
        )
        return int(cursor.lastrowid)


def test_sqlite_fts_retrieval_finds_relevant_chunk(tmp_path):
    db_path = tmp_path / "accesslab.db"
    init_db(db_path)

    document_id = _insert_document(db_path)
    _insert_chunk(
        db_path,
        document_id=document_id,
        source_file="worksheet.md",
        chunk_id="chunk-1",
        chunk_text="Question 3 explains that a for loop goes through a list one item at a time.",
    )

    retrieval = SQLiteFTSRetrieval(db_path)
    results = retrieval.search("Explain question 3 and the loop")

    assert results
    assert results[0].chunk_id == "chunk-1"
    assert results[0].source_file == "worksheet.md"


def test_semantic_search_backfills_old_chunks_and_preserves_citation_metadata(tmp_path):
    db_path = tmp_path / "accesslab.db"
    init_db(db_path)
    document_id = _insert_document(db_path, file_name="teacher_notes.md")

    chunk_text = "Add the values in the basket to get the total for the answer."
    _insert_chunk(
        db_path,
        document_id=document_id,
        source_file="teacher_notes.md",
        page_number=3,
        chunk_id="teacher-p3-c1",
        chunk_text=chunk_text,
    )

    provider = StubEmbeddingProvider(
        {
            chunk_text: [1.0, 0.0],
            "How do I find the sum?": [1.0, 0.0],
        }
    )
    semantic_index = SQLiteSemanticIndex(db_path=db_path, embedding_provider=provider)

    results = semantic_index.search("How do I find the sum?", limit=2)

    assert results
    assert results[0].chunk_id == "teacher-p3-c1"
    assert results[0].source_file == "teacher_notes.md"
    assert results[0].page_number == 3
    assert results[0].semantic_similarity == 1.0

    citations = build_citations(results)
    assert citations[0].display == "[S1] teacher_notes.md, page 3 · teacher-p3-c1"

    with db_connection(db_path) as connection:
        embedding_count = connection.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
    assert embedding_count == 1


def test_hybrid_retrieval_surfaces_semantic_match_on_wording_mismatch(tmp_path):
    db_path = tmp_path / "accesslab.db"
    init_db(db_path)
    document_id = _insert_document(db_path)

    relevant_text = "Add the values together to get the final total."
    lexical_text = "The numbers are listed next to question 3 on the worksheet."
    _insert_chunk(
        db_path,
        document_id=document_id,
        source_file="worksheet.md",
        chunk_id="chunk-relevant",
        chunk_text=relevant_text,
    )
    _insert_chunk(
        db_path,
        document_id=document_id,
        source_file="worksheet.md",
        chunk_id="chunk-lexical",
        chunk_text=lexical_text,
    )

    lexical = SQLiteFTSRetrieval(db_path)
    lexical_results = lexical.search("What is the sum of the numbers?", limit=2)
    assert lexical_results
    assert lexical_results[0].chunk_id == "chunk-lexical"

    provider = StubEmbeddingProvider(
        {
            relevant_text: [1.0, 0.0],
            lexical_text: [0.0, 1.0],
            "What is the sum of the numbers?": [1.0, 0.0],
        }
    )
    hybrid = HybridSQLiteRetrieval(
        db_path,
        semantic_index=SQLiteSemanticIndex(db_path=db_path, embedding_provider=provider),
    )

    hybrid_results = hybrid.search("What is the sum of the numbers?", limit=2)

    assert hybrid_results
    assert hybrid_results[0].chunk_id == "chunk-relevant"
    assert hybrid_results[0].match_source in {"semantic", "hybrid"}
    assert hybrid_results[0].semantic_similarity == 1.0


def test_hybrid_retrieval_falls_back_to_lexical_when_semantic_unavailable(tmp_path):
    db_path = tmp_path / "accesslab.db"
    init_db(db_path)
    document_id = _insert_document(db_path)

    chunk_text = "Question 3 explains that a loop goes through a list one item at a time."
    _insert_chunk(
        db_path,
        document_id=document_id,
        source_file="worksheet.md",
        chunk_id="chunk-1",
        chunk_text=chunk_text,
    )

    lexical = SQLiteFTSRetrieval(db_path)
    hybrid = HybridSQLiteRetrieval(
        db_path,
        semantic_index=SQLiteSemanticIndex(
            db_path=db_path,
            embedding_provider=StubEmbeddingProvider({}, available=False),
        ),
    )

    assert [result.chunk_id for result in hybrid.search("Explain question 3 and the loop")] == [
        result.chunk_id for result in lexical.search("Explain question 3 and the loop")
    ]


def test_hybrid_retrieval_handles_ocr_noisy_but_semantically_relevant_text(tmp_path):
    db_path = tmp_path / "accesslab.db"
    init_db(db_path)
    document_id = _insert_document(db_path, file_name="scan.txt")

    noisy_chunk = "The lo0p cheks each vlaue one by one before it stops."
    _insert_chunk(
        db_path,
        document_id=document_id,
        source_file="scan.txt",
        chunk_id="scan-p1-c1",
        page_number=1,
        chunk_text=noisy_chunk,
    )

    provider = StubEmbeddingProvider(
        {
            noisy_chunk: [0.0, 1.0],
            "How does the loop check each value?": [0.0, 1.0],
        }
    )
    hybrid = HybridSQLiteRetrieval(
        db_path,
        semantic_index=SQLiteSemanticIndex(db_path=db_path, embedding_provider=provider),
    )

    results = hybrid.search("How does the loop check each value?", limit=2)

    assert results
    assert results[0].chunk_id == "scan-p1-c1"
    assert results[0].page_number == 1


def test_lexical_retrieval_respects_class_space_boundary(tmp_path):
    db_path = tmp_path / "accesslab.db"
    init_db(db_path)
    biology_doc = _insert_document_in_space(
        db_path,
        file_name="biology.md",
        class_space="biology-lab",
    )
    history_doc = _insert_document_in_space(
        db_path,
        file_name="history.md",
        class_space="history-lab",
    )

    _insert_chunk(
        db_path,
        document_id=biology_doc,
        source_file="biology.md",
        chunk_id="bio-1",
        chunk_text="Cells use mitochondria to make energy for the organism.",
    )
    _insert_chunk(
        db_path,
        document_id=history_doc,
        source_file="history.md",
        chunk_id="hist-1",
        chunk_text="Mitochondria was a mistaken term in this history worksheet distractor.",
    )

    retrieval = SQLiteFTSRetrieval(db_path, class_space="biology-lab")
    results = retrieval.search("What do mitochondria do?", limit=4)

    assert results
    assert [result.chunk_id for result in results] == ["bio-1"]


def test_hybrid_mode_degrades_to_lexical_when_embeddings_exist_only_in_other_class_space(tmp_path):
    db_path = tmp_path / "accesslab.db"
    init_db(db_path)
    biology_doc = _insert_document_in_space(
        db_path,
        file_name="biology.md",
        class_space="biology-lab",
    )
    history_doc = _insert_document_in_space(
        db_path,
        file_name="history.md",
        class_space="history-lab",
    )

    biology_text = "Cells use mitochondria to make energy."
    history_text = "History class discusses industrial change."
    _insert_chunk(
        db_path,
        document_id=biology_doc,
        source_file="biology.md",
        chunk_id="bio-1",
        chunk_text=biology_text,
    )
    _insert_chunk(
        db_path,
        document_id=history_doc,
        source_file="history.md",
        chunk_id="hist-1",
        chunk_text=history_text,
    )

    provider = StubEmbeddingProvider(
        {
            history_text: [1.0, 0.0],
            "What do factories change?": [1.0, 0.0],
        }
    )
    semantic_index = SQLiteSemanticIndex(
        db_path=db_path,
        embedding_provider=provider,
        class_space="history-lab",
    )
    semantic_index.index_chunk_rows([("hist-1", history_text, "history.md")])

    retrieval = HybridSQLiteRetrieval(
        db_path,
        semantic_index=SQLiteSemanticIndex(
            db_path=db_path,
            embedding_provider=StubEmbeddingProvider({}, available=False),
            class_space="biology-lab",
        ),
        retrieval_mode="hybrid",
        class_space="biology-lab",
    )

    assert retrieval.current_mode() == ("lexical", "Lexical only")


def test_strong_semantic_match_is_not_flagged_as_weak_retrieval():
    results = [
        SearchResult(
            chunk_id="chunk-1",
            source_file="worksheet.md",
            page_number=None,
            chunk_text="Add the values together to get the total.",
            snippet="Add the values together to get the total.",
            score=0.9,
            match_source="semantic",
            semantic_similarity=0.9,
        )
    ]

    assert is_weak_retrieval("What is the sum of the numbers?", results) is False
