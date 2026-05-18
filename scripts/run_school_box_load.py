from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.config import get_settings
from app.services.work_queue import LocalWorkQueue


JOB_KINDS = ("grounded-qa", "code-tutor", "grounded-qa", "grounded-qa")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Exercise AccessLab's local school-box queue with synthetic concurrent jobs."
    )
    parser.add_argument("--jobs", type=int, default=12)
    parser.add_argument("--max-concurrent-jobs", type=int, default=settings.max_concurrent_jobs)
    parser.add_argument("--job-seconds", type=float, default=0.2)
    parser.add_argument("--submit-spacing-seconds", type=float, default=0.0)
    parser.add_argument("--device-label", default="school-box-host")
    parser.add_argument("--device-tier", default="school-box-host")
    parser.add_argument(
        "--output-json",
        default=str(ROOT / "reports" / "school_box_load_latest.json"),
    )
    parser.add_argument(
        "--output-markdown",
        default=str(ROOT / "reports" / "school_box_load_latest.md"),
    )
    return parser.parse_args()


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return round(ordered[index], 3)


def _run_job(
    queue: LocalWorkQueue,
    *,
    job_index: int,
    job_kind: str,
    job_seconds: float,
    start_event: threading.Event,
) -> dict[str, Any]:
    submitted_at = datetime.now(timezone.utc).isoformat()
    start_event.wait()
    with queue.job(job_kind=job_kind) as receipt:
        time.sleep(max(0.0, job_seconds))
    return {
        "job_index": job_index,
        "job_kind": job_kind,
        "submitted_at": submitted_at,
        "ticket_id": receipt.ticket_id,
        "started_at": receipt.started_at,
        "finished_at": receipt.finished_at,
        "outcome": receipt.outcome,
        "wait_seconds": round(receipt.wait_seconds, 3),
        "run_seconds": round(receipt.run_seconds, 3),
        "weight": receipt.weight,
    }


