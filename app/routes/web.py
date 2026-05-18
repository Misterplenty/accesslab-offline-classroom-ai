from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from contextlib import contextmanager

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from markupsafe import Markup

from app.config import PROFILE_MODELS
from app.db import (
    apply_class_space_migration,
    db_connection,
    delete_document,
    get_code_session_entry,
    get_qa_history_entry,
    list_session_labels,
    list_training_capture_events,
    list_documents,
    list_recent_classroom_activity,
    list_recent_code_sessions,
    list_recent_qa_history,
    preview_class_space_migration,
    save_session_label,
)
from app.models.schemas import Citation, CodeTutorResult, ExecutionResult, IngestSummary, QAResult
from app.services.answer_rendering import build_evidence_cards, render_answer_html
from app.services.bootstrap import ensure_semantic_backfill
from app.services.code_tutor import _missing_submission_imports
from app.services.judge_demo import DEMO_ACTOR_KEY, seed_judge_demo
from app.services.llm import ALLOWED_GEMMA4_MODELS, list_ollama_model_names
from app.services.local_identity import ACTOR_COOKIE_NAME, actor_label, attach_actor_cookie, current_actor_key
from app.services.ocr import create_ocr_backend
from app.services.operator_preflight import build_operator_preflight
from app.services.session_review import KNOWN_SESSION_LABELS, session_label_display
from app.services.roles import (
    ROLE_COOKIE_NAME,
    ROLE_CATALOG,
    current_local_role,
    resolve_local_role,
)
from app.services.semantic import SQLiteSemanticIndex, create_embedding_provider
from app.services.source_view import load_source_view
from app.services.system_status import build_retrieval_diagnostics


router = APIRouter()


def _finalize_response(request: Request, response: HTMLResponse | RedirectResponse) -> HTMLResponse | RedirectResponse:
    return attach_actor_cookie(response, request)


@contextmanager
def _queue_job(request: Request, *, job_kind: str = "request"):
    work_queue = getattr(request.app.state, "work_queue", None)
    if work_queue is None:
        yield None
        return
    with work_queue.job(job_kind=job_kind) as receipt:
        yield receipt


def _default_queue_snapshot(max_concurrent_jobs: int) -> dict[str, int | float | str]:
    return {
        "max_concurrent_jobs": max_concurrent_jobs,
        "active_jobs": 0,
        "waiting_jobs": 0,
        "queue_depth": 0,
        "active_budget": 0,
        "available_budget": max_concurrent_jobs,
        "last_started_at": "",
        "last_completed_at": "",
        "last_failed_at": "",
        "last_job_kind": "",
        "last_wait_seconds": 0.0,
        "average_wait_seconds": 0.0,
        "completed_jobs": 0,
        "failed_jobs": 0,
        "active_by_kind": {},
        "waiting_by_kind": {},
        "recent_jobs": [],
        "active_job_receipts": [],
    }


def _queue_wait_summary(receipt) -> str:
    if receipt is None:
        return "Queue wait not measured."
    wait_seconds = round(float(getattr(receipt, "wait_seconds", 0.0) or 0.0), 2)
    if wait_seconds <= 0:
        return "Started immediately."
    return f"Queued for {wait_seconds:.2f}s."


def _queue_kind_summary(queue_snapshot: dict[str, object], key: str) -> str:
    raw = queue_snapshot.get(key, {})
    if not isinstance(raw, dict) or not raw:
        return "None"
    parts = [f"{kind}: {count}" for kind, count in sorted(raw.items())]
    return ", ".join(parts)


def _queue_recent_rows(queue_snapshot: dict[str, object]) -> list[dict[str, str]]:
    rows = queue_snapshot.get("recent_jobs", [])
    if not isinstance(rows, list):
        return []
    return [
        {
            "ticket_id": str(row.get("ticket_id", "")),
            "job_kind": str(row.get("job_kind", "request")).replace("-", " "),
            "outcome": str(row.get("outcome", "queued")),
            "wait_seconds": f"{float(row.get('wait_seconds', 0.0) or 0.0):.2f}s",
            "finished_at": _format_created_at_label(row.get("finished_at") or row.get("started_at")),
        }
        for row in rows[:5]
        if isinstance(row, dict)
    ]


def _read_if_present(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _sanitize_ui_paths(value: object, settings) -> object:
    if isinstance(value, str):
        sanitized = value
        for raw, replacement in (
            (str(settings.base_dir), "<workspace>"),
            (str(Path.home()), "<home>"),
        ):
            if raw:
                sanitized = sanitized.replace(raw, replacement)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_ui_paths(item, settings) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_ui_paths(item, settings) for item in value)
    if isinstance(value, dict):
        return {key: _sanitize_ui_paths(item, settings) for key, item in value.items()}
    return value


def _paragraphs(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _current_path_with_query(request: Request) -> str:
    target = request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return target


def _safe_next_path(raw_target: str | None) -> str:
    target = (raw_target or "").strip()
    if not target:
        return "/"
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return "/"
    if not target.startswith("/"):
        return "/"
    return target


def _saved_session_visible_to_current_actor(
    request: Request,
    *,
    actor_key: str,
    class_space: str,
) -> bool:
    current_role = current_local_role(request)
    settings = request.app.state.settings
    if class_space != settings.class_space:
        return False
    if current_role.sees_all_sessions:
        return True
    return actor_key == current_actor_key(request)


def _saved_session_unavailable_status(
    *,
    title: str,
    retry_href: str,
    retry_label: str,
) -> dict[str, str]:
    return _status_block(
        title,
        "That saved entry is not available in this local role and class-space context.",
        tone="warn",
        action_href=retry_href,
        action_label=retry_label,
    )


def _safe_qa_return_href(request: Request, qa_id: int | None) -> str:
    if qa_id is None:
        return "/qa"
    entry = get_qa_history_entry(request.app.state.settings.db_path, qa_id)
    if entry is None:
        return f"/qa?qa_id={qa_id}"
    if not _saved_session_visible_to_current_actor(
        request,
        actor_key=str(entry.get("actor_key", "")),
        class_space=str(entry.get("class_space", "")),
    ):
        return "/qa"
    return f"/qa?qa_id={qa_id}"


def _role_options(current_role_id: str) -> list[dict[str, str]]:
    return [
        {
            "id": role.id,
            "label": role.label,
            "selected": "true" if role.id == current_role_id else "false",
        }
        for role in ROLE_CATALOG.values()
    ]


LANGUAGE_OPTIONS = {
    "auto": "Match question",
    "english": "English",
    "spanish": "Spanish",
    "french": "French",
    "swahili": "Swahili",
    "hindi": "Hindi",
    "arabic": "Arabic",
}


def _answer_language_options(selected: str = "auto") -> list[dict[str, str]]:
    normalized = selected if selected in LANGUAGE_OPTIONS else "auto"
    return [
        {
            "value": value,
            "label": label,
            "selected": "true" if value == normalized else "false",
        }
        for value, label in LANGUAGE_OPTIONS.items()
    ]


def _device_mode(llm_ready: bool) -> str:
    """Return a human-readable device mode label based on LLM availability."""
    return "Local" if llm_ready else "Light"


def _format_created_at_label(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "Indexed locally"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return "Indexed locally"

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
        return parsed.strftime("%Y-%m-%d %H:%M UTC")
    return parsed.strftime("%Y-%m-%d %H:%M")


def _document_rows(
    db_path: Path,
    *,
    class_space: str,
    highlight_document_id: int | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in list_documents(db_path, class_space=class_space):
        chunk_count = int(row.get("chunk_count") or 0)
        file_type = str(row.get("file_type", "")).lower()
        document_id = int(row.get("id") or 0)
        is_recent_upload = highlight_document_id is not None and document_id == highlight_document_id
        uploader_role = resolve_local_role(str(row.get("uploader_role", "teacher")))
        rows.append(
            {
                **row,
                "document_id": document_id,
                "file_type_label": file_type.upper() if file_type else "FILE",
                "chunk_label": f"{chunk_count} chunk" if chunk_count == 1 else f"{chunk_count} chunks",
                "indexed_at_label": _format_created_at_label(row.get("created_at")),
                "indexed_status": "Just indexed" if is_recent_upload else "Indexed",
                "is_recent_upload": is_recent_upload,
                "visibility_label": "Class-shared material",
                "uploader_role_label": uploader_role.short_label,
                "class_space_label": str(row.get("class_space", "")).replace("-", " "),
            }
        )
    return rows


def _runtime_status_block(title: str, summary: str, tone: str = "default") -> dict[str, str]:
    return {
        "title": title,
        "summary": summary,
        "tone": tone,
    }


def _build_runtime_statuses(request: Request, *, llm_ready: bool, llm_message: str) -> dict[str, dict[str, str]]:
    settings = request.app.state.settings
    semantic_index = getattr(request.app.state, "semantic_index", None)
    if semantic_index is None:
        semantic_index = SQLiteSemanticIndex(
            db_path=settings.db_path,
            embedding_provider=create_embedding_provider(
                enabled=settings.semantic_enabled,
                base_url=settings.accesslab_ollama_url,
                model_name=settings.semantic_embedding_model,
            ),
            class_space=settings.class_space,
        )
    ocr_backend = getattr(request.app.state, "ocr_backend", None)
    ensure_semantic_backfill(semantic_index)
    retrieval_diagnostics = build_retrieval_diagnostics(settings, semantic_index)

    if llm_ready:
        local_status = _runtime_status_block(
            "Gemma 4 ready",
            llm_message
            or f"{settings.accesslab_model} is ready on the {settings.runtime_backend_display.lower()}.",
            "success",
        )
    else:
        local_status = _runtime_status_block(
            "Gemma 4 needs setup",
            llm_message
            or f"{settings.accesslab_model} is unavailable on the {settings.runtime_backend_display.lower()}.",
            "warn",
        )

    if retrieval_diagnostics.actual_mode == "hybrid":
        retrieval_status = _runtime_status_block(
            "Hybrid retrieval ready",
            (
                f"{retrieval_diagnostics.lexical_backend_label} + "
                f"{settings.semantic_model_family} ({settings.semantic_embedding_model}). "
                f"{retrieval_diagnostics.index_status.summary}"
            ),
            "success",
        )
    elif retrieval_diagnostics.actual_mode == "semantic":
        retrieval_status = _runtime_status_block(
            "Semantic retrieval ready",
            retrieval_diagnostics.semantic.detail,
            "success",
        )
    else:
        retrieval_status = _runtime_status_block(
            "SQLite FTS5 only",
            (
                f"{retrieval_diagnostics.semantic.label}: "
                f"{retrieval_diagnostics.semantic.detail}"
            ),
            "default" if settings.retrieval_mode == "lexical" else "warn",
        )

    if settings.ocr_enabled == "off":
        ocr_status = _runtime_status_block(
            "OCR fallback off",
            "Scanned PDFs will not use OCR on this device.",
            "default",
        )
    elif ocr_backend is not None and ocr_backend.is_available():
        ocr_status = _runtime_status_block(
            "OCR fallback ready",
            ocr_backend.describe(),
            "success",
        )
    else:
        reason = (
            ocr_backend.unavailable_reason()
            if ocr_backend is not None
            else "OCR backend is not configured."
        )
        ocr_status = _runtime_status_block(
            "OCR fallback optional",
            reason or "OCR extras are not available.",
            "warn",
        )

    return {
        "local_status": local_status,
        "retrieval_status": retrieval_status,
        "ocr_status": ocr_status,
        "retrieval_diagnostics": retrieval_diagnostics,
    }


def _status_block(
    title: str,
    body: str,
    *,
    tone: str = "default",
    action_href: str | None = None,
    action_label: str | None = None,
) -> dict[str, str]:
    return {
        "title": title,
        "body": body,
        "tone": tone,
        "action_href": action_href or "",
        "action_label": action_label or "",
    }


def _notice_block(
    title: str,
    body: str,
    *,
    tone: str = "info",
    action_href: str | None = None,
    action_label: str | None = None,
) -> dict[str, str]:
    return {
        "title": title,
        "body": body,
        "tone": tone,
        "action_href": action_href or "",
        "action_label": action_label or "",
    }


def _search_mode_label(retrieval_diagnostics) -> str:
    return retrieval_diagnostics.actual_mode_label


def _recent_question_rows(
    request: Request,
    *,
    role_id: str,
    actor_key: str,
    sees_all_sessions: bool,
) -> list[dict[str, str]]:
    db_path = request.app.state.settings.db_path
    class_space = request.app.state.settings.class_space
    rows = list_recent_qa_history(
        db_path,
        actor_role=None if sees_all_sessions else role_id,
        actor_key=None if sees_all_sessions else actor_key,
        class_space=class_space,
        limit=5,
    )
    return [
        {
            "href": f"/qa?qa_id={int(row['id'])}",
            "title": str(row.get("question", "Saved question")),
            "kind": "Explain materials",
            "saved_at": _format_created_at_label(row.get("created_at")),
            "role_label": resolve_local_role(str(row.get("actor_role", "learner"))).short_label,
            "actor_label": actor_label(
                actor_key=str(row.get("actor_key", "")),
                actor_role=str(row.get("actor_role", "learner")),
            ),
            "state_label": str(row.get("result_mode", "answered")).replace("_", " "),
            "detail_label": str(row.get("retrieval_mode_label", "Lexical only")),
        }
        for row in rows
    ]


def _code_session_title(row: dict[str, object]) -> str:
    session_data = row.get("session_data")
    if isinstance(session_data, dict):
        instruction = str(session_data.get("instruction", "")).strip()
        if instruction:
            return instruction

    original_code = str(row.get("original_code", ""))
    for line in original_code.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:80]
    return "Saved Python review"


def _recent_code_rows(
    request: Request,
    *,
    role_id: str,
    actor_key: str,
    sees_all_sessions: bool,
) -> list[dict[str, str]]:
    db_path = request.app.state.settings.db_path
    class_space = request.app.state.settings.class_space
    rows = list_recent_code_sessions(
        db_path,
        actor_role=None if sees_all_sessions else role_id,
        actor_key=None if sees_all_sessions else actor_key,
        class_space=class_space,
        limit=5,
    )
    return [
        {
            "href": f"/code?session_id={int(row['id'])}",
            "title": _code_session_title(row),
            "kind": "Fix Python code",
            "saved_at": _format_created_at_label(row.get("created_at")),
            "role_label": resolve_local_role(str(row.get("actor_role", "learner"))).short_label,
            "actor_label": actor_label(
                actor_key=str(row.get("actor_key", "")),
                actor_role=str(row.get("actor_role", "learner")),
            ),
            "state_label": "saved review",
            "detail_label": "Local rerun",
        }
        for row in rows
    ]


def _recent_activity_rows(request: Request) -> list[dict[str, str]]:
    settings = request.app.state.settings
    rows = list_recent_classroom_activity(
        settings.db_path,
        class_space=settings.class_space,
        limit=8,
    )
    return [
        {
            "href": str(row.get("href", "/")),
            "title": str(row.get("title", "Saved activity")),
            "activity_type": "Grounded answer" if row.get("activity_type") == "qa" else "Python review",
            "saved_at": _format_created_at_label(row.get("created_at")),
            "actor_label": actor_label(
                actor_key=str(row.get("actor_key", "")),
                actor_role=str(row.get("actor_role", "learner")),
            ),
            "state_label": str(row.get("state_label", "")).replace("_", " "),
            "detail_label": str(row.get("detail_label", "")),
        }
        for row in rows
    ]


def _format_sandbox_profile_label(profile: str) -> str:
    labels = {
        "audit-posix-linux": "POSIX + memory limits",
        "audit-posix": "POSIX limits",
        "audit-only": "Best-effort sandbox",
        "none": "Local runner",
    }
    return labels.get(profile, profile.replace("-", " ").title())


def _can_label_saved_sessions(current_role) -> bool:
    return current_role.id in {"teacher", "admin"}


def _session_label_rows(
    db_path: Path,
    *,
    source_type: str,
    source_id: int | None,
    class_space: str,
) -> list[dict[str, str]]:
    if source_id is None:
        return []
    rows = list_session_labels(
        db_path,
        source_type=source_type,
        source_id=source_id,
        class_space=class_space,
        limit=12,
    )
    return [
        {
            "label": str(row.get("label", "")),
            "label_display": session_label_display(str(row.get("label", ""))),
            "note": str(row.get("note", "")),
            "actor_role": str(row.get("actor_role", "")),
            "created_at": _format_created_at_label(row.get("created_at")),
        }
        for row in rows
    ]


def _training_capture_summary(settings) -> dict[str, object]:
    with db_connection(settings.db_path) as connection:
        capture_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM training_capture_events WHERE class_space = ?",
                (settings.class_space,),
            ).fetchone()[0]
        )
        label_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM session_labels WHERE class_space = ?",
                (settings.class_space,),
            ).fetchone()[0]
        )
    recent_captures = list_training_capture_events(
        settings.db_path,
        class_space=settings.class_space,
        limit=5,
    )
    return {
        "capture_enabled_display": settings.training_capture_display,
        "capture_enabled_summary": settings.training_capture_summary,
        "captured_examples": capture_count,
        "session_labels": label_count,
        "recent_captures": [
            {
                "capture_kind": str(row.get("capture_kind", "")).replace("-", " "),
                "source_type": str(row.get("source_type", "")),
                "source_id": str(row.get("source_id", "")),
                "actor_role": str(row.get("actor_role", "")),
                "created_at": _format_created_at_label(row.get("created_at")),
            }
            for row in recent_captures
        ],
    }


