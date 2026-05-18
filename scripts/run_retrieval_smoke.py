from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from app.config import Settings
from app.db import init_db
from app.models.schemas import SearchResult
from app.services.document_ingest import DocumentIngestService
from app.services.retrieval import HybridSQLiteRetrieval, SQLiteFTSRetrieval
from app.services.semantic import SQLiteSemanticIndex, create_embedding_provider
from app.services.system_status import build_retrieval_diagnostics


DEFAULT_FIXTURE_DOCUMENTS: tuple[tuple[str, str], ...] = (
    (
        "retrieval_smoke_distractor.md",
        "The worksheet lists the numbers beside question 3 so students can copy them.",
    ),
    (
        "retrieval_smoke_relevant.md",
        "Add the values together to get the final total for the answer.",
    ),
)

DEFAULT_QUESTION = "How do I combine the numbers?"
DEFAULT_EXPECTED_SUBSTRING = "add the values together to get the final total"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproducible lexical, semantic, and hybrid retrieval proof for local classroom evidence."
    )
    parser.add_argument(
        "--document",
        type=Path,
        default=None,
        help="Optional local file to ingest instead of the built-in paraphrase fixture.",
    )
    parser.add_argument(
        "--question",
        default=DEFAULT_QUESTION,
        help="Question to run against the ingested content.",
    )
    parser.add_argument(
        "--expected-substring",
        default=DEFAULT_EXPECTED_SUBSTRING,
        help="Lower-cased text expected in the top supported result.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPO_ROOT / "data" / "retrieval-smoke",
        help="Isolated data directory for the smoke run.",
    )
    parser.add_argument(
        "--keep-data-dir",
        action="store_true",
        help="Keep the smoke data directory instead of clearing it before each run.",
    )
    parser.add_argument(
        "--output-json",
        default=str(REPO_ROOT / "reports" / "semantic_retrieval_proof_latest.json"),
    )
    parser.add_argument(
        "--output-markdown",
        default=str(REPO_ROOT / "reports" / "semantic_retrieval_proof_latest.md"),
    )
    return parser.parse_args()


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _prepare_fixture_documents(data_dir: Path, source_path: Path | None) -> list[Path]:
    uploads_dir = data_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    if source_path is not None:
        target = uploads_dir / source_path.name
        shutil.copy2(source_path, target)
        return [target]

    targets: list[Path] = []
    for file_name, content in DEFAULT_FIXTURE_DOCUMENTS:
        target = uploads_dir / file_name
        target.write_text(content, encoding="utf-8")
        targets.append(target)
    return targets


def _result_row(result: SearchResult) -> dict[str, Any]:
    return {
        "chunk_id": result.chunk_id,
        "source_file": result.source_file,
        "page_number": result.page_number,
        "snippet": result.snippet,
        "score": result.score,
        "match_source": result.match_source,
        "semantic_similarity": result.semantic_similarity,
        "chunk_text": result.chunk_text,
    }


def _contains_expected(results: list[SearchResult], expected: str) -> bool:
    if not expected:
        return bool(results)
    return any(expected in result.chunk_text.lower() for result in results)


def _top_contains_expected(results: list[SearchResult], expected: str) -> bool:
    if not results:
        return False
    if not expected:
        return True
    return expected in results[0].chunk_text.lower()


def _ids(results: list[SearchResult]) -> list[str]:
    return [result.chunk_id for result in results]


def _mode_proof(
    *,
    requested_mode: str,
    effective_mode: str,
    effective_label: str,
    results: list[SearchResult],
    expected: str,
) -> dict[str, Any]:
    return {
        "requested_mode": requested_mode,
        "effective_mode": effective_mode,
        "effective_mode_label": effective_label,
        "top_chunk_id": results[0].chunk_id if results else "",
        "top_source_file": results[0].source_file if results else "",
        "top_match_source": results[0].match_source if results else "",
        "top_semantic_similarity": results[0].semantic_similarity if results else None,
        "top_contains_expected": _top_contains_expected(results, expected),
        "any_result_contains_expected": _contains_expected(results, expected),
        "result_count": len(results),
        "results": [_result_row(result) for result in results],
    }


