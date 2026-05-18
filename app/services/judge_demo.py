from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.db import (
    db_connection,
    init_db,
    list_session_labels,
    save_code_session,
    save_qa_history,
    save_session_label,
)
from app.services.document_ingest import DocumentIngestService


DEMO_CLASS_SPACE = "judge-demo-class"
DEMO_ACTOR_KEY = "judge-demo-learner"
DEMO_TEACHER_KEY = "judge-demo-teacher"
DEMO_QUESTION = "What does `for item in numbers:` mean?"
DEMO_WEAK_QUESTION = "What homework is due Friday?"

DEMO_DOCUMENTS = (
    "worksheet_question3.md",
    "python_loops_notes.txt",
    "spanish_python_loops.md",
    "french_algebra_note.md",
    "swahili_classroom_instructions.md",
)


def seed_judge_demo(settings, *, class_space: str | None = None) -> dict[str, Any]:
    """Seed a deterministic judge demo that works even when Gemma 4 is offline."""
    resolved_class_space = (class_space or settings.class_space or DEMO_CLASS_SPACE).strip()
    settings.ensure_directories()
    init_db(settings.db_path)

    _reset_demo_class_space(settings, class_space=resolved_class_space)
    seeded_documents = _ensure_documents(settings, class_space=resolved_class_space)
    chunks = _chunk_lookup(settings.db_path, class_space=resolved_class_space)
    qa_id = _ensure_demo_qa(settings, class_space=resolved_class_space, chunks=chunks)
    weak_qa_id = _ensure_weak_demo_qa(settings, class_space=resolved_class_space)
    code_id = _ensure_demo_code_session(settings, class_space=resolved_class_space)
    _ensure_labels(settings, class_space=resolved_class_space, qa_id=qa_id, code_id=code_id)

    source_chunk_id = _first_chunk_id(chunks, "worksheet_question3.md")
    return {
        "class_space": resolved_class_space,
        "documents": seeded_documents,
        "qa_id": qa_id,
        "weak_qa_id": weak_qa_id,
        "code_id": code_id,
        "qa_url": f"/qa?qa_id={qa_id}" if qa_id else "/qa",
        "weak_qa_url": f"/qa?qa_id={weak_qa_id}" if weak_qa_id else "/qa",
        "code_url": f"/code?session_id={code_id}" if code_id else "/code",
        "source_url": f"/sources/{source_chunk_id}?qa_id={qa_id}" if source_chunk_id and qa_id else "/qa",
        "teacher_url": "/",
        "proofs_url": "/proofs",
    }


def _reset_demo_class_space(settings, *, class_space: str) -> None:
    """Clear generated judge-demo rows so visits never accumulate stale sessions."""
    upload_paths: list[Path] = []
    with db_connection(settings.db_path) as connection:
        document_rows = connection.execute(
            "SELECT id, stored_path FROM documents WHERE class_space = ?",
            (class_space,),
        ).fetchall()
        document_ids = [int(row["id"]) for row in document_rows]
        upload_paths = [Path(str(row["stored_path"])) for row in document_rows if row["stored_path"]]

        if document_ids:
            placeholders = ",".join("?" for _ in document_ids)
            connection.execute(
                f"DELETE FROM document_chunks_fts WHERE document_id IN ({placeholders})",
                document_ids,
            )
            connection.execute(
                f"DELETE FROM documents WHERE id IN ({placeholders})",
                document_ids,
            )
        connection.execute("DELETE FROM qa_history WHERE class_space = ?", (class_space,))
        connection.execute("DELETE FROM code_sessions WHERE class_space = ?", (class_space,))
        connection.execute("DELETE FROM session_labels WHERE class_space = ?", (class_space,))
        connection.execute("DELETE FROM training_capture_events WHERE class_space = ?", (class_space,))
        for table_name in (
            "documents",
            "document_chunks",
            "qa_history",
            "code_sessions",
            "session_labels",
            "training_capture_events",
        ):
            connection.execute(
                "DELETE FROM sqlite_sequence WHERE name = ?",
                (table_name,),
            )

    uploads_root = settings.uploads_dir.resolve()
    for stored_path in upload_paths:
        try:
            resolved_path = stored_path.resolve()
        except OSError:
            continue
        if resolved_path == uploads_root or uploads_root not in resolved_path.parents:
            continue
        try:
            resolved_path.unlink(missing_ok=True)
        except OSError:
            pass


