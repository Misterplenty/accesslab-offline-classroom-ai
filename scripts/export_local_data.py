from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.config import get_settings
from app.db import db_connection, init_db, list_session_labels, list_training_capture_events


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Export local AccessLab QA/code sessions for future tuning or review."
    )
    parser.add_argument(
        "--include",
        default="qa,code",
        help="Comma-separated session types to export: qa, code, or both.",
    )
    parser.add_argument(
        "--profile",
        default="all",
        choices=[
            "all",
            "labeled-good",
            "labeled-bad",
            "code",
            "qa",
            "weak-retrieval",
            "screen-reader-friendly",
            "teacher-reviewed",
        ],
        help="Named export profile for future tuning dataset assembly.",
    )
    parser.add_argument(
        "--class-space",
        default="",
        help="Restrict export to one class-space label. Empty means all class spaces.",
    )
    parser.add_argument(
        "--label",
        default="",
        help="Restrict export to examples with this local quality label.",
    )
    parser.add_argument(
        "--qa-ids",
        default="",
        help="Comma-separated QA session IDs to export. Empty means all matching QA sessions.",
    )
    parser.add_argument(
        "--code-ids",
        default="",
        help="Comma-separated code session IDs to export. Empty means all matching code sessions.",
    )
    parser.add_argument(
        "--only-labeled",
        action="store_true",
        help="Export only sessions that have at least one local quality label.",
    )
    parser.add_argument(
        "--only-captured",
        action="store_true",
        help="Export only sessions that have at least one opt-in training-capture record.",
    )
    parser.add_argument(
        "--db-path",
        default=str(settings.db_path),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "reports" / "training_export_latest.jsonl"),
    )
    parser.add_argument(
        "--summary-output",
        default=str(ROOT / "reports" / "training_export_latest.md"),
    )
    return parser.parse_args()


def _normalize_include(raw_value: str) -> set[str]:
    include = {part.strip().lower() for part in raw_value.split(",") if part.strip()}
    return include & {"qa", "code"}


def _parse_id_filter(raw_value: str) -> set[int]:
    parsed: set[int] = set()
    for part in (raw_value or "").split(","):
        cleaned = part.strip()
        if not cleaned:
            continue
        try:
            parsed.add(int(cleaned))
        except ValueError:
            continue
    return parsed


def _model_tier(model_name: str) -> str:
    normalized = (model_name or "").strip().lower()
    if normalized.endswith(":e2b"):
        return "E2B"
    if normalized.endswith(":e4b"):
        return "E4B"
    return "Custom"


def _label_names(labels: list[dict[str, Any]]) -> list[str]:
    return sorted({str(label.get("label", "")).strip().lower() for label in labels if label.get("label")})


def _teacher_reviewed(labels: list[dict[str, Any]]) -> bool:
    return any(str(label.get("actor_role", "")).lower() in {"teacher", "admin"} for label in labels)


def _review_flags(labels: list[dict[str, Any]], captures: list[dict[str, Any]]) -> dict[str, Any]:
    names = _label_names(labels)
    return {
        "label_names": names,
        "teacher_reviewed": _teacher_reviewed(labels),
        "labeled_good": "good" in names,
        "labeled_bad": "bad" in names,
        "needs_review": "needs-review" in names,
        "training_capture_count": len(captures),
    }


def _semantic_available_from_profile(profile: dict[str, Any], retrieved_results: list[Any]) -> bool | None:
    status = str(profile.get("semantic_status_code") or "").lower()
    if status:
        return status == "ok"
    if retrieved_results:
        return any(
            isinstance(result, dict) and str(result.get("match_source", "")).lower() == "semantic"
            for result in retrieved_results
        )
    return None


def _label_map(db_path: Path, *, class_space: str, label_filter: str) -> dict[tuple[str, int], list[dict[str, Any]]]:
    rows = list_session_labels(
        db_path,
        class_space=class_space or None,
        label=label_filter or None,
        limit=50_000,
    )
    label_map: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["source_type"]), int(row["source_id"]))
        label_map.setdefault(key, []).append(row)
    return label_map


