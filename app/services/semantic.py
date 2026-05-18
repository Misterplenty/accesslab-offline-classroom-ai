from __future__ import annotations

import heapq
import logging
import math
import struct
from pathlib import Path
from typing import Protocol, Sequence

import requests

from app.db import (
    db_connection,
    mark_semantic_index_failed,
    mark_semantic_index_indexed,
    mark_semantic_index_pending,
    semantic_index_counts,
    utc_now_iso,
)
from app.models.schemas import SearchResult
from app.services.ollama_runtime import build_missing_model_store_hint


logger = logging.getLogger(__name__)


DEFAULT_SEMANTIC_ENABLED = "auto"
SEMANTIC_ENABLED_VALUES = frozenset({"auto", "off"})
DEFAULT_SEMANTIC_EMBEDDING_MODEL = "embeddinggemma"
DEFAULT_SEMANTIC_BATCH_SIZE = 24
DEFAULT_EMBEDDINGGEMMA_RETRIEVAL_TASK = "search result"

SEMANTIC_STATUS_OK = "ok"
SEMANTIC_STATUS_DISABLED = "disabled"
SEMANTIC_STATUS_MODEL_NOT_INSTALLED = "model_not_installed"
SEMANTIC_STATUS_PROVIDER_CONNECTION_FAILED = "provider_connection_failed"
SEMANTIC_STATUS_EMBEDDING_GENERATION_ERROR = "embedding_generation_error"


def build_semantic_setup_fix_message(model_name: str = DEFAULT_SEMANTIC_EMBEDDING_MODEL) -> str:
    model = (model_name or DEFAULT_SEMANTIC_EMBEDDING_MODEL).strip()
    return (
        f"Run `ollama pull {model}` against the same user/account that runs AccessLab, "
        "verify the active Ollama store with `ollama list`, restart AccessLab if it was already running, "
        "then check `/healthz` for `semantic_provider_ready: true` and "
        "`semantic_retrieval_ready: true` after class materials have been indexed."
    )


class EmbeddingError(RuntimeError):
    """Raised when the local embedding backend cannot satisfy a request."""

    def __init__(self, message: str, *, code: str = SEMANTIC_STATUS_EMBEDDING_GENERATION_ERROR) -> None:
        super().__init__(message)
        self.code = code


class EmbeddingProvider(Protocol):
    model_name: str

    def is_available(self) -> bool:
        ...

    def unavailable_reason(self) -> str:
        ...

    def health_status(self) -> tuple[str, str]:
        ...

    def describe(self) -> str:
        ...

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        ...


class NullEmbeddingProvider:
    def __init__(self, reason: str = "Semantic retrieval disabled.") -> None:
        self.reason = reason
        self.model_name = ""

    def is_available(self) -> bool:
        return False

    def unavailable_reason(self) -> str:
        return self.reason

    def health_status(self) -> tuple[str, str]:
        return SEMANTIC_STATUS_DISABLED, self.reason

    def describe(self) -> str:
        return "disabled"

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        raise EmbeddingError(self.reason, code=SEMANTIC_STATUS_DISABLED)


