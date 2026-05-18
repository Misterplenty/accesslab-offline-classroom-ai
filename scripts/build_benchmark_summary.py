from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a scan-friendly AccessLab benchmark summary from eval and accessibility artifacts."
    )
    parser.add_argument(
        "--summary",
        action="append",
        default=[],
        help="Path to a run summary.json emitted by scripts/run_accesslab_eval.py. Repeat for multiple runs.",
    )
    parser.add_argument(
        "--a11y",
        action="append",
        default=[],
        help="Path to an accessibility smoke JSON artifact emitted by scripts/run_accesslab_a11y_smoke.py.",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "reports" / "accesslab_benchmark_summary.md"),
    )
    parser.add_argument(
        "--highlights-output",
        default=str(ROOT / "reports" / "accesslab_benchmark_highlights.md"),
    )
    parser.add_argument(
        "--bundle-output",
        default=str(ROOT / "reports" / "accesslab_benchmark_bundle.json"),
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _format_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0%}"


def _format_seconds(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}s"


def _format_number(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _summary_key(summary: dict[str, Any], *keys: str) -> tuple[str, ...]:
    values = []
    for key in keys:
        if key == "categories":
            values.append(",".join(summary.get("categories") or ["all"]))
        elif key == "device_tier":
            values.append(str(summary.get("device", {}).get("tier") or ""))
        else:
            values.append(str(summary.get(key) or ""))
    return tuple(values)


def _model_tier(summary: dict[str, Any]) -> str:
    tier = str(summary.get("model_tier") or "").strip()
    if tier:
        return tier
    model = str(summary.get("model") or "").lower()
    if model.endswith(":e2b"):
        return "E2B"
    if model.endswith(":e4b"):
        return "E4B"
    return "Custom" if model else ""


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def build_bundle(summaries: list[dict[str, Any]], a11y_reports: list[dict[str, Any]]) -> dict[str, Any]:
    comparisons = build_comparison_data(summaries)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_count": len(summaries),
        "a11y_report_count": len(a11y_reports),
        "runs": summaries,
        "accessibility_reports": a11y_reports,
        "comparisons": comparisons,
        "device_tiers": sorted(
            {
                str(summary.get("device", {}).get("tier_display") or summary.get("device", {}).get("tier") or "")
                for summary in summaries
            }
            - {""}
        ),
        "deployment_modes": sorted(
            {str(summary.get("deployment_mode_display") or summary.get("deployment_mode") or "") for summary in summaries}
            - {""}
        ),
        "runtime_backends": sorted({str(summary.get("runtime_backend") or "") for summary in summaries} - {""}),
    }


def _comparison_row(a: dict[str, Any], b: dict[str, Any], *, axis: str) -> dict[str, Any]:
    a_latency = a.get("latency", {})
    b_latency = b.get("latency", {})
    return {
        "axis": axis,
        "left_run": a.get("run_label") or a.get("run_id"),
        "right_run": b.get("run_label") or b.get("run_id"),
        "left_model_tier": _model_tier(a),
        "right_model_tier": _model_tier(b),
        "left_retrieval": a.get("retrieval_mode_display", a.get("retrieval_mode")),
        "right_retrieval": b.get("retrieval_mode_display", b.get("retrieval_mode")),
        "left_runtime": a.get("runtime_backend"),
        "right_runtime": b.get("runtime_backend"),
        "left_pass_rate": a.get("counts", {}).get("pass_rate"),
        "right_pass_rate": b.get("counts", {}).get("pass_rate"),
        "left_avg_total_seconds": a_latency.get("avg_total_seconds"),
        "right_avg_total_seconds": b_latency.get("avg_total_seconds"),
        "left_avg_ttft_seconds": a_latency.get("avg_ttft_seconds"),
        "right_avg_ttft_seconds": b_latency.get("avg_ttft_seconds"),
        "left_avg_queue_wait_seconds": a_latency.get("avg_queue_wait_seconds"),
        "right_avg_queue_wait_seconds": b_latency.get("avg_queue_wait_seconds"),
    }


