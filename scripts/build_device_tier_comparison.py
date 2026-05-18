from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

DEVICE_TIER_ALIASES = {
    "proxy": "constrained-proxy",
    "decent": "standard-laptop",
    "standard-local-laptop": "standard-laptop",
}
DEVICE_TIER_LABELS = {
    "teacher-laptop": "Teacher laptop / mini-PC",
    "standard-laptop": "Standard laptop",
    "school-box-host": "Shared school-box host",
    "edge-validation-device": "Edge-validation device",
    "constrained-proxy": "Constrained proxy",
    "other": "Other / explicitly unsupported tier",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build stable AccessLab device-tier comparison artifacts from benchmark summary.json files."
    )
    parser.add_argument(
        "--summary",
        action="append",
        default=[],
        help="Path to a benchmark summary.json. Repeat for multiple runs. If omitted, recent run summaries are used.",
    )
    parser.add_argument(
        "--max-auto",
        type=int,
        default=8,
        help="Number of recent summaries to include when --summary is omitted.",
    )
    parser.add_argument(
        "--output-json",
        default=str(ROOT / "reports" / "device_tier_comparison_latest.json"),
    )
    parser.add_argument(
        "--output-markdown",
        default=str(ROOT / "reports" / "device_tier_comparison_latest.md"),
    )
    return parser.parse_args()


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_source_path"] = display_path(path)
    return data


