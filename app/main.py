from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import PROFILE_MODELS, get_settings
from app.db import init_db
from app.routes import router
from app.services.code_runner import LocalPythonRunner
from app.services.code_tutor import CodeTutorService
from app.services.bootstrap import (
    ensure_ocr_requirements,
    ensure_semantic_backfill,
    seed_default_documents,
)
from app.services.document_ingest import DocumentIngestService
from app.services.llm import ALLOWED_GEMMA4_MODELS, create_generation_provider, list_ollama_model_names
from app.services.ocr import create_ocr_backend
from app.services.operator_preflight import build_operator_preflight
from app.services.qa import GroundedQAService
from app.services.retrieval import HybridSQLiteRetrieval
from app.services.semantic import (
    SQLiteSemanticIndex,
    create_embedding_provider,
)
from app.services.system_status import build_retrieval_diagnostics
from app.services.work_queue import LocalWorkQueue


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_directories()
    init_db(settings.db_path)

    semantic_index = SQLiteSemanticIndex(
        db_path=settings.db_path,
        embedding_provider=create_embedding_provider(
            enabled=settings.semantic_enabled,
            base_url=settings.accesslab_ollama_url,
            model_name=settings.semantic_embedding_model,
        ),
        class_space=settings.class_space,
    )
    ensure_ocr_requirements(settings)
    ocr_backend = create_ocr_backend(enabled=settings.ocr_enabled, dpi=settings.ocr_dpi)
    seed_default_documents(
        settings,
        ocr_backend=ocr_backend,
        semantic_index=semantic_index,
    )
    ensure_semantic_backfill(semantic_index)
    retrieval_backend = HybridSQLiteRetrieval(
        settings.db_path,
        semantic_index=semantic_index,
        retrieval_mode=settings.retrieval_mode,
        class_space=settings.class_space,
    )
    llm_provider = create_generation_provider(
        runtime_backend=settings.runtime_backend,
        base_url=settings.accesslab_ollama_url,
        model_name=settings.accesslab_model,
    )
    execution_backend = LocalPythonRunner(timeout_seconds=5)
    work_queue = LocalWorkQueue(max_concurrent_jobs=settings.max_concurrent_jobs)

    app.state.settings = settings
    app.state.templates = Jinja2Templates(directory=str(settings.templates_dir))
    app.state.ocr_backend = ocr_backend
    app.state.semantic_index = semantic_index
    app.state.retrieval_backend = retrieval_backend
    app.state.work_queue = work_queue
    app.state.ingest_service = DocumentIngestService(
        uploads_dir=settings.uploads_dir,
        db_path=settings.db_path,
        ocr_backend=ocr_backend,
        semantic_index=semantic_index,
        ocr_min_chars_per_page=settings.ocr_min_chars_per_page,
    )
    # The QA output-discipline profile follows the deployment profile by
    # default (weak deployment -> weak discipline suffix), but operators can
    # override it independently via ACCESSLAB_QA_DISCIPLINE_PROFILE for
    # triage / experiments. See WEAK_TIER_QA_DISCIPLINE_SUFFIX in
    # app/services/qa.py and resolve_qa_discipline_profile in app/config.py.
    app.state.qa_service = GroundedQAService(
        db_path=settings.db_path,
        retrieval_backend=retrieval_backend,
        llm_provider=llm_provider,
        qa_discipline_profile=settings.qa_discipline_profile,
        training_capture_enabled=settings.training_capture_enabled_bool,
    )
    app.state.code_tutor_service = CodeTutorService(
        db_path=settings.db_path,
        llm_provider=llm_provider,
        execution_backend=execution_backend,
        training_capture_enabled=settings.training_capture_enabled_bool,
    )
    app.state.llm_provider = llm_provider
    yield