def _artifact_status_row(
    settings,
    title: str,
    path: Path,
    *,
    command: str,
    max_age_days: int | None = 14,
) -> dict[str, str]:
    relative_path = str(path.relative_to(settings.base_dir))
    if not path.exists():
        return {
            "title": title,
            "path": relative_path,
            "status": "Missing",
            "tone": "error",
            "detail": f"Run `{command}` to generate this artifact.",
            "command": command,
            "modified_at": "",
        }

    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    modified_at = _format_created_at_label(modified.isoformat())
    age_days = max(0, (datetime.now(timezone.utc) - modified).days)
    if max_age_days is not None and age_days > max_age_days:
        return {
            "title": title,
            "path": relative_path,
            "status": "Stale",
            "tone": "warn",
            "detail": f"Last updated {modified_at}. Regenerate with `{command}`.",
            "command": command,
            "modified_at": modified_at,
        }
    return {
        "title": title,
        "path": relative_path,
        "status": "Ready",
        "tone": "success",
        "detail": f"Last updated {modified_at}.",
        "command": command,
        "modified_at": modified_at,
    }


def _artifact_snapshot_rows(settings) -> list[dict[str, str]]:
    reports_dir = settings.base_dir / "reports"
    rows = [
        ("Operator preflight", reports_dir / "operator_preflight_latest.md", "make preflight", 14),
        ("System snapshot", reports_dir / "system_status_snapshot_latest.json", "make preflight", 14),
        ("Deployment snapshot", reports_dir / "deployment_mode_snapshot_latest.md", "make preflight", 14),
        ("Benchmark summary", reports_dir / "accesslab_benchmark_summary.md", "make benchmark-summary", 14),
        ("Benchmark highlights", reports_dir / "accesslab_benchmark_highlights.md", "make benchmark-summary", 14),
        ("Code runner hardening smoke", reports_dir / "code_runner_hardening_smoke_latest.md", "make smoke-code-runner", 14),
        ("Accessibility smoke", reports_dir / "a11y_smoke_latest.md", "make smoke-a11y", 14),
        ("Semantic retrieval proof", reports_dir / "semantic_retrieval_proof_latest.md", "make smoke-retrieval", 14),
        ("EmbeddingGemma setup", reports_dir / "embeddinggemma_setup_latest.md", "make setup-semantic", 30),
        ("OCR decision memo", reports_dir / "ocr_decision_memo.md", "make smoke-ocr", None),
        ("School-box demo proof", reports_dir / "school_box_demo_proof_latest.md", "make school-box-demo-proof", 14),
        ("School-box load proof", reports_dir / "school_box_load_latest.md", "make school-box-load", 14),
        ("Judge proof index", reports_dir / "judge" / "latest" / "proof_index.md", "make judge-bundle", 14),
    ]
    return [
        _artifact_status_row(
            settings,
            title,
            path,
            command=command,
            max_age_days=max_age_days,
        )
        for title, path, command, max_age_days in rows
    ]


def _preflight_check(preflight: dict[str, object], check_id: str) -> dict[str, object]:
    for check in preflight.get("checks", []):
        if isinstance(check, dict) and check.get("id") == check_id:
            return check
    return {
        "id": check_id,
        "label": check_id.replace("-", " "),
        "status": "fail",
        "summary": "Missing from preflight.",
        "detail": "Run `make preflight` and reload this dashboard.",
    }


def _tone_from_status(status: str) -> str:
    return {
        "pass": "success",
        "ready": "success",
        "present": "success",
        "info": "default",
        "warn": "warn",
        "stale": "warn",
        "missing": "error",
        "fail": "error",
        "blocked": "error",
    }.get((status or "").strip().lower(), "default")


def _preflight_proof_card(
    title: str,
    check: dict[str, object],
    *,
    pass_label: str = "Ready",
) -> dict[str, str]:
    status = str(check.get("status", "fail"))
    display_status = {
        "pass": pass_label,
        "warn": "Attention",
        "fail": "Blocked",
        "info": "Info",
    }.get(status, "Attention")
    return {
        "title": title,
        "status": display_status,
        "tone": _tone_from_status(status),
        "body": str(check.get("summary") or check.get("detail") or "No detail recorded."),
        "detail": str(check.get("detail") or ""),
        "path": "",
        "command": "make preflight",
    }


def _artifact_by_title(rows: list[dict[str, str]], title: str) -> dict[str, str]:
    for row in rows:
        if row["title"] == title:
            return row
    return {
        "title": title,
        "status": "Missing",
        "tone": "error",
        "detail": "Artifact is not configured.",
        "path": "",
        "command": "make judge-bundle",
        "modified_at": "",
    }


def _artifact_proof_card(
    title: str,
    row: dict[str, str],
    *,
    body: str,
) -> dict[str, str]:
    return {
        "title": title,
        "status": row["status"],
        "tone": row["tone"],
        "body": body if row["status"] == "Ready" else row["detail"],
        "detail": row["detail"],
        "path": row["path"],
        "command": row["command"],
    }