def discover_recent(max_auto: int) -> list[Path]:
    candidates = sorted(
        (ROOT / "reports" / "runs").glob("*/summary.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[: max(1, int(max_auto))]


def _rate(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.0%}"
    return "n/a"


def _seconds(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}s"
    return "n/a"


def _number(value: Any) -> str:
    if value is None:
        return "n/a"
    return str(value)


def _model_tier(summary: dict[str, Any]) -> str:
    tier = str(summary.get("model_tier") or "").strip()
    if tier:
        return tier
    model = str(summary.get("model") or "").lower()
    if model.endswith(":e4b"):
        return "E4B"
    if model.endswith(":e2b"):
        return "E2B"
    return "Custom" if model else "unknown"


def _device_tier(raw_value: Any) -> str:
    value = str(raw_value or "").strip().lower()
    value = DEVICE_TIER_ALIASES.get(value, value)
    if value in DEVICE_TIER_LABELS:
        return value
    return "other" if value else ""


def _device_tier_display(raw_value: Any, raw_display: Any) -> str:
    tier = _device_tier(raw_value)
    if tier in DEVICE_TIER_LABELS:
        return DEVICE_TIER_LABELS[tier]
    return str(raw_display or raw_value or "")


def _run_row(summary: dict[str, Any]) -> dict[str, Any]:
    device = summary.get("device", {})
    latency = summary.get("latency", {})
    counts = summary.get("counts", {})
    metrics = summary.get("metrics", {})
    normalized_tier = _device_tier(device.get("tier", ""))
    return {
        "run_id": summary.get("run_id", ""),
        "run_label": summary.get("run_label") or summary.get("run_id", ""),
        "source_path": summary.get("_source_path", ""),
        "generated_at": summary.get("run_timestamp", ""),
        "device_label": device.get("label", ""),
        "device_tier": normalized_tier,
        "device_tier_display": _device_tier_display(device.get("tier", ""), device.get("tier_display", "")),
        "platform": device.get("platform", ""),
        "machine": device.get("machine", ""),
        "cpu_brand": device.get("cpu_brand", ""),
        "logical_cores": device.get("logical_cores"),
        "memory_gb": device.get("memory_gb"),
        "runtime_backend": summary.get("runtime_backend", ""),
        "model": summary.get("model", ""),
        "model_tier": _model_tier(summary),
        "deployment_mode": summary.get("deployment_mode", ""),
        "deployment_mode_display": summary.get("deployment_mode_display", ""),
        "requested_retrieval_mode": summary.get("requested_retrieval_mode", ""),
        "effective_retrieval_mode": summary.get("retrieval_mode", ""),
        "effective_retrieval_mode_display": summary.get("retrieval_mode_display", ""),
        "semantic_available": summary.get("semantic_available"),
        "semantic_status_code": summary.get("semantic_status_code", ""),
        "ocr_available": summary.get("ocr_available"),
        "avg_ttft_seconds": latency.get("avg_ttft_seconds"),
        "avg_total_seconds": latency.get("avg_total_seconds"),
        "avg_prompt_eval_count": latency.get("avg_prompt_eval_count"),
        "avg_eval_count": latency.get("avg_eval_count"),
        "avg_queue_wait_seconds": latency.get("avg_queue_wait_seconds"),
        "peak_memory_mb": latency.get("peak_memory_mb"),
        "pass_rate": counts.get("pass_rate"),
        "code_pass_rate": metrics.get("code_pass_rate"),
        "answer_support_rate": metrics.get("answer_support_rate"),
        "citation_presence_rate": metrics.get("citation_presence_rate"),
    }


def build_report(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [_run_row(summary) for summary in summaries]
    real_rows = [
        row for row in rows
        if row["device_tier"] not in {"constrained-proxy", "other", ""}
    ]
    proxy_rows = [row for row in rows if row["device_tier"] == "constrained-proxy"]
    device_tiers = sorted({row["device_tier_display"] or row["device_tier"] for row in rows if row["device_tier"]})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_count": len(rows),
        "real_hardware_run_count": len(real_rows),
        "constrained_proxy_run_count": len(proxy_rows),
        "device_tiers": device_tiers,
        "runs": rows,
        "what_this_proves": [
            "The listed benchmark rows ran on the recorded local hardware and runtime backend.",
            "Gemma 4 task pass, citation, code repair, latency, token, queue, OCR, and semantic fields are taken from run artifacts.",
            "Rows marked teacher-laptop, standard-laptop, school-box-host, or edge-validation-device are hardware evidence for that recorded host only.",
        ],
        "what_this_does_not_prove": [
            "It does not prove performance on lowest-end phones or untested devices.",
            "It does not prove production multi-user serving.",
            "It does not prove secure code sandboxing.",
            "Constrained-proxy rows are stress comparisons on the same host, not separate hardware tiers.",
        ],
        "honest_limits": [
            "Unknown tiers are not marketed as target tiers.",
            "A single host result should be described as measured hardware evidence, not a fleet guarantee.",
            "LiteRT-LM rows remain validation-only unless their runtime backend was actually exercised.",
        ],
    }


def build_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# AccessLab Device-Tier Comparison",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Runs included: {report['run_count']}",
        f"- Real hardware runs: {report['real_hardware_run_count']}",
        f"- Constrained-proxy runs: {report['constrained_proxy_run_count']}",
        f"- Device tiers: {', '.join(report['device_tiers']) or 'none'}",
        "",
        "## Run Table",
        "",
        "| Run | Device Tier | CPU/RAM | Runtime | Model | Mode | Retrieval | Semantic | OCR | Pass | Code | Support | TTFT | Total | Tokens In/Out | Queue | Peak MB |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["runs"]:
        cpu_ram = f"{row['cpu_brand'] or row['machine']} / {_number(row['memory_gb'])} GB"
        tokens = f"{_number(row['avg_prompt_eval_count'])}/{_number(row['avg_eval_count'])}"
        lines.append(
            f"| {row['run_label']} | {row['device_tier_display'] or row['device_tier']} | "
            f"{cpu_ram} | {row['runtime_backend']} | {row['model']} ({row['model_tier']}) | "
            f"{row['deployment_mode_display'] or row['deployment_mode']} | "
            f"{row['requested_retrieval_mode']} -> {row['effective_retrieval_mode_display'] or row['effective_retrieval_mode']} | "
            f"{row['semantic_status_code']} | {row['ocr_available']} | {_rate(row['pass_rate'])} | "
            f"{_rate(row['code_pass_rate'])} | {_rate(row['answer_support_rate'])} | "
            f"{_seconds(row['avg_ttft_seconds'])} | {_seconds(row['avg_total_seconds'])} | "
            f"{tokens} | {_seconds(row['avg_queue_wait_seconds'])} | {_number(row['peak_memory_mb'])} |"
        )
    lines.extend(["", "## What This Proves", ""])
    lines.extend(f"- {item}" for item in report["what_this_proves"])
    lines.extend(["", "## What This Does Not Prove", ""])
    lines.extend(f"- {item}" for item in report["what_this_does_not_prove"])
    lines.extend(["", "## Source Summaries", ""])
    lines.extend(f"- `{row['source_path']}`" for row in report["runs"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    summary_paths = [Path(path) for path in args.summary] if args.summary else discover_recent(args.max_auto)
    summaries = [read_json(path) for path in summary_paths if path.exists()]
    report = build_report(summaries)
    if not summaries:
        report["honest_limits"].insert(
            0,
            "No reports/runs/*/summary.json files were present when this artifact was refreshed.",
        )
    json_path = Path(args.output_json)
    markdown_path = Path(args.output_markdown)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown_path.write_text(build_markdown(report), encoding="utf-8")
    print(display_path(json_path))
    print(display_path(markdown_path))


if __name__ == "__main__":
    main()
