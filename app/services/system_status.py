from __future__ import annotations

from app.db import get_semantic_index_meta, semantic_index_counts
from app.models.schemas import (
    RetrievalDiagnostics,
    SemanticAvailability,
    SemanticIndexStatus,
)
from app.services.retrieval import RETRIEVAL_MODE_LABELS
from app.services.semantic import (
    SEMANTIC_STATUS_DISABLED,
    SEMANTIC_STATUS_EMBEDDING_GENERATION_ERROR,
    SEMANTIC_STATUS_MODEL_NOT_INSTALLED,
    SEMANTIC_STATUS_OK,
    SEMANTIC_STATUS_PROVIDER_CONNECTION_FAILED,
    SQLiteSemanticIndex,
    is_embeddinggemma_model,
)


INDEX_STATUS_LABELS = {
    "not_indexed": "Not indexed",
    "indexing_pending": "Indexing pending",
    "indexed": "Indexed",
    "indexing_failed": "Indexing failed",
}

SEMANTIC_STATUS_LABELS = {
    SEMANTIC_STATUS_OK: "Ready",
    SEMANTIC_STATUS_DISABLED: "Disabled",
    SEMANTIC_STATUS_MODEL_NOT_INSTALLED: "Model not installed",
    SEMANTIC_STATUS_PROVIDER_CONNECTION_FAILED: "Provider connection failed",
    "indexing_unavailable": "Indexing unavailable",
    SEMANTIC_STATUS_EMBEDDING_GENERATION_ERROR: "Embedding generation error",
}


def build_retrieval_diagnostics(settings, semantic_index: SQLiteSemanticIndex) -> RetrievalDiagnostics:
    counts = semantic_index_counts(
        settings.db_path,
        model_name=semantic_index.model_name,
        class_space=getattr(settings, "class_space", None),
    )
    meta = get_semantic_index_meta(settings.db_path)
    index_status = _build_index_status(meta=meta, counts=counts)
    semantic = _build_semantic_availability(
        settings=settings,
        semantic_index=semantic_index,
        counts=counts,
        index_status=index_status,
    )

    requested_mode = settings.retrieval_mode
    requested_mode_label = settings.retrieval_mode_display
    actual_mode = _resolve_actual_retrieval_mode(
        requested_mode=requested_mode,
        semantic=semantic,
    )
    return RetrievalDiagnostics(
        requested_mode=requested_mode,
        requested_mode_label=requested_mode_label,
        actual_mode=actual_mode,
        actual_mode_label=RETRIEVAL_MODE_LABELS.get(
            actual_mode,
            actual_mode.replace("-", " ").title(),
        ),
        lexical_backend_label="SQLite FTS5",
        semantic=semantic,
        index_status=index_status,
    )


def _build_index_status(*, meta: dict, counts: dict[str, int]) -> SemanticIndexStatus:
    chunk_count = int(counts["chunk_count"])
    embedded_chunk_count = int(counts["embedded_chunk_count"])
    missing_chunk_count = int(counts["missing_chunk_count"])

    status = "not_indexed"
    summary = "No class materials have been embedded for semantic retrieval yet."
    if chunk_count == 0:
        status = "not_indexed"
        summary = "No class materials are indexed yet, so the semantic index has nothing to build."
    elif embedded_chunk_count >= chunk_count:
        status = "indexed"
        summary = (
            f"{embedded_chunk_count} evidence chunk"
            f"{'' if embedded_chunk_count == 1 else 's'} are ready for semantic retrieval."
        )
    elif str(meta.get("last_error_code") or "").strip():
        status = "indexing_failed"
        summary = (
            "Semantic indexing hit an error. Lexical retrieval stays available while the embedding "
            "index is repaired."
        )
    else:
        status = "indexing_pending"
        summary = (
            f"{missing_chunk_count} evidence chunk"
            f"{'' if missing_chunk_count == 1 else 's'} still need embeddings."
        )

    return SemanticIndexStatus(
        status=status,
        label=INDEX_STATUS_LABELS[status],
        summary=summary,
        document_count=int(counts["document_count"]),
        chunk_count=chunk_count,
        embedded_chunk_count=embedded_chunk_count,
        missing_chunk_count=missing_chunk_count,
        last_error_code=str(meta.get("last_error_code") or ""),
        last_error_message=str(meta.get("last_error_message") or ""),
        last_attempted_at=str(meta.get("last_attempted_at") or ""),
        last_completed_at=str(meta.get("last_completed_at") or ""),
    )


def _build_semantic_availability(
    *,
    settings,
    semantic_index: SQLiteSemanticIndex,
    counts: dict[str, int],
    index_status: SemanticIndexStatus,
) -> SemanticAvailability:
    provider_code, provider_message = semantic_index.health_status()
    provider_ready = provider_code == SEMANTIC_STATUS_OK
    retrieval_ready = False
    code = provider_code
    detail = provider_message

    if settings.semantic_enabled == "off":
        code = SEMANTIC_STATUS_DISABLED
        detail = "Semantic retrieval is disabled by configuration."
    elif not provider_ready:
        code = provider_code
    elif int(counts["chunk_count"]) == 0:
        code = "indexing_unavailable"
        detail = "EmbeddingGemma is healthy, but no class materials have been indexed yet."
    elif index_status.status == "indexing_failed" and int(counts["embedded_chunk_count"]) == 0:
        code = index_status.last_error_code or SEMANTIC_STATUS_EMBEDDING_GENERATION_ERROR
        detail = index_status.last_error_message or index_status.summary
    elif int(counts["embedded_chunk_count"]) == 0:
        code = "indexing_unavailable"
        detail = "Semantic retrieval is waiting for the shared embedding index to finish building."
    else:
        code = SEMANTIC_STATUS_OK
        retrieval_ready = True
        detail = provider_message

    if retrieval_ready and index_status.status == "indexing_pending":
        detail = (
            f"{provider_message} Some newer material is still indexing "
            f"({index_status.missing_chunk_count} pending chunk"
            f"{'' if index_status.missing_chunk_count == 1 else 's'})."
        )

    if code == SEMANTIC_STATUS_OK:
        summary = (
            f"{settings.semantic_model_family} is ready and the shared embedding index is usable."
        )
    elif code == SEMANTIC_STATUS_DISABLED:
        summary = "Semantic retrieval is turned off, so AccessLab is running lexical-only search."
    elif code == SEMANTIC_STATUS_MODEL_NOT_INSTALLED:
        summary = "EmbeddingGemma is configured, but the local embedding model is not installed."
    elif code == SEMANTIC_STATUS_PROVIDER_CONNECTION_FAILED:
        summary = "The local embedding provider is not responding."
    elif code == "indexing_unavailable":
        summary = "EmbeddingGemma is healthy, but the semantic index is not ready yet."
    else:
        summary = "EmbeddingGemma is configured, but embedding generation failed."

    return SemanticAvailability(
        provider_ready=provider_ready,
        retrieval_ready=retrieval_ready,
        code=code,
        label=SEMANTIC_STATUS_LABELS.get(code, code.replace("_", " ").title()),
        summary=summary,
        detail=detail,
        backend=semantic_index.describe(),
        model_name=semantic_index.model_name,
        model_family=settings.semantic_model_family,
        embeddinggemma_configured=is_embeddinggemma_model(settings.semantic_embedding_model),
    )


def _resolve_actual_retrieval_mode(
    *,
    requested_mode: str,
    semantic: SemanticAvailability,
) -> str:
    if requested_mode == "lexical":
        return "lexical"
    if semantic.retrieval_ready:
        return requested_mode
    return "lexical"
