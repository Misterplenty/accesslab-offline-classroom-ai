"""Compare two AccessLab benchmark summary JSONs and print a decision memo.

Usage:
    python scripts/compare_benchmark_runs.py \\
        reports/runs/<baseline>/summary.json \\
        reports/runs/<experimental>/summary.json

Or with more than two runs for multi-run averaging (pass any number of paths
for the same label; the script groups by run_label):
    python scripts/compare_benchmark_runs.py run_A/summary.json run_B/summary.json

Output:
    Console comparison table + short decision memo.

The memo answers:
    - Did TTFT improve?
    - Did prompt_eval_duration (prefill) improve?
    - Did eval_duration (decode) improve?
    - Did pass rate change?
    - Did parse/formatting reliability break?
    - Is the regression likely prefill-related, decode-related, or inconclusive?
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import fmean
from typing import Any


def load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _f(val: float | None, decimals: int = 3) -> str:
    if val is None:
        return "n/a"
    return f"{val:.{decimals}f}s"


def _pct(val: float | None) -> str:
    if val is None:
        return "n/a"
    return f"{val:.1%}"


def _delta(a: float | None, b: float | None) -> str:
    """Return delta string: positive = b is larger (regression), negative = improvement."""
    if a is None or b is None:
        return "n/a"
    d = b - a
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.3f}s"


def _delta_pct(a: float | None, b: float | None) -> str:
    if a is None or b is None or a == 0:
        return "n/a"
    pct = (b - a) / a * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def summarise(summary: dict[str, Any]) -> dict[str, Any]:
    lat = summary.get("latency", {})
    counts = summary.get("counts", {})
    return {
        "run_id": summary.get("run_id", ""),
        "run_label": summary.get("run_label", summary.get("run_id", "")),
        "cold_or_warm": summary.get("cold_or_warm", "?"),
        "prompt_variant": summary.get("prompt_variant", "baseline"),
        "model": summary.get("model", ""),
        "pass_rate": counts.get("pass_rate"),
        "parse_ok_rate": counts.get("parse_ok_rate"),
        "total_tasks": counts.get("total_tasks"),
        "avg_ttft": lat.get("avg_ttft_seconds"),
        "median_ttft": lat.get("median_ttft_seconds"),
        "avg_total": lat.get("avg_total_seconds"),
        "avg_load": lat.get("avg_load_duration_sec"),
        "avg_prefill": lat.get("avg_prompt_eval_duration_sec"),
        "median_prefill": lat.get("median_prompt_eval_duration_sec"),
        "avg_decode": lat.get("avg_eval_duration_sec"),
        "median_decode": lat.get("median_eval_duration_sec"),
        "avg_prompt_tokens": lat.get("avg_prompt_eval_count"),
        "avg_output_tokens": lat.get("avg_eval_count"),
    }


def print_row(label: str, a_val: str, b_val: str, delta: str, width: int = 30) -> None:
    print(f"  {label:<{width}} {a_val:>10}  {b_val:>10}  {delta:>12}")


def main() -> None:
    paths = sys.argv[1:]
    if len(paths) < 2:
        print("Usage: compare_benchmark_runs.py <summary_A.json> <summary_B.json>")
        sys.exit(1)

    summaries = [load(p) for p in paths]
    runs = [summarise(s) for s in summaries]

    if len(runs) == 2:
        a, b = runs
    else:
        print(f"Loaded {len(runs)} summaries. Comparing first two.")
        a, b = runs[0], runs[1]

    sep = "=" * 70
    print(sep)
    print("AccessLab Benchmark Comparison")
    print(sep)
    print(f"  A: {a['run_label']} [{a['cold_or_warm']}] variant={a['prompt_variant']}")
    print(f"  B: {b['run_label']} [{b['cold_or_warm']}] variant={b['prompt_variant']}")
    print(f"  Model: {a['model']} vs {b['model']}")
    print()

    hdr = f"  {'Metric':<30} {'A':>10}  {'B':>10}  {'Delta (B-A)':>12}"
    print(hdr)
    print("-" * 70)
    print_row("pass_rate", _pct(a["pass_rate"]), _pct(b["pass_rate"]),
               _delta_pct(a["pass_rate"], b["pass_rate"]))
    print_row("parse_ok_rate", _pct(a["parse_ok_rate"]), _pct(b["parse_ok_rate"]),
               _delta_pct(a["parse_ok_rate"], b["parse_ok_rate"]))
    print()
    print_row("avg TTFT (wall-clock)", _f(a["avg_ttft"]), _f(b["avg_ttft"]),
               _delta(a["avg_ttft"], b["avg_ttft"]))
    print_row("median TTFT", _f(a["median_ttft"]), _f(b["median_ttft"]),
               _delta(a["median_ttft"], b["median_ttft"]))
    print_row("avg total (wall-clock)", _f(a["avg_total"]), _f(b["avg_total"]),
               _delta(a["avg_total"], b["avg_total"]))
    print()
    print_row("avg load_duration", _f(a["avg_load"]), _f(b["avg_load"]),
               _delta(a["avg_load"], b["avg_load"]))
    print_row("avg prefill (prompt_eval)", _f(a["avg_prefill"]), _f(b["avg_prefill"]),
               _delta(a["avg_prefill"], b["avg_prefill"]))
    print_row("median prefill", _f(a["median_prefill"]), _f(b["median_prefill"]),
               _delta(a["median_prefill"], b["median_prefill"]))
    print_row("avg decode (eval_duration)", _f(a["avg_decode"]), _f(b["avg_decode"]),
               _delta(a["avg_decode"], b["avg_decode"]))
    print_row("median decode", _f(a["median_decode"]), _f(b["median_decode"]),
               _delta(a["median_decode"], b["median_decode"]))
    print()
    print_row("avg prompt tokens", str(a["avg_prompt_tokens"]), str(b["avg_prompt_tokens"]),
               _delta_pct(a["avg_prompt_tokens"], b["avg_prompt_tokens"]))
    print_row("avg output tokens", str(a["avg_output_tokens"]), str(b["avg_output_tokens"]),
               _delta_pct(a["avg_output_tokens"], b["avg_output_tokens"]))
    print(sep)

    # --- Decision memo ---
    print()
    print("Decision Memo")
    print(sep)

    def _improve(a_val: float | None, b_val: float | None, threshold: float = 0.5) -> str:
        if a_val is None or b_val is None:
            return "inconclusive (missing data)"
        diff = b_val - a_val
        pct = diff / a_val * 100 if a_val else 0
        if abs(pct) < threshold:
            return f"no meaningful change ({diff:+.3f}s, {pct:+.1f}%)"
        direction = "improved" if diff < 0 else "regressed"
        return f"{direction} by {abs(diff):.3f}s ({abs(pct):.1f}%)"

    print(f"  TTFT:              {_improve(a['avg_ttft'], b['avg_ttft'])}")
    print(f"  Prefill duration:  {_improve(a['avg_prefill'], b['avg_prefill'])}")
    print(f"  Decode duration:   {_improve(a['avg_decode'], b['avg_decode'])}")
    print(f"  Pass rate:         {_improve(a['pass_rate'], b['pass_rate'], threshold=1.0)}")
    print(f"  Parse reliability: {_improve(a['parse_ok_rate'], b['parse_ok_rate'], threshold=1.0)}")

    # Root cause hint
    print()
    prefill_a = a["avg_prefill"]
    decode_a = a["avg_decode"]
    prefill_b = b["avg_prefill"]
    decode_b = b["avg_decode"]

    if prefill_a and prefill_b and decode_a and decode_b:
        prefill_delta_pct = (prefill_b - prefill_a) / prefill_a * 100
        decode_delta_pct = (decode_b - decode_a) / decode_a * 100
        total_delta_pct = ((a["avg_total"] or 0) and
                           ((b["avg_total"] or 0) - (a["avg_total"] or 0)) / (a["avg_total"] or 1) * 100)

        if abs(prefill_delta_pct) < 5 and abs(decode_delta_pct) < 5:
            verdict = "INCONCLUSIVE — both prefill and decode are stable. Latency difference may be noise or load-related."
        elif prefill_delta_pct < -5 and abs(decode_delta_pct) < 5:
            verdict = "PREFILL WIN — prompt_eval improved meaningfully. Token reduction or simpler instructions helped prefill."
        elif abs(prefill_delta_pct) < 5 and decode_delta_pct < -5:
            verdict = "DECODE WIN — eval_duration improved. Shorter output format reduced generation length."
        elif prefill_delta_pct < -5 and decode_delta_pct < -5:
            verdict = "BOTH PHASES IMPROVED — prompt simplification reduced both prefill and decode cost."
        elif prefill_delta_pct > 5 or decode_delta_pct > 5:
            verdict = "REGRESSION — one or both phases are slower in B. Experimental variant may have increased output length."
        else:
            verdict = "MIXED — check individual phase deltas above."
    else:
        verdict = "INCONCLUSIVE — Ollama-native timing fields missing. Ensure Ollama is v0.5+ and streaming is used."

    print(f"  Root cause hint:   {verdict}")
    print(sep)


if __name__ == "__main__":
    main()