def _build_proof_scorecard_rows(
    *,
    preflight: dict[str, object],
    retrieval_diagnostics,
    artifact_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    storage = _preflight_check(preflight, "storage")
    database = _preflight_check(preflight, "database")
    local_status = "pass" if storage.get("status") == "pass" and database.get("status") == "pass" else "fail"
    local_card = {
        "title": "Local/offline proof",
        "status": "Ready" if local_status == "pass" else "Attention",
        "tone": _tone_from_status(local_status),
        "body": "Writable local storage and SQLite checks passed." if local_status == "pass" else "Local storage or database preflight needs attention.",
        "detail": f"{storage.get('summary', '')} {database.get('summary', '')}".strip(),
        "path": "",
        "command": "make preflight",
    }
    retrieval_check = _preflight_check(preflight, "semantic-retrieval")
    retrieval_card = _preflight_proof_card(
        "Retrieval status",
        retrieval_check,
        pass_label="Ready",
    )
    retrieval_card["body"] = str(getattr(retrieval_diagnostics, "actual_mode_label", "Retrieval status unavailable."))

    return [
        local_card,
        _preflight_proof_card("Ollama Gemma 4 runtime", _preflight_check(preflight, "generation-runtime")),
        retrieval_card,
        _artifact_proof_card(
            "Grounded citations",
            _artifact_by_title(artifact_rows, "School-box demo proof"),
            body="Latest school-box demo proof includes citation-backed QA and source inspection.",
        ),
        _artifact_proof_card(
            "Abstention behavior",
            _artifact_by_title(artifact_rows, "School-box demo proof"),
            body="Latest school-box demo proof includes the no-match abstention path.",
        ),
        _artifact_proof_card(
            "Code runner boundary",
            _artifact_by_title(artifact_rows, "Code runner hardening smoke"),
            body="Latest hardening smoke exercised blocked imports/calls and constrained execution behavior.",
        ),
        _artifact_proof_card(
            "Accessibility smoke",
            _artifact_by_title(artifact_rows, "Accessibility smoke"),
            body="Latest accessibility smoke exercised toolbar, focus, source, and keyboard paths.",
        ),
        _artifact_proof_card(
            "School-box load",
            _artifact_by_title(artifact_rows, "School-box load proof"),
            body="Latest local synthetic load proof exercised queue behavior for a shared classroom host.",
        ),
        _artifact_proof_card(
            "Benchmark summary",
            _artifact_by_title(artifact_rows, "Benchmark summary"),
            body="Latest benchmark summary captures the local evaluation snapshot.",
        ),
        _artifact_proof_card(
            "Judge bundle freshness",
            _artifact_by_title(artifact_rows, "Judge proof index"),
            body="Judge-facing proof index exists and was generated recently.",
        ),
    ]


def _file_contains(path: Path, *patterns: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return all(pattern in text for pattern in patterns)


def _feature_proof_card(title: str, present: bool, *, body: str, missing_body: str) -> dict[str, str]:
    return {
        "title": title,
        "status": "Present" if present else "Missing",
        "tone": "success" if present else "error",
        "body": body if present else missing_body,
        "detail": "",
        "path": "",
        "command": "make smoke-a11y",
    }


def _build_accessibility_proof_rows(settings, artifact_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    templates_dir = settings.templates_dir
    static_dir = settings.static_dir
    a11y_artifact = _artifact_by_title(artifact_rows, "Accessibility smoke")
    return [
        _feature_proof_card(
            "Keyboard navigation",
            _file_contains(templates_dir / "base.html", "skip-link", "main-content")
            and _file_contains(static_dir / "styles.css", ":focus-visible"),
            body="Skip link, main landmark, and visible focus styling are present.",
            missing_body="Skip link or visible focus styling was not found in the UI shell.",
        ),
        _feature_proof_card(
            "Screen-reader labels",
            _file_contains(templates_dir / "qa.html", "aria-label")
            and _file_contains(templates_dir / "source.html", "aria-label"),
            body="Primary QA and source templates include screen-reader labels.",
            missing_body="Expected ARIA labels were not found in QA/source templates.",
        ),
        _feature_proof_card(
            "High-contrast mode",
            _file_contains(templates_dir / "base.html", 'data-a11y-toggle="high-contrast"'),
            body="High-contrast toggle is exposed in the accessibility toolbar.",
            missing_body="High-contrast toggle is not exposed in the accessibility toolbar.",
        ),
        _feature_proof_card(
            "Large-text mode",
            _file_contains(templates_dir / "base.html", 'data-a11y-toggle="large-text"'),
            body="Large-text toggle is exposed in the accessibility toolbar.",
            missing_body="Large-text toggle is not exposed in the accessibility toolbar.",
        ),
        _feature_proof_card(
            "Plain-language mode",
            _file_contains(templates_dir / "qa.html", "inclusive_plain_language")
            or _file_contains(templates_dir / "code.html", "simplify"),
            body="Inclusive classroom controls expose plain-language mode without mutating the saved question.",
            missing_body="Plain-language controls were not found in learner flows.",
        ),
        _feature_proof_card(
            "Read aloud",
            _file_contains(static_dir / "app.js", "speechSynthesis"),
            body="Read-aloud controls use local browser speech synthesis when available.",
            missing_body="Read-aloud support was not found in frontend JavaScript.",
        ),
        {
            "title": "Captions / transcript",
            "status": "Owner task",
            "tone": "warn",
            "body": "The app shows textual content; the final demo video still needs captions or a transcript from the owner.",
            "detail": "",
            "path": "",
            "command": "docs/accessibility_submission_notes.md",
        },
        _artifact_proof_card(
            "Accessibility smoke run",
            a11y_artifact,
            body="Latest smoke artifact recorded keyboard/focus/accessibility checks.",
        ),
    ]


def _json_loads(value: object, default: object) -> object:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _evidence_strength(result: QAResult) -> str:
    if result.result_mode == "no_match" or not result.citations:
        return "No local source found"
    if result.result_mode == "weak_match" or result.unsure:
        return "Not enough evidence"
    return "Strong match"


def _qa_trust_rows(settings, result: QAResult) -> list[dict[str, str]]:
    return [
        {"label": "Model", "value": settings.accesslab_model, "summary": settings.generation_model_family},
        {"label": "Retrieval mode", "value": result.retrieval_mode_label or settings.retrieval_mode_display, "summary": "Lexical, semantic, or hybrid local search."},
        {"label": "Evidence strength", "value": _evidence_strength(result), "summary": result.result_mode.replace("_", " ")},
        {"label": "Citation count", "value": str(len(result.citations)), "summary": "Each citation opens a local source view."},
        {"label": "Source scope", "value": "local classroom only", "summary": settings.class_space_display},
        {"label": "Internet used", "value": "no", "summary": "No web retrieval or cloud QA fallback."},
        {"label": "Limit", "value": "may be incomplete", "summary": "Answers depend on the uploaded local materials."},
    ]


def _code_trust_rows(settings, result: CodeTutorResult, execution_backend) -> list[dict[str, str]]:
    timeout_seconds = getattr(execution_backend, "timeout_seconds", 5)
    sandbox_note = result.initial_run.sandbox_note or str(getattr(execution_backend, "sandbox_note", ""))
    return [
        {"label": "Model", "value": settings.accesslab_model, "summary": settings.generation_model_family},
        {"label": "Timeout", "value": f"{timeout_seconds}s", "summary": "Each local run has a short timeout."},
        {"label": "Network", "value": "blocked", "summary": "Socket imports and runtime network access are blocked."},
        {"label": "Dangerous imports", "value": "blocked", "summary": "Examples include os, socket, subprocess, shutil, and ctypes."},
        {"label": "Subprocess", "value": "blocked", "summary": "Child process APIs are denied for submitted code."},
        {"label": "Sandbox profile", "value": result.initial_run.sandbox_profile or "best effort", "summary": sandbox_note},
        {"label": "Limit", "value": "not production sandbox", "summary": "This is a local beginner-code demo runner."},
    ]


def _categorize_code_bug(session_data: dict[str, object], original_code: str) -> str:
    text = " ".join(
        str(session_data.get(key, ""))
        for key in ("diagnosis", "evidence", "next_fix")
    ).lower()
    initial_run = session_data.get("initial_run")
    if isinstance(initial_run, dict):
        text += " " + str(initial_run.get("stderr", "")).lower()
    code_text = original_code.lower()
    if "timed out" in text or "infinite" in text or "while true" in code_text:
        return "Timeout or infinite loop"
    if "blocked" in text or "sandbox" in text:
        return "Sandbox policy"
    if "nameerror" in text or "not defined" in text:
        return "Missing or wrong name"
    if "assert" in text or "expected" in text or "test gets" in text:
        return "Wrong returned value"
    if "syntaxerror" in text or "syntax" in text:
        return "Syntax error"
    if "loop" in text or "range" in text or "index" in text:
        return "Loop or indexing bug"
    return "Other beginner bug"


def _teacher_class_summary(settings) -> dict[str, object]:
    with db_connection(settings.db_path) as connection:
        qa_rows = connection.execute(
            """
            SELECT id, question, result_mode, unsure, citation_list, retrieval_mode_label, actor_role, actor_key, created_at
            FROM qa_history
            WHERE class_space = ?
            ORDER BY id DESC
            LIMIT 80
            """,
            (settings.class_space,),
        ).fetchall()
        code_rows = connection.execute(
            """
            SELECT id, original_code, patched_test_result, session_data, actor_role, actor_key, created_at
            FROM code_sessions
            WHERE class_space = ?
            ORDER BY id DESC
            LIMIT 80
            """,
            (settings.class_space,),
        ).fetchall()
        document_rows = connection.execute(
            """
            SELECT file_name, file_type, created_at
            FROM documents
            WHERE class_space = ?
            ORDER BY id DESC
            LIMIT 80
            """,
            (settings.class_space,),
        ).fetchall()

    question_counts: dict[str, dict[str, object]] = {}
    weak_rows: list[dict[str, str]] = []
    document_use_counts: dict[str, int] = {}
    for row in qa_rows:
        question = str(row["question"])
        key = question.strip().lower()
        if key:
            entry = question_counts.setdefault(
                key,
                {"question": question, "count": 0, "href": f"/qa?qa_id={int(row['id'])}"},
            )
            entry["count"] = int(entry["count"]) + 1
        citations = _json_loads(row["citation_list"], [])
        if isinstance(citations, list):
            for citation in citations:
                if isinstance(citation, dict):
                    source_file = str(citation.get("source_file", "")).strip()
                    if source_file:
                        document_use_counts[source_file] = document_use_counts.get(source_file, 0) + 1
        if row["result_mode"] in {"weak_match", "no_match"} or bool(row["unsure"]):
            weak_rows.append(
                {
                    "href": f"/qa?qa_id={int(row['id'])}",
                    "question": question,
                    "state": str(row["result_mode"]).replace("_", " "),
                    "saved_at": _format_created_at_label(row["created_at"]),
                }
            )

    bug_counts: dict[str, int] = {}
    repair_rows: list[dict[str, str]] = []
    for row in code_rows:
        session_data = _json_loads(row["session_data"], {})
        if not isinstance(session_data, dict):
            session_data = {}
        category = _categorize_code_bug(session_data, str(row["original_code"]))
        bug_counts[category] = bug_counts.get(category, 0) + 1
        if bool(session_data.get("rerun_success")):
            repair_rows.append(
                {
                    "href": f"/code?session_id={int(row['id'])}",
                    "title": _code_session_title({"original_code": row["original_code"], "session_data": session_data}),
                    "saved_at": _format_created_at_label(row["created_at"]),
                }
            )

    if not document_use_counts:
        for row in document_rows:
            document_use_counts[str(row["file_name"])] = 0

    top_questions = sorted(
        question_counts.values(),
        key=lambda item: (-int(item["count"]), str(item["question"]).lower()),
    )[:5]
    bug_categories = [
        {"category": key, "count": count}
        for key, count in sorted(bug_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]
    documents_used = [
        {"file_name": key, "count": count}
        for key, count in sorted(document_use_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]
    return {
        "qa_count": len(qa_rows),
        "code_count": len(code_rows),
        "document_count": len(document_rows),
        "top_questions": top_questions,
        "weak_questions": weak_rows[:5],
        "bug_categories": bug_categories,
        "recent_repairs": repair_rows[:5],
        "documents_used": documents_used,
        "export_href": "/teacher/report.csv",
    }


def _teacher_report_csv(settings) -> str:
    summary = _teacher_class_summary(settings)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["AccessLab class report", settings.class_space_display])
    writer.writerow(["Generated at", datetime.now(timezone.utc).isoformat()])
    writer.writerow([])
    writer.writerow(["Metric", "Value"])
    writer.writerow(["Grounded answers", summary["qa_count"]])
    writer.writerow(["Code assists", summary["code_count"]])
    writer.writerow(["Documents", summary["document_count"]])
    writer.writerow([])
    writer.writerow(["Top student questions", "Count"])
    for row in summary["top_questions"]:
        writer.writerow([row["question"], row["count"]])
    writer.writerow([])
    writer.writerow(["Weak/no-match questions", "State", "Saved at"])
    for row in summary["weak_questions"]:
        writer.writerow([row["question"], row["state"], row["saved_at"]])
    writer.writerow([])
    writer.writerow(["Common code bug categories", "Count"])
    for row in summary["bug_categories"]:
        writer.writerow([row["category"], row["count"]])
    writer.writerow([])
    writer.writerow(["Documents used most often", "Citation count"])
    for row in summary["documents_used"]:
        writer.writerow([row["file_name"], row["count"]])
    return output.getvalue()


def _read_json_artifact(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _latest_generation_metrics(settings) -> dict[str, str]:
    proof = _read_json_artifact(settings.base_dir / "reports" / "school_box_demo_proof_latest.json")
    qa_profile = (
        proof.get("scenario", {})
        if isinstance(proof.get("scenario"), dict)
        else {}
    ).get("learner_grounded_question", {})
    if isinstance(qa_profile, dict):
        profile = qa_profile.get("profile", {})
    else:
        profile = {}
    if not isinstance(profile, dict):
        profile = {}
    total = profile.get("total_seconds")
    ttft = profile.get("ttft_seconds")
    eval_duration = profile.get("eval_duration_sec")
    eval_count = profile.get("eval_count")
    tokens_per_second = ""
    try:
        if eval_duration and eval_count:
            tokens_per_second = f"{float(eval_count) / float(eval_duration):.2f}"
    except (TypeError, ValueError, ZeroDivisionError):
        tokens_per_second = ""
    return {
        "last_generation_latency": f"{float(total):.2f}s" if isinstance(total, (int, float)) else "No recent model-backed run recorded",
        "time_to_first_token": f"{float(ttft):.2f}s" if isinstance(ttft, (int, float)) else "Not recorded",
        "tokens_per_second": tokens_per_second or "Not recorded",
    }


def _ollama_proof_rows(settings, retrieval_diagnostics) -> list[dict[str, str]]:
    available_models, listing_message = list_ollama_model_names(settings.accesslab_ollama_url)
    available_gemma_models = [model for model in available_models if model in ALLOWED_GEMMA4_MODELS]
    metrics = _latest_generation_metrics(settings)
    return [
        {"label": "Ollama URL", "value": settings.accesslab_ollama_url, "summary": listing_message},
        {"label": "Active model", "value": settings.accesslab_model, "summary": settings.deployment_profile_display},
        {"label": "Available Gemma models", "value": ", ".join(available_gemma_models) or "Not visible from Ollama right now", "summary": "Allowed: " + ", ".join(sorted(ALLOWED_GEMMA4_MODELS))},
        {"label": "Strong/weak mapping", "value": f"strong={PROFILE_MODELS['strong']}; weak={PROFILE_MODELS['weak']}", "summary": "Profile-pinned local Gemma 4 pairing."},
        {"label": "EmbeddingGemma", "value": retrieval_diagnostics.semantic.label, "summary": retrieval_diagnostics.semantic.summary},
        {"label": "Last generation latency", "value": metrics["last_generation_latency"], "summary": "From latest local demo proof when available."},
        {"label": "Time-to-first-token", "value": metrics["time_to_first_token"], "summary": "Ollama-native streaming timing when captured."},
        {"label": "Tokens/sec", "value": metrics["tokens_per_second"], "summary": "Derived from Ollama eval count and eval duration."},
        {"label": "Cloud API key", "value": "not required", "summary": "No cloud model fallback is configured."},
    ]


def _workspace_runtime_notices(
    *,
    active_view: str,
    local_status: dict[str, str],
    retrieval_status: dict[str, str],
    ocr_status: dict[str, str],
) -> list[dict[str, str]]:
    notices: list[dict[str, str]] = []

    if active_view == "home":
        if local_status["tone"] == "warn":
            notices.append(
                _notice_block(
                    "Gemma 4 setup needed",
                    local_status["summary"],
                    tone="warn",
                )
            )
        if retrieval_status["tone"] == "warn":
            notices.append(
                _notice_block(
                    "Search: lexical only",
                    retrieval_status["summary"],
                    tone="warn",
                )
            )
        if ocr_status["tone"] == "warn":
            notices.append(
                _notice_block(
                    "Scanned PDFs may need OCR extras",
                    ocr_status["summary"],
                    tone="warn",
                )
            )
        return notices

    if active_view == "qa":
        if local_status["tone"] == "warn":
            notices.append(
                _notice_block(
                    "Model setup needed",
                    local_status["summary"],
                    tone="warn",
                )
            )
        if retrieval_status["tone"] == "warn":
            notices.append(
                _notice_block(
                    "Current search mode: lexical only",
                    retrieval_status["summary"],
                    tone="info",
                )
            )
        return notices

    if active_view == "code" and local_status["tone"] == "warn":
        notices.append(
            _notice_block(
                "Code explanations need Gemma 4",
                local_status["summary"],
                tone="warn",
            )
        )
    return notices


def _upload_feedback(ingest_result: IngestSummary) -> dict[str, str]:
    tone = "success"
    title = "File indexed"
    if ingest_result.ocr_status in {"unavailable", "applied_no_text", "error"}:
        tone = "warn"
        title = "File indexed with OCR limits"
    body = (
        f"{ingest_result.file_name}: {ingest_result.chunks_created} searchable "
        f"{'section' if ingest_result.chunks_created == 1 else 'sections'}."
    )
    if ingest_result.ocr_status == "applied":
        body += f" OCR read {ingest_result.ocr_pages_applied} scanned page(s)."
    elif ingest_result.ocr_status == "unavailable":
        body += " Some scanned pages were skipped."
    elif ingest_result.ocr_status == "applied_no_text":
        body += " OCR ran on scanned pages but did not recover usable text."
    elif ingest_result.ocr_status == "error":
        body += " OCR hit an error on at least one scanned page."
    return _notice_block(
        title,
        body,
        tone=tone,
        action_href="/qa",
        action_label="Explain materials",
    )


def _upload_error_status(message: str) -> dict[str, str]:
    cleaned = message.strip() or "AccessLab could not index that file."
    if cleaned == "Choose a PDF, TXT, or MD file with readable text.":
        return _status_block(
            "Choose a local document first",
            cleaned,
            tone="warn",
        )
    if cleaned.startswith("Unsupported file type."):
        return _status_block(
            "This file type is not supported",
            cleaned,
            tone="warn",
        )
    if cleaned.startswith("No readable text was found in that file."):
        if "OCR is unavailable" in cleaned or "requirements-ocr.txt" in cleaned:
            return _status_block(
                "This scanned file needs OCR support",
                cleaned,
                tone="warn",
                action_href="#workspace-status",
                action_label="Review local setup",
            )
        return _status_block(
            "No readable text could be indexed",
            cleaned,
            tone="warn",
        )
    return _status_block(
        "Document could not be indexed",
        cleaned,
        tone="error",
    )


def _ingest_status_message(ingest_result: IngestSummary) -> str:
    parts = [
        f"Uploaded {ingest_result.file_name}: {ingest_result.chunks_created} section(s)."
    ]
    if ingest_result.ocr_status == "applied":
        parts.append(f"OCR read {ingest_result.ocr_pages_applied} page(s).")
    elif ingest_result.ocr_status == "unavailable":
        parts.append("Some scanned pages could not be OCR'd locally.")
    elif ingest_result.ocr_status == "applied_no_text":
        parts.append("OCR ran on the scanned pages but did not recover usable text.")
    elif ingest_result.ocr_status == "error":
        parts.append("OCR hit an error on at least one scanned page.")
    return " ".join(parts)


def _qa_result_notice(result: QAResult) -> dict[str, str] | None:
    if result.result_mode == "no_match":
        return _notice_block(
            "No close evidence match",
            result.more_detail or "Try a more specific question or upload the worksheet page that contains the answer.",
            tone="warn",
            action_href="/",
            action_label="Add materials",
        )
    if result.result_mode == "weak_match":
        return _notice_block(
            "Weak match",
            "Review the evidence before relying on this answer.",
            tone="warn",
        )
    if result.result_mode == "model_unavailable":
        return _notice_block(
            "Gemma 4 unavailable",
            result.more_detail or "Start the configured Gemma 4 model and try again.",
            tone="warn",
        )
    if result.unsure:
        return _notice_block(
            "Review evidence",
            "This answer is uncertain.",
            tone="warn",
        )
    return None


def _qa_evidence_empty_state(
    *,
    has_documents: bool,
    qa_result: QAResult | None,
) -> dict[str, str]:
    if not has_documents:
        return {
            "title": "No materials available yet.",
            "body": "Upload a worksheet or notes first.",
            "action_href": "/",
            "action_label": "Go to Workspace",
        }
    if qa_result is not None and qa_result.result_mode == "no_match":
        return {
            "title": "No evidence was retrieved for this question.",
            "body": "Try a more specific question or upload the exact worksheet page you want explained.",
            "action_href": "/",
            "action_label": "Add another material",
        }
    return {
        "title": "Evidence will appear here after you ask a question.",
        "body": "Citations will link here.",
        "action_href": "",
        "action_label": "",
    }


def _execution_status_label(result: ExecutionResult) -> str:
    if result.denied_by_policy:
        return "blocked by policy"
    if result.status == "blocked":
        return "blocked"
    if result.timed_out or result.status == "timeout":
        return "timed out"
    if result.status == "not_run":
        return "not run"
    return result.status


def _code_result_notice(result: CodeTutorResult) -> dict[str, str] | None:
    if result.result_mode == "test_mismatch":
        return _notice_block(
            "Tests do not match this code",
            "Clear the optional tests or make them import names defined in the submitted code.",
            tone="warn",
        )
    if result.result_mode == "blocked":
        return _notice_block(
            "Execution blocked by local sandbox policy",
            "Remove restricted imports or blocked operations, then retry.",
            tone="warn",
        )
    if result.result_mode == "model_unavailable":
        return _notice_block(
            "Code ran, but explanation needs Gemma 4",
            result.next_fix,
            tone="warn",
        )
    if result.initial_run.timed_out or result.initial_run.status == "timeout":
        return _notice_block(
            "Original run timed out",
            "Add a stopping condition or simplify the code, then try again.",
            tone="warn",
        )
    return None


def _patched_run_view(result: CodeTutorResult) -> dict[str, str]:
    run = result.patched_run
    if result.result_mode == "blocked" or run.status == "not_run":
        return {
            "tone": "warn",
            "verdict": "No rerun attempted",
            "status_label": _execution_status_label(run),
            "summary": run.combined_output or run.stderr or "AccessLab did not rerun the patch.",
        }
    if run.denied_by_policy or run.status == "blocked":
        return {
            "tone": "warn",
            "verdict": "Patched run was blocked",
            "status_label": _execution_status_label(run),
            "summary": run.combined_output or run.stderr or "The patched code was blocked before rerun.",
        }
    if run.timed_out or run.status == "timeout":
        return {
            "tone": "warn",
            "verdict": "Patched run timed out",
            "status_label": _execution_status_label(run),
            "summary": run.combined_output or run.stderr or "Execution timed out.",
        }
    if run.passed:
        return {
            "tone": "success",
            "verdict": "Passed local test run",
            "status_label": _execution_status_label(run),
            "summary": run.combined_output or "No output produced.",
        }
    return {
        "tone": "warn",
        "verdict": "Needs another fix",
        "status_label": _execution_status_label(run),
        "summary": run.combined_output or run.stderr or "The patched code still needs another change.",
    }


def _qa_result_from_history_entry(entry: dict[str, object]) -> QAResult:
    citation_list = entry.get("citation_list", [])
    citations = [
        Citation(
            label=str(citation["label"]),
            source_file=str(citation["source_file"]),
            page_number=citation["page_number"],
            chunk_id=str(citation["chunk_id"]),
            snippet=str(citation["snippet"]),
        )
        for citation in citation_list
        if isinstance(citation, dict)
    ]
    return QAResult(
        question=str(entry["question"]),
        short_answer=str(entry["answer_text"]),
        more_detail=str(entry.get("more_detail", "")),
        citations=citations,
        unsure=bool(entry.get("unsure", False)),
        result_mode=str(entry.get("result_mode", "answered") or "answered"),
        history_id=int(entry["id"]),
        retrieval_mode=str(entry.get("retrieval_mode", "lexical") or "lexical"),
        retrieval_mode_label=str(
            entry.get("retrieval_mode_label", "Lexical only") or "Lexical only"
        ),
    )


def _saved_queue_wait_summary(session_data: object) -> str:
    if not isinstance(session_data, dict):
        return ""
    profile = session_data.get("profile")
    if isinstance(profile, dict):
        raw_wait = profile.get("queue_wait_seconds")
    else:
        raw_wait = session_data.get("queue_wait_seconds")
    try:
        wait_seconds = float(raw_wait or 0.0)
    except (TypeError, ValueError):
        return ""
    if wait_seconds <= 0:
        return " It started immediately on the local host."
    return f" It waited {wait_seconds:.2f}s in the local queue before running."


def _execution_result_from_session_data(data: dict[str, object]) -> ExecutionResult:
    return ExecutionResult(
        status=str(data.get("status", "completed")),
        return_code=data.get("return_code") if isinstance(data.get("return_code"), int | type(None)) else None,
        stdout=str(data.get("stdout", "")),
        stderr=str(data.get("stderr", "")),
        timed_out=bool(data.get("timed_out", False)),
        command=list(data.get("command", [])) if isinstance(data.get("command"), list) else [],
        mode=str(data.get("mode", "session")),
        effective_test_code=data.get("effective_test_code") if isinstance(data.get("effective_test_code"), str | type(None)) else None,
        used_generated_tests=bool(data.get("used_generated_tests", False)),
        working_directory=data.get("working_directory") if isinstance(data.get("working_directory"), str | type(None)) else None,
        sandbox_profile=str(data.get("sandbox_profile", "none")),
        sandbox_note=str(data.get("sandbox_note", "")),
        denied_by_policy=bool(data.get("denied_by_policy", False)),
    )


def _code_test_mismatch_result(
    *,
    original_code: str,
    tests: str,
    missing_names: set[str],
    session_id: int,
) -> CodeTutorResult:
    missing_label = ", ".join(sorted(missing_names))
    message = (
        f"The tests import {missing_label} from submission.py, but this code does not define "
        f"{missing_label}."
    )
    return CodeTutorResult(
        diagnosis="The tests do not match this code.",
        evidence=message,
        next_fix="Clear the optional tests, or change them so they import names that this code actually defines.",
        patched_code=original_code,
        why_it_works="This prevents Code Assist from repairing your code toward an unrelated sample function.",
        initial_run=ExecutionResult(
            status="not_run",
            return_code=None,
            stdout="",
            stderr=message,
            timed_out=False,
            command=[],
            mode="test_mismatch",
            effective_test_code=tests,
            used_generated_tests=False,
        ),
        patched_run=ExecutionResult(
            status="not_run",
            return_code=None,
            stdout="",
            stderr="No rerun was attempted because the tests do not match the submitted code.",
            timed_out=False,
            command=[],
            mode="test_mismatch",
            effective_test_code=tests,
            used_generated_tests=False,
        ),
        result_mode="test_mismatch",
        session_id=session_id,
    )


def _code_result_from_session_entry(entry: dict[str, object]) -> tuple[CodeTutorResult, str, str, str]:
    session_data = entry.get("session_data", {})
    if isinstance(session_data, dict) and session_data:
        original_code = str(session_data.get("original_code", entry["original_code"]))
        form_tests = str(session_data.get("form_tests", entry["test_code"] or ""))
        missing_names = _missing_submission_imports(original_code, form_tests)
        if missing_names:
            return (
                _code_test_mismatch_result(
                    original_code=original_code,
                    tests=form_tests,
                    missing_names=missing_names,
                    session_id=int(entry["id"]),
                ),
                original_code,
                form_tests,
                str(session_data.get("instruction", "")),
            )
        initial_run = _execution_result_from_session_data(
            session_data.get("initial_run", {}) if isinstance(session_data.get("initial_run"), dict) else {}
        )
        patched_run = _execution_result_from_session_data(
            session_data.get("patched_run", {}) if isinstance(session_data.get("patched_run"), dict) else {}
        )
        result = CodeTutorResult(
            diagnosis=str(session_data.get("diagnosis", "Saved code result.")),
            evidence=str(session_data.get("evidence", entry["execution_output"])),
            next_fix=str(session_data.get("next_fix", "Review the saved patch below.")),
            patched_code=str(session_data.get("patched_code", entry["patched_code"] or "")),
            why_it_works=str(session_data.get("why_it_works", "This explanation was saved from a previous run.")),
            initial_run=initial_run,
            patched_run=patched_run,
            result_mode=str(session_data.get("result_mode", "completed") or "completed"),
            session_id=int(entry["id"]),
        )
        return (
            result,
            original_code,
            form_tests,
            str(session_data.get("instruction", "")),
        )

    original_code = str(entry["original_code"])
    form_tests = str(entry["test_code"] or "")
    missing_names = _missing_submission_imports(original_code, form_tests)
    if missing_names:
        return (
            _code_test_mismatch_result(
                original_code=original_code,
                tests=form_tests,
                missing_names=missing_names,
                session_id=int(entry["id"]),
            ),
            original_code,
            form_tests,
            "",
        )

    initial_run = ExecutionResult(
        status="completed",
        return_code=None,
        stdout=str(entry["execution_output"] or ""),
        stderr="",
        timed_out=False,
        command=[],
        mode="session",
        effective_test_code=entry["test_code"] if isinstance(entry["test_code"], str | type(None)) else None,
        used_generated_tests=False,
    )
    patched_run = ExecutionResult(
        status="completed",
        return_code=None,
        stdout=str(entry["patched_test_result"] or ""),
        stderr="",
        timed_out=False,
        command=[],
        mode="session",
        effective_test_code=entry["test_code"] if isinstance(entry["test_code"], str | type(None)) else None,
        used_generated_tests=False,
    )
    result = CodeTutorResult(
        diagnosis="Saved code result from an earlier AccessLab run.",
        evidence=str(entry["execution_output"] or ""),
        next_fix="Review the saved patched code below.",
        patched_code=str(entry["patched_code"] or ""),
        why_it_works="This session predates the richer saved-session format, so only the stored runtime outputs are available.",
        initial_run=initial_run,
        patched_run=patched_run,
        result_mode="completed",
        session_id=int(entry["id"]),
    )
    return (
        result,
        original_code,
        form_tests,
        "",
    )


def _base_context(request: Request, active_view: str = "home", **extra: object) -> dict[str, object]:
    settings = request.app.state.settings
    current_role = current_local_role(request)
    actor_key = current_actor_key(request)
    llm_provider = request.app.state.llm_provider
    llm_ready, llm_message = llm_provider.health_check()
    default_code = _read_if_present(settings.sample_code_dir / "buggy_sum.py")
    default_tests = _read_if_present(settings.sample_code_dir / "test_buggy_sum.py")
    runtime_statuses = _build_runtime_statuses(request, llm_ready=llm_ready, llm_message=llm_message)
    retrieval_diagnostics = runtime_statuses["retrieval_diagnostics"]
    highlight_document_id = extra.pop("highlight_document_id", None)
    documents = _document_rows(
        settings.db_path,
        class_space=settings.class_space,
        highlight_document_id=highlight_document_id,
    )
    code_tutor_service = getattr(request.app.state, "code_tutor_service", None)
    execution_backend = getattr(code_tutor_service, "execution_backend", None)
    sandbox_profile = str(getattr(execution_backend, "sandbox_profile", "none"))
    sandbox_note = str(getattr(execution_backend, "sandbox_note", ""))
    work_queue = getattr(request.app.state, "work_queue", None)
    queue_snapshot = (
        work_queue.snapshot()
        if work_queue is not None
        else _default_queue_snapshot(settings.max_concurrent_jobs)
    )
    page_notices = _workspace_runtime_notices(
        active_view=active_view,
        local_status=runtime_statuses["local_status"],
        retrieval_status=runtime_statuses["retrieval_status"],
        ocr_status=runtime_statuses["ocr_status"],
    )
    if active_view in {"home", "admin"} and settings.deployment_mode == "school-box-shared":
        pass  # Banner removed — mode is indicated in the workspace title
    elif active_view in {"home", "admin"} and settings.deployment_mode == "classroom-local":
        pass  # Banner removed — mode is indicated in the workspace title
    if active_view in {"home", "admin"} and settings.generation_model_notice:
        page_notices.insert(
            0,
            _notice_block(
                "Gemma 4 centrality",
                settings.generation_model_notice,
                tone="warn",
            ),
        )
    page_notices.extend(extra.pop("page_notices", []))
    # On the home view, suppress info-tone banners — info is shown in the workspace title
    if active_view == "home":
        page_notices = [n for n in page_notices if n.get("tone") != "info"]
    status = extra.pop("status", None)
    current_path = _current_path_with_query(request)
    focus_target_id = str(extra.pop("focus_target_id", ""))
    recent_question_rows = _recent_question_rows(
        request,
        role_id=current_role.id,
        actor_key=actor_key,
        sees_all_sessions=current_role.sees_all_sessions,
    )
    recent_code_rows = _recent_code_rows(
        request,
        role_id=current_role.id,
        actor_key=actor_key,
        sees_all_sessions=current_role.sees_all_sessions,
    )
    recent_activity_rows = _recent_activity_rows(request)

    context: dict[str, object] = {
        "request": request,
        "app_name": settings.app_name,
        "current_role": current_role,
        "current_role_id": current_role.id,
        "current_role_label": current_role.label,
        "current_actor_key": actor_key,
        "role_options": _role_options(current_role.id),
        "role_switch_target": current_path,
        "can_upload": current_role.upload_allowed,
        "can_manage_materials": current_role.manage_materials,
        "can_label_saved_sessions": _can_label_saved_sessions(current_role),
        "show_runtime_details": current_role.show_runtime_details,
        "shared_mode_enabled": settings.deployment_mode != "single-user-local",
        "deployment_mode": settings.deployment_mode,
        "deployment_mode_display": settings.deployment_mode_display,
        "deployment_mode_summary": settings.deployment_mode_summary,
        "class_space": settings.class_space,
        "class_space_display": settings.class_space_display,
        "saved_sessions_scope_label": (
            "Saved classroom sessions"
            if current_role.sees_all_sessions
            else "Your saved sessions"
        ),
        "recent_question_rows": recent_question_rows,
        "recent_code_rows": recent_code_rows,
        "recent_activity_rows": recent_activity_rows,
        "documents": documents,
        "document_count": len(documents),
        "llm_ready": llm_ready,
        "llm_message": llm_message,
        "device_mode": _device_mode(llm_ready),
        "runtime_backend": settings.runtime_backend,
        "runtime_backend_display": settings.runtime_backend_display,
        "deployment_profile": settings.deployment_profile,
        "deployment_profile_display": settings.deployment_profile_display,
        "deployment_profile_summary": settings.deployment_profile_summary,
        "active_model": settings.accesslab_model,
        "generation_model_family": settings.generation_model_family,
        "generation_model_policy": settings.generation_model_policy,
        "model_explicitly_set": settings.model_explicitly_set,
        "generation_model_notice": settings.generation_model_notice,
        "runtime_capabilities": llm_provider.capabilities(),
        "semantic_model": settings.semantic_embedding_model,
        "semantic_model_family": settings.semantic_model_family,
        "semantic_model_summary": settings.semantic_model_summary,
        "future_runtime_validation_track": settings.future_runtime_validation_track,
        "retrieval_requested_mode": settings.retrieval_mode,
        "retrieval_requested_mode_display": settings.retrieval_mode_display,
        "retrieval_diagnostics": retrieval_diagnostics,
        "lexical_backend_label": retrieval_diagnostics.lexical_backend_label,
        "local_status": runtime_statuses["local_status"],
        "retrieval_status": runtime_statuses["retrieval_status"],
        "ocr_status": runtime_statuses["ocr_status"],
        "search_mode_label": _search_mode_label(retrieval_diagnostics),
        "active_view": active_view,
        "focus_target_id": focus_target_id,
        "status_message": "",
        "status_title": "",
        "status_body": "",
        "status_tone": "default",
        "status_action_href": "",
        "status_action_label": "",
        "page_notices": page_notices,
        "sandbox_profile": sandbox_profile,
        "sandbox_profile_display": _format_sandbox_profile_label(sandbox_profile),
        "sandbox_note": sandbox_note,
        "queue_snapshot": queue_snapshot,
        "queue_recent_rows": _queue_recent_rows(queue_snapshot),
        "queue_waiting_summary": _queue_kind_summary(queue_snapshot, "waiting_by_kind"),
        "queue_active_summary": _queue_kind_summary(queue_snapshot, "active_by_kind"),
        "quality_label_options": [
            {"value": label, "label": session_label_display(label)}
            for label in KNOWN_SESSION_LABELS
        ],
        "operator_preflight": extra.pop("operator_preflight", None),
        "operator_training_snapshot": extra.pop("operator_training_snapshot", None),
        "artifact_snapshot_rows": extra.pop("artifact_snapshot_rows", []),
        "ollama_proof_rows": extra.pop("ollama_proof_rows", []),
        "teacher_summary": extra.pop("teacher_summary", _teacher_class_summary(settings)),
        "judge_demo": extra.pop("judge_demo", None),
        "class_space_migration": extra.pop("class_space_migration", None),
        "class_space_migration_form": extra.pop(
            "class_space_migration_form",
            {
                "from_class_space": settings.class_space,
                "to_class_space": settings.class_space,
                "include_sessions": True,
            },
        ),
        "code_value": "",
        "test_value": "",
        "instruction_value": "",
        "question_value": "",
        "answer_language_value": "auto",
        "answer_language_options": _answer_language_options("auto"),
        "qa_form_disabled": len(documents) == 0,
        "qa_notice": None,
        "qa_evidence_empty_state": _qa_evidence_empty_state(
            has_documents=bool(documents),
            qa_result=None,
        ),
        "qa_short_paragraphs": [],
        "qa_detail_paragraphs": [],
        "qa_short_rendered_html": Markup(""),
        "qa_detail_rendered_html": Markup(""),
        "qa_evidence_cards": [],
        "qa_trust_rows": [],
        "qa_session_labels": [],
        "code_notice": None,
        "code_initial_status_label": "",
        "code_patched_run_view": {
            "tone": "warn",
            "verdict": "Needs another fix",
            "status_label": "",
            "summary": "",
        },
        "code_trust_rows": [],
        "code_session_labels": [],
        **extra,
    }

    if isinstance(status, dict):
        context["status_title"] = str(status.get("title", ""))
        context["status_body"] = str(status.get("body", ""))
        context["status_tone"] = str(status.get("tone", "default"))
        context["status_action_href"] = str(status.get("action_href", ""))
        context["status_action_label"] = str(status.get("action_label", ""))

    if context["status_message"] and not context["status_body"]:
        context["status_body"] = context["status_message"]
    elif context["status_body"] and not context["status_message"]:
        context["status_message"] = context["status_body"]

    context["answer_language_options"] = _answer_language_options(
        str(context.get("answer_language_value", "auto"))
    )

    qa_result = context.get("qa_result")
    if qa_result:
        context["qa_short_paragraphs"] = _paragraphs(qa_result.short_answer)
        context["qa_detail_paragraphs"] = _paragraphs(qa_result.more_detail)
        context["qa_short_rendered_html"] = render_answer_html(
            qa_result.short_answer, qa_result.citations
        )
        context["qa_detail_rendered_html"] = render_answer_html(
            qa_result.more_detail, qa_result.citations
        )
        context["qa_evidence_cards"] = build_evidence_cards(
            qa_result.citations,
            qa_id=qa_result.history_id,
        )
        context["qa_notice"] = _qa_result_notice(qa_result)
        context["qa_evidence_empty_state"] = _qa_evidence_empty_state(
            has_documents=bool(documents),
            qa_result=qa_result,
        )
        context["qa_trust_rows"] = _qa_trust_rows(settings, qa_result)

    code_result = context.get("code_result")
    if code_result:
        context["code_notice"] = _code_result_notice(code_result)
        context["code_initial_status_label"] = _execution_status_label(code_result.initial_run)
        context["code_patched_run_view"] = _patched_run_view(code_result)
        context["code_trust_rows"] = _code_trust_rows(settings, code_result, execution_backend)

    return context


def _document_media_type(file_type: str) -> str:
    if file_type == "pdf":
        return "application/pdf"
    if file_type == "md":
        return "text/markdown; charset=utf-8"
    return "text/plain; charset=utf-8"


# ── Home / Workspace ──────────────────────────────────────────────────────────

@router.post("/role")
async def set_local_role(
    request: Request,
    role: str = Form(...),
    next_path: str = Form("/"),
) -> RedirectResponse:
    resolved = resolve_local_role(role)
    response = RedirectResponse(url=_safe_next_path(next_path), status_code=303)
    response.set_cookie(
        key=ROLE_COOKIE_NAME,
        value=resolved.id,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 365,
        path="/",
    )
    return _finalize_response(request, response)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    templates = request.app.state.templates
    response = templates.TemplateResponse(
        request,
        "home.html",
        _base_context(request, active_view="home"),
    )
    return _finalize_response(request, response)


@router.get("/judge-demo", response_class=HTMLResponse)
async def judge_demo_view(request: Request) -> HTMLResponse:
    templates = request.app.state.templates
    settings = request.app.state.settings
    # Only redirect when the ?ready=1 flag is missing.  Previously we also
    # checked the role cookie with `or`, which caused an infinite redirect loop
    # on Hugging Face Spaces because HF's reverse proxy does not reliably
    # forward cookies on cross-origin 303 redirects.
    if request.query_params.get("ready") != "1":
        response = RedirectResponse(url="/judge-demo?ready=1", status_code=303)
        response.set_cookie(
            key=ROLE_COOKIE_NAME,
            value="admin",
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 365,
            path="/",
        )
        response.set_cookie(
            key=ACTOR_COOKIE_NAME,
            value=DEMO_ACTOR_KEY,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 365,
            path="/",
        )
        return response
    demo_summary = seed_judge_demo(settings, class_space=settings.class_space)
    response = templates.TemplateResponse(
        request,
        "judge_demo.html",
        _base_context(
            request,
            active_view="home",
            judge_demo=demo_summary,
            status=_status_block(
                "Judge demo ready",
                "Seeded local materials, saved QA with citations, source inspection, Python repair, teacher summary, and proof links.",
                tone="success",
            ),
            focus_target_id="status-region",
        ),
    )
    # Set admin+demo cookies on the page response too, so they stick even if
    # the redirect cookie was lost by the proxy.
    response.set_cookie(
        key=ROLE_COOKIE_NAME,
        value="admin",
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 365,
        path="/",
    )
    response.set_cookie(
        key=ACTOR_COOKIE_NAME,
        value=DEMO_ACTOR_KEY,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 365,
        path="/",
    )
    return _finalize_response(request, response)


@router.get("/teacher/report.csv")
async def export_teacher_report(request: Request) -> Response:
    current_role = current_local_role(request)
    if current_role.id not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="Teacher or admin access needed.")
    settings = request.app.state.settings
    csv_text = _teacher_report_csv(settings)
    safe_class = settings.class_space.replace("/", "-")
    return Response(
        csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="accesslab-{safe_class}-class-report.csv"'},
    )


@router.post("/upload", response_class=HTMLResponse)
async def upload_document(request: Request, document: UploadFile = File(...)) -> HTMLResponse:
    templates = request.app.state.templates
    ingest_service = request.app.state.ingest_service
    current_role = current_local_role(request)

    if not current_role.upload_allowed:
        context = _base_context(
            request,
            active_view="home",
            status=_status_block(
                "Teacher or admin access needed",
                "Switch to Teacher or Admin to upload files.",
                tone="warn",
            ),
            focus_target_id="status-region",
        )
        response = templates.TemplateResponse(request, "home.html", context, status_code=403)
        return _finalize_response(request, response)

    try:
        queue_receipt = None
        content = await document.read()
        if not document.filename or not content:
            raise ValueError("Choose a PDF, TXT, or MD file with readable text.")
        with _queue_job(request, job_kind="upload-material") as queue_receipt:
            ingest_result = ingest_service.ingest_upload(
                file_name=document.filename,
                content=content,
                uploader_role=current_role.id,
                visibility_scope="class",
                class_space=request.app.state.settings.class_space,
            )
        context = _base_context(
            request,
            active_view="home",
            ingest_result=ingest_result,
            ingest_feedback=_upload_feedback(ingest_result),
            highlight_document_id=ingest_result.document_id,
            status_message=f"{_ingest_status_message(ingest_result)} {_queue_wait_summary(queue_receipt)}",
            focus_target_id="status-region",
        )
    except Exception as exc:  # pragma: no cover - template fallback path
        context = _base_context(
            request,
            active_view="home",
            status=_upload_error_status(
                f"{str(exc)} {_queue_wait_summary(queue_receipt) if queue_receipt is not None else ''}".strip()
            ),
            focus_target_id="status-region",
        )

    response = templates.TemplateResponse(request, "home.html", context)
    return _finalize_response(request, response)


@router.post("/documents/{document_id}/delete", response_class=HTMLResponse)
async def remove_document(request: Request, document_id: int) -> HTMLResponse:
    templates = request.app.state.templates
    current_role = current_local_role(request)
    if not current_role.manage_materials:
        context = _base_context(
            request,
            active_view="home",
            status=_status_block(
                "Teacher or admin access needed",
                "Switch to Teacher or Admin to remove files.",
                tone="warn",
            ),
            focus_target_id="status-region",
        )
        response = templates.TemplateResponse(request, "home.html", context, status_code=403)
        return _finalize_response(request, response)

    with _queue_job(request, job_kind="delete-material") as queue_receipt:
        deleted = delete_document(
            request.app.state.settings.db_path,
            document_id,
            class_space=request.app.state.settings.class_space,
        )
    if deleted is None:
        context = _base_context(
            request,
            active_view="home",
            status=_status_block(
                "Material not found",
                "That class-shared material is no longer in the local index.",
                tone="warn",
            ),
            focus_target_id="status-region",
        )
        response = templates.TemplateResponse(request, "home.html", context, status_code=404)
        return _finalize_response(request, response)

    stored_path = Path(str(deleted.get("stored_path", "")))
    file_note = ""
    if stored_path.exists():
        try:
            stored_path.unlink()
        except OSError:
            file_note = " The stored file remained on disk because it could not be removed automatically."

    context = _base_context(
        request,
        active_view="home",
        status=_status_block(
            "Class-shared material removed",
                f"{deleted['file_name']} was removed.{file_note} {_queue_wait_summary(queue_receipt)}",
            tone="success",
        ),
        focus_target_id="status-region",
    )
    response = templates.TemplateResponse(request, "home.html", context)
    return _finalize_response(request, response)


@router.get("/admin", response_class=HTMLResponse)
async def admin_view(request: Request) -> HTMLResponse:
    templates = request.app.state.templates
    current_role = current_local_role(request)
    if not current_role.show_runtime_details:
        context = _base_context(
            request,
            active_view="home",
            status=_status_block(
                "Admin access needed",
                "Runtime, model, OCR, retrieval, and deployment diagnostics are reserved for Admin mode on this device.",
                tone="warn",
            ),
            focus_target_id="status-region",
        )
        response = templates.TemplateResponse(request, "home.html", context, status_code=403)
        return _finalize_response(request, response)

    settings = request.app.state.settings
    semantic_index = getattr(request.app.state, "semantic_index", None) or SQLiteSemanticIndex(
        db_path=settings.db_path,
        embedding_provider=create_embedding_provider(
            enabled=settings.semantic_enabled,
            base_url=settings.accesslab_ollama_url,
            model_name=settings.semantic_embedding_model,
        ),
        class_space=settings.class_space,
    )
    ocr_backend = getattr(request.app.state, "ocr_backend", None) or create_ocr_backend(
        enabled=settings.ocr_enabled,
        dpi=settings.ocr_dpi,
    )
    preflight = build_operator_preflight(
        settings,
        llm_provider=request.app.state.llm_provider,
        semantic_index=semantic_index,
        ocr_backend=ocr_backend,
        work_queue=getattr(request.app.state, "work_queue", None),
    )
    preflight = _sanitize_ui_paths(preflight, settings)
    response = templates.TemplateResponse(
        request,
        "admin.html",
        _base_context(
            request,
            active_view="admin",
            operator_preflight=preflight,
            operator_training_snapshot=_training_capture_summary(settings),
            artifact_snapshot_rows=_artifact_snapshot_rows(settings),
        ),
    )
    return _finalize_response(request, response)


def _proof_dashboard_context(request: Request, *, active_view: str) -> dict[str, object]:
    settings = request.app.state.settings
    semantic_index = getattr(request.app.state, "semantic_index", None) or SQLiteSemanticIndex(
        db_path=settings.db_path,
        embedding_provider=create_embedding_provider(
            enabled=settings.semantic_enabled,
            base_url=settings.accesslab_ollama_url,
            model_name=settings.semantic_embedding_model,
        ),
        class_space=settings.class_space,
    )
    ocr_backend = getattr(request.app.state, "ocr_backend", None) or create_ocr_backend(
        enabled=settings.ocr_enabled,
        dpi=settings.ocr_dpi,
    )
    preflight = build_operator_preflight(
        settings,
        llm_provider=request.app.state.llm_provider,
        semantic_index=semantic_index,
        ocr_backend=ocr_backend,
        work_queue=getattr(request.app.state, "work_queue", None),
    )
    preflight = _sanitize_ui_paths(preflight, settings)
    retrieval_diagnostics = build_retrieval_diagnostics(settings, semantic_index)
    artifact_rows = _artifact_snapshot_rows(settings)
    return _base_context(
        request,
        active_view=active_view,
        operator_preflight=preflight,
        artifact_snapshot_rows=artifact_rows,
        proof_scorecard_rows=_build_proof_scorecard_rows(
            preflight=preflight,
            retrieval_diagnostics=retrieval_diagnostics,
            artifact_rows=artifact_rows,
        ),
        accessibility_proof_rows=_build_accessibility_proof_rows(settings, artifact_rows),
        ollama_proof_rows=_ollama_proof_rows(settings, retrieval_diagnostics),
        status=_status_block(
            "Proof dashboard loaded",
            "Review local/offline proof, Ollama readiness, and generated artifact freshness.",
            tone="default",
        ),
        focus_target_id="status-region",
    )


@router.get("/proofs", response_class=HTMLResponse)
async def public_proofs_view(request: Request) -> HTMLResponse:
    templates = request.app.state.templates
    response = templates.TemplateResponse(
        request,
        "proofs.html",
        _proof_dashboard_context(request, active_view="home"),
    )
    return _finalize_response(request, response)


@router.get("/admin/proofs", response_class=HTMLResponse)
async def admin_proofs_view(request: Request) -> HTMLResponse:
    templates = request.app.state.templates
    current_role = current_local_role(request)
    if not current_role.show_runtime_details:
        context = _base_context(
            request,
            active_view="home",
            status=_status_block(
                "Admin access needed",
                "Switch to Admin to inspect local proof artifacts and Ollama runtime details.",
                tone="warn",
            ),
            focus_target_id="status-region",
        )
        response = templates.TemplateResponse(request, "home.html", context, status_code=403)
        return _finalize_response(request, response)

    response = templates.TemplateResponse(
        request,
        "proofs.html",
        _proof_dashboard_context(request, active_view="admin"),
    )
    return _finalize_response(request, response)


@router.post("/admin/class-space-migration", response_class=HTMLResponse)
async def admin_class_space_migration(
    request: Request,
    from_class_space: str = Form(""),
    to_class_space: str = Form(""),
    include_sessions: str | None = Form(None),
    action: str = Form("preview"),
) -> HTMLResponse:
    templates = request.app.state.templates
    current_role = current_local_role(request)
    if not current_role.show_runtime_details:
        context = _base_context(
            request,
            active_view="home",
            status=_status_block(
                "Admin access needed",
                "Only Admin mode can preview or apply class-space reassignment on this device.",
                tone="warn",
            ),
            focus_target_id="status-region",
        )
        response = templates.TemplateResponse(request, "home.html", context, status_code=403)
        return _finalize_response(request, response)

    settings = request.app.state.settings
    normalized_from = (from_class_space or "").strip() or settings.class_space
    normalized_to = (to_class_space or "").strip() or settings.class_space
    include_saved_sessions = include_sessions is not None
    if action == "apply":
        migration_summary = apply_class_space_migration(
            settings.db_path,
            from_class_space=normalized_from,
            to_class_space=normalized_to,
            include_sessions=include_saved_sessions,
        )
        status = _status_block(
            "Class-space reassignment applied" if migration_summary.get("applied") else "No reassignment applied",
            (
                f"Reassigned rows from {migration_summary['from_class_space']} to {migration_summary['to_class_space']}."
                if migration_summary.get("applied")
                else "Review the dry-run summary below before applying any changes."
            ),
            tone="success" if migration_summary.get("applied") else "warn",
        )
    else:
        migration_summary = preview_class_space_migration(
            settings.db_path,
            from_class_space=normalized_from,
            to_class_space=normalized_to,
            include_sessions=include_saved_sessions,
        )
        status = _status_block(
            "Dry-run preview ready",
            "Review the affected row counts and warnings below. Nothing has been changed yet.",
            tone="default",
        )

    semantic_index = getattr(request.app.state, "semantic_index", None) or SQLiteSemanticIndex(
        db_path=settings.db_path,
        embedding_provider=create_embedding_provider(
            enabled=settings.semantic_enabled,
            base_url=settings.accesslab_ollama_url,
            model_name=settings.semantic_embedding_model,
        ),
        class_space=settings.class_space,
    )
    ocr_backend = getattr(request.app.state, "ocr_backend", None) or create_ocr_backend(
        enabled=settings.ocr_enabled,
        dpi=settings.ocr_dpi,
    )
    preflight = build_operator_preflight(
        settings,
        llm_provider=request.app.state.llm_provider,
        semantic_index=semantic_index,
        ocr_backend=ocr_backend,
        work_queue=getattr(request.app.state, "work_queue", None),
    )
    response = templates.TemplateResponse(
        request,
        "admin.html",
        _base_context(
            request,
            active_view="admin",
            operator_preflight=preflight,
            operator_training_snapshot=_training_capture_summary(settings),
            artifact_snapshot_rows=_artifact_snapshot_rows(settings),
            class_space_migration=migration_summary,
            class_space_migration_form={
                "from_class_space": normalized_from,
                "to_class_space": normalized_to,
                "include_sessions": include_saved_sessions,
            },
            status=status,
            focus_target_id="status-region",
        ),
    )
    return _finalize_response(request, response)


@router.post("/session-labels")
async def create_session_label(
    request: Request,
    source_type: str = Form(...),
    source_id: int = Form(...),
    label: str = Form(...),
    note: str = Form(""),
    redirect_to: str = Form("/"),
) -> RedirectResponse:
    current_role = current_local_role(request)
    if not _can_label_saved_sessions(current_role):
        raise HTTPException(status_code=403, detail="Teacher or admin access needed.")

    settings = request.app.state.settings
    if source_type == "qa":
        entry = get_qa_history_entry(settings.db_path, source_id)
    else:
        entry = get_code_session_entry(settings.db_path, source_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Saved session not found.")
    if str(entry.get("class_space", "")) != settings.class_space:
        raise HTTPException(status_code=404, detail="Saved session not found in this class space.")

    normalized_label = (label or "").strip().lower()
    if normalized_label not in KNOWN_SESSION_LABELS:
        raise HTTPException(status_code=422, detail="Unknown label.")

    save_session_label(
        settings.db_path,
        source_type=source_type,
        source_id=source_id,
        label=normalized_label,
        note=note,
        actor_role=current_role.id,
        actor_key=current_actor_key(request),
        class_space=settings.class_space,
    )
    response = RedirectResponse(url=_safe_next_path(redirect_to), status_code=303)
    return _finalize_response(request, response)


# ── Local Materials Q&A ───────────────────────────────────────────────────────

@router.get("/qa", response_class=HTMLResponse)
async def qa_view(request: Request, qa_id: int | None = None) -> HTMLResponse:
    templates = request.app.state.templates
    if qa_id is None:
        response = templates.TemplateResponse(
            request,
            "qa.html",
            _base_context(request, active_view="qa"),
        )
        return _finalize_response(request, response)

    history_entry = get_qa_history_entry(request.app.state.settings.db_path, qa_id)
    if history_entry is None or not _saved_session_visible_to_current_actor(
        request,
        actor_key=str(history_entry.get("actor_key", "")) if history_entry else "",
        class_space=str(history_entry.get("class_space", "")) if history_entry else "",
    ):
        response = templates.TemplateResponse(
            request,
            "qa.html",
            _base_context(
                request,
                active_view="qa",
                status=_saved_session_unavailable_status(
                    title="Saved answer not found",
                    retry_href="/qa",
                    retry_label="Ask a new question",
                ),
                focus_target_id="status-region",
            ),
            status_code=404,
        )
        return _finalize_response(request, response)

    qa_result = _qa_result_from_history_entry(history_entry)
    response = templates.TemplateResponse(
        request,
        "qa.html",
        _base_context(
            request,
            active_view="qa",
            qa_result=qa_result,
            qa_session_labels=_session_label_rows(
                request.app.state.settings.db_path,
                source_type="qa",
                source_id=qa_result.history_id,
                class_space=request.app.state.settings.class_space,
            ),
            question_value=qa_result.question,
            status=_status_block(
                "Saved answer reopened",
                f"QA #{qa_result.history_id} loaded."
                f"{_saved_queue_wait_summary(history_entry.get('session_data'))}",
                tone="default",
            ),
            focus_target_id="status-region",
        ),
    )
    return _finalize_response(request, response)


@router.post("/qa", response_class=HTMLResponse)
async def ask_question(
    request: Request,
    question: str = Form(...),
    simplify: str = Form("0"),
    answer_language: str = Form("auto"),
    inclusive_plain_language: str = Form("0"),
) -> HTMLResponse:
    templates = request.app.state.templates
    settings = request.app.state.settings
    current_role = current_local_role(request)

    clean_question = question.strip()
    plain_language_requested = simplify == "1" or inclusive_plain_language == "1"
    if not clean_question:
        context = _base_context(
            request,
            active_view="qa",
            question_value="",
            answer_language_value=answer_language,
            status=_status_block(
                "Enter a question first",
                "Type a question about the indexed materials, then try again.",
                tone="warn",
            ),
            focus_target_id="status-region",
        )
        response = templates.TemplateResponse(request, "qa.html", context, status_code=422)
        return _finalize_response(request, response)

    if not _document_rows(settings.db_path, class_space=settings.class_space):
        context = _base_context(
            request,
            active_view="qa",
            question_value=clean_question,
            answer_language_value=answer_language,
            status=_status_block(
                "Add materials before asking a grounded question",
                "Upload a worksheet, notes, or study guide first.",
                tone="warn",
                action_href="/",
                action_label="Go to Workspace",
            ),
            focus_target_id="status-region",
        )
        response = templates.TemplateResponse(request, "qa.html", context, status_code=409)
        return _finalize_response(request, response)

    qa_service = request.app.state.qa_service

    try:
        queue_receipt = None
        with _queue_job(request, job_kind="grounded-qa") as queue_receipt:
            qa_result = qa_service.answer(
                clean_question,
                actor_role=current_role.id,
                actor_key=current_actor_key(request),
                class_space=settings.class_space,
                queue_wait_seconds=float(getattr(queue_receipt, "wait_seconds", 0.0) or 0.0),
                answer_language=answer_language,
                plain_language_requested=plain_language_requested,
            )
        if qa_result.history_id is not None:
            response = RedirectResponse(url=f"/qa?qa_id={qa_result.history_id}", status_code=303)
            return _finalize_response(request, response)
        context = _base_context(
            request,
            active_view="qa",
            qa_result=qa_result,
            question_value=question.strip(),
            answer_language_value=answer_language,
            status=_status_block(
                "Answer saved",
                _queue_wait_summary(queue_receipt),
                tone="success",
            ),
            focus_target_id="status-region",
        )
    except Exception as exc:  # pragma: no cover - template fallback path
        context = _base_context(
            request,
            active_view="qa",
            question_value=question,
            answer_language_value=answer_language,
            status=_status_block(
                "Could not answer that question",
                f"{exc} {_queue_wait_summary(queue_receipt) if queue_receipt is not None else ''}".strip(),
                tone="error",
            ),
            focus_target_id="status-region",
        )

    response = templates.TemplateResponse(request, "qa.html", context)
    return _finalize_response(request, response)


@router.get("/sources/{chunk_id}", response_class=HTMLResponse)
async def view_source(request: Request, chunk_id: str, qa_id: int | None = None) -> HTMLResponse:
    templates = request.app.state.templates
    settings = request.app.state.settings
    source_view = load_source_view(
        settings.db_path,
        chunk_id,
        class_space=settings.class_space,
    )
    qa_return_href = _safe_qa_return_href(request, qa_id)

    if source_view is None:
        context = _base_context(
            request,
            active_view="qa",
            source_view=None,
            missing_chunk_id=chunk_id,
            qa_return_href=qa_return_href,
            status=_status_block(
                "Source reference not found",
                "That citation could not be resolved from the local index.",
                tone="warn",
                action_href=qa_return_href,
                action_label="Return to Q&A",
            ),
            focus_target_id="status-region",
        )
        response = templates.TemplateResponse(request, "source.html", context, status_code=404)
        return _finalize_response(request, response)

    context = _base_context(
        request,
        active_view="qa",
        source_view=source_view,
        qa_return_href=qa_return_href,
        status=_status_block(
            "Inspecting local source",
            f"Reviewing the cited context from {source_view.file_name}.",
            tone="default",
        ),
        focus_target_id="status-region",
    )
    response = templates.TemplateResponse(request, "source.html", context)
    return _finalize_response(request, response)


@router.get("/documents/{document_id}/file")
async def open_document_file(request: Request, document_id: int) -> FileResponse:
    settings = request.app.state.settings

    with db_connection(settings.db_path) as connection:
        row = connection.execute(
            """
            SELECT id, file_name, file_type, stored_path
            FROM documents
            WHERE id = ? AND class_space = ?
            LIMIT 1
            """,
            (document_id, settings.class_space),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    stored_path = Path(row["stored_path"])
    if not stored_path.exists():
        raise HTTPException(status_code=404, detail="Stored file not found.")

    safe_name = Path(row["file_name"]).name
    return FileResponse(
        stored_path,
        media_type=_document_media_type(row["file_type"]),
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


# ── Beginner Python Coach ─────────────────────────────────────────────────────

@router.get("/code", response_class=HTMLResponse)
async def code_view(request: Request, session_id: int | None = None) -> HTMLResponse:
    templates = request.app.state.templates
    if session_id is None:
        response = templates.TemplateResponse(
            request,
            "code.html",
            _base_context(request, active_view="code"),
        )
        return _finalize_response(request, response)

    session_entry = get_code_session_entry(request.app.state.settings.db_path, session_id)
    if session_entry is None or not _saved_session_visible_to_current_actor(
        request,
        actor_key=str(session_entry.get("actor_key", "")) if session_entry else "",
        class_space=str(session_entry.get("class_space", "")) if session_entry else "",
    ):
        response = templates.TemplateResponse(
            request,
            "code.html",
            _base_context(
                request,
                active_view="code",
                status=_saved_session_unavailable_status(
                    title="Saved code review not found",
                    retry_href="/code",
                    retry_label="Run a new review",
                ),
                focus_target_id="status-region",
            ),
            status_code=404,
        )
        return _finalize_response(request, response)

    code_result, code_value, test_value, instruction_value = _code_result_from_session_entry(session_entry)
    response = templates.TemplateResponse(
        request,
        "code.html",
        _base_context(
            request,
            active_view="code",
            code_result=code_result,
            code_session_labels=_session_label_rows(
                request.app.state.settings.db_path,
                source_type="code",
                source_id=code_result.session_id,
                class_space=request.app.state.settings.class_space,
            ),
            code_value=code_value,
            test_value=test_value,
            instruction_value=instruction_value,
            status=_status_block(
                "Saved code review reopened",
                f"Code session #{code_result.session_id} loaded."
                f"{_saved_queue_wait_summary(session_entry.get('session_data'))}",
                tone="default",
            ),
            focus_target_id="status-region",
        ),
    )
    return _finalize_response(request, response)


@router.post("/code", response_class=HTMLResponse)
async def run_code_tutor(
    request: Request,
    code: str = Form(...),
    tests: str = Form(""),
    instruction: str = Form(""),
    inclusive_plain_language: str = Form("0"),
) -> HTMLResponse:
    templates = request.app.state.templates
    code_tutor_service = request.app.state.code_tutor_service
    current_role = current_local_role(request)
    code_value = code.strip()

    if not code_value:
        context = _base_context(
            request,
            active_view="code",
            code_value="",
            test_value=tests,
            instruction_value=instruction,
            status=_status_block(
                "Paste some Python code first",
                "Paste a short Python example.",
                tone="warn",
            ),
            focus_target_id="status-region",
        )
        response = templates.TemplateResponse(request, "code.html", context, status_code=422)
        return _finalize_response(request, response)

    try:
        queue_receipt = None
        effective_instruction = instruction
        if inclusive_plain_language == "1":
            effective_instruction = (
                f"{instruction.strip()}\n\n" if instruction.strip() else ""
            ) + "Explain the bug and fix in plain language for a beginner student."
        with _queue_job(request, job_kind="code-tutor") as queue_receipt:
            result = code_tutor_service.tutor(
                code,
                tests or None,
                effective_instruction or None,
                actor_role=current_role.id,
                actor_key=current_actor_key(request),
                class_space=request.app.state.settings.class_space,
                queue_wait_seconds=float(getattr(queue_receipt, "wait_seconds", 0.0) or 0.0),
            )
        if result.session_id is not None:
            response = RedirectResponse(url=f"/code?session_id={result.session_id}", status_code=303)
            return _finalize_response(request, response)
        context = _base_context(
            request,
            active_view="code",
            code_result=result,
            code_value=code,
            test_value=tests,
            instruction_value=effective_instruction,
            status=_status_block(
                "Code Assist complete",
                _queue_wait_summary(queue_receipt),
                tone="success",
            ),
            focus_target_id="status-region",
        )
    except Exception as exc:  # pragma: no cover - template fallback path
        context = _base_context(
            request,
            active_view="code",
            code_value=code,
            test_value=tests,
            instruction_value=instruction,
            status=_status_block(
                "Code Assist could not be completed",
                f"{exc} {_queue_wait_summary(queue_receipt) if queue_receipt is not None else ''}".strip(),
                tone="error",
            ),
            focus_target_id="status-region",
        )

    response = templates.TemplateResponse(request, "code.html", context)
    return _finalize_response(request, response)
