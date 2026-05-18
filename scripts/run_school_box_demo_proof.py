from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.config import Settings
from app.db import (
    get_code_session_entry,
    get_qa_history_entry,
    init_db,
    list_recent_classroom_activity,
    list_session_labels,
    save_session_label,
)
from app.services.code_runner import LocalPythonRunner
from app.services.code_tutor import CodeTutorService
from app.services.document_ingest import DocumentIngestService
from app.services.llm import create_generation_provider
from app.services.ocr import create_ocr_backend
from app.services.operator_preflight import build_operator_preflight
from app.services.qa import GroundedQAService
from app.services.retrieval import HybridSQLiteRetrieval
from app.services.semantic import SQLiteSemanticIndex, create_embedding_provider
from app.services.system_status import build_retrieval_diagnostics
from app.services.work_queue import LocalWorkQueue


DEFAULT_CLASS_SPACE = "judge-demo-class"
DEFAULT_QUESTION = "What does `for item in numbers:` mean?"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a canonical local school-box demo proof with teacher, learner, and admin artifacts."
    )
    parser.add_argument("--data-dir", default=str(ROOT / "data" / "school-box-demo"))
    parser.add_argument("--keep-data-dir", action="store_true")
    parser.add_argument("--class-space", default=DEFAULT_CLASS_SPACE)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--model", default=Settings().accesslab_model)
    parser.add_argument("--max-concurrent-jobs", type=int, default=1)
    parser.add_argument(
        "--output-json",
        default=str(ROOT / "reports" / "school_box_demo_proof_latest.json"),
    )
    parser.add_argument(
        "--output-markdown",
        default=str(ROOT / "reports" / "school_box_demo_proof_latest.md"),
    )
    return parser.parse_args()


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


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


def _profile_payload(profile: Any) -> dict[str, Any]:
    if profile is None:
        return {}
    return {
        "ttft_seconds": profile.ttft_seconds,
        "total_seconds": profile.total_seconds,
        "retrieval_seconds": getattr(profile, "retrieval_seconds", None),
        "model_inference_seconds": getattr(profile, "model_inference_seconds", None),
        "prompt_eval_count": getattr(profile, "prompt_eval_count", None),
        "eval_count": getattr(profile, "eval_count", None),
        "queue_wait_seconds": getattr(profile, "queue_wait_seconds", None),
        "retrieval_mode": getattr(profile, "retrieval_mode", ""),
        "retrieval_mode_label": getattr(profile, "retrieval_mode_label", ""),
    }