def _build_markdown(report: dict[str, Any]) -> str:
    comparison = report["comparison"]
    lines = [
        "# AccessLab Semantic Retrieval Proof",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Runtime backend: {report['runtime_backend']}",
        f"- Deployment mode: {report['deployment_mode']}",
        f"- Model tier: {report['model_tier']}",
        f"- Semantic model: {report['semantic_model']}",
        f"- Semantic status: {report['semantic_status_label']} ({report['semantic_status_code']})",
        f"- Semantic retrieval ready: {report['semantic_retrieval_ready']}",
        f"- Question: {report['question']}",
        f"- Expected evidence substring: `{report['expected_substring']}`",
        "",
        "## Retrieval Modes",
        "",
        "| Requested | Effective | Top chunk | Top source | Top expected | Any expected | Results |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for mode_name in ("lexical", "semantic", "hybrid"):
        proof = report["modes"][mode_name]
        lines.append(
            f"| {proof['requested_mode']} | {proof['effective_mode_label']} | "
            f"{proof['top_chunk_id'] or 'none'} | {proof['top_source_file'] or 'none'} | "
            f"{proof['top_contains_expected']} | {proof['any_result_contains_expected']} | "
            f"{proof['result_count']} |"
        )
    lines.extend(
        [
            "",
            "## Comparison Summary",
            "",
            f"- Hybrid improved expected-evidence support over lexical: {comparison['hybrid_improved_expected_support_over_lexical']}",
            f"- Semantic changed retrieved chunks versus lexical: {comparison['semantic_changed_chunks_vs_lexical']}",
            f"- Hybrid changed retrieved chunks versus lexical: {comparison['hybrid_changed_chunks_vs_lexical']}",
            f"- Semantic neutral or failed: {comparison['semantic_neutral_or_failed']}",
            f"- Overall result: {report['overall_result']}",
            "",
            "## Honest Limits",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["honest_limits"])
    lines.append("")
    for mode_name in ("lexical", "semantic", "hybrid"):
        proof = report["modes"][mode_name]
        lines.extend([f"## {mode_name.title()} Results", ""])
        if not proof["results"]:
            lines.extend(["No results.", ""])
            continue
        for index, result in enumerate(proof["results"], start=1):
            similarity = result["semantic_similarity"]
            similarity_text = f", semantic_similarity={similarity:.4f}" if isinstance(similarity, float) else ""
            lines.extend(
                [
                    f"{index}. `{result['chunk_id']}` from `{result['source_file']}` "
                    f"(match={result['match_source']}{similarity_text})",
                    f"   {result['snippet']}",
                    "",
                ]
            )
    return "\n".join(lines)


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    settings = Settings()
    data_dir = args.data_dir.expanduser().resolve()
    if data_dir.exists() and not args.keep_data_dir:
        shutil.rmtree(data_dir, ignore_errors=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    db_path = data_dir / "accesslab.db"
    init_db(db_path)

    source_path = args.document.expanduser().resolve() if args.document is not None else None
    if source_path is not None and not source_path.exists():
        raise FileNotFoundError(f"document not found: {source_path}")

    stored_paths = _prepare_fixture_documents(data_dir, source_path)
    semantic_index = SQLiteSemanticIndex(
        db_path=db_path,
        embedding_provider=create_embedding_provider(
            enabled=settings.semantic_enabled,
            base_url=settings.accesslab_ollama_url,
            model_name=settings.semantic_embedding_model,
        ),
        class_space=settings.class_space,
    )
    ingest_service = DocumentIngestService(
        uploads_dir=data_dir / "uploads",
        db_path=db_path,
        semantic_index=semantic_index,
    )
    summaries = [
        ingest_service.ingest_file(
            stored_path=stored_path,
            original_name=stored_path.name,
            class_space=settings.class_space,
        )
        for stored_path in stored_paths
    ]

    lexical_backend = SQLiteFTSRetrieval(db_path, class_space=settings.class_space)
    semantic_backend = HybridSQLiteRetrieval(
        db_path,
        semantic_index=semantic_index,
        retrieval_mode="semantic",
        class_space=settings.class_space,
    )
    hybrid_backend = HybridSQLiteRetrieval(
        db_path,
        semantic_index=semantic_index,
        retrieval_mode="hybrid",
        class_space=settings.class_space,
    )
    expected = args.expected_substring.strip().lower()

    lexical_results = lexical_backend.search(args.question, limit=4)
    semantic_results = semantic_backend.search(args.question, limit=4)
    hybrid_results = hybrid_backend.search(args.question, limit=4)
    semantic_mode, semantic_label = semantic_backend.current_mode()
    hybrid_mode, hybrid_label = hybrid_backend.current_mode()

    diag_settings = type("RetrievalProofSettings", (), {})()
    diag_settings.db_path = db_path
    diag_settings.retrieval_mode = "hybrid"
    diag_settings.retrieval_mode_display = "Hybrid"
    diag_settings.semantic_embedding_model = settings.semantic_embedding_model
    diag_settings.semantic_model_family = settings.semantic_model_family
    diag_settings.semantic_enabled = settings.semantic_enabled
    diag_settings.class_space = settings.class_space
    diagnostics = build_retrieval_diagnostics(diag_settings, semantic_index)

    lexical_expected = _top_contains_expected(lexical_results, expected)
    semantic_expected = _top_contains_expected(semantic_results, expected)
    hybrid_expected = _top_contains_expected(hybrid_results, expected)
    semantic_ready = bool(diagnostics.semantic.retrieval_ready)
    semantic_changed = _ids(semantic_results) != _ids(lexical_results)
    hybrid_changed = _ids(hybrid_results) != _ids(lexical_results)
    hybrid_improved = not lexical_expected and hybrid_expected
    semantic_neutral_or_failed = (not semantic_ready) or (not semantic_changed and not semantic_expected)
    overall_result = "pass" if semantic_ready and hybrid_expected else "fail"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_backend": settings.runtime_backend,
        "deployment_mode": settings.deployment_mode,
        "deployment_mode_display": settings.deployment_mode_display,
        "model": settings.accesslab_model,
        "model_tier": "E4B" if settings.accesslab_model.endswith(":e4b") else "E2B",
        "retrieval_backend": "sqlite-fts5 + local semantic index",
        "semantic_model": settings.semantic_embedding_model,
        "semantic_backend": diagnostics.semantic.backend,
        "semantic_status_code": diagnostics.semantic.code,
        "semantic_status_label": diagnostics.semantic.label,
        "semantic_summary": diagnostics.semantic.summary,
        "semantic_detail": diagnostics.semantic.detail,
        "semantic_provider_ready": diagnostics.semantic.provider_ready,
        "semantic_retrieval_ready": diagnostics.semantic.retrieval_ready,
        "semantic_index_status": diagnostics.index_status.status,
        "semantic_index_label": diagnostics.index_status.label,
        "semantic_counts": {
            "documents": diagnostics.index_status.document_count,
            "chunks": diagnostics.index_status.chunk_count,
            "embedded_chunks": diagnostics.index_status.embedded_chunk_count,
            "missing_chunks": diagnostics.index_status.missing_chunk_count,
        },
        "data_dir": _display_path(data_dir),
        "db_path": _display_path(db_path),
        "files": [summary.file_name for summary in summaries],
        "chunks_created": sum(summary.chunks_created for summary in summaries),
        "question": args.question,
        "expected_substring": expected,
        "modes": {
            "lexical": _mode_proof(
                requested_mode="lexical",
                effective_mode="lexical",
                effective_label="Lexical only",
                results=lexical_results,
                expected=expected,
            ),
            "semantic": _mode_proof(
                requested_mode="semantic",
                effective_mode=semantic_mode,
                effective_label=semantic_label,
                results=semantic_results,
                expected=expected,
            ),
            "hybrid": _mode_proof(
                requested_mode="hybrid",
                effective_mode=hybrid_mode,
                effective_label=hybrid_label,
                results=hybrid_results,
                expected=expected,
            ),
        },
        "comparison": {
            "hybrid_improved_expected_support_over_lexical": hybrid_improved,
            "semantic_changed_chunks_vs_lexical": semantic_changed,
            "hybrid_changed_chunks_vs_lexical": hybrid_changed,
            "semantic_neutral_or_failed": semantic_neutral_or_failed,
        },
        "overall_result": overall_result,
        "honest_limits": [
            "This proof measures retrieval ranking over a small local fixture, not answer quality by itself.",
            "Hybrid may be neutral when lexical already retrieves the strongest evidence.",
            "Semantic-only is useful as a diagnostic, not the default product path.",
            "If EmbeddingGemma is unavailable, AccessLab must report lexical fallback instead of claiming hybrid retrieval.",
        ],
    }


def main() -> int:
    args = _parse_args()
    try:
        report = build_report(args)
    except Exception as exc:
        generated_at = datetime.now(timezone.utc).isoformat()
        report = {
            "generated_at": generated_at,
            "overall_result": "fail",
            "error": str(exc),
            "honest_limits": [
                "Retrieval proof did not complete.",
                "No semantic success should be claimed from this failed run.",
            ],
        }

    json_path = Path(args.output_json)
    markdown_path = Path(args.output_markdown)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown_path.write_text(_build_markdown(report) if "modes" in report else json.dumps(report, indent=2), encoding="utf-8")
    print(_display_path(json_path))
    print(_display_path(markdown_path))
    return 0 if report.get("overall_result") == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
