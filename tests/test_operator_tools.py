from pathlib import Path

from app.db import (
    apply_class_space_migration,
    db_connection,
    get_code_session_entry,
    get_qa_history_entry,
    init_db,
    save_training_capture,
    preview_class_space_migration,
    save_code_session,
    save_qa_history,
    save_session_label,
    utc_now_iso,
)
from scripts.export_local_data import _capture_map, _export_code_rows, _export_qa_rows, _label_map


def _insert_document(db_path: Path, *, class_space: str, file_name: str = "worksheet.md") -> None:
    stored_path = db_path.parent / file_name
    stored_path.write_text("Question 3 explains loops.", encoding="utf-8")
    created_at = utc_now_iso()
    with db_connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO documents (file_name, file_type, stored_path, class_space, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (file_name, "md", str(stored_path), class_space, created_at),
        )
        document_id = int(cursor.lastrowid)
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
            (
                document_id,
                file_name,
                1,
                f"{file_name}-p1-c1",
                "Question 3 explains loops.",
                created_at,
            ),
        )


def test_class_space_migration_preview_counts_documents_and_sessions(tmp_path: Path):
    db_path = tmp_path / "accesslab.db"
    init_db(db_path)
    _insert_document(db_path, class_space="old-space")
    save_qa_history(
        db_path,
        question="Explain loops",
        retrieved_chunk_ids=["worksheet.md-p1-c1"],
        answer_text="Loops go item by item.",
        more_detail="",
        actor_role="learner",
        actor_key="user-a",
        class_space="old-space",
        citation_list=[],
    )
    save_code_session(
        db_path,
        original_code="print('hi')",
        test_code="",
        execution_output="hi",
        patched_code="print('hi')",
        patched_test_result="hi",
        actor_role="learner",
        actor_key="user-a",
        class_space="old-space",
        session_data={"prompt_variant": "hybrid"},
    )

    preview = preview_class_space_migration(
        db_path,
        from_class_space="old-space",
        to_class_space="new-space",
        include_sessions=True,
    )

    assert preview["counts"]["documents"] == 1
    assert preview["counts"]["document_chunks"] == 1
    assert preview["counts"]["qa_sessions"] == 1
    assert preview["counts"]["code_sessions"] == 1
    assert preview["include_sessions"] is True
    assert preview["warnings"]


def test_class_space_migration_apply_preserves_saved_ids(tmp_path: Path):
    db_path = tmp_path / "accesslab.db"
    init_db(db_path)
    _insert_document(db_path, class_space="old-space")
    qa_id = save_qa_history(
        db_path,
        question="Explain loops",
        retrieved_chunk_ids=[],
        answer_text="Loops answer",
        more_detail="",
        actor_role="learner",
        actor_key="user-a",
        class_space="old-space",
        citation_list=[],
    )
    code_id = save_code_session(
        db_path,
        original_code="print('hi')",
        test_code="",
        execution_output="hi",
        patched_code="print('hi')",
        patched_test_result="hi",
        actor_role="learner",
        actor_key="user-a",
        class_space="old-space",
        session_data={"prompt_variant": "hybrid"},
    )

    summary = apply_class_space_migration(
        db_path,
        from_class_space="old-space",
        to_class_space="new-space",
        include_sessions=True,
    )

    assert summary["applied"] is True
    assert get_qa_history_entry(db_path, qa_id)["class_space"] == "new-space"
    assert get_code_session_entry(db_path, code_id)["class_space"] == "new-space"


def test_export_rows_include_labels_and_saved_metadata(tmp_path: Path):
    db_path = tmp_path / "accesslab.db"
    init_db(db_path)
    qa_id = save_qa_history(
        db_path,
        question="Explain loops",
        retrieved_chunk_ids=["chunk-1"],
        answer_text="Loops go item by item. [S1]",
        more_detail="Local evidence only.",
        actor_role="teacher",
        actor_key="user-a",
        class_space="history-lab",
        retrieval_mode="hybrid",
        retrieval_mode_label="Hybrid",
        citation_list=[{"label": "S1", "source_file": "worksheet.md", "page_number": 1, "chunk_id": "chunk-1", "snippet": "Loops."}],
        session_data={
            "prompt_variant": "baseline",
            "qa_discipline_profile": "default",
            "runtime_backend": "ollama",
            "model_name": "gemma4:e4b",
            "retrieved_results": [{"chunk_id": "chunk-1"}],
            "profile": {"queue_wait_seconds": 0.0},
        },
    )
    code_id = save_code_session(
        db_path,
        original_code="def add(a, b): return a - b",
        test_code="assert add(2, 3) == 5",
        execution_output="AssertionError",
        patched_code="def add(a, b): return a + b",
        patched_test_result="ok",
        actor_role="learner",
        actor_key="user-b",
        class_space="history-lab",
        session_data={
            "prompt_variant": "hybrid",
            "runtime_backend": "ollama",
            "model_name": "gemma4:e4b",
            "diagnosis": "Wrong operator.",
            "evidence": "AssertionError",
            "next_fix": "Use addition.",
            "why_it_works": "Now it matches the test.",
            "rerun_success": True,
            "profile": {"queue_wait_seconds": 0.2},
        },
    )
    save_session_label(
        db_path,
        source_type="qa",
        source_id=qa_id,
        label="screen-reader-friendly",
        class_space="history-lab",
    )
    save_session_label(
        db_path,
        source_type="code",
        source_id=code_id,
        label="good",
        class_space="history-lab",
    )
    save_training_capture(
        db_path,
        source_type="qa",
        source_id=qa_id,
        capture_kind="grounded-qa",
        actor_role="teacher",
        actor_key="user-a",
        class_space="history-lab",
        retrieval_mode="hybrid",
        runtime_backend="ollama",
        model_name="gemma4:e4b",
        prompt_variant="baseline",
        payload={"capture_version": "v1"},
    )

    labels = _label_map(db_path, class_space="history-lab", label_filter="")
    captures = _capture_map(db_path, class_space="history-lab")
    qa_rows = _export_qa_rows(
        db_path,
        class_space="history-lab",
        label_map=labels,
        capture_map=captures,
        only_labeled=True,
    )
    code_rows = _export_code_rows(
        db_path,
        class_space="history-lab",
        label_map=labels,
        capture_map=captures,
        only_labeled=True,
    )

    assert qa_rows[0]["labels"][0]["label"] == "screen-reader-friendly"
    assert qa_rows[0]["prompt_variant"] == "baseline"
    assert qa_rows[0]["retrieved_results"] == [{"chunk_id": "chunk-1"}]
    assert qa_rows[0]["training_capture_count"] == 1
    assert code_rows[0]["labels"][0]["label"] == "good"
    assert code_rows[0]["rerun_success"] is True