def _code_passed(result: Any) -> bool:
    return bool(getattr(getattr(result, "patched_run", None), "passed", False))


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    start = perf_counter()
    data_dir = Path(args.data_dir).expanduser().resolve()
    if data_dir.exists() and not args.keep_data_dir:
        shutil.rmtree(data_dir, ignore_errors=True)
    base_settings = Settings(
        deployment_mode="school-box-shared",
        class_space=args.class_space,
        max_concurrent_jobs=max(1, int(args.max_concurrent_jobs)),
        data_dir=data_dir,
    )
    uploads_dir = base_settings.uploads_dir
    uploads_dir.mkdir(parents=True, exist_ok=True)
    db_path = base_settings.db_path
    init_db(db_path)

    semantic_index = SQLiteSemanticIndex(
        db_path=db_path,
        embedding_provider=create_embedding_provider(
            enabled=base_settings.semantic_enabled,
            base_url=base_settings.accesslab_ollama_url,
            model_name=base_settings.semantic_embedding_model,
        ),
        class_space=args.class_space,
    )
    ocr_backend = create_ocr_backend(enabled=base_settings.ocr_enabled, dpi=base_settings.ocr_dpi)
    llm_provider = create_generation_provider(
        runtime_backend=base_settings.runtime_backend,
        base_url=base_settings.accesslab_ollama_url,
        model_name=args.model,
    )
    queue = LocalWorkQueue(max_concurrent_jobs=max(1, int(args.max_concurrent_jobs)))
    ingest_service = DocumentIngestService(
        uploads_dir=uploads_dir,
        db_path=db_path,
        ocr_backend=ocr_backend,
        semantic_index=semantic_index,
        ocr_min_chars_per_page=base_settings.ocr_min_chars_per_page,
    )
    retrieval_backend = HybridSQLiteRetrieval(
        db_path,
        semantic_index=semantic_index,
        retrieval_mode=base_settings.retrieval_mode,
        class_space=args.class_space,
    )
    qa_service = GroundedQAService(
        db_path=db_path,
        retrieval_backend=retrieval_backend,
        llm_provider=llm_provider,
        qa_discipline_profile=base_settings.qa_discipline_profile,
        training_capture_enabled=base_settings.training_capture_enabled_bool,
    )
    code_service = CodeTutorService(
        db_path=db_path,
        llm_provider=llm_provider,
        execution_backend=LocalPythonRunner(timeout_seconds=5),
        training_capture_enabled=base_settings.training_capture_enabled_bool,
    )

    uploaded = []
    for source_path in (
        ROOT / "sample_data" / "worksheet_question3.md",
        ROOT / "sample_data" / "python_loops_notes.txt",
    ):
        with queue.job(job_kind="upload-index"):
            summary = ingest_service.ingest_upload(
                file_name=source_path.name,
                content=source_path.read_bytes(),
                uploader_role="teacher",
                class_space=args.class_space,
            )
        uploaded.append(
            {
                "file_name": summary.file_name,
                "file_type": summary.file_type,
                "chunks_created": summary.chunks_created,
                "ocr_status": summary.ocr_status,
            }
        )

    with queue.job(job_kind="grounded-qa") as receipt:
        qa_result = qa_service.answer(
            args.question,
            actor_role="learner",
            actor_key="demo-learner",
            class_space=args.class_space,
            queue_wait_seconds=receipt.wait_seconds,
        )

    code_path = ROOT / "sample_code" / "buggy_sum.py"
    test_path = ROOT / "sample_code" / "test_buggy_sum.py"
    with queue.job(job_kind="code-tutor") as receipt:
        code_result = code_service.tutor(
            code_path.read_text(encoding="utf-8"),
            test_path.read_text(encoding="utf-8"),
            "Fix the smallest beginner bug and rerun the tests.",
            actor_role="learner",
            actor_key="demo-learner",
            class_space=args.class_space,
            queue_wait_seconds=receipt.wait_seconds,
        )

    qa_id = int(qa_result.history_id or 0)
    code_id = int(code_result.session_id or 0)
    if qa_id:
        save_session_label(
            db_path,
            source_type="qa",
            source_id=qa_id,
            label="good" if qa_result.citations and not qa_result.unsure else "needs-review",
            note="Canonical school-box demo review label.",
            actor_role="teacher",
            actor_key="demo-teacher",
            class_space=args.class_space,
        )
    if code_id:
        save_session_label(
            db_path,
            source_type="code",
            source_id=code_id,
            label="good" if _code_passed(code_result) else "needs-review",
            note="Canonical school-box demo review label.",
            actor_role="teacher",
            actor_key="demo-teacher",
            class_space=args.class_space,
        )

    retrieval_diagnostics = build_retrieval_diagnostics(base_settings, semantic_index)
    preflight = build_operator_preflight(
        base_settings,
        llm_provider=llm_provider,
        semantic_index=semantic_index,
        ocr_backend=ocr_backend,
        work_queue=queue,
    )
    activity = list_recent_classroom_activity(db_path, class_space=args.class_space, limit=8)
    labels = {
        "qa": list_session_labels(db_path, source_type="qa", source_id=qa_id, class_space=args.class_space),
        "code": list_session_labels(db_path, source_type="code", source_id=code_id, class_space=args.class_space),
    }
    qa_entry = get_qa_history_entry(db_path, qa_id) if qa_id else None
    code_entry = get_code_session_entry(db_path, code_id) if code_id else None

    qa_pass = bool(qa_result.citations) and qa_result.result_mode in {"answered", "weak_match"}
    code_pass = _code_passed(code_result)
    overall = "pass" if qa_pass and code_pass and preflight["overall_status"] in {"ready", "attention"} else "fail"

    return _sanitize_paths({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall,
        "runtime_backend": base_settings.runtime_backend,
        "deployment_mode": "school-box-shared",
        "deployment_mode_display": base_settings.deployment_mode_display,
        "class_space": args.class_space,
        "model": args.model,
        "model_tier": "E4B" if args.model.endswith(":e4b") else "E2B",
        "semantic_model": base_settings.semantic_embedding_model,
        "retrieval_requested_mode": base_settings.retrieval_mode,
        "retrieval_effective_mode": retrieval_diagnostics.actual_mode,
        "retrieval_effective_mode_label": retrieval_diagnostics.actual_mode_label,
        "semantic_status_code": retrieval_diagnostics.semantic.code,
        "semantic_retrieval_ready": retrieval_diagnostics.semantic.retrieval_ready,
        "ocr_available": bool(ocr_backend.is_available()),
        "queue": queue.snapshot(),
        "data_dir": display_path(data_dir),
        "db_path": display_path(db_path),
        "scenario": {
            "teacher_uploads_materials": uploaded,
            "learner_grounded_question": {
                "question": args.question,
                "history_id": qa_id,
                "saved_url": f"/qa?qa_id={qa_id}" if qa_id else "",
                "result_mode": qa_result.result_mode,
                "short_answer": qa_result.short_answer,
                "citation_count": len(qa_result.citations),
                "citations": [asdict(citation) for citation in qa_result.citations],
                "profile": _profile_payload(qa_result.profile),
            },
            "learner_python_repair": {
                "session_id": code_id,
                "saved_url": f"/code?session_id={code_id}" if code_id else "",
                "passed_tests": code_pass,
                "diagnosis": code_result.diagnosis,
                "evidence": code_result.evidence,
                "next_fix": code_result.next_fix,
                "profile": _profile_payload(code_result.profile),
            },
            "teacher_admin_review": {
                "qa_entry_found": qa_entry is not None,
                "code_entry_found": code_entry is not None,
                "labels": labels,
                "recent_activity": activity,
                "preflight_overall": preflight["overall_status"],
                "preflight_checks": preflight["checks"],
            },
        },
        "demo_checklist": [
            "Start with ACCESSLAB_DEPLOYMENT_MODE=school-box-shared.",
            "Use class-space judge-demo-class unless the judge asks for a different class.",
            "Pull gemma4:e4b and embeddinggemma before the demo.",
            "Keep ACCESSLAB_MAX_CONCURRENT_JOBS=1 for the safest live demo.",
            "Show local URL http://127.0.0.1:8000 and LAN URL from the host network settings.",
            "Expected failures: missing Gemma 4 model, missing EmbeddingGemma, OCR extras unavailable, or long queue wait during embedding/generation.",
        ],
        "classroom_limitations": [
            "One host bottlenecks under simultaneous generation, OCR, and embedding work.",
            "The queue is local/in-process in this prototype.",
            "School-box mode is intended for supervised local classroom deployment.",
            "This is not production multi-user serving or a production secure sandbox.",
        ],
        "total_seconds": round(perf_counter() - start, 3),
    })


