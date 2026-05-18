from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from app.db import db_connection
from app.services.system_status import build_retrieval_diagnostics


def build_operator_preflight(
    settings,
    *,
    llm_provider,
    semantic_index,
    ocr_backend,
    work_queue=None,
) -> dict[str, Any]:
    retrieval_diagnostics = build_retrieval_diagnostics(settings, semantic_index)
    queue_snapshot = work_queue.snapshot() if work_queue is not None else {
        "max_concurrent_jobs": settings.max_concurrent_jobs,
        "active_jobs": 0,
        "waiting_jobs": 0,
        "queue_depth": 0,
        "active_budget": 0,
        "available_budget": settings.max_concurrent_jobs,
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
    llm_ready, llm_message = llm_provider.health_check()
    storage_ok, storage_detail, storage_probe_path = _probe_storage(settings.data_dir)
    db_ok, db_detail, dataset_counts = _probe_database(settings.db_path, settings.class_space)
    ocr_available = bool(ocr_backend.is_available())

    checks = [
        _check(
            "generation-runtime",
            "Gemma 4 runtime",
            "pass" if llm_ready else "fail",
            llm_message if llm_ready else "Gemma 4 is not ready on this runtime.",
            llm_provider.describe_runtime(),
            critical=True,
        ),
        _check(
            "embedding-model",
            "EmbeddingGemma model",
            _embedding_status(settings, retrieval_diagnostics),
            retrieval_diagnostics.semantic.summary,
            retrieval_diagnostics.semantic.detail,
        ),
        _check(
            "semantic-retrieval",
            "Semantic retrieval",
            _semantic_status(settings, retrieval_diagnostics),
            (
                f"{retrieval_diagnostics.actual_mode_label} active."
                if retrieval_diagnostics.semantic.retrieval_ready
                else retrieval_diagnostics.semantic.summary
            ),
            retrieval_diagnostics.semantic.detail,
        ),
        _check(
            "ocr",
            "OCR fallback",
            "info" if settings.ocr_enabled == "off" else ("pass" if ocr_available else "warn"),
            (
                "OCR is turned off for this install."
                if settings.ocr_enabled == "off"
                else ("OCR extras are available locally." if ocr_available else "OCR extras are not available.")
            ),
            ocr_backend.describe(),
        ),
        _check(
            "storage",
            "Writable local storage",
            "pass" if storage_ok else "fail",
            storage_detail,
            storage_probe_path,
            critical=True,
        ),
        _check(
            "database",
            "Database state",
            "pass" if db_ok else "fail",
            db_detail,
            (
                f"{dataset_counts['documents']} document(s), {dataset_counts['qa_sessions']} QA session(s), "
                f"{dataset_counts['code_sessions']} code session(s), "
                f"{dataset_counts['session_labels']} label(s), and "
                f"{dataset_counts['training_capture_events']} captured example(s) in {settings.class_space_display}."
            ),
            critical=True,
        ),
        _check(
            "deployment",
            "Deployment mode",
            "info",
            settings.deployment_mode_display,
            settings.deployment_mode_summary,
        ),
        _check(
            "class-space",
            "Class space",
            "info",
            settings.class_space_display,
            "Shared material and saved-session scope for this deployment.",
        ),
        _check(
            "queue",
            "Concurrent job limit",
            "info",
            f"{queue_snapshot['max_concurrent_jobs']} capacity slot(s)",
            (
                f"Queue depth {queue_snapshot['queue_depth']} with {queue_snapshot['active_jobs']} active, "
                f"{queue_snapshot['waiting_jobs']} waiting, and "
                f"{queue_snapshot['available_budget']} slot(s) currently free."
            ),
        ),
        _check(
            "training-capture",
            "Training-data capture",
            "info",
            settings.training_capture_display,
            settings.training_capture_summary,
        ),
    ]
    overall_status = _overall_status(checks)

    return {
        "overall_status": overall_status,
        "overall_label": {
            "ready": "Ready",
            "attention": "Needs attention",
            "blocked": "Blocked",
        }[overall_status],
        "checks": checks,
        "runtime_capabilities": llm_provider.capabilities(),
        "dataset_counts": dataset_counts,
        "storage_probe_path": storage_probe_path,
        "database_quick_check": "ok" if db_ok else "failed",
        "queue_snapshot": queue_snapshot,
    }


def _check(
    check_id: str,
    label: str,
    status: str,
    summary: str,
    detail: str,
    *,
    critical: bool = False,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "summary": summary,
        "detail": detail,
        "critical": critical,
    }


def _overall_status(checks: list[dict[str, Any]]) -> str:
    if any(check["status"] == "fail" for check in checks):
        return "blocked"
    if any(check["status"] == "warn" for check in checks):
        return "attention"
    return "ready"


def _embedding_status(settings, retrieval_diagnostics) -> str:
    if settings.semantic_enabled == "off":
        return "info"
    if retrieval_diagnostics.semantic.provider_ready:
        return "pass"
    if retrieval_diagnostics.semantic.code == "model_not_installed":
        return "fail"
    return "warn"


def _semantic_status(settings, retrieval_diagnostics) -> str:
    if settings.retrieval_mode == "lexical" or settings.semantic_enabled == "off":
        return "info"
    if retrieval_diagnostics.semantic.retrieval_ready:
        return "pass"
    return "warn"


def _probe_storage(data_dir: Path) -> tuple[bool, str, str]:
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".tmp",
            prefix="accesslab-preflight-",
            dir=data_dir,
            delete=False,
            encoding="utf-8",
        ) as handle:
            handle.write("ok")
            probe_path = Path(handle.name)
        probe_path.unlink(missing_ok=True)
    except OSError as exc:
        return False, f"Could not write inside {data_dir}.", str(exc)
    return True, f"Storage is writable in {data_dir}.", str(probe_path)


def _probe_database(db_path: Path, class_space: str) -> tuple[bool, str, dict[str, int]]:
    counts = {
        "documents": 0,
        "qa_sessions": 0,
        "code_sessions": 0,
        "session_labels": 0,
        "training_capture_events": 0,
    }
    try:
        with db_connection(db_path) as connection:
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            if quick_check is None or str(quick_check[0]).lower() != "ok":
                return False, "SQLite quick_check did not return ok.", counts
            counts["documents"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM documents WHERE class_space = ?",
                    (class_space,),
                ).fetchone()[0]
            )
            counts["qa_sessions"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM qa_history WHERE class_space = ?",
                    (class_space,),
                ).fetchone()[0]
            )
            counts["code_sessions"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM code_sessions WHERE class_space = ?",
                    (class_space,),
                ).fetchone()[0]
            )
            counts["session_labels"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM session_labels WHERE class_space = ?",
                    (class_space,),
                ).fetchone()[0]
            )
            counts["training_capture_events"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM training_capture_events WHERE class_space = ?",
                    (class_space,),
                ).fetchone()[0]
            )
    except Exception as exc:
        return False, f"Could not read the SQLite database at {db_path}.", str(exc)
    return True, f"SQLite quick_check passed for {db_path}.", counts
