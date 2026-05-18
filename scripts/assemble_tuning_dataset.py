from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assemble a narrow AccessLab tuning JSONL from a local export."
    )
    parser.add_argument("--input", required=True, help="JSONL from scripts/export_local_data.py")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--task-profile",
        default="mixed-product-behavior",
        choices=[
            "mixed-product-behavior",
            "qa-citation-abstention",
            "code-minimal-fix",
            "accessibility-style",
        ],
    )
    parser.add_argument(
        "--format",
        default="sft",
        choices=["sft", "preference-candidates"],
    )
    parser.add_argument(
        "--include-unreviewed",
        action="store_true",
        help="Allow unreviewed examples. Default keeps labeled-good or teacher-reviewed rows only.",
    )
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _review_ok(record: dict[str, Any], *, include_unreviewed: bool) -> bool:
    if include_unreviewed:
        return not bool(record.get("review_flags", {}).get("labeled_bad"))
    flags = record.get("review_flags", {})
    return bool(flags.get("labeled_good") or flags.get("teacher_reviewed")) and not bool(flags.get("labeled_bad"))


def _profile_ok(record: dict[str, Any], task_profile: str) -> bool:
    if task_profile == "mixed-product-behavior":
        return record.get("source_type") in {"qa", "code"}
    if task_profile == "qa-citation-abstention":
        return record.get("source_type") == "qa"
    if task_profile == "code-minimal-fix":
        return record.get("source_type") == "code" and bool(record.get("rerun_success"))
    if task_profile == "accessibility-style":
        return bool(record.get("accessibility_flags", {}).get("screen_reader_requested")) or bool(
            record.get("accessibility_flags", {}).get("screen_reader_friendly_label")
        )
    return False


def _qa_sft(record: dict[str, Any]) -> dict[str, Any]:
    evidence = []
    for item in record.get("retrieved_results", [])[:4]:
        if isinstance(item, dict):
            evidence.append(f"[{item.get('chunk_id')}] {item.get('snippet') or item.get('chunk_text')}")
    answer = record.get("answer") or {}
    return {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are AccessLab in grounded_qa mode. Answer only from local evidence, cite sources, "
                    "and abstain when retrieval is weak."
                ),
            },
            {
                "role": "user",
                "content": f"Question: {record.get('question', '')}\n\nEvidence:\n" + "\n".join(evidence),
            },
            {
                "role": "assistant",
                "content": "\n".join(
                    part
                    for part in [answer.get("short") or record.get("short_answer"), answer.get("more_detail")]
                    if part
                ),
            },
        ],
        "metadata": _metadata(record),
    }


def _code_sft(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are AccessLab in beginner_code_tutor mode. Use runtime evidence, make the smallest fix, "
                    "and keep the explanation beginner-friendly."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Original code:\n{record.get('code') or record.get('original_code', '')}\n\n"
                    f"Tests/error:\n{record.get('error') or record.get('execution_output', '')}"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    f"What failed: {record.get('diagnosis', '')}\n"
                    f"Evidence: {record.get('evidence', '')}\n"
                    f"Smallest fix: {record.get('next_fix', '')}\n"
                    f"Patched code:\n{record.get('patch') or record.get('patched_code', '')}\n"
                    f"Why it works: {record.get('why_it_works', '')}"
                ),
            },
        ],
        "metadata": _metadata(record),
    }


def _metadata(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_type": record.get("source_type"),
        "source_id": record.get("id"),
        "class_space": record.get("class_space"),
        "role": record.get("role") or record.get("actor_role"),
        "runtime_backend": record.get("runtime_backend"),
        "model_name": record.get("model_name"),
        "model_tier": record.get("model_tier"),
        "retrieval_mode_requested": record.get("retrieval_mode_requested"),
        "retrieval_mode_effective": record.get("retrieval_mode_effective"),
        "weak_retrieval": record.get("weak_retrieval"),
        "label_names": record.get("review_flags", {}).get("label_names", []),
    }


def _preference_candidate(record: dict[str, Any]) -> dict[str, Any]:
    item = _qa_sft(record) if record.get("source_type") == "qa" else _code_sft(record)
    item["preference_contract"] = {
        "preferred_if": [
            "answer-first",
            "cites local evidence",
            "abstains under weak retrieval",
            "minimal code patch",
            "screen-reader-friendly formatting when requested",
        ],
        "rejected_if": [
            "open chat behavior",
            "uncited claims",
            "guessing under weak retrieval",
            "large rewrite for beginner code",
            "overlong explanation",
        ],
    }
    return item


def main() -> None:
    args = parse_args()
    records = read_jsonl(Path(args.input))
    assembled = []
    for record in records:
        if not _profile_ok(record, args.task_profile):
            continue
        if not _review_ok(record, include_unreviewed=args.include_unreviewed):
            continue
        if record.get("source_type") == "qa":
            assembled.append(_preference_candidate(record) if args.format != "sft" else _qa_sft(record))
        elif record.get("source_type") == "code":
            assembled.append(_preference_candidate(record) if args.format != "sft" else _code_sft(record))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for item in assembled:
            handle.write(json.dumps(item, ensure_ascii=True) + "\n")
    print(output_path)
    print(f"records={len(assembled)}")


if __name__ == "__main__":
    main()
