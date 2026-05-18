from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


FAILURE_FIXES = {
    "missed_expected_content": "Tighten retrieved context size so the strongest chunk dominates the prompt.",
    "citation_mismatch": "Strengthen citation formatting and require the first cited source to match the highest-ranked chunk.",
    "retrieval_or_grounding": "Compact the QA prompt and add a stricter weak-retrieval fallback before generation.",
    "uncertainty_guardrail_miss": "Raise the weak-retrieval threshold so nonexistent worksheet questions trigger source-first fallback more often.",
    "patch_did_not_pass_tests": "Shorten the code-tutor prompt and emphasize smallest possible patch before any rewrite.",
    "weak_evidence_reference": "Make the code-tutor prompt quote failing test or runtime lines explicitly before proposing a fix.",
    "verbosity": "Reduce default output length and cap extra detail unless the user explicitly asks for more.",
    "runner_error": "Harden the eval runner so individual task failures do not leave missing outputs.",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the AccessLab v0.1 evaluation report from one or more run summaries.")
    parser.add_argument("summaries", nargs="+", help="Path(s) to summary.json emitted by scripts/run_accesslab_eval.py")
    parser.add_argument("--output", default=str(ROOT / "reports" / "accesslab_v0_1_evaluation.md"))
    return parser.parse_args()


def read_summary(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def format_seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}s"


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def next_three_fixes(top_failures: list[str]) -> list[str]:
    fixes: list[str] = []
    for tag in top_failures:
        fix = FAILURE_FIXES.get(tag)
        if fix and fix not in fixes:
            fixes.append(fix)
        if len(fixes) == 3:
            break

    defaults = [
        "Improve prompt compactness so local inference spends less time on boilerplate.",
        "Reduce default output length and only expand when the user asks for more detail.",
        "Evaluate whether a smaller fallback model should handle the easiest tasks on weaker devices.",
    ]
    for fix in defaults:
        if len(fixes) == 3:
            break
        if fix not in fixes:
            fixes.append(fix)
    return fixes


def build_report(summaries: list[dict[str, Any]]) -> str:
    primary = summaries[0]
    primary_rows = primary["rows"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    primary_model = primary["model"]
    primary_device_label = primary["device"]["label"]
    has_weak_e2b = any(summary["model"] == "gemma4:e2b" for summary in summaries[1:])
    is_preliminary = not has_weak_e2b
    hardware_signatures = {
        (
            summary["device"].get("cpu_brand") or "unknown",
            summary["device"].get("memory_gb"),
            summary["device"].get("logical_cores"),
        )
        for summary in summaries
    }
    same_hardware_only = len(summaries) > 1 and len(hardware_signatures) == 1
    title = "# AccessLab v0.1 Evaluation"
    if is_preliminary:
        title = "# AccessLab v0.1 Evaluation — Preliminary (e4b complete, e2b pending)"
    elif same_hardware_only:
        title = "# AccessLab v0.1 Evaluation — Model-Tier Complete (e4b and e2b), Real Weak-Device Benchmark Pending"

    pass_fail_rows = [
        [
            row["task_id"],
            row["category"],
            row["task_pass"],
            format_seconds(row["ttft_seconds"]),
            format_seconds(row["total_response_time_seconds"]),
            row["grounded"],
            row["citation_correct"] or "n/a",
            row["helpful"],
            row["too_verbose"],
            row["passed_tests"] or "n/a",
        ]
        for row in primary_rows
    ]

    device_rows = []
    for summary in summaries:
        device = summary["device"]
        latency = summary["latency"]
        device_rows.append(
            [
                device["label"],
                device["tier"],
                summary["model"],
                device.get("cpu_brand") or "unknown",
                f"{device.get('memory_gb', 'n/a')} GB" if device.get("memory_gb") is not None else "n/a",
                str(device.get("logical_cores") or "n/a"),
                format_seconds(latency["avg_ttft_seconds"]),
                format_seconds(latency["avg_total_seconds"]),
                f"{summary['counts']['pass_rate']:.0%}",
            ]
        )

    ttft_rows = []
    for summary in summaries:
        latency = summary["latency"]
        ttft_rows.append(
            [
                summary["device"]["label"],
                format_seconds(latency["avg_ttft_seconds"]),
                format_seconds(latency["median_ttft_seconds"]),
                format_seconds(latency["avg_total_seconds"]),
                format_seconds(latency["avg_retrieval_seconds"]),
                format_seconds(latency["avg_prompt_build_seconds"]),
                format_seconds(latency["avg_model_inference_seconds"]),
                format_seconds(latency["avg_post_processing_seconds"]),
                format_seconds(latency["avg_code_execution_seconds"]),
            ]
        )

    failure_counter: Counter[str] = Counter()
    for summary in summaries:
        for row in summary["rows"]:
            failure_counter.update(row.get("failure_tags", []))
    top_failures = [tag for tag, _count in failure_counter.most_common(3)]
    top_failure_lines = []
    for tag, count in failure_counter.most_common(3):
        top_failure_lines.append(f"- `{tag}`: {count} task(s)")
    if not top_failure_lines:
        top_failure_lines.append("- No recurring failure tags were recorded in the primary run.")

    fixes = next_three_fixes(top_failures)

    lines = [
        title,
        "",
        f"Generated: {now}",
        "",
        "This report summarizes the current AccessLab evaluation pack, timing profile, device comparison, and the next fixes to prioritize before any training work.",
        "",
        "## Summary Status",
        "",
        (
            "> Status: preliminary"
            if is_preliminary
            else "> Status: model-tier complete, hardware-tier provisional"
            if same_hardware_only
            else "> Status: complete"
        ),
        (
            f"> Complete for: {primary_model} on {primary_device_label}"
            if is_preliminary
            else f"> Complete for: gemma4:e4b and gemma4:e2b on the current host ({primary['device'].get('cpu_brand') or 'unknown'})"
            if same_hardware_only
            else f"> Complete for: {primary_model} on {primary_device_label}"
        ),
        (
            "> Pending: gemma4:e2b weak-tier benchmark"
            if is_preliminary
            else "> Pending: a real weak-device benchmark on separate aging hardware"
            if same_hardware_only
            else "> Pending: none"
        ),
        (
            "> Do not treat device comparison as final until e2b is run"
            if is_preliminary
            else "> Do not treat hardware-tier conclusions as final until the same task pack is run on a separate weak machine"
            if same_hardware_only
            else "> Device comparison is final for the runs included here"
        ),
        "",
        "## Pass/Fail Table",
        "",
        markdown_table(
            [
                "Task",
                "Category",
                "Pass",
                "TTFT",
                "Total",
                "Grounded",
                "Citation",
                "Helpful",
                "Too Verbose",
                "Passed Tests",
            ],
            pass_fail_rows,
        ),
        "",
        "## Device Table",
        "",
        markdown_table(
            [
                "Device",
                "Tier",
                "Model",
                "CPU",
                "Memory",
                "Cores",
                "Avg TTFT",
                "Avg Total",
                "Pass Rate",
            ],
            device_rows,
        ),
        "",
        (
            "Current device table is incomplete because the weak-tier gemma4:e2b comparison has not yet been executed."
            if is_preliminary
            else "Current device table includes the weak-tier gemma4:e2b comparison, but both runs were executed on the same host. Treat this as a Gemma 4 model-tier comparison, not a true two-machine hardware benchmark."
            if same_hardware_only
            else "Current device table includes the weak-tier gemma4:e2b comparison."
        ),
        "",
        "## TTFT Table",
        "",
        markdown_table(
            [
                "Device",
                "Avg TTFT",
                "Median TTFT",
                "Avg Total",
                "Retrieval",
                "Prompt Build",
                "Model Inference",
                "Post-Processing",
                "Code Execution",
            ],
            ttft_rows,
        ),
        "",
        "## Top 3 Failure Modes",
        "",
        *top_failure_lines,
        "",
        "## Next 3 Fixes",
        "",
        *[f"- {fix}" for fix in fixes],
        "",
        "## Conclusion Note",
        "",
        (
            "Current conclusions are valid for the primary e4b run only. Hardware-tier conclusions remain provisional until the weak-tier e2b benchmark is added."
            if is_preliminary
            else "Current conclusions include both Gemma 4 model tiers on the current host. Hardware-tier conclusions remain provisional until a separate weak machine is benchmarked with the same 20-task pack."
            if same_hardware_only
            else "Current conclusions include both the primary e4b run and the weak-tier e2b benchmark."
        ),
        "",
        "## Notes",
        "",
        f"- Primary run: `{primary['paths']['summary']}`",
        *[f"- Comparison run: `{summary['paths']['summary']}`" for summary in summaries[1:]],
    ]

    lines.append("- The preferred weak-tier comparison for this project is `gemma4:e2b`.")

    if not has_weak_e2b:
        lines.extend(
            [
                "- A completed `gemma4:e2b` weak-tier benchmark is still pending in this report.",
            ]
        )
    elif same_hardware_only:
        lines.extend(
            [
                "- Both runs in this report were executed on the same Apple M4 Pro host on 2026-04-14.",
                "- This report now proves the Gemma 4 quality/latency tradeoff across `gemma4:e4b` and `gemma4:e2b`, but it does not yet prove behavior on a separate aging laptop.",
            ]
        )

    if any(summary["device"]["tier"] == "proxy" for summary in summaries):
        lines.extend(
            [
                "- A `proxy` tier is a useful fallback signal, but it is not a substitute for a true old-laptop benchmark.",
            ]
        )

    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    summaries = [read_summary(Path(path)) for path in args.summaries]
    report = build_report(summaries)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(output_path.relative_to(ROOT))


if __name__ == "__main__":
    main()
