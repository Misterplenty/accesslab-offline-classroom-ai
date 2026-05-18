from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.config import get_settings
from app.db import init_db
from app.services.bootstrap import ensure_ocr_requirements, seed_default_documents
from app.services.llm import create_generation_provider
from app.services.ocr import create_ocr_backend
from app.services.operator_preflight import build_operator_preflight
from app.services.semantic import SQLiteSemanticIndex, create_embedding_provider
from app.services.system_status import build_retrieval_diagnostics
from app.services.work_queue import LocalWorkQueue


def _sanitize_paths(value: Any) -> Any:
    if isinstance(value, str):
        sanitized = value
        for raw, replacement in (
            (str(ROOT), "<workspace>"),
            (str(Path.home()), "<home>"),
        ):
            if raw:
                sanitized = sanitized.replace(raw, replacement)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_paths(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_paths(item) for key, item in value.items()}
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a local AccessLab operator preflight and deployment snapshot."
    )
    parser.add_argument(
        "--output-json",
        default=str(ROOT / "reports" / "operator_preflight_latest.json"),
    )
    parser.add_argument(
        "--output-markdown",
        default=str(ROOT / "reports" / "operator_preflight_latest.md"),
    )
    parser.add_argument(
        "--system-status-output",
        default=str(ROOT / "reports" / "system_status_snapshot_latest.json"),
    )
    parser.add_argument(
        "--deployment-output",
        default=str(ROOT / "reports" / "deployment_mode_snapshot_latest.md"),
    )
    return parser.parse_args()


def build_snapshot() -> dict[str, Any]:
    settings = get_settings()
    settings.ensure_directories()
    init_db(settings.db_path)

    llm_provider = create_generation_provider(
        runtime_backend=settings.runtime_backend,
        base_url=settings.accesslab_ollama_url,
        model_name=settings.accesslab_model,
    )
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
    semantic_backfilled_chunks = semantic_index.ensure_embeddings()
    work_queue = LocalWorkQueue(max_concurrent_jobs=settings.max_concurrent_jobs)
    retrieval_diagnostics = build_retrieval_diagnostics(settings, semantic_index)
    preflight = build_operator_preflight(
        settings,
        llm_provider=llm_provider,
        semantic_index=semantic_index,
        ocr_backend=ocr_backend,
        work_queue=work_queue,
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "app_name": settings.app_name,
        "deployment": {
            "profile": settings.deployment_profile,
            "profile_display": settings.deployment_profile_display,
            "mode": settings.deployment_mode,
            "mode_display": settings.deployment_mode_display,
            "mode_summary": settings.deployment_mode_summary,
            "class_space": settings.class_space,
            "class_space_display": settings.class_space_display,
            "training_capture_enabled": settings.training_capture_enabled,
            "training_capture_display": settings.training_capture_display,
        },
        "runtime": {
            "backend": settings.runtime_backend,
            "backend_display": settings.runtime_backend_display,
            "active_model": settings.accesslab_model,
            "generation_model_family": settings.generation_model_family,
            "runtime_description": llm_provider.describe_runtime(),
            "capabilities": asdict(preflight["runtime_capabilities"]),
        },
        "retrieval": {
            "requested_mode": settings.retrieval_mode,
            "requested_mode_display": settings.retrieval_mode_display,
            "effective_mode": retrieval_diagnostics.actual_mode,
            "effective_mode_display": retrieval_diagnostics.actual_mode_label,
            "semantic_status_code": retrieval_diagnostics.semantic.code,
            "semantic_status_label": retrieval_diagnostics.semantic.label,
            "semantic_summary": retrieval_diagnostics.semantic.summary,
            "semantic_detail": retrieval_diagnostics.semantic.detail,
            "semantic_index_status": retrieval_diagnostics.index_status.status,
            "semantic_index_label": retrieval_diagnostics.index_status.label,
            "semantic_backfilled_chunks": semantic_backfilled_chunks,
            "semantic_counts": {
                "documents": retrieval_diagnostics.index_status.document_count,
                "chunks": retrieval_diagnostics.index_status.chunk_count,
                "embedded_chunks": retrieval_diagnostics.index_status.embedded_chunk_count,
                "missing_chunks": retrieval_diagnostics.index_status.missing_chunk_count,
            },
        },
        "queue": preflight["queue_snapshot"],
        "preflight": {
            "overall_status": preflight["overall_status"],
            "overall_label": preflight["overall_label"],
            "checks": preflight["checks"],
            "dataset_counts": preflight["dataset_counts"],
            "storage_probe_path": preflight["storage_probe_path"],
            "database_quick_check": preflight["database_quick_check"],
        },
    }