def _ensure_documents(settings, *, class_space: str) -> list[dict[str, Any]]:
    existing_names = _existing_document_names(settings.db_path, class_space=class_space)
    ingest_service = DocumentIngestService(
        uploads_dir=settings.uploads_dir,
        db_path=settings.db_path,
        ocr_backend=None,
        semantic_index=None,
        ocr_min_chars_per_page=settings.ocr_min_chars_per_page,
    )
    seeded: list[dict[str, Any]] = []
    for file_name in DEMO_DOCUMENTS:
        source_path = settings.sample_data_dir / file_name
        if not source_path.exists():
            continue
        if file_name not in existing_names:
            summary = ingest_service.ingest_upload(
                file_name=file_name,
                content=source_path.read_bytes(),
                uploader_role="teacher",
                visibility_scope="class",
                class_space=class_space,
            )
            seeded.append(
                {
                    "file_name": summary.file_name,
                    "chunks_created": summary.chunks_created,
                    "created": True,
                }
            )
        else:
            seeded.append({"file_name": file_name, "chunks_created": None, "created": False})
    return seeded


def _existing_document_names(db_path: Path, *, class_space: str) -> set[str]:
    with db_connection(db_path) as connection:
        rows = connection.execute(
            "SELECT file_name FROM documents WHERE class_space = ?",
            (class_space,),
        ).fetchall()
    return {str(row["file_name"]) for row in rows}


def _chunk_lookup(db_path: Path, *, class_space: str) -> dict[str, list[dict[str, Any]]]:
    with db_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT c.chunk_id, c.source_file, c.page_number, c.chunk_text
            FROM document_chunks AS c
            JOIN documents AS d ON d.id = c.document_id
            WHERE d.class_space = ?
            ORDER BY c.id
            """,
            (class_space,),
        ).fetchall()
    lookup: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        lookup.setdefault(str(row["source_file"]), []).append(
            {
                "chunk_id": str(row["chunk_id"]),
                "source_file": str(row["source_file"]),
                "page_number": row["page_number"],
                "chunk_text": str(row["chunk_text"]),
            }
        )
    return lookup


def _first_chunk_id(chunks: dict[str, list[dict[str, Any]]], source_file: str) -> str:
    rows = chunks.get(source_file) or []
    return str(rows[0]["chunk_id"]) if rows else ""


def _find_existing_qa_id(db_path: Path, *, question: str, class_space: str) -> int | None:
    with db_connection(db_path) as connection:
        row = connection.execute(
            """
            SELECT id
            FROM qa_history
            WHERE question = ? AND class_space = ? AND actor_key = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (question, class_space, DEMO_ACTOR_KEY),
        ).fetchone()
    return int(row["id"]) if row else None


