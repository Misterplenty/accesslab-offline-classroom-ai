from __future__ import annotations

from collections import defaultdict
import re
from pathlib import Path
from typing import Protocol

from app.db import db_connection
from app.models.schemas import SearchResult
from app.services.semantic import SQLiteSemanticIndex


DEFAULT_FUSION_K = 60
DEFAULT_CANDIDATE_LIMIT = 8
SEMANTIC_STRONG_MATCH_THRESHOLD = 0.4
RETRIEVAL_MODE_LABELS = {
    "lexical": "Lexical only",
    "semantic": "Semantic only",
    "hybrid": "Hybrid",
}


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower(), flags=re.UNICODE)


def sanitize_fts_query(query: str) -> str:
    tokens = [token for token in tokenize(query) if len(token) > 1]
    if not tokens:
        return ""
    return " OR ".join(f'"{token}"' for token in tokens[:8])


def overlap_ratio(query: str, text: str) -> float:
    query_terms = {token for token in tokenize(query) if len(token) > 2}
    if not query_terms:
        return 0.0
    text_terms = set(tokenize(text))
    return len(query_terms & text_terms) / len(query_terms)


def is_weak_retrieval(query: str, results: list[SearchResult]) -> bool:
    if not results:
        return True
    if any(
        result.semantic_similarity is not None and result.semantic_similarity >= SEMANTIC_STRONG_MATCH_THRESHOLD
        for result in results
    ):
        return False
    best_overlap = max(overlap_ratio(query, result.chunk_text) for result in results)
    return best_overlap < 0.3


class RetrievalBackend(Protocol):
    def search(self, query: str, *, limit: int = 4) -> list[SearchResult]:
        ...

    def current_mode(self) -> tuple[str, str]:
        ...


class SQLiteFTSRetrieval:
    def __init__(self, db_path: Path, *, class_space: str | None = None) -> None:
        self.db_path = db_path
        self.class_space = (class_space or "").strip()

    def current_mode(self) -> tuple[str, str]:
        return "lexical", RETRIEVAL_MODE_LABELS["lexical"]

    def search(self, query: str, *, limit: int = 4) -> list[SearchResult]:
        search_query = sanitize_fts_query(query)
        if not search_query:
            return []

        lexical_params: list[object] = [search_query]
        lexical_join = ""
        lexical_where = "WHERE document_chunks_fts MATCH ?"
        if self.class_space:
            lexical_join = "JOIN documents AS d ON d.id = document_chunks_fts.document_id"
            lexical_where += " AND d.class_space = ?"
            lexical_params.append(self.class_space)
        lexical_params.append(limit)

        with db_connection(self.db_path) as connection:
            rows = connection.execute(
                f"""
                SELECT
                    chunk_id,
                    source_file,
                    page_number,
                    chunk_text,
                    snippet(document_chunks_fts, 4, '[', ']', '...', 18) AS snippet,
                    bm25(document_chunks_fts) AS score
                FROM document_chunks_fts
                {lexical_join}
                {lexical_where}
                ORDER BY score
                LIMIT ?
                """,
                lexical_params,
            ).fetchall()

            if not rows:
                like_terms = [token for token in tokenize(query) if len(token) > 2][:5]
                if not like_terms:
                    return []
                filters = " OR ".join("LOWER(chunk_text) LIKE ?" for _ in like_terms)
                like_params: list[object] = [f"%{term.lower()}%" for term in like_terms]
                like_join = ""
                like_where = filters
                if self.class_space:
                    like_join = "JOIN documents AS d ON d.id = c.document_id"
                    like_where = f"d.class_space = ? AND ({filters})"
                    like_params.insert(0, self.class_space)
                like_params.append(limit)
                rows = connection.execute(
                    f"""
                    SELECT
                        c.chunk_id,
                        c.source_file,
                        c.page_number,
                        c.chunk_text,
                        substr(c.chunk_text, 1, 240) AS snippet,
                        999.0 AS score
                    FROM document_chunks AS c
                    {like_join}
                    WHERE {like_where}
                    ORDER BY c.created_at DESC
                    LIMIT ?
                    """,
                    like_params,
                ).fetchall()

        return [
            SearchResult(
                chunk_id=row["chunk_id"],
                source_file=row["source_file"],
                page_number=row["page_number"],
                chunk_text=row["chunk_text"],
                snippet=row["snippet"] or row["chunk_text"][:240],
                score=float(row["score"]),
                match_source="lexical",
            )
            for row in rows
        ]