def build_markdown(snapshot: dict[str, Any]) -> str:
    deployment = snapshot["deployment"]
    runtime = snapshot["runtime"]
    retrieval = snapshot["retrieval"]
    preflight = snapshot["preflight"]
    queue = snapshot["queue"]
    lines = [
        "# AccessLab Operator Preflight",
        "",
        f"- Generated at: {snapshot['generated_at']}",
        f"- Overall status: {preflight['overall_label']}",
        "",
        "## Deployment snapshot",
        "",
        f"- Mode: {deployment['mode_display']}",
        f"- Profile: {deployment['profile_display']}",
        f"- Class space: {deployment['class_space_display']}",
        f"- Training capture: {deployment['training_capture_display']}",
        f"- Summary: {deployment['mode_summary']}",
        "",
        "## Runtime snapshot",
        "",
        f"- Backend: {runtime['backend_display']}",
        f"- Model: {runtime['active_model']}",
        f"- Runtime: {runtime['runtime_description']}",
        f"- Validation only: {runtime['capabilities'].get('validation_only')}",
        f"- Supported profiles: {', '.join(runtime['capabilities'].get('supported_profiles') or []) or 'not declared'}",
        "",
        "## Retrieval snapshot",
        "",
        f"- Requested mode: {retrieval['requested_mode_display']}",
        f"- Effective mode: {retrieval['effective_mode_display']}",
        f"- Semantic status: {retrieval['semantic_status_label']} ({retrieval['semantic_status_code']})",
        f"- Semantic index: {retrieval['semantic_index_label']}",
        f"- Semantic chunks backfilled during preflight: {retrieval.get('semantic_backfilled_chunks', 0)}",
        f"- Semantic counts: {retrieval['semantic_counts']['documents']}/{retrieval['semantic_counts']['chunks']}/"
        f"{retrieval['semantic_counts']['embedded_chunks']}/{retrieval['semantic_counts']['missing_chunks']}",
        "",
        "## Queue snapshot",
        "",
        f"- Max concurrent jobs: {queue['max_concurrent_jobs']}",
        f"- Queue depth: {queue['queue_depth']}",
        f"- Active jobs: {queue['active_jobs']}",
        f"- Waiting jobs: {queue['waiting_jobs']}",
        f"- Active mix: {queue.get('active_by_kind', {}) or 'None'}",
        f"- Waiting mix: {queue.get('waiting_by_kind', {}) or 'None'}",
        "",
        "## Preflight checks",
        "",
    ]
    for check in preflight["checks"]:
        lines.append(
            f"- {check['label']}: {check['status']} — {check['summary']} {check['detail']}"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    snapshot = _sanitize_paths(build_snapshot())
    json_path = Path(args.output_json)
    markdown_path = Path(args.output_markdown)
    system_status_path = Path(args.system_status_output)
    deployment_path = Path(args.deployment_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    system_status_path.parent.mkdir(parents=True, exist_ok=True)
    deployment_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    markdown_path.write_text(build_markdown(snapshot), encoding="utf-8")
    system_status_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    deployment_lines = [
        "# AccessLab Deployment Mode Snapshot",
        "",
        f"- Mode: {snapshot['deployment']['mode_display']}",
        f"- Profile: {snapshot['deployment']['profile_display']}",
        f"- Class space: {snapshot['deployment']['class_space_display']}",
        f"- Training capture: {snapshot['deployment']['training_capture_display']}",
        f"- Summary: {snapshot['deployment']['mode_summary']}",
        "",
        f"- Runtime backend: {snapshot['runtime']['backend_display']}",
        f"- Active model: {snapshot['runtime']['active_model']}",
        f"- Effective retrieval: {snapshot['retrieval']['effective_mode_display']}",
        "",
    ]
    deployment_path.write_text("\n".join(deployment_lines), encoding="utf-8")
    print(json_path.relative_to(ROOT))
    print(markdown_path.relative_to(ROOT))
    print(system_status_path.relative_to(ROOT))
    print(deployment_path.relative_to(ROOT))


if __name__ == "__main__":
    main()