def _capture_map(
    db_path: Path,
    *,
    class_space: str,
) -> dict[tuple[str, int], list[dict[str, Any]]]:
    rows = list_training_capture_events(
        db_path,
        class_space=class_space or None,
        limit=50_000,
    )
    capture_map: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["source_type"]), int(row["source_id"]))
        capture_map.setdefault(key, []).append(row)
    return capture_map


def _export_qa_rows(
    db_path: Path,
    *,
    class_space: str,
    label_map: dict[tuple[str, int], list[dict[str, Any]]],
    capture_map: dict[tuple[str, int], list[dict[str, Any]]] | None = None,
    only_labeled: bool,
    only_captured: bool = False,
    selected_ids: set[int] | None = None,
) -> list[dict[str, Any]]:
    filters: list[str] = []
    params: list[Any] = []
    if class_space:
        filters.append("class_space = ?")
        params.append(class_space)
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    rows: list[dict[str, Any]] = []
    with db_connection(db_path) as connection:
        records = connection.execute(
            f"""
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
            {where_clause}
            ORDER BY id ASC
            """,
            params,
        ).fetchall()
    capture_map = capture_map or {}
    selected_ids = selected_ids or set()
    for row in records:
        record_id = int(row["id"])
        if selected_ids and record_id not in selected_ids:
            continue
        labels = label_map.get(("qa", int(row["id"])), [])
        captures = capture_map.get(("qa", int(row["id"])), [])
        if only_labeled and not labels:
            continue
        if only_captured and not captures:
            continue
        session_data = json.loads(row["session_data"] or "{}")
        profile = session_data.get("profile", {}) if isinstance(session_data.get("profile", {}), dict) else {}
        retrieved_results = session_data.get("retrieved_results", [])
        model_name = str(session_data.get("model_name", ""))
        review_flags = _review_flags(labels, captures)
        retrieved_chunk_ids = json.loads(row["retrieved_chunk_ids"])
        weak_retrieval = row["result_mode"] == "weak_match"
        screen_reader_requested = "screen-reader" in str(row["question"]).lower()
        rows.append(
            {
                "source_type": "qa",
                "id": record_id,
                "created_at": row["created_at"],
                "role": row["actor_role"],
                "class_space": row["class_space"],
                "actor_role": row["actor_role"],
                "actor_key": row["actor_key"],
                "question": row["question"],
                "short_answer": row["answer_text"],
                "more_detail": row["more_detail"],
                "answer": {
                    "short": row["answer_text"],
                    "more_detail": row["more_detail"],
                },
                "unsure": bool(row["unsure"]),
                "weak_retrieval": weak_retrieval,
                "result_mode": row["result_mode"],
                "retrieval_mode": row["retrieval_mode"],
                "retrieval_mode_requested": session_data.get("requested_retrieval_mode", row["retrieval_mode"]),
                "retrieval_mode_effective": profile.get("retrieval_mode", row["retrieval_mode"]),
                "retrieval_mode_effective_label": profile.get("retrieval_mode_label", row["retrieval_mode_label"]),
                "retrieval_mode_label": row["retrieval_mode_label"],
                "semantic_available": _semantic_available_from_profile(profile, retrieved_results),
                "semantic_status_code": profile.get("semantic_status_code", ""),
                "semantic_index_status": profile.get("semantic_index_status", ""),
                "retrieved_chunk_ids": retrieved_chunk_ids,
                "retrieved_evidence_ids": retrieved_chunk_ids,
                "citations": json.loads(row["citation_list"]),
                "prompt_variant": session_data.get("prompt_variant", ""),
                "qa_discipline_profile": session_data.get("qa_discipline_profile", ""),
                "runtime_backend": session_data.get("runtime_backend", ""),
                "model_name": model_name,
                "model_tier": _model_tier(model_name),
                "raw_response": session_data.get("raw_response", ""),
                "retrieved_results": retrieved_results,
                "profile": profile,
                "accessibility_flags": {
                    "screen_reader_requested": screen_reader_requested,
                    "screen_reader_friendly_label": "screen-reader-friendly" in review_flags["label_names"],
                },
                "review_flags": review_flags,
                "labels": labels,
                "training_capture_records": captures,
                "training_capture_count": len(captures),
            }
        )
    return rows