def _find_existing_code_id(db_path: Path, *, class_space: str) -> int | None:
    with db_connection(db_path) as connection:
        row = connection.execute(
            """
            SELECT id
            FROM code_sessions
            WHERE class_space = ? AND actor_key = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (class_space, DEMO_ACTOR_KEY),
        ).fetchone()
    return int(row["id"]) if row else None


def _ensure_demo_qa(settings, *, class_space: str, chunks: dict[str, list[dict[str, Any]]]) -> int:
    existing = _find_existing_qa_id(settings.db_path, question=DEMO_QUESTION, class_space=class_space)
    if existing is not None:
        return existing

    worksheet = (chunks.get("worksheet_question3.md") or [{}])[0]
    notes = (chunks.get("python_loops_notes.txt") or [worksheet])[0]
    citations = [
        {
            "label": "S1",
            "source_file": worksheet.get("source_file", "worksheet_question3.md"),
            "page_number": worksheet.get("page_number"),
            "chunk_id": worksheet.get("chunk_id", ""),
            "snippet": "Question 3 asks what `for item in numbers:` means and explains that the loop takes one item at a time.",
        },
        {
            "label": "S2",
            "source_file": notes.get("source_file", "python_loops_notes.txt"),
            "page_number": notes.get("page_number"),
            "chunk_id": notes.get("chunk_id", ""),
            "snippet": "The notes say a for loop visits each value in a group.",
        },
    ]
    citations = [citation for citation in citations if citation["chunk_id"]]
    session_data = {
        "question": DEMO_QUESTION,
        "answer_language": "auto",
        "answer_language_label": "Match question",
        "plain_language_requested": False,
        "short_answer": "It means Python takes each value from the local list `numbers` one at a time and stores the current value in `item` [S1].",
        "more_detail": "In the demo material, `numbers = [3, 5, 8]`, so `item` becomes 3, then 5, then 8 [S2].",
        "unsure": False,
        "result_mode": "answered",
        "prompt_variant": "cached-demo",
        "qa_discipline_profile": settings.qa_discipline_profile,
        "runtime_backend": "cached-local-demo",
        "model_name": settings.accesslab_model,
        "raw_response": "Cached judge-demo answer. Use live QA for a model-backed run.",
        "citations": citations,
        "retrieved_results": [
            {
                "chunk_id": citation["chunk_id"],
                "source_file": citation["source_file"],
                "page_number": citation["page_number"],
                "chunk_text": citation["snippet"],
                "snippet": citation["snippet"],
                "score": 1.0,
                "match_source": "lexical",
                "semantic_similarity": None,
            }
            for citation in citations
        ],
        "profile": {
            "ttft_seconds": 0.0,
            "retrieval_seconds": 0.01,
            "prompt_build_seconds": 0.0,
            "model_inference_seconds": 0.0,
            "post_processing_seconds": 0.0,
            "total_seconds": 0.02,
            "retrieved_chunks": len(citations),
            "retrieval_mode": "lexical",
            "retrieval_mode_label": "Lexical only",
            "queue_wait_seconds": 0.0,
        },
    }
    return save_qa_history(
        settings.db_path,
        question=DEMO_QUESTION,
        retrieved_chunk_ids=[str(citation["chunk_id"]) for citation in citations],
        answer_text=session_data["short_answer"],
        more_detail=session_data["more_detail"],
        unsure=False,
        result_mode="answered",
        actor_role="learner",
        actor_key=DEMO_ACTOR_KEY,
        class_space=class_space,
        retrieval_mode="lexical",
        retrieval_mode_label="Lexical only",
        citation_list=citations,
        session_data=session_data,
    )


def _ensure_weak_demo_qa(settings, *, class_space: str) -> int:
    existing = _find_existing_qa_id(settings.db_path, question=DEMO_WEAK_QUESTION, class_space=class_space)
    if existing is not None:
        return existing
    return save_qa_history(
        settings.db_path,
        question=DEMO_WEAK_QUESTION,
        retrieved_chunk_ids=[],
        answer_text="I could not find a close match in the uploaded classroom materials.",
        more_detail="This is a seeded follow-up item for the teacher summary.",
        unsure=True,
        result_mode="no_match",
        actor_role="learner",
        actor_key=DEMO_ACTOR_KEY,
        class_space=class_space,
        retrieval_mode="lexical",
        retrieval_mode_label="Lexical only",
        citation_list=[],
        session_data={
            "question": DEMO_WEAK_QUESTION,
            "answer_language": "auto",
            "answer_language_label": "Match question",
            "plain_language_requested": False,
            "short_answer": "I could not find a close match in the uploaded classroom materials.",
            "more_detail": "This is a seeded follow-up item for the teacher summary.",
            "result_mode": "no_match",
            "runtime_backend": "cached-local-demo",
            "model_name": settings.accesslab_model,
            "retrieved_results": [],
            "profile": {"retrieval_mode": "lexical", "retrieval_mode_label": "Lexical only"},
        },
    )


def _ensure_demo_code_session(settings, *, class_space: str) -> int:
    existing = _find_existing_code_id(settings.db_path, class_space=class_space)
    if existing is not None:
        return existing

    original_code = (settings.sample_code_dir / "buggy_sum.py").read_text(encoding="utf-8")
    test_code = (settings.sample_code_dir / "test_buggy_sum.py").read_text(encoding="utf-8")
    patched_code = "def add_numbers(a, b):\n    return a + b\n"
    initial_output = (
        "assert add_numbers(2, 3) == 5\n"
        "E       assert -1 == 5\n"
        "E        +  where -1 = add_numbers(2, 3)"
    )
    patched_output = "1 passed"
    session_data = {
        "instruction": "Fix the smallest beginner bug and rerun the tests.",
        "original_code": original_code,
        "form_tests": test_code,
        "prompt_variant": "cached-demo",
        "runtime_backend": "cached-local-demo",
        "model_name": settings.accesslab_model,
        "diagnosis": "The function subtracts `b` from `a`, so the test gets -1 instead of 5.",
        "evidence": initial_output,
        "next_fix": "Change `return a - b` to `return a + b`.",
        "why_it_works": "The patched function now adds both inputs, matching the test expectation.",
        "patched_code": patched_code,
        "result_mode": "completed",
        "initial_run": {
            "status": "completed",
            "return_code": 1,
            "stdout": "",
            "stderr": initial_output,
            "timed_out": False,
            "command": ["python", "-m", "pytest"],
            "mode": "tests",
            "effective_test_code": test_code,
            "used_generated_tests": False,
            "working_directory": "cached-demo",
            "sandbox_profile": "audit-posix",
            "sandbox_note": "Best-effort local sandbox: temp directory, scrubbed environment, policy checks, and POSIX resource limits where available.",
            "denied_by_policy": False,
        },
        "patched_run": {
            "status": "completed",
            "return_code": 0,
            "stdout": patched_output,
            "stderr": "",
            "timed_out": False,
            "command": ["python", "-m", "pytest"],
            "mode": "tests",
            "effective_test_code": test_code,
            "used_generated_tests": False,
            "working_directory": "cached-demo",
            "sandbox_profile": "audit-posix",
            "sandbox_note": "Best-effort local sandbox: temp directory, scrubbed environment, policy checks, and POSIX resource limits where available.",
            "denied_by_policy": False,
        },
        "rerun_success": True,
        "profile": {
            "ttft_seconds": 0.0,
            "prompt_build_seconds": 0.0,
            "model_inference_seconds": 0.0,
            "post_processing_seconds": 0.0,
            "code_execution_seconds": 0.03,
            "patched_execution_seconds": 0.03,
            "total_seconds": 0.06,
            "queue_wait_seconds": 0.0,
        },
    }
    return save_code_session(
        settings.db_path,
        original_code=original_code,
        test_code=test_code,
        execution_output=initial_output,
        patched_code=patched_code,
        patched_test_result=patched_output,
        actor_role="learner",
        actor_key=DEMO_ACTOR_KEY,
        class_space=class_space,
        session_data=session_data,
    )


def _ensure_labels(settings, *, class_space: str, qa_id: int, code_id: int) -> None:
    for source_type, source_id in (("qa", qa_id), ("code", code_id)):
        if source_id <= 0:
            continue
        existing = list_session_labels(
            settings.db_path,
            source_type=source_type,
            source_id=source_id,
            class_space=class_space,
            limit=1,
        )
        if existing:
            continue
        save_session_label(
            settings.db_path,
            source_type=source_type,
            source_id=source_id,
            label="good",
            note="Seeded judge-demo teacher review.",
            actor_role="teacher",
            actor_key=DEMO_TEACHER_KEY,
            class_space=class_space,
        )


def dump_demo_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, ensure_ascii=False)