class OllamaEmbeddingProvider:
    def __init__(self, *, base_url: str, model_name: str, timeout_seconds: int = 45) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name.strip()
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        ok, _, _ = self._health()
        return ok

    def unavailable_reason(self) -> str:
        ok, _, message = self._health()
        return "" if ok else message

    def health_status(self) -> tuple[str, str]:
        ok, code, message = self._health()
        if ok:
            return SEMANTIC_STATUS_OK, message
        return code, message

    def describe(self) -> str:
        return f"ollama:{self.model_name}"

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        cleaned = [text.strip() for text in texts if text and text.strip()]
        if not cleaned:
            return []

        payload = {
            "model": self.model_name,
            "input": cleaned,
            "truncate": True,
        }
        try:
            response = requests.post(
                f"{self.base_url}/api/embed",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise EmbeddingError(
                "Local semantic retrieval is unavailable. Start `ollama serve` and pull "
                f"`{self.model_name}` to enable hybrid retrieval.",
                code=SEMANTIC_STATUS_PROVIDER_CONNECTION_FAILED,
            ) from exc

        body = response.json()
        embeddings = body.get("embeddings")
        if not isinstance(embeddings, list):
            raise EmbeddingError("Ollama returned an unexpected embedding response.")
        if len(embeddings) != len(cleaned):
            raise EmbeddingError("Ollama returned an unexpected number of embeddings.")
        return [_normalize_vector(vector) for vector in embeddings]

    def _health(self) -> tuple[bool, str, str]:
        if not self.model_name:
            return False, SEMANTIC_STATUS_MODEL_NOT_INSTALLED, "No local embedding model is configured."
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()
        except requests.RequestException:
            return (
                False,
                SEMANTIC_STATUS_PROVIDER_CONNECTION_FAILED,
                "Ollama is not responding. Run `ollama serve` to enable local semantic retrieval.",
            )

        models = response.json().get("models", [])
        installed = {model.get("name", "") for model in models}
        accepted_names = {self.model_name}
        if ":" not in self.model_name:
            accepted_names.add(f"{self.model_name}:latest")
        if not (installed & accepted_names):
            extra_hint = build_missing_model_store_hint(self.model_name)
            if extra_hint:
                return (
                    False,
                    SEMANTIC_STATUS_MODEL_NOT_INSTALLED,
                    f"Ollama is running, but embedding model `{self.model_name}` is not installed in the active store. "
                    f"{extra_hint} {build_semantic_setup_fix_message(self.model_name)}",
                )
            return (
                False,
                SEMANTIC_STATUS_MODEL_NOT_INSTALLED,
                f"Ollama is running, but embedding model `{self.model_name}` is not installed. "
                f"{build_semantic_setup_fix_message(self.model_name)}",
            )
        return True, SEMANTIC_STATUS_OK, f"Ready with `{self.model_name}`."


def is_embeddinggemma_model(model_name: str) -> bool:
    normalized = (model_name or "").strip().lower()
    if not normalized:
        return False
    return normalized.split(":", 1)[0] == "embeddinggemma"


def build_query_embedding_input(query_text: str, *, model_name: str) -> str:
    cleaned = query_text.strip()
    if not cleaned:
        return ""
    if is_embeddinggemma_model(model_name):
        return f"task: {DEFAULT_EMBEDDINGGEMMA_RETRIEVAL_TASK} | query: {cleaned}"
    return cleaned


def build_document_embedding_input(
    chunk_text: str,
    *,
    model_name: str,
    title: str | None = None,
) -> str:
    cleaned = chunk_text.strip()
    if not cleaned:
        return ""
    if is_embeddinggemma_model(model_name):
        resolved_title = (title or "").strip() or "none"
        return f"title: {resolved_title} | text: {cleaned}"
    return cleaned


def create_embedding_provider(*, enabled: str, base_url: str, model_name: str) -> EmbeddingProvider:
    if enabled == "off":
        return NullEmbeddingProvider("Semantic retrieval is disabled by configuration.")
    return OllamaEmbeddingProvider(base_url=base_url, model_name=model_name)


class SQLiteSemanticIndex:
    """Optional SQLite-backed semantic lookup keyed by existing chunk IDs.

    The vectors live in ``chunk_embeddings`` so retrieval can stay grounded in
    the existing ``document_chunks`` rows and all citation metadata keeps
    flowing through the unchanged chunk/page/source path.
    """

    def __init__(
        self,
        *,
        db_path: Path,
        embedding_provider: EmbeddingProvider,
        batch_size: int = DEFAULT_SEMANTIC_BATCH_SIZE,
        class_space: str | None = None,
    ) -> None:
        self.db_path = db_path
        self.embedding_provider = embedding_provider
        self.batch_size = max(1, int(batch_size))
        self.class_space = (class_space or "").strip()
        self._unavailable_logged = False

    @property
    def model_name(self) -> str:
        return self.embedding_provider.model_name

    def describe(self) -> str:
        return self.embedding_provider.describe()

    def is_available(self) -> bool:
        return self.embedding_provider.is_available()

    def unavailable_reason(self) -> str:
        return self.embedding_provider.unavailable_reason()

    def health_status(self) -> tuple[str, str]:
        return self.embedding_provider.health_status()

    def index_counts(self) -> dict[str, int]:
        return semantic_index_counts(
            self.db_path,
            model_name=self.model_name,
            class_space=self.class_space or None,
        )

    def index_chunk_rows(self, chunk_rows: Sequence[tuple[str, str] | tuple[str, str, str | None]]) -> int:
        if not chunk_rows:
            return 0
        if not self.embedding_provider.is_available():
            self._log_unavailable_once()
            return 0

        mark_semantic_index_pending(self.db_path, model_name=self.model_name)
        stored = 0
        normalized_rows = [_normalize_chunk_row(row) for row in chunk_rows]
        for batch in _batched(normalized_rows, self.batch_size):
            try:
                embeddings = self.embedding_provider.embed_texts(
                    [
                        build_document_embedding_input(
                            chunk_text,
                            model_name=self.model_name,
                            title=title,
                        )
                        for _, chunk_text, title in batch
                    ]
                )
            except EmbeddingError as exc:
                logger.warning("Semantic indexing failed; falling back to lexical-only retrieval: %s", exc)
                mark_semantic_index_failed(
                    self.db_path,
                    model_name=self.model_name,
                    error_code=exc.code,
                    error_message=str(exc),
                )
                return stored
            self._upsert_embeddings(
                (chunk_id, embedding)
                for (chunk_id, _, _), embedding in zip(batch, embeddings, strict=True)
            )
            stored += len(batch)
        mark_semantic_index_indexed(self.db_path, model_name=self.model_name)
        return stored

    def ensure_embeddings(self) -> int:
        missing = self._missing_chunk_rows()
        if not missing:
            return 0
        logger.info("Backfilling %d missing semantic embedding(s) for hybrid retrieval.", len(missing))
        return self.index_chunk_rows(
            [
                (
                    row["chunk_id"],
                    row["chunk_text"],
                    row["source_file"],
                )
                for row in missing
            ]
        )

    def search(self, query: str, *, limit: int = 8) -> list[SearchResult]:
        cleaned = query.strip()
        if not cleaned:
            return []
        if not self.embedding_provider.is_available():
            self._log_unavailable_once()
            return []

        self.ensure_embeddings()

        try:
            query_vector = self.embedding_provider.embed_texts(
                [build_query_embedding_input(cleaned, model_name=self.model_name)]
            )[0]
        except (EmbeddingError, IndexError) as exc:
            logger.warning("Semantic query embedding failed; using lexical retrieval only: %s", exc)
            if isinstance(exc, EmbeddingError):
                mark_semantic_index_failed(
                    self.db_path,
                    model_name=self.model_name,
                    error_code=exc.code,
                    error_message=str(exc),
                )
            return []

        with db_connection(self.db_path) as connection:
            params: list[object] = [self.model_name]
            class_space_filter = ""
            if self.class_space:
                class_space_filter = " AND d.class_space = ?"
                params.append(self.class_space)
            rows = connection.execute(
                f"""
                SELECT
                    c.chunk_id,
                    c.source_file,
                    c.page_number,
                    c.chunk_text,
                    e.vector_dim,
                    e.embedding_vector
                FROM chunk_embeddings AS e
                JOIN document_chunks AS c ON c.chunk_id = e.chunk_id
                JOIN documents AS d ON d.id = c.document_id
                WHERE e.embedding_model = ?{class_space_filter}
                """,
                params,
            ).fetchall()

        if not rows:
            return []

        scored: list[tuple[float, object]] = []
        for row in rows:
            vector = _deserialize_embedding(row["embedding_vector"], row["vector_dim"])
            similarity = _dot_product(query_vector, vector)
            scored.append((similarity, row))

        best = heapq.nlargest(limit, scored, key=lambda item: item[0])
        return [
            SearchResult(
                chunk_id=row["chunk_id"],
                source_file=row["source_file"],
                page_number=row["page_number"],
                chunk_text=row["chunk_text"],
                snippet=row["chunk_text"][:240],
                score=similarity,
                match_source="semantic",
                semantic_similarity=similarity,
            )
            for similarity, row in best
        ]

    def _missing_chunk_rows(self):
        with db_connection(self.db_path) as connection:
            params: list[object] = [self.model_name]
            class_space_filter = ""
            if self.class_space:
                class_space_filter = " AND d.class_space = ?"
                params.append(self.class_space)
            return connection.execute(
                f"""
                SELECT c.chunk_id, c.chunk_text, c.source_file
                FROM document_chunks AS c
                JOIN documents AS d ON d.id = c.document_id
                LEFT JOIN chunk_embeddings AS e ON e.chunk_id = c.chunk_id
                WHERE (e.chunk_id IS NULL OR e.embedding_model != ?){class_space_filter}
                ORDER BY c.id
                """,
                params,
            ).fetchall()

    def _upsert_embeddings(self, rows: Sequence[tuple[str, Sequence[float]]]) -> None:
        payload = [
            (
                chunk_id,
                self.model_name,
                len(embedding),
                _serialize_embedding(embedding),
                utc_now_iso(),
            )
            for chunk_id, embedding in rows
        ]
        if not payload:
            return
        with db_connection(self.db_path) as connection:
            connection.executemany(
                """
                INSERT INTO chunk_embeddings (
                    chunk_id,
                    embedding_model,
                    vector_dim,
                    embedding_vector,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    embedding_model = excluded.embedding_model,
                    vector_dim = excluded.vector_dim,
                    embedding_vector = excluded.embedding_vector,
                    created_at = excluded.created_at
                """,
                payload,
            )

    def _log_unavailable_once(self) -> None:
        if self._unavailable_logged:
            return
        logger.warning(
            "Semantic retrieval unavailable; falling back to FTS-only mode. %s",
            self.embedding_provider.unavailable_reason(),
        )
        self._unavailable_logged = True


def _batched(
    items: list[tuple[str, str, str | None]],
    size: int,
) -> list[list[tuple[str, str, str | None]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _normalize_chunk_row(
    row: tuple[str, str] | tuple[str, str, str | None],
) -> tuple[str, str, str | None]:
    if len(row) == 2:
        chunk_id, chunk_text = row
        return chunk_id, chunk_text, None
    chunk_id, chunk_text, title = row
    return chunk_id, chunk_text, title


def _normalize_vector(values: Sequence[float]) -> list[float]:
    vector = [float(value) for value in values]
    if not vector:
        raise EmbeddingError("Embedding backend returned an empty vector.")
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


def _serialize_embedding(values: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def _deserialize_embedding(blob: bytes, dimension: int) -> tuple[float, ...]:
    if dimension <= 0:
        return ()
    return struct.unpack(f"<{dimension}f", bytes(blob))


def _dot_product(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(left_value * right_value for left_value, right_value in zip(left, right, strict=False))