def _export_code_rows(
    db_path: Path,
    *,
    class_space: str,
    label_map: dict[tuple[str, int], list[dict[str, Any]]],
    capture_map: dict[tuple[str, int], list[dict[str, Any]]] | None = None,
    only_labeled: bool,
    only_captured: bool = False,
    selected_ids: set[int] | None = None,
) -> list[dict[str, Any]]:
    filters: list[str] = []
    params: list[Any] = []
    if class_space:
        filters.append("class_space = ?")
        params.append(class_space)
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    rows: list[dict[str, Any]] = []
    with db_connection(db_path) as connection:
        records = connection.execute(
            f"""
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
            {where_clause}
            ORDER BY id ASC
            """,
            params,
        ).fetchall()
    capture_map = capture_map or {}
    selected_ids = selected_ids or set()
    for row in records:
        record_id = int(row["id"])
        if selected_ids and record_id not in selected_ids:
            continue
        labels = label_map.get(("code", int(row["id"])), [])
        captures = capture_map.get(("code", int(row["id"])), [])
        if only_labeled and not labels:
            continue
        if only_captured and not captures:
            continue
        session_data = json.loads(row["session_data"] or "{}")
        profile = session_data.get("profile", {}) if isinstance(session_data.get("profile", {}), dict) else {}
        model_name = str(session_data.get("model_name", ""))
        review_flags = _review_flags(labels, captures)
        rows.append(
            {
                "source_type": "code",
                "id": record_id,
                "created_at": row["created_at"],
                "role": row["actor_role"],
                "class_space": row["class_space"],
                "actor_role": row["actor_role"],
                "actor_key": row["actor_key"],
                "original_code": row["original_code"],
                "test_code": row["test_code"],
                "execution_output": row["execution_output"],
                "patched_code": row["patched_code"],
                "patched_test_result": row["patched_test_result"],
                "code": row["original_code"],
                "error": row["execution_output"],
                "patch": row["patched_code"],
                "rerun_result": row["patched_test_result"],
                "prompt_variant": session_data.get("prompt_variant", ""),
                "retrieval_mode_requested": "",
                "retrieval_mode_effective": "",
                "semantic_available": None,
                "weak_retrieval": False,
                "retrieved_evidence_ids": [],
                "runtime_backend": session_data.get("runtime_backend", ""),
                "model_name": model_name,
                "model_tier": _model_tier(model_name),
                "diagnosis": session_data.get("diagnosis", ""),
                "evidence": session_data.get("evidence", ""),
                "next_fix": session_data.get("next_fix", ""),
                "why_it_works": session_data.get("why_it_works", ""),
                "rerun_success": bool(session_data.get("rerun_success", False)),
                "initial_run": session_data.get("initial_run", {}),
                "patched_run": session_data.get("patched_run", {}),
                "profile": profile,
                "accessibility_flags": {
                    "screen_reader_friendly_label": "screen-reader-friendly" in review_flags["label_names"],
                },
                "review_flags": review_flags,
                "labels": labels,
                "training_capture_records": captures,
                "training_capture_count": len(captures),
            }
        )
    return rows


