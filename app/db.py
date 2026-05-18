from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


DEFAULT_CLASS_SPACE = "default-classroom"
DEFAULT_ACTOR_KEY = "local-user"


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    visibility_scope TEXT NOT NULL DEFAULT 'class',
    uploader_role TEXT NOT NULL DEFAULT 'teacher',
    class_space TEXT NOT NULL DEFAULT 'default-classroom',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    source_file TEXT NOT NULL,
    page_number INTEGER,
    chunk_id TEXT NOT NULL UNIQUE,
    chunk_text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id TEXT PRIMARY KEY REFERENCES document_chunks(chunk_id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL,
    vector_dim INTEGER NOT NULL,
    embedding_vector BLOB NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_model ON chunk_embeddings(embedding_model);

CREATE TABLE IF NOT EXISTS qa_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    retrieved_chunk_ids TEXT NOT NULL,
    answer_text TEXT NOT NULL,
    more_detail TEXT NOT NULL DEFAULT '',
    unsure INTEGER NOT NULL DEFAULT 0,
    result_mode TEXT NOT NULL DEFAULT 'answered',
    actor_role TEXT NOT NULL DEFAULT 'learner',
    actor_key TEXT NOT NULL DEFAULT 'local-user',
    class_space TEXT NOT NULL DEFAULT 'default-classroom',
    retrieval_mode TEXT NOT NULL DEFAULT 'lexical',
    retrieval_mode_label TEXT NOT NULL DEFAULT 'Lexical only',
    citation_list TEXT NOT NULL,
    session_data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS code_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_code TEXT NOT NULL,
    test_code TEXT,
    execution_output TEXT NOT NULL,
    patched_code TEXT,
    patched_test_result TEXT NOT NULL,
    actor_role TEXT NOT NULL DEFAULT 'learner',
    actor_key TEXT NOT NULL DEFAULT 'local-user',
    class_space TEXT NOT NULL DEFAULT 'default-classroom',
    session_data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS semantic_index_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    status TEXT NOT NULL DEFAULT 'not_indexed',
    last_error_code TEXT NOT NULL DEFAULT '',
    last_error_message TEXT NOT NULL DEFAULT '',
    last_attempted_at TEXT NOT NULL DEFAULT '',
    last_completed_at TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS session_labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    actor_role TEXT NOT NULL DEFAULT 'teacher',
    actor_key TEXT NOT NULL DEFAULT 'local-user',
    class_space TEXT NOT NULL DEFAULT 'default-classroom',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_labels_source ON session_labels(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_session_labels_class_space ON session_labels(class_space, created_at);

CREATE TABLE IF NOT EXISTS training_capture_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    capture_kind TEXT NOT NULL,
    actor_role TEXT NOT NULL DEFAULT 'learner',
    actor_key TEXT NOT NULL DEFAULT 'local-user',
    class_space TEXT NOT NULL DEFAULT 'default-classroom',
    retrieval_mode TEXT NOT NULL DEFAULT '',
    weak_retrieval INTEGER NOT NULL DEFAULT 0,
    runtime_backend TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    prompt_variant TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_training_capture_source ON training_capture_events(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_training_capture_class_space ON training_capture_events(class_space, created_at);

CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
    chunk_id UNINDEXED,
    document_id UNINDEXED,
    source_file,
    page_number UNINDEXED,
    chunk_text,
    tokenize = 'unicode61'
);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA)
        _migrate_schema(connection)
        _ensure_semantic_index_meta_row(connection)
        connection.commit()


def _migrate_schema(connection: sqlite3.Connection) -> None:
    document_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(documents)").fetchall()
    }
    if "visibility_scope" not in document_columns:
        connection.execute(
            "ALTER TABLE documents ADD COLUMN visibility_scope TEXT NOT NULL DEFAULT 'class'"
        )
    if "uploader_role" not in document_columns:
        connection.execute(
            "ALTER TABLE documents ADD COLUMN uploader_role TEXT NOT NULL DEFAULT 'teacher'"
        )
    if "class_space" not in document_columns:
        connection.execute(
            "ALTER TABLE documents ADD COLUMN class_space TEXT NOT NULL DEFAULT 'default-classroom'"
        )

    qa_history_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(qa_history)").fetchall()
    }
    if "more_detail" not in qa_history_columns:
        connection.execute(
            "ALTER TABLE qa_history ADD COLUMN more_detail TEXT NOT NULL DEFAULT ''"
        )
    if "unsure" not in qa_history_columns:
        connection.execute(
            "ALTER TABLE qa_history ADD COLUMN unsure INTEGER NOT NULL DEFAULT 0"
        )
    if "result_mode" not in qa_history_columns:
        connection.execute(
            "ALTER TABLE qa_history ADD COLUMN result_mode TEXT NOT NULL DEFAULT 'answered'"
        )
    if "actor_role" not in qa_history_columns:
        connection.execute(
            "ALTER TABLE qa_history ADD COLUMN actor_role TEXT NOT NULL DEFAULT 'learner'"
        )
    if "actor_key" not in qa_history_columns:
        connection.execute(
            "ALTER TABLE qa_history ADD COLUMN actor_key TEXT NOT NULL DEFAULT 'local-user'"
        )
    if "class_space" not in qa_history_columns:
        connection.execute(
            "ALTER TABLE qa_history ADD COLUMN class_space TEXT NOT NULL DEFAULT 'default-classroom'"
        )
    if "retrieval_mode" not in qa_history_columns:
        connection.execute(
            "ALTER TABLE qa_history ADD COLUMN retrieval_mode TEXT NOT NULL DEFAULT 'lexical'"
        )
    if "retrieval_mode_label" not in qa_history_columns:
        connection.execute(
            "ALTER TABLE qa_history ADD COLUMN retrieval_mode_label TEXT NOT NULL DEFAULT 'Lexical only'"
        )
    if "session_data" not in qa_history_columns:
        connection.execute(
            "ALTER TABLE qa_history ADD COLUMN session_data TEXT NOT NULL DEFAULT '{}'"
        )

    code_session_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(code_sessions)").fetchall()
    }
    if "session_data" not in code_session_columns:
        connection.execute(
            "ALTER TABLE code_sessions ADD COLUMN session_data TEXT NOT NULL DEFAULT '{}'"
        )
    if "actor_role" not in code_session_columns:
        connection.execute(
            "ALTER TABLE code_sessions ADD COLUMN actor_role TEXT NOT NULL DEFAULT 'learner'"
        )
    if "actor_key" not in code_session_columns:
        connection.execute(
            "ALTER TABLE code_sessions ADD COLUMN actor_key TEXT NOT NULL DEFAULT 'local-user'"
        )
    if "class_space" not in code_session_columns:
        connection.execute(
            "ALTER TABLE code_sessions ADD COLUMN class_space TEXT NOT NULL DEFAULT 'default-classroom'"
        )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS semantic_index_meta (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            status TEXT NOT NULL DEFAULT 'not_indexed',
            last_error_code TEXT NOT NULL DEFAULT '',
            last_error_message TEXT NOT NULL DEFAULT '',
            last_attempted_at TEXT NOT NULL DEFAULT '',
            last_completed_at TEXT NOT NULL DEFAULT '',
            model_name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS session_labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            actor_role TEXT NOT NULL DEFAULT 'teacher',
            actor_key TEXT NOT NULL DEFAULT 'local-user',
            class_space TEXT NOT NULL DEFAULT 'default-classroom',
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_labels_source ON session_labels(source_type, source_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_labels_class_space ON session_labels(class_space, created_at)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS training_capture_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            capture_kind TEXT NOT NULL,
            actor_role TEXT NOT NULL DEFAULT 'learner',
            actor_key TEXT NOT NULL DEFAULT 'local-user',
            class_space TEXT NOT NULL DEFAULT 'default-classroom',
            retrieval_mode TEXT NOT NULL DEFAULT '',
            weak_retrieval INTEGER NOT NULL DEFAULT 0,
            runtime_backend TEXT NOT NULL DEFAULT '',
            model_name TEXT NOT NULL DEFAULT '',
            prompt_variant TEXT NOT NULL DEFAULT '',
            payload TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_capture_source ON training_capture_events(source_type, source_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_capture_class_space ON training_capture_events(class_space, created_at)"
    )


def _ensure_semantic_index_meta_row(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT singleton FROM semantic_index_meta WHERE singleton = 1"
    ).fetchone()
    if row is None:
        connection.execute(
            """
            INSERT INTO semantic_index_meta (
                singleton,
                status,
                last_error_code,
                last_error_message,
                last_attempted_at,
                last_completed_at,
                model_name,
                updated_at
            )
            VALUES (1, 'not_indexed', '', '', '', '', '', ?)
            """,
            (utc_now_iso(),),
        )


@contextmanager
def db_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def list_documents(
    db_path: Path,
    *,
    class_space: str | None = None,
) -> list[dict[str, Any]]:
    query = """
    SELECT
        d.id,
        d.file_name,
        d.file_type,
        d.stored_path,
        d.visibility_scope,
        d.uploader_role,
        d.class_space,
        d.created_at,
        COUNT(c.id) AS chunk_count
    FROM documents AS d
    LEFT JOIN document_chunks AS c ON c.document_id = d.id
    {where_clause}
    GROUP BY d.id
    ORDER BY d.created_at DESC;
    """
    params: list[Any] = []
    where_clause = ""
    if class_space:
        where_clause = "WHERE d.class_space = ?"
        params.append(class_space)
    with db_connection(db_path) as connection:
        rows = connection.execute(query.format(where_clause=where_clause), params).fetchall()
    return [row_to_dict(row) for row in rows]


def save_qa_history(
    db_path: Path,
    *,
    question: str,
    retrieved_chunk_ids: list[str],
    answer_text: str,
    citation_list: list[dict[str, Any]],
    actor_role: str = "learner",
    actor_key: str = DEFAULT_ACTOR_KEY,
    class_space: str = DEFAULT_CLASS_SPACE,
    more_detail: str = "",
    unsure: bool = False,
    result_mode: str = "answered",
    retrieval_mode: str = "lexical",
    retrieval_mode_label: str = "Lexical only",
    session_data: dict[str, Any] | None = None,
) -> int:
    with db_connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO qa_history (
                question,
                retrieved_chunk_ids,
                answer_text,
                more_detail,
                unsure,
                result_mode,
                actor_role,
                actor_key,
                class_space,
                retrieval_mode,
                retrieval_mode_label,
                citation_list,
                session_data,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                question,
                json.dumps(retrieved_chunk_ids),
                answer_text,
                more_detail,
                int(unsure),
                result_mode,
                actor_role,
                actor_key,
                class_space,
                retrieval_mode,
                retrieval_mode_label,
                json.dumps(citation_list),
                json.dumps(session_data or {}),
                utc_now_iso(),
            ),
        )
        return int(cursor.lastrowid)


def get_qa_history_entry(db_path: Path, qa_id: int) -> dict[str, Any] | None:
    with db_connection(db_path) as connection:
        row = connection.execute(
            """
            SELECT
                id,
                question,
                retrieved_chunk_ids,
                answer_text,
                more_detail,
                unsure,
                result_mode,
                actor_role,
                actor_key,
                class_space,
                retrieval_mode,
                retrieval_mode_label,
                citation_list,
                session_data,
                created_at
            FROM qa_history
            WHERE id = ?
            LIMIT 1
            """,
            (qa_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "question": row["question"],
        "retrieved_chunk_ids": json.loads(row["retrieved_chunk_ids"]),
        "answer_text": row["answer_text"],
        "more_detail": row["more_detail"],
        "unsure": bool(row["unsure"]),
        "result_mode": row["result_mode"] or "answered",
        "actor_role": row["actor_role"] or "learner",
        "actor_key": row["actor_key"] or DEFAULT_ACTOR_KEY,
        "class_space": row["class_space"] or DEFAULT_CLASS_SPACE,
        "retrieval_mode": row["retrieval_mode"] or "lexical",
        "retrieval_mode_label": row["retrieval_mode_label"] or "Lexical only",
        "citation_list": json.loads(row["citation_list"]),
        "session_data": json.loads(row["session_data"] or "{}"),
        "created_at": row["created_at"],
    }


def save_code_session(
    db_path: Path,
    *,
    original_code: str,
    test_code: str | None,
    execution_output: str,
    patched_code: str | None,
    patched_test_result: str,
    actor_role: str = "learner",
    actor_key: str = DEFAULT_ACTOR_KEY,
    class_space: str = DEFAULT_CLASS_SPACE,
    session_data: dict[str, Any] | None = None,
) -> int:
    with db_connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO code_sessions (
                original_code,
                test_code,
                execution_output,
                patched_code,
                patched_test_result,
                actor_role,
                actor_key,
                class_space,
                session_data,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                original_code,
                test_code,
                execution_output,
                patched_code,
                patched_test_result,
                actor_role,
                actor_key,
                class_space,
                json.dumps(session_data or {}),
                utc_now_iso(),
            ),
        )
        return int(cursor.lastrowid)


def get_code_session_entry(db_path: Path, session_id: int) -> dict[str, Any] | None:
    with db_connection(db_path) as connection:
        row = connection.execute(
            """
            SELECT
                id,
                original_code,
                test_code,
                execution_output,
                patched_code,
                patched_test_result,
                actor_role,
                actor_key,
                class_space,
                session_data,
                created_at
            FROM code_sessions
            WHERE id = ?
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "original_code": row["original_code"],
        "test_code": row["test_code"],
        "execution_output": row["execution_output"],
        "patched_code": row["patched_code"],
        "patched_test_result": row["patched_test_result"],
        "actor_role": row["actor_role"] or "learner",
        "actor_key": row["actor_key"] or DEFAULT_ACTOR_KEY,
        "class_space": row["class_space"] or DEFAULT_CLASS_SPACE,
        "session_data": json.loads(row["session_data"] or "{}"),
        "created_at": row["created_at"],
    }


def list_recent_qa_history(
    db_path: Path,
    *,
    actor_role: str | None = None,
    actor_key: str | None = None,
    class_space: str | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    query = """
    SELECT
        id,
        question,
        result_mode,
        actor_role,
        actor_key,
        class_space,
        retrieval_mode,
        retrieval_mode_label,
        created_at
    FROM qa_history
    {where_clause}
    ORDER BY id DESC
    LIMIT ?
    """
    params: list[Any] = []
    filters: list[str] = []
    if actor_role:
        filters.append("actor_role = ?")
        params.append(actor_role)
    if actor_key:
        filters.append("actor_key = ?")
        params.append(actor_key)
    if class_space:
        filters.append("class_space = ?")
        params.append(class_space)
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    params.append(limit)
    with db_connection(db_path) as connection:
        rows = connection.execute(query.format(where_clause=where_clause), params).fetchall()
    return [row_to_dict(row) for row in rows]


def list_recent_code_sessions(
    db_path: Path,
    *,
    actor_role: str | None = None,
    actor_key: str | None = None,
    class_space: str | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    query = """
    SELECT
        id,
        original_code,
        actor_role,
        actor_key,
        class_space,
        session_data,
        created_at
    FROM code_sessions
    {where_clause}
    ORDER BY id DESC
    LIMIT ?
    """
    params: list[Any] = []
    filters: list[str] = []
    if actor_role:
        filters.append("actor_role = ?")
        params.append(actor_role)
    if actor_key:
        filters.append("actor_key = ?")
        params.append(actor_key)
    if class_space:
        filters.append("class_space = ?")
        params.append(class_space)
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    params.append(limit)
    with db_connection(db_path) as connection:
        rows = connection.execute(query.format(where_clause=where_clause), params).fetchall()
    return [
        {
            "id": row["id"],
            "original_code": row["original_code"],
            "actor_role": row["actor_role"] or "learner",
            "actor_key": row["actor_key"] or DEFAULT_ACTOR_KEY,
            "class_space": row["class_space"] or DEFAULT_CLASS_SPACE,
            "session_data": json.loads(row["session_data"] or "{}"),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def list_recent_classroom_activity(
    db_path: Path,
    *,
    class_space: str | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    qa_rows = list_recent_qa_history(
        db_path,
        class_space=class_space,
        limit=limit,
    )
    code_rows = list_recent_code_sessions(
        db_path,
        class_space=class_space,
        limit=limit,
    )

    activity_rows: list[dict[str, Any]] = []
    for row in qa_rows:
        activity_rows.append(
            {
                "activity_type": "qa",
                "id": row["id"],
                "actor_role": row["actor_role"],
                "actor_key": row["actor_key"],
                "title": row["question"],
                "state_label": row["result_mode"],
                "detail_label": row["retrieval_mode_label"],
                "created_at": row["created_at"],
                "href": f"/qa?qa_id={int(row['id'])}",
            }
        )
    for row in code_rows:
        activity_rows.append(
            {
                "activity_type": "code",
                "id": row["id"],
                "actor_role": row["actor_role"],
                "actor_key": row["actor_key"],
                "title": _code_session_title_from_row(row),
                "state_label": "saved review",
                "detail_label": "Local rerun",
                "created_at": row["created_at"],
                "href": f"/code?session_id={int(row['id'])}",
            }
        )

    activity_rows.sort(
        key=lambda row: (
            str(row.get("created_at", "")),
            int(row.get("id", 0)),
        ),
        reverse=True,
    )
    return activity_rows[:limit]


def _code_session_title_from_row(row: dict[str, Any]) -> str:
    session_data = row.get("session_data")
    if isinstance(session_data, dict):
        instruction = str(session_data.get("instruction", "")).strip()
        if instruction:
            return instruction[:80]

    original_code = str(row.get("original_code", ""))
    for line in original_code.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:80]
    return "Saved Python review"


def save_session_label(
    db_path: Path,
    *,
    source_type: str,
    source_id: int,
    label: str,
    note: str = "",
    actor_role: str = "teacher",
    actor_key: str = DEFAULT_ACTOR_KEY,
    class_space: str = DEFAULT_CLASS_SPACE,
) -> int:
    with db_connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO session_labels (
                source_type,
                source_id,
                label,
                note,
                actor_role,
                actor_key,
                class_space,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_type.strip().lower(),
                int(source_id),
                label.strip().lower(),
                note.strip(),
                actor_role,
                actor_key,
                class_space,
                utc_now_iso(),
            ),
        )
        return int(cursor.lastrowid)


def list_session_labels(
    db_path: Path,
    *,
    source_type: str | None = None,
    source_id: int | None = None,
    class_space: str | None = None,
    label: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    filters: list[str] = []
    params: list[Any] = []
    if source_type:
        filters.append("source_type = ?")
        params.append(source_type.strip().lower())
    if source_id is not None:
        filters.append("source_id = ?")
        params.append(int(source_id))
    if class_space:
        filters.append("class_space = ?")
        params.append(class_space)
    if label:
        filters.append("label = ?")
        params.append(label.strip().lower())
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    params.append(limit)
    with db_connection(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT
                id,
                source_type,
                source_id,
                label,
                note,
                actor_role,
                actor_key,
                class_space,
                created_at
            FROM session_labels
            {where_clause}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def save_training_capture(
    db_path: Path,
    *,
    source_type: str,
    source_id: int,
    capture_kind: str,
    actor_role: str = "learner",
    actor_key: str = DEFAULT_ACTOR_KEY,
    class_space: str = DEFAULT_CLASS_SPACE,
    retrieval_mode: str = "",
    weak_retrieval: bool = False,
    runtime_backend: str = "",
    model_name: str = "",
    prompt_variant: str = "",
    payload: dict[str, Any] | None = None,
) -> int:
    with db_connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO training_capture_events (
                source_type,
                source_id,
                capture_kind,
                actor_role,
                actor_key,
                class_space,
                retrieval_mode,
                weak_retrieval,
                runtime_backend,
                model_name,
                prompt_variant,
                payload,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_type.strip().lower(),
                int(source_id),
                capture_kind.strip().lower(),
                actor_role,
                actor_key,
                class_space,
                retrieval_mode.strip().lower(),
                int(bool(weak_retrieval)),
                runtime_backend.strip().lower(),
                model_name.strip(),
                prompt_variant.strip().lower(),
                json.dumps(payload or {}),
                utc_now_iso(),
            ),
        )
        return int(cursor.lastrowid)


def list_training_capture_events(
    db_path: Path,
    *,
    source_type: str | None = None,
    source_id: int | None = None,
    class_space: str | None = None,
    capture_kind: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    filters: list[str] = []
    params: list[Any] = []
    if source_type:
        filters.append("source_type = ?")
        params.append(source_type.strip().lower())
    if source_id is not None:
        filters.append("source_id = ?")
        params.append(int(source_id))
    if class_space:
        filters.append("class_space = ?")
        params.append(class_space)
    if capture_kind:
        filters.append("capture_kind = ?")
        params.append(capture_kind.strip().lower())
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    params.append(limit)
    with db_connection(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT
                id,
                source_type,
                source_id,
                capture_kind,
                actor_role,
                actor_key,
                class_space,
                retrieval_mode,
                weak_retrieval,
                runtime_backend,
                model_name,
                prompt_variant,
                payload,
                created_at
            FROM training_capture_events
            {where_clause}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [
        {
            **row_to_dict(row),
            "weak_retrieval": bool(row["weak_retrieval"]),
            "payload": json.loads(row["payload"] or "{}"),
        }
        for row in rows
    ]


def preview_class_space_migration(
    db_path: Path,
    *,
    from_class_space: str,
    to_class_space: str,
    include_sessions: bool = True,
) -> dict[str, Any]:
    normalized_from = (from_class_space or "").strip() or DEFAULT_CLASS_SPACE
    normalized_to = (to_class_space or "").strip() or DEFAULT_CLASS_SPACE
    warnings: list[str] = []
    if normalized_from == normalized_to:
        warnings.append("Source and destination class-space labels are the same. No rows need reassignment.")

    with db_connection(db_path) as connection:
        documents = int(
            connection.execute(
                "SELECT COUNT(*) FROM documents WHERE class_space = ?",
                (normalized_from,),
            ).fetchone()[0]
        )
        chunks = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM document_chunks AS c
                JOIN documents AS d ON d.id = c.document_id
                WHERE d.class_space = ?
                """,
                (normalized_from,),
            ).fetchone()[0]
        )
        embeddings = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM chunk_embeddings AS e
                JOIN document_chunks AS c ON c.chunk_id = e.chunk_id
                JOIN documents AS d ON d.id = c.document_id
                WHERE d.class_space = ?
                """,
                (normalized_from,),
            ).fetchone()[0]
        )
        qa_sessions = int(
            connection.execute(
                "SELECT COUNT(*) FROM qa_history WHERE class_space = ?",
                (normalized_from,),
            ).fetchone()[0]
        )
        code_sessions = int(
            connection.execute(
                "SELECT COUNT(*) FROM code_sessions WHERE class_space = ?",
                (normalized_from,),
            ).fetchone()[0]
        )
        session_labels = int(
            connection.execute(
                "SELECT COUNT(*) FROM session_labels WHERE class_space = ?",
                (normalized_from,),
            ).fetchone()[0]
        )
        training_capture_events = int(
            connection.execute(
                "SELECT COUNT(*) FROM training_capture_events WHERE class_space = ?",
                (normalized_from,),
            ).fetchone()[0]
        )

    if documents == 0 and (not include_sessions or (qa_sessions == 0 and code_sessions == 0)):
        warnings.append(f"No rows were found in class space `{normalized_from}`.")
    if include_sessions:
        warnings.append(
            "Saved QA and code session URLs keep the same IDs, but their access now follows the destination class-space scope."
        )
    else:
        warnings.append(
            "Saved QA and code sessions will stay in the source class space unless you rerun with --include-sessions."
        )

    return {
        "from_class_space": normalized_from,
        "to_class_space": normalized_to,
        "include_sessions": include_sessions,
        "counts": {
            "documents": documents,
            "document_chunks": chunks,
            "chunk_embeddings": embeddings,
            "qa_sessions": qa_sessions,
            "code_sessions": code_sessions,
            "session_labels": session_labels,
            "training_capture_events": training_capture_events,
        },
        "warnings": warnings,
    }


def apply_class_space_migration(
    db_path: Path,
    *,
    from_class_space: str,
    to_class_space: str,
    include_sessions: bool = True,
) -> dict[str, Any]:
    preview = preview_class_space_migration(
        db_path,
        from_class_space=from_class_space,
        to_class_space=to_class_space,
        include_sessions=include_sessions,
    )
    if preview["from_class_space"] == preview["to_class_space"]:
        preview["applied"] = False
        return preview

    with db_connection(db_path) as connection:
        connection.execute(
            "UPDATE documents SET class_space = ? WHERE class_space = ?",
            (preview["to_class_space"], preview["from_class_space"]),
        )
        if include_sessions:
            connection.execute(
                "UPDATE qa_history SET class_space = ? WHERE class_space = ?",
                (preview["to_class_space"], preview["from_class_space"]),
            )
            connection.execute(
                "UPDATE code_sessions SET class_space = ? WHERE class_space = ?",
                (preview["to_class_space"], preview["from_class_space"]),
            )
            connection.execute(
                "UPDATE session_labels SET class_space = ? WHERE class_space = ?",
                (preview["to_class_space"], preview["from_class_space"]),
            )
            connection.execute(
                "UPDATE training_capture_events SET class_space = ? WHERE class_space = ?",
                (preview["to_class_space"], preview["from_class_space"]),
            )

    preview["applied"] = True
    return preview


def delete_document(
    db_path: Path,
    document_id: int,
    *,
    class_space: str | None = None,
) -> dict[str, Any] | None:
    with db_connection(db_path) as connection:
        params: list[Any] = [document_id]
        where_clause = "WHERE id = ?"
        if class_space:
            where_clause += " AND class_space = ?"
            params.append(class_space)
        row = connection.execute(
            f"""
            SELECT id, file_name, stored_path, visibility_scope, uploader_role, class_space
            FROM documents
            {where_clause}
            LIMIT 1
            """,
            params,
        ).fetchone()
        if row is None:
            return None
        connection.execute(
            f"DELETE FROM documents {where_clause}",
            params,
        )
    return row_to_dict(row)


def get_semantic_index_meta(db_path: Path) -> dict[str, Any]:
    with db_connection(db_path) as connection:
        _ensure_semantic_index_meta_row(connection)
        row = connection.execute(
            """
            SELECT
                singleton,
                status,
                last_error_code,
                last_error_message,
                last_attempted_at,
                last_completed_at,
                model_name,
                updated_at
            FROM semantic_index_meta
            WHERE singleton = 1
            """
        ).fetchone()
    return row_to_dict(row)


def update_semantic_index_meta(
    db_path: Path,
    *,
    status: str | None = None,
    last_error_code: str | None = None,
    last_error_message: str | None = None,
    last_attempted_at: str | None = None,
    last_completed_at: str | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    with db_connection(db_path) as connection:
        _ensure_semantic_index_meta_row(connection)
        current = connection.execute(
            """
            SELECT
                status,
                last_error_code,
                last_error_message,
                last_attempted_at,
                last_completed_at,
                model_name
            FROM semantic_index_meta
            WHERE singleton = 1
            """
        ).fetchone()
        payload = {
            "status": status if status is not None else current["status"],
            "last_error_code": (
                last_error_code
                if last_error_code is not None
                else current["last_error_code"]
            ),
            "last_error_message": (
                last_error_message
                if last_error_message is not None
                else current["last_error_message"]
            ),
            "last_attempted_at": (
                last_attempted_at
                if last_attempted_at is not None
                else current["last_attempted_at"]
            ),
            "last_completed_at": (
                last_completed_at
                if last_completed_at is not None
                else current["last_completed_at"]
            ),
            "model_name": model_name if model_name is not None else current["model_name"],
            "updated_at": utc_now_iso(),
        }
        connection.execute(
            """
            UPDATE semantic_index_meta
            SET
                status = :status,
                last_error_code = :last_error_code,
                last_error_message = :last_error_message,
                last_attempted_at = :last_attempted_at,
                last_completed_at = :last_completed_at,
                model_name = :model_name,
                updated_at = :updated_at
            WHERE singleton = 1
            """,
            payload,
        )
    return get_semantic_index_meta(db_path)


def mark_semantic_index_pending(db_path: Path, *, model_name: str) -> dict[str, Any]:
    return update_semantic_index_meta(
        db_path,
        status="indexing_pending",
        last_error_code="",
        last_error_message="",
        last_attempted_at=utc_now_iso(),
        model_name=model_name,
    )


def mark_semantic_index_indexed(db_path: Path, *, model_name: str) -> dict[str, Any]:
    timestamp = utc_now_iso()
    return update_semantic_index_meta(
        db_path,
        status="indexed",
        last_error_code="",
        last_error_message="",
        last_attempted_at=timestamp,
        last_completed_at=timestamp,
        model_name=model_name,
    )


def mark_semantic_index_failed(
    db_path: Path,
    *,
    model_name: str,
    error_code: str,
    error_message: str,
) -> dict[str, Any]:
    return update_semantic_index_meta(
        db_path,
        status="indexing_failed",
        last_error_code=error_code,
        last_error_message=error_message,
        last_attempted_at=utc_now_iso(),
        model_name=model_name,
    )


def semantic_index_counts(
    db_path: Path,
    *,
    model_name: str,
    class_space: str | None = None,
) -> dict[str, int]:
    with db_connection(db_path) as connection:
        document_params: list[Any] = []
        document_where = ""
        chunk_join = ""
        chunk_params: list[Any] = []
        if class_space:
            document_where = "WHERE class_space = ?"
            document_params.append(class_space)
            chunk_join = "JOIN documents AS d ON d.id = c.document_id"
            chunk_params.append(class_space)

        document_count = connection.execute(
            f"SELECT COUNT(*) FROM documents {document_where}",
            document_params,
        ).fetchone()[0]
        chunk_count = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM document_chunks AS c
            {chunk_join}
            {"WHERE d.class_space = ?" if class_space else ""}
            """,
            chunk_params,
        ).fetchone()[0]
        if model_name:
            embedding_params: list[Any] = [model_name]
            embedding_join = ""
            embedding_where = "WHERE e.embedding_model = ?"
            if class_space:
                embedding_join = (
                    "JOIN document_chunks AS c ON c.chunk_id = e.chunk_id "
                    "JOIN documents AS d ON d.id = c.document_id"
                )
                embedding_where += " AND d.class_space = ?"
                embedding_params.append(class_space)
            embedded_chunk_count = connection.execute(
                f"""
                SELECT COUNT(*)
                FROM chunk_embeddings AS e
                {embedding_join}
                {embedding_where}
                """,
                embedding_params,
            ).fetchone()[0]
        else:
            embedded_chunk_count = 0
    missing_chunk_count = max(0, int(chunk_count) - int(embedded_chunk_count))
    return {
        "document_count": int(document_count),
        "chunk_count": int(chunk_count),
        "embedded_chunk_count": int(embedded_chunk_count),
        "missing_chunk_count": int(missing_chunk_count),
    }