def build_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    lines = [
        "# AccessLab School-Box Load Snapshot",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Scenario: {report['scenario']}",
        f"- Scenario description: {report['scenario_description']}",
        f"- Submitted jobs: {metrics['submitted_jobs']}",
        f"- Completed jobs: {metrics['completed_jobs']}",
        f"- Failed jobs: {metrics['failed_jobs']}",
        f"- Completion rate: {metrics['completion_rate']:.1%}",
        f"- Max concurrent jobs configured: {report['max_concurrent_jobs']}",
        f"- Max observed active jobs: {metrics['max_observed_active_jobs']}",
        f"- Max observed waiting jobs: {metrics['max_observed_waiting_jobs']}",
        f"- Avg queue wait: {metrics['avg_wait_seconds']}s",
        f"- Median queue wait: {metrics['median_wait_seconds']}s",
        f"- P95 queue wait: {metrics['p95_wait_seconds']}s",
        f"- Max queue wait: {metrics['max_wait_seconds']}s",
        "",
        "## Queue Behavior",
        "",
        "Jobs are first-in, first-served by ticket and constrained by the local capacity budget. "
        "This synthetic run exercises the same queue primitive used by uploads, grounded QA, code repair, OCR, and indexing.",
        "",
        "## What The Synthetic Test Does",
        "",
        "- Submits multiple local jobs at nearly the same time.",
        "- Measures queue wait distribution under the configured local concurrency budget.",
        "- Confirms the in-process queue exposes active, waiting, completed, and failed job state.",
        "",
        "## What The Synthetic Test Does Not Prove",
        "",
        "- It does not call Gemma 4, OCR, or EmbeddingGemma for every synthetic job.",
        "- It does not prove production multi-user serving or a distributed queue.",
        "- It does not prove one host can satisfy a full classroom at once without wait time.",
        "",
        "## Honest Limits",
        "",
        "- This is local synthetic load, not internet-scale concurrency proof.",
        "- School-box mode is intended for a classroom LAN and a conservative number of simultaneous learners.",
        "- Queue pressure increases wait time; large OCR or embedding work should be avoided during live student use.",
        "- Prefer teacher-laptop or classroom-local mode when one machine is driving the lesson for the room.",
        "- Prefer school-box mode when several browsers need the same local materials and host.",
        "",
        "## Job Rows",
        "",
        "| Ticket | Kind | Outcome | Wait | Run |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in report["jobs"]:
        lines.append(
            f"| {row['ticket_id']} | {row['job_kind']} | {row['outcome']} | "
            f"{row['wait_seconds']}s | {row['run_seconds']}s |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    queue = LocalWorkQueue(max_concurrent_jobs=args.max_concurrent_jobs)
    start_event = threading.Event()
    samples: list[dict[str, Any]] = []
    stop_sampling = False

    def sampler() -> None:
        while not stop_sampling:
            samples.append(queue.snapshot())
            time.sleep(0.02)

    sampler_thread = threading.Thread(target=sampler, daemon=True)
    sampler_thread.start()

    jobs: list[dict[str, Any]] = []
    submitted = max(1, int(args.jobs))
    with ThreadPoolExecutor(max_workers=submitted) as executor:
        futures = []
        for index in range(submitted):
            futures.append(
                executor.submit(
                    _run_job,
                    queue,
                    job_index=index + 1,
                    job_kind=JOB_KINDS[index % len(JOB_KINDS)],
                    job_seconds=args.job_seconds,
                    start_event=start_event,
                )
            )
            if args.submit_spacing_seconds > 0:
                time.sleep(args.submit_spacing_seconds)
        start_event.set()
        for future in as_completed(futures):
            try:
                jobs.append(future.result())
            except Exception as exc:
                jobs.append(
                    {
                        "job_index": 0,
                        "job_kind": "unknown",
                        "outcome": "failed",
                        "wait_seconds": 0.0,
                        "run_seconds": 0.0,
                        "error": str(exc),
                    }
                )

    stop_sampling = True
    sampler_thread.join(timeout=1)
    final_snapshot = queue.snapshot()
    jobs.sort(key=lambda row: int(row.get("ticket_id") or 0))

    wait_values = [float(row.get("wait_seconds", 0.0) or 0.0) for row in jobs]
    completed_jobs = sum(row.get("outcome") == "complete" for row in jobs)
    failed_jobs = len(jobs) - completed_jobs
    max_active = max([int(sample.get("active_jobs", 0) or 0) for sample in samples] + [0])
    max_waiting = max([int(sample.get("waiting_jobs", 0) or 0) for sample in samples] + [0])
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scenario": "school-box-shared-queued-load",
        "scenario_description": (
            "Synthetic local contention against the same in-process queue primitive used by uploads, "
            "grounded QA, code tutor, OCR, and embedding/indexing work."
        ),
        "deployment_mode": "school-box-shared",
        "runtime_backend": "local-in-process-queue",
        "model_tier": "not-applicable",
        "retrieval_mode": "not-applicable",
        "device": {
            "label": args.device_label,
            "tier": args.device_tier,
        },
        "max_concurrent_jobs": max(1, int(args.max_concurrent_jobs)),
        "job_seconds": max(0.0, float(args.job_seconds)),
        "submit_spacing_seconds": max(0.0, float(args.submit_spacing_seconds)),
        "metrics": {
            "submitted_jobs": submitted,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
            "completion_rate": round(completed_jobs / submitted, 3) if submitted else 0.0,
            "failure_rate": round(failed_jobs / submitted, 3) if submitted else 0.0,
            "avg_wait_seconds": round(fmean(wait_values), 3) if wait_values else None,
            "median_wait_seconds": round(median(wait_values), 3) if wait_values else None,
            "p95_wait_seconds": _percentile(wait_values, 0.95),
            "max_wait_seconds": round(max(wait_values), 3) if wait_values else None,
            "max_observed_active_jobs": max_active,
            "max_observed_waiting_jobs": max_waiting,
        },
        "operator_visible_queue_behavior": {
            "final_snapshot": final_snapshot,
            "max_sampled_queue_depth": max(
                [int(sample.get("queue_depth", 0) or 0) for sample in samples] + [0]
            ),
            "sample_count": len(samples),
        },
        "jobs": jobs,
        "honest_limits": [
            "synthetic local queue proof",
            "not internet-scale",
            "not a durable distributed queue",
            "avoid large OCR or indexing work during live classroom contention",
        ],
    }

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