app = FastAPI(
    title="AccessLab",
    summary="Gemma 4-powered offline classroom and coding-lab assistant.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(get_settings().static_dir)), name="static")
app.include_router(router)


@app.get("/healthz")
async def healthz() -> JSONResponse:
    settings = get_settings()
    llm_provider = create_generation_provider(
        runtime_backend=settings.runtime_backend,
        base_url=settings.accesslab_ollama_url,
        model_name=settings.accesslab_model,
    )
    llm_ready, llm_message = llm_provider.health_check()
    ocr_backend = getattr(app.state, "ocr_backend", None) or create_ocr_backend(
        enabled=settings.ocr_enabled, dpi=settings.ocr_dpi
    )
    semantic_index = getattr(app.state, "semantic_index", None) or SQLiteSemanticIndex(
        db_path=settings.db_path,
        embedding_provider=create_embedding_provider(
            enabled=settings.semantic_enabled,
            base_url=settings.accesslab_ollama_url,
            model_name=settings.semantic_embedding_model,
        ),
        class_space=settings.class_space,
    )
    ensure_semantic_backfill(semantic_index)
    retrieval_diagnostics = build_retrieval_diagnostics(settings, semantic_index)
    work_queue = getattr(app.state, "work_queue", None)
    queue_snapshot = (
        work_queue.snapshot()
        if work_queue is not None
        else {
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
    )
    preflight = build_operator_preflight(
        settings,
        llm_provider=llm_provider,
        semantic_index=semantic_index,
        ocr_backend=ocr_backend,
        work_queue=work_queue,
    )
    available_models, model_listing_message = list_ollama_model_names(settings.accesslab_ollama_url)
    return JSONResponse(
        {
            "status": "ok",
            "db_path": str(settings.db_path),
            "runtime_backend": settings.runtime_backend,
            "runtime_backend_display": settings.runtime_backend_display,
            "runtime_runtime": llm_provider.describe_runtime(),
            "runtime_capabilities": asdict(preflight["runtime_capabilities"]),
            "future_runtime_validation_track": settings.future_runtime_validation_track,
            "llm_ready": llm_ready,
            "llm_message": llm_message,
            "deployment_profile": settings.deployment_profile,
            "deployment_profile_display": settings.deployment_profile_display,
            "deployment_mode": settings.deployment_mode,
            "deployment_mode_display": settings.deployment_mode_display,
            "deployment_mode_summary": settings.deployment_mode_summary,
            "class_space": settings.class_space,
            "training_capture_enabled": settings.training_capture_enabled,
            "training_capture_display": settings.training_capture_display,
            "active_model": settings.accesslab_model,
            "ollama_url": settings.accesslab_ollama_url,
            "available_local_gemma_models": [
                model for model in available_models if model in ALLOWED_GEMMA4_MODELS
            ],
            "ollama_model_listing_message": model_listing_message,
            "profile_model_mapping": PROFILE_MODELS,
            "no_cloud_api_key_required": True,
            "generation_model_family": settings.generation_model_family,
            "generation_model_policy": settings.generation_model_policy,
            "model_explicitly_set": settings.model_explicitly_set,
            "requested_generation_model": settings.requested_generation_model,
            "generation_model_override_ignored": settings.generation_model_override_ignored,
            "generation_model_notice": settings.generation_model_notice,
            "qa_discipline_profile": settings.qa_discipline_profile,
            "qa_discipline_explicitly_set": settings.qa_discipline_explicitly_set,
            "retrieval_requested_mode": settings.retrieval_mode,
            "retrieval_requested_mode_display": settings.retrieval_mode_display,
            "retrieval_mode": retrieval_diagnostics.actual_mode,
            "retrieval_mode_display": retrieval_diagnostics.actual_mode_label,
            "lexical_backend": retrieval_diagnostics.lexical_backend_label,
            "semantic_enabled": settings.semantic_enabled,
            "semantic_model": settings.semantic_embedding_model,
            "semantic_model_family": settings.semantic_model_family,
            "semantic_provider_ready": retrieval_diagnostics.semantic.provider_ready,
            "semantic_retrieval_ready": retrieval_diagnostics.semantic.retrieval_ready,
            "semantic_status_code": retrieval_diagnostics.semantic.code,
            "semantic_status_label": retrieval_diagnostics.semantic.label,
            "semantic_summary": retrieval_diagnostics.semantic.summary,
            "semantic_detail": retrieval_diagnostics.semantic.detail,
            "semantic_backend": retrieval_diagnostics.semantic.backend,
            "embeddinggemma_configured": retrieval_diagnostics.semantic.embeddinggemma_configured,
            "semantic_index_status": retrieval_diagnostics.index_status.status,
            "semantic_index_label": retrieval_diagnostics.index_status.label,
            "semantic_index_summary": retrieval_diagnostics.index_status.summary,
            "semantic_document_count": retrieval_diagnostics.index_status.document_count,
            "semantic_chunk_count": retrieval_diagnostics.index_status.chunk_count,
            "semantic_embedded_chunk_count": retrieval_diagnostics.index_status.embedded_chunk_count,
            "semantic_missing_chunk_count": retrieval_diagnostics.index_status.missing_chunk_count,
            "semantic_last_error_code": retrieval_diagnostics.index_status.last_error_code,
            "semantic_last_error_message": retrieval_diagnostics.index_status.last_error_message,
            "semantic_last_attempted_at": retrieval_diagnostics.index_status.last_attempted_at,
            "semantic_last_completed_at": retrieval_diagnostics.index_status.last_completed_at,
            "ocr_enabled": settings.ocr_enabled,
            "ocr_dpi": settings.ocr_dpi,
            "ocr_min_chars_per_page": settings.ocr_min_chars_per_page,
            "ocr_available": bool(ocr_backend.is_available()),
            "ocr_backend": ocr_backend.describe(),
            "queue": queue_snapshot,
            "preflight": {
                "overall_status": preflight["overall_status"],
                "overall_label": preflight["overall_label"],
                "checks": preflight["checks"],
                "dataset_counts": preflight["dataset_counts"],
            },
        }
    )