def build_markdown(report: dict[str, Any]) -> str:
    scenario = report["scenario"]
    qa = scenario["learner_grounded_question"]
    code = scenario["learner_python_repair"]
    lines = [
        "# AccessLab School-Box Demo Proof",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Overall status: {report['overall_status']}",
        f"- Runtime backend: {report['runtime_backend']}",
        f"- Deployment mode: {report['deployment_mode_display']}",
        f"- Class space: {report['class_space']}",
        f"- Model: {report['model']} ({report['model_tier']})",
        f"- Retrieval: {report['retrieval_requested_mode']} -> {report['retrieval_effective_mode_label']}",
        f"- Semantic: {report['semantic_status_code']} / ready={report['semantic_retrieval_ready']}",
        f"- OCR available: {report['ocr_available']}",
        f"- Total demo script seconds: {report['total_seconds']}",
        "",
        "## Story",
        "",
        f"- Teacher uploaded {len(scenario['teacher_uploads_materials'])} local material file(s).",
        f"- Learner asked: {qa['question']}",
        f"- QA saved URL: `{qa['saved_url']}` with {qa['citation_count']} citation(s).",
        f"- Code repair saved URL: `{code['saved_url']}`; patched tests passed: {code['passed_tests']}.",
        f"- Teacher/admin review found saved QA: {scenario['teacher_admin_review']['qa_entry_found']}; saved code: {scenario['teacher_admin_review']['code_entry_found']}.",
        "",
        "## Live Demo Checklist",
        "",
    ]
    lines.extend(f"- {item}" for item in report["demo_checklist"])
    lines.extend(["", "## Classroom Limitations", ""])
    lines.extend(f"- {item}" for item in report["classroom_limitations"])
    lines.extend(["", "## Uploaded Materials", ""])
    for item in scenario["teacher_uploads_materials"]:
        lines.append(f"- `{item['file_name']}`: {item['chunks_created']} chunk(s), OCR={item['ocr_status']}")
    lines.extend(["", "## QA Evidence", "", qa["short_answer"], ""])
    for citation in qa["citations"]:
        lines.append(f"- [{citation['label']}] `{citation['source_file']}` chunk `{citation['chunk_id']}`")
    lines.extend(["", "## Code Repair", "", f"- Diagnosis: {code['diagnosis']}", f"- Evidence: {code['evidence']}", f"- Next fix: {code['next_fix']}", ""])
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    report = build_report(args)
    json_path = Path(args.output_json)
    markdown_path = Path(args.output_markdown)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown_path.write_text(build_markdown(report), encoding="utf-8")
    print(display_path(json_path))
    print(display_path(markdown_path))
    return 0 if report["overall_status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
