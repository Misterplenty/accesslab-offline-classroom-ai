#!/usr/bin/env python3
"""Run a model-tier sweep on the full 20-task pack.

Four runs by default:
  1. e4b reference (unconstrained, GPU on)
  2. e2b reference (unconstrained, GPU on)
  3. e4b proxy    (num_thread=N, num_gpu=0, num_ctx=K)
  4. e2b proxy    (num_thread=N, num_gpu=0, num_ctx=K)

The "proxy" runs are NOT a real weak-device test. On the M4 Pro they
disable the Metal GPU path, restrict CPU threads, and shrink the KV
cache, which is useful for *comparative* model behavior under stress.
They cannot prove deployment viability on actual old laptops or phones.

Usage:
    python scripts/run_model_tier_sweep.py --device-label m4pro

Requires Ollama running and both gemma4:e4b + gemma4:e2b installed.
Each run writes its own `reports/runs/<id>/{summary.json,results.csv}`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
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
    p.add_argument(
        "--ollama-url",
        default=settings.accesslab_ollama_url,
        help=f"Ollama base URL (default: {settings.accesslab_ollama_url})",
    )
    p.add_argument(
        "--runtime-backend",
        default=settings.runtime_backend,
        help=f"Generation runtime backend (default: {settings.runtime_backend})",
    )
    p.add_argument(
        "--deployment-mode",
        default=settings.deployment_mode,
        help=f"Deployment mode recorded in run summaries (default: {settings.deployment_mode})",
    )
    p.add_argument(
        "--retrieval-mode",
        default="hybrid",
        choices=["hybrid", "lexical"],
        help="Pass through to scripts/run_accesslab_eval.py.",
    )
    p.add_argument("--cold-warm", default="warm", choices=["cold", "warm"])
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument(
        "--models",
        default="gemma4:e4b,gemma4:e2b",
        help="Comma-separated model names to sweep (default: gemma4:e4b,gemma4:e2b)",
    )
    p.add_argument(
        "--proxy-num-thread",
        type=int,
        default=4,
        help="Constrained-proxy num_thread (default: 4)",
    )
    p.add_argument(
        "--proxy-num-gpu",
        type=int,
        default=0,
        help="Constrained-proxy num_gpu (default: 0 — CPU-only)",
    )
    p.add_argument(
        "--proxy-num-ctx",
        type=int,
        default=2048,
        help="Constrained-proxy num_ctx (default: 2048)",
    )
    p.add_argument(
        "--skip-reference",
        action="store_true",
        help="Skip the unconstrained reference runs (only run proxy variants).",
    )
    p.add_argument(
        "--skip-proxy",
        action="store_true",
        help="Skip the constrained proxy runs (only run reference variants).",
    )
    return p.parse_args()


def _preflight_ollama(base_url: str, models: list[str]) -> None:
    url = base_url.rstrip("/") + "/api/tags"
    try:
        response = requests.get(url, timeout=8)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(
            f"Ollama is not reachable at {base_url!r} ({exc}).\n"
            "Start Ollama on this machine and re-run.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    installed = {m.get("name", "") for m in response.json().get("models", [])}
    missing = [m for m in models if m not in installed]
    if missing:
        print(
            f"Models missing: {missing!r}. Installed: {sorted(installed)!r}\n"
            f"Run: ollama pull {' && ollama pull '.join(missing)}",
            file=sys.stderr,
        )
        raise SystemExit(1)


def run_eval(
    *,
    args: argparse.Namespace,
    model: str,
    run_label: str,
    constrained: bool,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_accesslab_eval.py"),
        "--device-label",
        args.device_label,
        "--device-tier",
        "constrained-proxy" if constrained else "standard-laptop",
        "--cold-warm",
        args.cold_warm,
        "--run-label",
        run_label,
        "--temperature",
        str(args.temperature),
        "--seed",
        str(args.seed),
        "--model",
        model,
        "--runtime-backend",
        args.runtime_backend,
        "--deployment-mode",
        args.deployment_mode,
        "--ollama-url",
        args.ollama_url,
        "--retrieval-mode",
        args.retrieval_mode,
    ]
    if constrained:
        cmd.extend(
            [
                "--num-thread",
                str(args.proxy_num_thread),
                "--num-gpu",
                str(args.proxy_num_gpu),
                "--num-ctx",
                str(args.proxy_num_ctx),
            ]
        )

    print("\n" + "=" * 78)
    print(f"Running: model={model}  constrained={constrained}  label={run_label}")
    print("=" * 78)
    before = {p.resolve() for p in (ROOT / "reports" / "runs").iterdir() if p.is_dir()}
    subprocess.run(cmd, cwd=str(ROOT), check=True)

    candidates = sorted(
        (
            p
            for p in (ROOT / "reports" / "runs").iterdir()
            if p.is_dir() and p.resolve() not in before
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for d in candidates:
        summary_path = d / "summary.json"
        if not summary_path.is_file():
            continue
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        if data.get("run_label") == run_label and data.get("model") == model:
            return data
    raise RuntimeError(f"Could not locate summary for label={run_label!r} model={model!r}")


def _f(x: float | None, nd: int = 3) -> str:
    if x is None:
        return "n/a"
    return f"{x:.{nd}f}"


def _pct(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{x:.1%}"


def category_breakdown(summary: dict[str, Any]) -> dict[str, dict[str, int]]:
    rows = summary.get("rows", [])
    by_cat: dict[str, dict[str, int]] = {}
    for row in rows:
        cat = row.get("category", "?")
        bucket = by_cat.setdefault(cat, {"n": 0, "pass": 0, "parse": 0})
        bucket["n"] += 1
        if row.get("task_pass") == "yes":
            bucket["pass"] += 1
        if row.get("parse_ok") == "yes":
            bucket["parse"] += 1
    return by_cat


def summarize_row(label: str, data: dict[str, Any]) -> dict[str, str]:
    counts = data.get("counts", {})
    lat = data.get("latency", {})
    return {
        "run": label,
        "model": data.get("model", ""),
        "n": str(counts.get("total_tasks", "")),
        "pass": f"{counts.get('passed_tasks', '')}/{counts.get('total_tasks', '')}",
        "pass%": _pct(counts.get("pass_rate")),
        "parse": f"{counts.get('parse_ok_tasks', '')}/{counts.get('total_tasks', '')}",
        "parse%": _pct(counts.get("parse_ok_rate")),
        "TTFT": _f(lat.get("avg_ttft_seconds")),
        "total": _f(lat.get("avg_total_seconds")),
        "prefill": _f(lat.get("avg_prompt_eval_duration_sec")),
        "decode": _f(lat.get("avg_eval_duration_sec")),
        "outTok": _f(lat.get("avg_eval_count"), 1),
    }


def print_table(rows: list[dict[str, str]]) -> None:
    headers = ["run", "model", "n", "pass", "pass%", "parse", "parse%", "TTFT", "total", "prefill", "decode", "outTok"]
    widths = [max(len(h), max(len(r[h]) for r in rows)) for h in headers]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))

    print("\n" + "=" * 88)
    print("Model-tier sweep summary (full 20-task pack)")
    print("=" * 88)
    print(line)
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(row[h].ljust(widths[i]) for i, h in enumerate(headers)))
    print("=" * 88)


def print_category_breakdown(label: str, summary: dict[str, Any]) -> None:
    print(f"\n  {label}: per-category pass / parse")
    for cat, b in sorted(category_breakdown(summary).items()):
        print(f"    {cat:35s}  pass {b['pass']}/{b['n']}   parse {b['parse']}/{b['n']}")


def main() -> None:
    args = parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    _preflight_ollama(args.ollama_url, models)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    completed: list[tuple[str, dict[str, Any]]] = []

    if not args.skip_reference:
        for model in models:
            short = model.split(":")[-1]
            label = f"sweep-{short}-ref-{stamp}"
            data = run_eval(args=args, model=model, run_label=label, constrained=False)
            completed.append((f"{short} ref", data))

    if not args.skip_proxy:
        for model in models:
            short = model.split(":")[-1]
            label = f"sweep-{short}-proxy-{stamp}"
            data = run_eval(args=args, model=model, run_label=label, constrained=True)
            completed.append((f"{short} proxy", data))

    if not completed:
        print("No runs were executed.", file=sys.stderr)
        raise SystemExit(2)

    rows = [summarize_row(label, data) for label, data in completed]
    print_table(rows)

    print(
        "\nProxy runs use num_thread="
        f"{args.proxy_num_thread}, num_gpu={args.proxy_num_gpu}, "
        f"num_ctx={args.proxy_num_ctx}. These are comparative stress conditions "
        "on the M4 Pro and DO NOT prove behaviour on real weak devices."
    )

    print("\nPer-category pass / parse:")
    for label, data in completed:
        print_category_breakdown(label, data)

    print("\nSummary JSON paths:")
    for label, data in completed:
        print(f"  {label:18}  {data['paths']['summary']}")


if __name__ == "__main__":
    main()