def _apply_export_profile(records: list[dict[str, Any]], profile: str) -> list[dict[str, Any]]:
    if profile == "all":
        return records
    if profile == "qa":
        return [record for record in records if record.get("source_type") == "qa"]
    if profile == "code":
        return [record for record in records if record.get("source_type") == "code"]
    if profile == "weak-retrieval":
        return [record for record in records if bool(record.get("weak_retrieval"))]
    if profile == "screen-reader-friendly":
        return [
            record
            for record in records
            if bool(record.get("accessibility_flags", {}).get("screen_reader_requested"))
            or bool(record.get("accessibility_flags", {}).get("screen_reader_friendly_label"))
        ]
    if profile == "teacher-reviewed":
        return [record for record in records if bool(record.get("review_flags", {}).get("teacher_reviewed"))]
    if profile == "labeled-good":
        return [record for record in records if bool(record.get("review_flags", {}).get("labeled_good"))]
    if profile == "labeled-bad":
        return [record for record in records if bool(record.get("review_flags", {}).get("labeled_bad"))]
    return records


def build_summary(records: list[dict[str, Any]], *, output_path: Path, export_profile: str) -> str:
    qa_count = sum(record["source_type"] == "qa" for record in records)
    code_count = sum(record["source_type"] == "code" for record in records)
    labeled_count = sum(bool(record.get("labels")) for record in records)
    captured_count = sum(int(record.get("training_capture_count", 0) or 0) > 0 for record in records)
    weak_count = sum(bool(record.get("weak_retrieval")) for record in records)
    teacher_reviewed_count = sum(bool(record.get("review_flags", {}).get("teacher_reviewed")) for record in records)
    return "\n".join(
        [
            "# AccessLab Local Data Export",
            "",
            f"- Output: `{display_path(output_path)}`",
            f"- Export profile: `{export_profile}`",
            f"- Total records: {len(records)}",
            f"- QA records: {qa_count}",
            f"- Code records: {code_count}",
            f"- Labeled records: {labeled_count}",
            f"- Captured records: {captured_count}",
            f"- Weak-retrieval records: {weak_count}",
            f"- Teacher-reviewed records: {teacher_reviewed_count}",
            "",
            "This export stays local and is intended for future lightweight tuning or review workflows.",
            "",
            "Fields are shaped for SFT or later preference work, but low-quality, weak-retrieval, and unreviewed rows should be filtered before training.",
            "",
        ]
    )


def main() -> None:
    args = parse_args()
    include = _normalize_include(args.include)
    if not include:
        raise SystemExit("Nothing to export. Use --include qa,code or one of those values.")

    db_path = Path(args.db_path)
    init_db(db_path)
    label_map = _label_map(
        db_path,
        class_space=args.class_space.strip(),
        label_filter=args.label.strip().lower(),
    )
    capture_map = _capture_map(
        db_path,
        class_space=args.class_space.strip(),
    )
    qa_ids = _parse_id_filter(args.qa_ids)
    code_ids = _parse_id_filter(args.code_ids)

    records: list[dict[str, Any]] = []
    if "qa" in include:
        records.extend(
            _export_qa_rows(
                db_path,
                class_space=args.class_space.strip(),
                label_map=label_map,
                capture_map=capture_map,
                only_labeled=args.only_labeled or bool(args.label.strip()),
                only_captured=args.only_captured,
                selected_ids=qa_ids,
            )
        )
    if "code" in include:
        records.extend(
            _export_code_rows(
                db_path,
                class_space=args.class_space.strip(),
                label_map=label_map,
                capture_map=capture_map,
                only_labeled=args.only_labeled or bool(args.label.strip()),
                only_captured=args.only_captured,
                selected_ids=code_ids,
            )
        )
    records = _apply_export_profile(records, args.profile)

    output_path = Path(args.output)
    summary_path = Path(args.summary_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")
    summary_path.write_text(
        build_summary(records, output_path=output_path, export_profile=args.profile),
        encoding="utf-8",
    )

    print(display_path(output_path))
    print(display_path(summary_path))


if __name__ == "__main__":
    main()