def build_comparison_data(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    model_rows = []
    retrieval_rows = []
    runtime_rows = []
    school_box_rows = []

    for index, left in enumerate(summaries):
        for right in summaries[index + 1 :]:
            if {_model_tier(left), _model_tier(right)} == {"E2B", "E4B"} and _summary_key(
                left,
                "categories",
                "requested_retrieval_mode",
                "deployment_mode",
                "device_tier",
                "runtime_backend",
            ) == _summary_key(
                right,
                "categories",
                "requested_retrieval_mode",
                "deployment_mode",
                "device_tier",
                "runtime_backend",
            ):
                model_rows.append(_comparison_row(left, right, axis="model-tier"))

            if {
                str(left.get("requested_retrieval_mode")),
                str(right.get("requested_retrieval_mode")),
            } == {"lexical", "hybrid"} and _summary_key(
                left,
                "categories",
                "model",
                "deployment_mode",
                "device_tier",
                "runtime_backend",
            ) == _summary_key(
                right,
                "categories",
                "model",
                "deployment_mode",
                "device_tier",
                "runtime_backend",
            ):
                retrieval_rows.append(_comparison_row(left, right, axis="retrieval-mode"))

            if left.get("runtime_backend") != right.get("runtime_backend") and _summary_key(
                left,
                "categories",
                "model",
                "requested_retrieval_mode",
                "deployment_mode",
                "device_tier",
            ) == _summary_key(
                right,
                "categories",
                "model",
                "requested_retrieval_mode",
                "deployment_mode",
                "device_tier",
            ):
                runtime_rows.append(_comparison_row(left, right, axis="runtime-backend"))

    for summary in summaries:
        if summary.get("deployment_mode") == "school-box-shared":
            school_box_rows.append(
                {
                    "run": summary.get("run_label") or summary.get("run_id"),
                    "device_tier": summary.get("device", {}).get("tier"),
                    "avg_queue_wait_seconds": summary.get("latency", {}).get("avg_queue_wait_seconds"),
                    "pass_rate": summary.get("counts", {}).get("pass_rate"),
                    "avg_total_seconds": summary.get("latency", {}).get("avg_total_seconds"),
                }
            )

    return {
        "model_tier": model_rows,
        "retrieval_mode": retrieval_rows,
        "runtime_backend": runtime_rows,
        "school_box_queue": school_box_rows,
    }


def build_comparison_markdown(summaries: list[dict[str, Any]]) -> str:
    comparisons = build_comparison_data(summaries)
    lines = ["## Comparison readouts", ""]
    if not any(comparisons.values()):
        return "## Comparison readouts\n\nNo directly comparable run pairs were found in the supplied summaries.\n"

    def _comparison_table(title: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        lines.extend([f"### {title}", ""])
        table_rows = []
        for row in rows:
            table_rows.append(
                [
                    str(row["left_run"]),
                    str(row["right_run"]),
                    f"{_format_rate(row.get('left_pass_rate'))} / {_format_rate(row.get('right_pass_rate'))}",
                    f"{_format_seconds(row.get('left_avg_total_seconds'))} / {_format_seconds(row.get('right_avg_total_seconds'))}",
                    f"{_format_seconds(row.get('left_avg_ttft_seconds'))} / {_format_seconds(row.get('right_avg_ttft_seconds'))}",
                    f"{_format_seconds(row.get('left_avg_queue_wait_seconds'))} / {_format_seconds(row.get('right_avg_queue_wait_seconds'))}",
                ]
            )
        lines.extend(
            [
                _table(
                    ["Left Run", "Right Run", "Pass Rate", "Avg Total", "Avg TTFT", "Avg Queue Wait"],
                    table_rows,
                ),
                "",
            ]
        )

    _comparison_table("E2B vs E4B", comparisons["model_tier"])
    _comparison_table("Lexical vs Hybrid", comparisons["retrieval_mode"])
    _comparison_table("Runtime Backend", comparisons["runtime_backend"])

    if comparisons["school_box_queue"]:
        lines.extend(["### School-Box Queue", ""])
        rows = [
            [
                str(row["run"]),
                str(row["device_tier"]),
                _format_rate(row.get("pass_rate")),
                _format_seconds(row.get("avg_total_seconds")),
                _format_seconds(row.get("avg_queue_wait_seconds")),
            ]
            for row in comparisons["school_box_queue"]
        ]
        lines.extend([_table(["Run", "Device Tier", "Pass Rate", "Avg Total", "Avg Queue Wait"], rows), ""])

    return "\n".join(lines)


def build_highlights(summaries: list[dict[str, Any]], a11y_reports: list[dict[str, Any]]) -> str:
    lines = ["# AccessLab Benchmark Highlights", ""]
    for summary in summaries:
        metrics = summary.get("metrics", {})
        latency = summary.get("latency", {})
        lines.extend(
            [
                f"- {summary.get('run_label') or summary.get('run_id')}: {summary.get('model')} on "
                f"{summary.get('device', {}).get('tier_display', summary.get('device', {}).get('tier', 'device'))}",
                f"- Deployment: {summary.get('deployment_mode_display', summary.get('deployment_mode', 'single-user-local'))}; "
                f"retrieval: {summary.get('retrieval_mode_display', summary.get('retrieval_mode'))}",
                f"- Pass rate: {_format_rate(summary.get('counts', {}).get('pass_rate'))}; "
                f"citation precision: {_format_rate(metrics.get('citation_precision'))}; "
                f"code pass: {_format_rate(metrics.get('code_pass_rate'))}",
                f"- Avg TTFT: {_format_seconds(latency.get('avg_ttft_seconds'))}; "
                f"avg total: {_format_seconds(latency.get('avg_total_seconds'))}; "
                f"peak memory: {_format_number(latency.get('peak_memory_mb'))} MB",
                "",
            ]
        )
    for report in a11y_reports:
        counts = report.get("counts", {})
        lines.append(
            f"- Accessibility smoke: {counts.get('passed', 0)}/{counts.get('total', 0)} checks passed"
        )
    return "\n".join(lines) + "\n"


def build_markdown(
    summaries: list[dict[str, Any]],
    a11y_reports: list[dict[str, Any]],
) -> str:
    lines = [
        "# AccessLab Benchmark Summary",
        "",
        "## Eval runs",
        "",
    ]

    if summaries:
        run_rows = []
        for summary in summaries:
            metrics = summary.get("metrics", {})
            latency = summary.get("latency", {})
            run_rows.append(
                [
                    summary.get("run_label") or summary["run_id"],
                    summary.get("model", ""),
                    _model_tier(summary),
                    summary.get("runtime_backend", ""),
                    summary.get("deployment_profile_display", summary.get("deployment_profile", "")),
                    summary.get("deployment_mode_display", summary.get("deployment_mode", "")),
                    summary.get("device", {}).get("tier_display", summary.get("device", {}).get("tier", "")),
                    summary.get("requested_retrieval_mode", summary.get("retrieval_mode", "")),
                    summary.get("retrieval_mode_display", summary.get("retrieval_mode", "")),
                    summary.get("semantic_status_label", summary.get("semantic_status_code", "")),
                    str(summary.get("ocr_available", "")),
                    _format_rate(summary.get("counts", {}).get("pass_rate")),
                    _format_rate(metrics.get("answer_support_rate")),
                    _format_rate(metrics.get("citation_presence_rate")),
                    _format_rate(metrics.get("citation_precision")),
                    _format_rate(metrics.get("weak_retrieval_abstention_quality")),
                    _format_rate(metrics.get("code_pass_rate")),
                    _format_seconds(latency.get("avg_ttft_seconds")),
                    _format_seconds(latency.get("avg_total_seconds")),
                    _format_seconds(latency.get("avg_prompt_eval_duration_sec")),
                    _format_seconds(latency.get("avg_eval_duration_sec")),
                    _format_seconds(latency.get("avg_queue_wait_seconds")),
                    _format_number(latency.get("peak_memory_mb")),
                    _format_number(latency.get("avg_prompt_eval_count")),
                    _format_number(latency.get("avg_eval_count")),
                ]
            )
        lines.extend(
            [
                _table(
                    [
                        "Run",
                        "Model",
                        "Model Tier",
                        "Runtime",
                        "Profile",
                        "Mode",
                        "Device Tier",
                        "Requested Retrieval",
                        "Effective Retrieval",
                        "Semantic",
                        "OCR",
                        "Pass Rate",
                        "Support Rate",
                        "Citation Presence",
                        "Citation Precision",
                        "Abstention Quality",
                        "Code Pass Rate",
                        "Avg TTFT",
                        "Avg Total",
                        "Avg Prefill",
                        "Avg Decode",
                        "Avg Queue Wait",
                        "Peak Memory MB",
                        "Avg Prompt Tokens",
                        "Avg Output Tokens",
                    ],
                    run_rows,
                ),
                "",
            ]
        )
    else:
        lines.extend(["No eval summaries were provided.", ""])

    lines.extend([build_comparison_markdown(summaries), ""])

    lines.extend(["## Accessibility smoke", ""])
    if a11y_reports:
        for report in a11y_reports:
            counts = report.get("counts", {})
            lines.append(
                f"- {report.get('base_url', 'managed server')}: "
                f"{counts.get('passed', 0)}/{counts.get('total', 0)} checks passed"
            )
        lines.append("")
        a11y_rows = []
        for report in a11y_reports:
            for check in report.get("checks", []):
                a11y_rows.append(
                    [
                        report.get("base_url", "managed server"),
                        check.get("title", ""),
                        "pass" if check.get("passed") else "fail",
                        check.get("detail", ""),
                    ]
                )
        lines.extend(
            [
                _table(["Base URL", "Check", "Result", "Detail"], a11y_rows),
                "",
            ]
        )
    else:
        lines.extend(["No accessibility smoke artifacts were provided.", ""])

    lines.extend(["## References", ""])
    for summary in summaries:
        lines.append(f"- Eval summary: `{summary['paths']['summary']}`")
    for report_path in a11y_reports:
        if "path" in report_path:
            lines.append(f"- Accessibility smoke: `{report_path['path']}`")

    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    summaries = [read_json(Path(path)) for path in args.summary]
    a11y_reports = []
    for path in args.a11y:
        report = read_json(Path(path))
        report["path"] = path
        a11y_reports.append(report)
    markdown = build_markdown(summaries, a11y_reports)
    highlights = build_highlights(summaries, a11y_reports)
    bundle = build_bundle(summaries, a11y_reports)
    output_path = Path(args.output)
    highlights_path = Path(args.highlights_output)
    bundle_path = Path(args.bundle_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    highlights_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    highlights_path.write_text(highlights, encoding="utf-8")
    bundle_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    print(output_path.relative_to(ROOT))
    print(highlights_path.relative_to(ROOT))
    print(bundle_path.relative_to(ROOT))


if __name__ == "__main__":
    main()