class HybridSQLiteRetrieval:
    def __init__(
        self,
        db_path: Path,
        *,
        lexical_backend: SQLiteFTSRetrieval | None = None,
        semantic_index: SQLiteSemanticIndex | None = None,
        fusion_k: int = DEFAULT_FUSION_K,
        retrieval_mode: str = "hybrid",
        class_space: str | None = None,
    ) -> None:
        self.db_path = db_path
        self.class_space = (class_space or "").strip()
        self.lexical_backend = lexical_backend or SQLiteFTSRetrieval(
            db_path,
            class_space=self.class_space,
        )
        self.semantic_index = semantic_index
        self.fusion_k = max(1, int(fusion_k))
        self.retrieval_mode = retrieval_mode if retrieval_mode in RETRIEVAL_MODE_LABELS else "hybrid"

    def current_mode(self) -> tuple[str, str]:
        if self.retrieval_mode == "lexical":
            return "lexical", RETRIEVAL_MODE_LABELS["lexical"]
        if self.semantic_index is None or not self.semantic_index.is_available():
            return "lexical", RETRIEVAL_MODE_LABELS["lexical"]
        self.semantic_index.ensure_embeddings()
        counts = self.semantic_index.index_counts()
        if int(counts.get("embedded_chunk_count", 0)) <= 0:
            return "lexical", RETRIEVAL_MODE_LABELS["lexical"]
        return self.retrieval_mode, RETRIEVAL_MODE_LABELS[self.retrieval_mode]

    def search(self, query: str, *, limit: int = 4) -> list[SearchResult]:
        current_mode, _ = self.current_mode()
        candidate_limit = max(limit * 2, DEFAULT_CANDIDATE_LIMIT)
        lexical_results = self.lexical_backend.search(query, limit=candidate_limit)
        semantic_results = []
        if self.semantic_index is not None:
            semantic_results = self.semantic_index.search(query, limit=candidate_limit)

        if current_mode == "lexical":
            return lexical_results[:limit]
        if current_mode == "semantic":
            return semantic_results[:limit]
        if not lexical_results:
            return semantic_results[:limit]
        if not semantic_results:
            return lexical_results[:limit]
        return fuse_results(lexical_results, semantic_results, limit=limit, fusion_k=self.fusion_k)


def fuse_results(
    lexical_results: list[SearchResult],
    semantic_results: list[SearchResult],
    *,
    limit: int,
    fusion_k: int = DEFAULT_FUSION_K,
) -> list[SearchResult]:
    fused_scores: dict[str, float] = defaultdict(float)
    sources: dict[str, set[str]] = defaultdict(set)
    canonical: dict[str, SearchResult] = {}
    semantic_similarity: dict[str, float] = {}

    for source_name, results in (("lexical", lexical_results), ("semantic", semantic_results)):
        for rank, result in enumerate(results, start=1):
            fused_scores[result.chunk_id] += 1.0 / (fusion_k + rank)
            sources[result.chunk_id].add(source_name)
            if source_name == "lexical" or result.chunk_id not in canonical:
                canonical[result.chunk_id] = result
            if result.semantic_similarity is not None:
                semantic_similarity[result.chunk_id] = max(
                    semantic_similarity.get(result.chunk_id, float("-inf")),
                    result.semantic_similarity,
                )

    ranked_chunk_ids = sorted(
        fused_scores,
        key=lambda chunk_id: (
            -fused_scores[chunk_id],
            -semantic_similarity.get(chunk_id, float("-inf")),
            canonical[chunk_id].chunk_id,
        ),
    )

    merged: list[SearchResult] = []
    for chunk_id in ranked_chunk_ids[:limit]:
        result = canonical[chunk_id]
        matched_sources = sources[chunk_id]
        merged.append(
            SearchResult(
                chunk_id=result.chunk_id,
                source_file=result.source_file,
                page_number=result.page_number,
                chunk_text=result.chunk_text,
                snippet=result.snippet,
                score=fused_scores[chunk_id],
                match_source="hybrid" if len(matched_sources) > 1 else next(iter(matched_sources)),
                semantic_similarity=semantic_similarity.get(chunk_id),
            )
        )
    return merged
