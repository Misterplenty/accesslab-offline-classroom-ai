#!/usr/bin/env python3
"""Run code-only A/B/C benchmark: baseline vs experimental vs hybrid code tutor.

Invokes scripts/run_accesslab_eval.py three times (8 tasks, category
beginner-python-bug-fix) and prints a consolidated metrics table.

Usage:
    python scripts/run_code_tutor_abc_benchmark.py --device-label my-mac

Requires: Ollama running, model installed (default gemma4:e4b from .env / CLI).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from statistics import fmean
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--device-label", required=True)
    p.add_argument("--device-tier", default="decent", choices=["decent", "weak", "proxy"])
    p.add_argument(
        "--model",
        default=settings.accesslab_model,
        help=f"Ollama model name (default: {settings.accesslab_model})",
    )
    p.add_argument(
        "--ollama-url",
        default=settings.accesslab_ollama_url,
        help=f"Ollama base URL (default: {settings.accesslab_ollama_url})",
    )
    p.add_argument("--cold-warm", default="warm", choices=["cold", "warm"])
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument(
        "--categories",
        default="beginner-python-bug-fix",
        help="Comma-separated categories (default: 8 code tasks only)",
    )
    return p.parse_args()


def run_variant(
    *,
    variant: str,
    run_label: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_accesslab_eval.py"),
        "--device-label",
        args.device_label,
        "--device-tier",
        args.device_tier,
        "--cold-warm",
        args.cold_warm,
        "--prompt-variant",
        variant,
        "--run-label",
        run_label,
        "--categories",
        args.categories,
        "--temperature",
        str(args.temperature),
        "--seed",
        str(args.seed),
    ]
    cmd.extend(["--model", args.model, "--ollama-url", args.ollama_url])

    print("\n" + "=" * 72)
    print(f"Running: {variant}  (label={run_label})")
    print("=" * 72)
    before = {p.resolve() for p in (ROOT / "reports" / "runs").iterdir() if p.is_dir()}
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    after_dirs = sorted(
        (p for p in (ROOT / "reports" / "runs").iterdir() if p.is_dir() and p.resolve() not in before),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    # Prefer the run directory created by this subprocess (not present before).
    for d in after_dirs:
        summary_path = d / "summary.json"
        if summary_path.is_file():
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            if data.get("prompt_variant") == variant:
                return data
    # Fallback: newest summary with matching variant (e.g. if clock skew or dir reuse).
    for d in sorted(
        (p for p in (ROOT / "reports" / "runs").iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:8]:
        summary_path = d / "summary.json"
        if not summary_path.is_file():
            continue
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        if data.get("prompt_variant") == variant and data.get("run_label") == run_label:
            return data
    raise RuntimeError(f"Could not locate summary.json for variant={variant!r} label={run_label!r}")


def _f(x: float | None, nd: int = 3) -> str:
    if x is None:
        return "n/a"
    return f"{x:.{nd}f}"


def _pct(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{x:.1%}"


def summarize_row(label: str, s: dict[str, Any]) -> dict[str, str]:
    c = s.get("counts", {})
    lat = s.get("latency", {})
    return {
        "variant": label,
        "tasks": str(c.get("total_tasks", "")),
        "pass": f"{c.get('passed_tasks', '')}/{c.get('total_tasks', '')}",
        "pass_rate": _pct(c.get("pass_rate")),
        "parse_ok": f"{c.get('parse_ok_tasks', '')}/{c.get('total_tasks', '')}",
        "parse_rate": _pct(c.get("parse_ok_rate")),
        "avg_ttft": _f(lat.get("avg_ttft_seconds")),
        "avg_total": _f(lat.get("avg_total_seconds")),
        "avg_prefill": _f(lat.get("avg_prompt_eval_duration_sec")),
        "avg_decode": _f(lat.get("avg_eval_duration_sec")),
        "avg_out_tok": _f(lat.get("avg_eval_count"), 1),
    }


def print_table(rows: list[dict[str, str]]) -> None:
    cols = [
        ("variant", "variant"),
        ("tasks", "N"),
        ("pass", "pass"),
        ("pass_rate", "pass%"),
        ("parse_ok", "parse"),
        ("parse_rate", "parse%"),
        ("avg_ttft", "TTFT"),
        ("avg_total", "total"),
        ("avg_prefill", "prefill"),
        ("avg_decode", "decode"),
        ("avg_out_tok", "outTok"),
    ]
    headers = [h for _, h in cols]
    keys = [k for k, _ in cols]
    widths = [max(len(headers[i]), max(len(r[keys[i]]) for r in rows)) for i in range(len(cols))]

    def fmt_line(cells: list[str]) -> str:
        return "  ".join(c.ljust(widths[i]) for i, c in enumerate(cells))

    print("\n" + "=" * 72)
    print("Code-tutor A/B/C summary (code tasks only)")
    print("=" * 72)
    print(fmt_line(headers))
    print(fmt_line(["-" * w for w in widths]))
    for r in rows:
        print(fmt_line([r[k] for k in keys]))
    print("=" * 72)


def _preflight_ollama(base_url: str, model: str) -> None:
    url = base_url.rstrip("/") + "/api/tags"
    try:
        response = requests.get(url, timeout=8)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(
            f"Ollama is not reachable at {base_url!r} ({exc}).\n"
            "Start Ollama on this machine (e.g. `ollama serve` or open the Ollama app), "
            "then re-run this script from the same environment.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    names = {m.get("name", "") for m in response.json().get("models", [])}
    if model not in names:
        print(
            f"Model {model!r} is not installed. Installed: {sorted(names)!r}\n"
            f"Run: ollama pull {model}",
            file=sys.stderr,
        )
        raise SystemExit(1)


def main() -> None:
    args = parse_args()
    _preflight_ollama(args.ollama_url, args.model)
    from datetime import datetime

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    summaries: list[tuple[str, dict[str, Any]]] = []

    for variant, short in (
        ("baseline", "abc-baseline"),
        ("experimental", "abc-experimental"),
        ("hybrid", "abc-hybrid"),
    ):
        run_label = f"{short}-{stamp}"
        data = run_variant(variant=variant, run_label=run_label, args=args)
        summaries.append((variant, data))

    rows = [summarize_row(v, s) for v, s in summaries]
    print_table(rows)

    print("\nSummary JSON paths:")
    for variant, data in summaries:
        print(f"  {variant:12}  {data['paths']['summary']}")

    print("\nPairwise compare (copy/paste):")
    b_path = summaries[0][1]["paths"]["summary"]
    e_path = summaries[1][1]["paths"]["summary"]
    h_path = summaries[2][1]["paths"]["summary"]
    print(f"  python scripts/compare_benchmark_runs.py {b_path} {e_path}")
    print(f"  python scripts/compare_benchmark_runs.py {b_path} {h_path}")


if __name__ == "__main__":
    main()
