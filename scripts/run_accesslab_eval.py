from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, median
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX benchmark hosts
    resource = None

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import (
    DEPLOYMENT_MODE_LABELS,
    KNOWN_DEPLOYMENT_MODES,
    PROFILE_MODELS,
    get_settings,
)
from app.db import init_db
from app.models.schemas import CodeTutorResult, QAResult, ResponseProfile
from app.services.code_runner import LocalPythonRunner
from app.services.code_tutor import DEFAULT_CODE_TUTOR_PROMPT_VARIANT, CodeTutorService
from app.services.document_ingest import DocumentIngestService
from app.services.llm import create_generation_provider
from app.services.ocr import create_ocr_backend
from app.services.qa import (
    DEFAULT_QA_DISCIPLINE_PROFILE,
    DEFAULT_QA_PROMPT_VARIANT,
    KNOWN_QA_DISCIPLINE_PROFILES,
    GroundedQAService,
)
from app.services.retrieval import HybridSQLiteRetrieval, RETRIEVAL_MODE_LABELS
from app.services.semantic import SQLiteSemanticIndex, create_embedding_provider
from app.services.system_status import build_retrieval_diagnostics


DEVICE_TIER_ALIASES = {
    "decent": "standard-laptop",
    "standard-local-laptop": "standard-laptop",
    "weak": "edge-validation-device",
    "proxy": "constrained-proxy",
}
DEVICE_TIER_LABELS = {
    "teacher-laptop": "Teacher laptop / mini-PC",
    "standard-laptop": "Standard laptop",
    "school-box-host": "Shared school-box host",
    "edge-validation-device": "Edge-validation device",
    "constrained-proxy": "Constrained proxy",
    "other": "Other / explicitly unsupported tier",
}
KNOWN_DEVICE_TIERS = frozenset(set(DEVICE_TIER_ALIASES) | set(DEVICE_TIER_LABELS))


def resolve_model_tier(model_name: str) -> str:
    normalized = (model_name or "").strip().lower()
    if normalized.endswith(":e2b"):
        return "E2B"
    if normalized.endswith(":e4b"):
        return "E4B"
    return "Custom"


def resolve_prompt_variants(args: argparse.Namespace) -> tuple[str, str]:
    """Return (qa_variant, code_variant) honoring legacy --prompt-variant.

    Precedence:
      1. --prompt-variant (legacy) overrides both services if set.
      2. --qa-prompt-variant / --code-prompt-variant override per-service.
      3. Otherwise fall back to DEFAULT_QA_PROMPT_VARIANT and
         DEFAULT_CODE_TUTOR_PROMPT_VARIANT.
    """
    if args.prompt_variant is not None:
        return args.prompt_variant, args.prompt_variant
    qa_variant = args.qa_prompt_variant or DEFAULT_QA_PROMPT_VARIANT
    code_variant = args.code_prompt_variant or DEFAULT_CODE_TUTOR_PROMPT_VARIANT
    return qa_variant, code_variant


def resolve_qa_discipline_profile(args: argparse.Namespace) -> str:
    """Return the effective qa_discipline_profile for this run.

    'auto' (the default) maps the active model to a discipline profile via
    the same evidence-based mapping the deployment-profile mechanism uses:
      - gemma4:e2b (weak profile)   -> 'weak'   (apply discipline suffix)
      - any other model             -> 'default' (no suffix)

    Explicit 'default' / 'weak' always wins over 'auto', so an operator can
    A/B the discipline suffix on the same model without changing env vars.
    """
    requested = (args.qa_discipline_profile or "auto").strip().lower()
    if requested in KNOWN_QA_DISCIPLINE_PROFILES:
        return requested
    if requested != "auto":
        return DEFAULT_QA_DISCIPLINE_PROFILE
    weak_model = PROFILE_MODELS.get("weak")
    if weak_model and args.model == weak_model:
        return "weak"
    return DEFAULT_QA_DISCIPLINE_PROFILE


def normalize_device_tier(value: str) -> str:
    normalized = (value or "").strip().lower()
    normalized = DEVICE_TIER_ALIASES.get(normalized, normalized)
    if normalized in DEVICE_TIER_LABELS:
        return normalized
    return "other"


def device_tier_display(value: str) -> str:
    return DEVICE_TIER_LABELS.get(normalize_device_tier(value), "Standard laptop")


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run the AccessLab v0.1 evaluation pack.")
    parser.add_argument("--task-pack", default=str(ROOT / "evals" / "accesslab_eval_v0_1_tasks.json"))
    parser.add_argument("--device-label", required=True)
    parser.add_argument("--device-tier", default="standard-laptop", choices=sorted(KNOWN_DEVICE_TIERS))
    parser.add_argument("--model", default=settings.accesslab_model)
    parser.add_argument("--runtime-backend", default=settings.runtime_backend)
    parser.add_argument(
        "--deployment-mode",
        default=settings.deployment_mode,
        choices=sorted(KNOWN_DEPLOYMENT_MODES),
    )
    parser.add_argument("--ollama-url", default=settings.accesslab_ollama_url)
    parser.add_argument(
        "--retrieval-mode",
        default="hybrid",
        choices=["hybrid", "lexical", "semantic"],
        help="Hybrid keeps SQLite FTS5 plus local semantic retrieval when available. "
             "Lexical disables semantic retrieval for apples-to-apples comparison. "
             "Semantic requests EmbeddingGemma-only retrieval and falls back honestly when unavailable.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=5)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--num-thread", type=int)
    parser.add_argument("--num-gpu", type=int)
    # Benchmark harness controls
    parser.add_argument(
        "--run-label",
        default="",
        help="Short label attached to every row (e.g. 'baseline-v1', 'exp-lighter-tags'). "
             "Used to distinguish runs when CSVs are merged for comparison.",
    )
    parser.add_argument(
        "--cold-warm",
        default="warm",
        choices=["cold", "warm"],
        help="Mark this run as cold (model freshly loaded) or warm (model already resident). "
             "A cold run requires stopping the model before launching: `ollama stop <model>`.",
    )
    parser.add_argument(
        "--prompt-variant",
        default=None,
        choices=["baseline", "experimental", "hybrid"],
        help="Legacy override that sets BOTH the QA and code-tutor variants to the "
             "same value. If omitted, the harness uses the per-service defaults: "
             f"QA={DEFAULT_QA_PROMPT_VARIANT!r}, "
             f"code tutor={DEFAULT_CODE_TUTOR_PROMPT_VARIANT!r}. "
             "Prefer --qa-prompt-variant / --code-prompt-variant for new runs.",
    )
    parser.add_argument(
        "--qa-prompt-variant",
        default=None,
        choices=["baseline", "experimental", "hybrid"],
        help=f"Prompt variant for QA service (default: {DEFAULT_QA_PROMPT_VARIANT!r}). "
             "Overridden by --prompt-variant if that is also set.",
    )
    parser.add_argument(
        "--code-prompt-variant",
        default=None,
        choices=["baseline", "experimental", "hybrid"],
        help=f"Prompt variant for code-tutor service (default: "
             f"{DEFAULT_CODE_TUTOR_PROMPT_VARIANT!r}). "
             "Overridden by --prompt-variant if that is also set.",
    )
    parser.add_argument(
        "--qa-discipline-profile",
        default="auto",
        choices=["auto", *KNOWN_QA_DISCIPLINE_PROFILES],
        help="QA output-discipline profile. 'auto' (default) infers from the "
             "active model: gemma4:e2b -> 'weak' (appends the weak-tier "
             "discipline suffix to the baseline QA prompt); any other model "
             "-> 'default'. Pass 'default' or 'weak' explicitly to A/B the "
             "discipline suffix on the same model. The suffix is only "
             "applied when --qa-prompt-variant is 'baseline'.",
    )
    parser.add_argument(
        "--categories",
        default="",
        help="Comma-separated list of task categories to keep (e.g. "
             "'beginner-python-bug-fix' for code-only runs). Empty means run "
             "every task in the pack. Applied after --limit.",
    )
    # Context limit knob for weak-device testing (passed via Ollama options)
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=None,
        help="Override the model context window size (num_ctx). "
             "Only set this for controlled weak-device comparisons; "
             "lowering it reduces KV-cache memory and may affect answer quality.",
    )
    return parser.parse_args()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def split_paragraphs(*parts: str) -> list[str]:
    paragraphs: list[str] = []
    for part in parts:
        for paragraph in part.splitlines():
            cleaned = paragraph.strip()
            if cleaned:
                paragraphs.append(cleaned)
    return paragraphs


def sentence_count(text: str) -> int:
    return len([item for item in re.split(r"(?<=[.!?])\s+", text.strip()) if item.strip()])


def yes_no_or_na(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return "yes" if value else "no"


def round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 3)


def sysctl_value(key: str) -> str | None:
    try:
        return subprocess.check_output(["sysctl", "-n", key], text=True).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def current_peak_memory_mb() -> float | None:
    if resource is None:
        return None
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (AttributeError, OSError, ValueError):
        return None
    if usage <= 0:
        return None
    if sys.platform == "darwin":
        return round(float(usage) / (1024 * 1024), 1)
    return round(float(usage) / 1024, 1)


def capture_device_info(device_label: str, device_tier: str) -> dict[str, Any]:
    cpu_brand = sysctl_value("machdep.cpu.brand_string") or platform.processor() or "unknown"
    logical_cores = sysctl_value("hw.logicalcpu")
    memory_bytes = sysctl_value("hw.memsize")
    memory_gb = None
    if memory_bytes and memory_bytes.isdigit():
        memory_gb = round(int(memory_bytes) / (1024 ** 3), 1)

    return {
        "label": device_label,
        "tier": normalize_device_tier(device_tier),
        "tier_display": device_tier_display(device_tier),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "cpu_brand": cpu_brand,
        "logical_cores": int(logical_cores) if logical_cores and logical_cores.isdigit() else None,
        "memory_gb": memory_gb,
    }


def matches_expected_keywords(text: str, expected_keywords: list[str]) -> tuple[bool, list[str]]:
    normalized = normalize_text(text)
    hits = [keyword for keyword in expected_keywords if normalize_text(keyword) in normalized]
    return bool(hits), hits


def citations_match_sources(result: QAResult, expected_sources: list[str]) -> bool:
    if not result.citations:
        return False
    expected = set(expected_sources)
    return any(citation.source_file in expected for citation in result.citations)


def profile_dict(profile: ResponseProfile | None) -> dict[str, Any]:
    if profile is None:
        return {}
    return {
        # Wall-clock timings
        "ttft_seconds": round_or_none(profile.ttft_seconds),
        "retrieval_seconds": round_or_none(profile.retrieval_seconds),
        "prompt_build_seconds": round_or_none(profile.prompt_build_seconds),
        "model_inference_seconds": round_or_none(profile.model_inference_seconds),
        "post_processing_seconds": round_or_none(profile.post_processing_seconds),
        "code_execution_seconds": round_or_none(profile.code_execution_seconds),
        "patched_execution_seconds": round_or_none(profile.patched_execution_seconds),
        "total_seconds": round_or_none(profile.total_seconds),
        # Size counters
        "prompt_characters": profile.prompt_characters,
        "context_characters": profile.context_characters,
        "response_characters": profile.response_characters,
        "retrieved_chunks": profile.retrieved_chunks,
        # Ollama-native telemetry (prefill vs decode breakdown)
        "load_duration_sec": round_or_none(profile.load_duration_sec),
        "prompt_eval_duration_sec": round_or_none(profile.prompt_eval_duration_sec),
        "eval_duration_sec": round_or_none(profile.eval_duration_sec),
        "prompt_eval_count": profile.prompt_eval_count,
        "eval_count": profile.eval_count,
        "retrieval_mode": profile.retrieval_mode,
        "retrieval_mode_label": profile.retrieval_mode_label,
        "semantic_status_code": profile.semantic_status_code,
        "semantic_index_status": profile.semantic_index_status,
        "queue_wait_seconds": round_or_none(profile.queue_wait_seconds),
        "peak_memory_mb": round_or_none(profile.peak_memory_mb),
    }


def detect_parse_ok(result: "QAResult | CodeTutorResult") -> bool:
    """Return True if the model produced parseable structured output.

    For QA: at least one of short_answer or more_detail came from a tag match
    (we detect a fallback answer as a failure signal).
    For code: patched_code was extracted from a tag (not a fallback copy of the
    original code, and not the default 'could not parse' diagnosis text).
    """
    from app.models.schemas import CodeTutorResult, QAResult

    if isinstance(result, QAResult):
        fallback = "i could not create a grounded answer"
        return fallback not in (result.short_answer or "").lower()
    if isinstance(result, CodeTutorResult):
        unparsed = "could not parse a structured explanation"
        return unparsed not in (result.diagnosis or "").lower()
    return True


def task_prompt(task: dict[str, Any]) -> str:
    return str(task.get("prompt") or task.get("instruction") or "")


def build_output_markdown(task: dict[str, Any], row: dict[str, Any], result: QAResult | CodeTutorResult) -> str:
    lines = [
        f"# {task['id']}",
        "",
        f"- Category: {task['category']}",
        f"- Task type: {task['task_type']}",
        f"- Prompt: {task_prompt(task)}",
        f"- Task pass: {row['task_pass']}",
        f"- TTFT: {row['ttft_seconds']}",
        f"- Total response time: {row['total_response_time_seconds']}",
        f"- Grounded: {row['grounded']}",
        f"- Citation correct: {row['citation_correct']}",
        f"- Helpful: {row['helpful']}",
        f"- Too verbose: {row['too_verbose']}",
        f"- Passed tests: {row['passed_tests']}",
        f"- Notes: {row['notes']}",
        "",
        "## Profile",
        "",
        "```json",
        json.dumps(row["profile"], indent=2),
        "```",
        "",
    ]

    if isinstance(result, QAResult):
        lines.extend(
            [
                "## Short Answer",
                "",
                result.short_answer or "(empty)",
                "",
                "## More Detail",
                "",
                result.more_detail or "(empty)",
                "",
                "## Sources",
                "",
            ]
        )
        if result.citations:
            for citation in result.citations:
                lines.append(f"- {citation.display}: {citation.snippet}")
        else:
            lines.append("- None")
    else:
        lines.extend(
            [
                "## What Failed",
                "",
                result.diagnosis,
                "",
                "## Evidence",
                "",
                result.evidence,
                "",
                "## Smallest Fix",
                "",
                result.next_fix,
                "",
                "## Why It Works",
                "",
                result.why_it_works,
                "",
                "## Initial Run",
                "",
                result.initial_run.combined_output or "(no output)",
                "",
                "## Patched Code",
                "",
                "```python",
                result.patched_code,
                "```",
                "",
                "## Patched Run",
                "",
                result.patched_run.combined_output or result.patched_run.status,
            ]
        )

    return "\n".join(lines) + "\n"


def evaluate_qa_task(task: dict[str, Any], result: QAResult) -> tuple[dict[str, Any], list[str]]:
    combined_text = "\n".join(part for part in [result.short_answer, result.more_detail] if part)
    keyword_match, hits = matches_expected_keywords(combined_text, task.get("expected_keywords", []))
    expect_unsure = bool(task.get("expect_unsure"))
    citation_required = bool(task.get("citation_required", False))
    citation_correct = citations_match_sources(result, task.get("expected_sources", [])) if citation_required else None

    grounded = result.unsure if expect_unsure else (not result.unsure and bool(result.citations) and keyword_match)
    helpful = result.unsure if expect_unsure else keyword_match

    paragraphs = split_paragraphs(result.short_answer, result.more_detail)
    too_verbose = count_words(combined_text) > int(task.get("max_total_words", 120))
    if task.get("require_short_paragraphs"):
        too_verbose = too_verbose or any(sentence_count(paragraph) > 2 for paragraph in paragraphs)

    notes: list[str] = []
    failure_tags: list[str] = []
    if hits:
        notes.append(f"matched keywords: {', '.join(hits)}")
    if not keyword_match:
        notes.append("expected keywords missing")
        failure_tags.append("missed_expected_content")
    if citation_required and citation_correct is False:
        notes.append("expected citation source missing")
        failure_tags.append("citation_mismatch")
    if result.unsure and not expect_unsure:
        notes.append("model stayed unsure")
        failure_tags.append("retrieval_or_grounding")
    if expect_unsure and not result.unsure:
        notes.append("expected unsure fallback did not trigger")
        failure_tags.append("uncertainty_guardrail_miss")
    if too_verbose:
        notes.append("response exceeded verbosity target")
        failure_tags.append("verbosity")

    task_pass = grounded and helpful and not too_verbose and (citation_correct is not False)
    if task_pass:
        notes.append("pass")

    row = {
        "grounded": yes_no_or_na(grounded),
        "citation_present": yes_no_or_na(bool(result.citations)),
        "citation_correct": yes_no_or_na(citation_correct),
        "helpful": yes_no_or_na(helpful),
        "too_verbose": yes_no_or_na(too_verbose),
        "passed_tests": "",
        "task_pass": yes_no_or_na(task_pass),
        "notes": "; ".join(notes),
        "failure_tags": failure_tags,
    }
    return row, failure_tags


def evaluate_code_task(task: dict[str, Any], result: CodeTutorResult) -> tuple[dict[str, Any], list[str]]:
    combined_text = "\n".join([result.diagnosis, result.evidence, result.next_fix, result.why_it_works])
    lower_text = normalize_text(combined_text)
    evidence_terms = ("test", "assert", "error", "failed", "nameerror", "returned", "expected")
    grounded = any(term in lower_text for term in evidence_terms)
    passed_tests = result.patched_run.passed
    helpful = passed_tests and "could not" not in lower_text and "not ready" not in lower_text
    too_verbose = count_words(combined_text) > int(task.get("max_total_words", 180))

    notes: list[str] = []
    failure_tags: list[str] = []
    if passed_tests:
        notes.append("patched tests passed")
    else:
        notes.append("patched tests failed")
        failure_tags.append("patch_did_not_pass_tests")
    if not grounded:
        notes.append("diagnosis did not clearly reference runtime or test evidence")
        failure_tags.append("weak_evidence_reference")
    if too_verbose:
        notes.append("response exceeded verbosity target")
        failure_tags.append("verbosity")

    task_pass = passed_tests and grounded and helpful and not too_verbose
    if task_pass:
        notes.append("pass")

    row = {
        "grounded": yes_no_or_na(grounded),
        "citation_present": "n/a",
        "citation_correct": "n/a",
        "helpful": yes_no_or_na(helpful),
        "too_verbose": yes_no_or_na(too_verbose),
        "passed_tests": yes_no_or_na(passed_tests),
        "task_pass": yes_no_or_na(task_pass),
        "notes": "; ".join(notes),
        "failure_tags": failure_tags,
    }
    return row, failure_tags


def build_summary_markdown(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    latency = summary["latency"]
    metrics = summary.get("metrics", {})
    lines = [
        f"# {summary['run_id']}",
        "",
        f"- Model: {summary['model']}",
        f"- Model tier: {summary.get('model_tier', 'Custom')}",
        f"- Runtime backend: {summary['runtime_backend']}",
        f"- Deployment profile: {summary.get('deployment_profile_display', summary.get('deployment_profile', 'unknown'))}",
        f"- Deployment mode: {summary.get('deployment_mode_display', summary.get('deployment_mode', 'unknown'))}",
        f"- Requested retrieval mode: {summary.get('requested_retrieval_mode', summary.get('retrieval_mode'))}",
        f"- Effective retrieval mode: {summary.get('retrieval_mode_display', summary.get('retrieval_mode'))}",
        f"- Semantic status: {summary.get('semantic_status_label')} ({summary.get('semantic_status_code')})",
        f"- Semantic index: {summary.get('semantic_index_label')}",
        f"- OCR available: {summary.get('ocr_available')} ({summary.get('ocr_enabled')})",
        f"- Device label: {summary['device']['label']}",
        f"- Device tier: {summary['device'].get('tier_display', summary['device'].get('tier'))}",
        "",
        "## Key metrics",
        "",
        f"- Task pass rate: {counts['passed_tasks']}/{counts['total_tasks']} ({counts['pass_rate']:.1%})",
        f"- Parse OK rate: {counts.get('parse_ok_tasks', 0)}/{counts['total_tasks']} ({counts.get('parse_ok_rate', 0):.1%})",
        f"- Answer support rate: {metrics.get('answer_support_rate')}",
        f"- Citation presence rate: {metrics.get('citation_presence_rate')}",
        f"- Citation precision: {metrics.get('citation_precision')}",
        f"- Weak-retrieval abstention quality: {metrics.get('weak_retrieval_abstention_quality')}",
        f"- Code pass rate: {metrics.get('code_pass_rate')}",
        "",
        "## Latency",
        "",
        f"- Avg TTFT: {latency.get('avg_ttft_seconds')}s",
        f"- Avg total: {latency.get('avg_total_seconds')}s",
        f"- Avg retrieval: {latency.get('avg_retrieval_seconds')}s",
        f"- Avg model inference: {latency.get('avg_model_inference_seconds')}s",
        f"- Avg prefill: {latency.get('avg_prompt_eval_duration_sec')}s",
        f"- Avg decode: {latency.get('avg_eval_duration_sec')}s",
        f"- Avg prompt tokens: {latency.get('avg_prompt_eval_count')}",
        f"- Avg output tokens: {latency.get('avg_eval_count')}",
        f"- Avg queue wait: {latency.get('avg_queue_wait_seconds')}s",
        f"- Peak memory: {latency.get('peak_memory_mb')} MB",
        "",
        "## Semantic retrieval",
        "",
        f"- Semantic summary: {summary.get('semantic_summary')}",
        f"- Semantic detail: {summary.get('semantic_detail')}",
        f"- Documents/chunks/embedded/missing: "
        f"{summary.get('semantic_document_count')}/"
        f"{summary.get('semantic_chunk_count')}/"
        f"{summary.get('semantic_embedded_chunk_count')}/"
        f"{summary.get('semantic_missing_chunk_count')}",
        "",
        "## Paths",
        "",
        f"- Summary JSON: `{summary['paths']['summary']}`",
        f"- Results CSV: `{summary['paths']['csv']}`",
        f"- Concise summary: `{summary['paths']['summary_brief']}`",
    ]
    return "\n".join(lines) + "\n"


def build_summary_highlights(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    latency = summary["latency"]
    metrics = summary["metrics"]
    return "\n".join(
        [
            f"- {summary.get('run_label') or summary['run_id']}: {summary['model']} on "
            f"{summary['device'].get('tier_display', summary['device'].get('tier', 'device'))}",
            f"- Model tier: {summary.get('model_tier', 'Custom')}",
            f"- Deployment: {summary.get('deployment_mode_display')} via {summary.get('runtime_backend')}",
            f"- Retrieval: {summary.get('retrieval_mode_display')} (requested {summary.get('requested_retrieval_mode')})",
            f"- Pass rate: {counts['pass_rate']:.1%}; support rate: {metrics.get('answer_support_rate')}; "
            f"code pass: {metrics.get('code_pass_rate')}",
            f"- Avg TTFT: {latency.get('avg_ttft_seconds')}s; avg total: {latency.get('avg_total_seconds')}s; "
            f"peak memory: {latency.get('peak_memory_mb')} MB",
            "",
        ]
    )


def run_eval(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    settings = get_settings()
    task_pack_path = Path(args.task_pack)
    task_pack = read_json(task_pack_path)
    tasks = task_pack["tasks"][: args.limit] if args.limit else task_pack["tasks"]

    category_filter = {c.strip() for c in args.categories.split(",") if c.strip()}
    if category_filter:
        tasks = [task for task in tasks if task.get("category") in category_filter]
        if not tasks:
            raise RuntimeError(
                f"No tasks matched --categories {sorted(category_filter)}. "
                f"Available: {sorted({t['category'] for t in task_pack['tasks']})}"
            )

    category_tag = f"-{slugify('_'.join(sorted(category_filter)))}" if category_filter else ""
    label_tag = f"-{slugify(args.run_label)}" if args.run_label else ""
    run_id = (
        f"{utc_timestamp()}-{slugify(args.device_label)}"
        f"{category_tag}-{slugify(args.model)}{label_tag}"
    )
    run_dir = ROOT / "reports" / "runs" / run_id
    outputs_dir = run_dir / "task_outputs"
    data_dir = run_dir / "data"
    uploads_dir = data_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    db_path = data_dir / "accesslab.db"
    init_db(db_path)

    semantic_index = SQLiteSemanticIndex(
        db_path=db_path,
        embedding_provider=create_embedding_provider(
            enabled="off" if args.retrieval_mode == "lexical" else settings.semantic_enabled,
            base_url=args.ollama_url,
            model_name=settings.semantic_embedding_model,
        ),
    )
    ingest_service = DocumentIngestService(
        uploads_dir=uploads_dir,
        db_path=db_path,
        semantic_index=semantic_index if args.retrieval_mode != "lexical" else None,
    )
    retrieval_backend = HybridSQLiteRetrieval(
        db_path,
        semantic_index=semantic_index if args.retrieval_mode != "lexical" else None,
        retrieval_mode=args.retrieval_mode,
    )
    llm_provider = create_generation_provider(
        runtime_backend=args.runtime_backend,
        base_url=args.ollama_url,
        model_name=args.model,
    )
    ocr_backend = create_ocr_backend(enabled=settings.ocr_enabled, dpi=settings.ocr_dpi)
    ocr_available = bool(ocr_backend.is_available())
    llm_settings: dict[str, Any] = {
        "temperature": args.temperature,
        "seed": args.seed,
    }
    if args.num_thread is not None:
        llm_settings["num_thread"] = args.num_thread
    if args.num_gpu is not None:
        llm_settings["num_gpu"] = args.num_gpu
    if args.num_ctx is not None:
        llm_settings["num_ctx"] = args.num_ctx

    qa_variant, code_variant = resolve_prompt_variants(args)
    qa_discipline_profile = resolve_qa_discipline_profile(args)
    resolved_device_tier = normalize_device_tier(args.device_tier)
    deployment_profile = next(
        (profile for profile, model in PROFILE_MODELS.items() if model == args.model),
        settings.deployment_profile,
    )
    deployment_profile_display = "Constrained" if deployment_profile == "weak" else "Strong"
    deployment_mode_display = DEPLOYMENT_MODE_LABELS.get(
        args.deployment_mode,
        args.deployment_mode.replace("-", " ").title(),
    )
    model_tier = resolve_model_tier(args.model)

    code_runner = LocalPythonRunner(timeout_seconds=args.timeout_seconds)
    qa_service = GroundedQAService(
        db_path=db_path,
        retrieval_backend=retrieval_backend,
        llm_provider=llm_provider,
        llm_settings=llm_settings,
        prompt_variant=qa_variant,
        qa_discipline_profile=qa_discipline_profile,
    )
    code_tutor_service = CodeTutorService(
        db_path=db_path,
        llm_provider=llm_provider,
        execution_backend=code_runner,
        llm_settings=llm_settings,
        prompt_variant=code_variant,
    )

    health_ok, health_message = llm_provider.health_check()
    if not health_ok:
        raise RuntimeError(health_message)

    ingest_rows: list[dict[str, Any]] = []
    for relative_path in task_pack.get("documents", []):
        source_path = ROOT / relative_path
        ingest_result = ingest_service.ingest_upload(
            file_name=source_path.name,
            content=source_path.read_bytes(),
        )
        ingest_rows.append(
            {
                "file_name": ingest_result.file_name,
                "file_type": ingest_result.file_type,
                "chunks_created": ingest_result.chunks_created,
            }
        )

    eval_settings = type("EvalSettings", (), {})()
    eval_settings.db_path = db_path
    eval_settings.retrieval_mode = args.retrieval_mode
    eval_settings.retrieval_mode_display = RETRIEVAL_MODE_LABELS.get(
        args.retrieval_mode,
        args.retrieval_mode.title(),
    )
    eval_settings.semantic_embedding_model = settings.semantic_embedding_model
    eval_settings.semantic_model_family = settings.semantic_model_family
    eval_settings.semantic_enabled = "off" if args.retrieval_mode == "lexical" else settings.semantic_enabled
    retrieval_diagnostics = build_retrieval_diagnostics(eval_settings, semantic_index)

    run_label = args.run_label or slugify(args.device_label)
    cold_warm = args.cold_warm

    result_rows: list[dict[str, Any]] = []
    failure_counter: Counter[str] = Counter()

    for task in tasks:
        # Per-task prompt_variant in the CSV reports the *effective* variant for
        # that task type (QA tasks see qa_variant, code tasks see code_variant).
        per_task_variant = code_variant if task["task_type"] == "code" else qa_variant
        # qa_discipline only applies to QA tasks; report 'n/a' on code rows so
        # CSV consumers do not misread the column as code-tutor state.
        per_task_discipline = qa_discipline_profile if task["task_type"] == "qa" else "n/a"
        base_row = {
            "timestamp": utc_timestamp(),
            "run_label": run_label,
            "cold_or_warm": cold_warm,
            "prompt_variant": per_task_variant,
            "qa_discipline_profile": per_task_discipline,
            "task_id": task["id"],
            "category": task["category"],
            "task_type": task["task_type"],
            "prompt_or_instruction": task_prompt(task),
            "model": args.model,
            "model_tier": model_tier,
            "runtime_backend": args.runtime_backend,
            "deployment_profile": deployment_profile,
            "deployment_profile_display": deployment_profile_display,
            "deployment_mode": args.deployment_mode,
            "deployment_mode_display": deployment_mode_display,
            "requested_retrieval_mode": args.retrieval_mode,
            "semantic_status_code": retrieval_diagnostics.semantic.code,
            "semantic_index_status": retrieval_diagnostics.index_status.status,
            "semantic_available": retrieval_diagnostics.semantic.retrieval_ready,
            "ocr_enabled": settings.ocr_enabled,
            "ocr_available": ocr_available,
            "ocr_backend": ocr_backend.describe(),
            "device_label": args.device_label,
            "device_tier": resolved_device_tier,
            "device_tier_display": device_tier_display(resolved_device_tier),
            "expect_unsure": bool(task.get("expect_unsure", False)),
            "citation_required": bool(task.get("citation_required", False)),
        }

        try:
            if task["task_type"] == "qa":
                result = qa_service.answer(task["prompt"])
                eval_row, failure_tags = evaluate_qa_task(task, result)
            else:
                code = read_text(ROOT / task["code_path"])
                tests = read_text(ROOT / task["test_path"])
                result = code_tutor_service.tutor(code, tests, task.get("instruction"))
                eval_row, failure_tags = evaluate_code_task(task, result)

            profile = result.profile or ResponseProfile()
            profile.peak_memory_mb = current_peak_memory_mb()
            p = profile_dict(profile)
            row = {
                **base_row,
                "ttft_seconds": round_or_none(profile.ttft_seconds),
                "total_response_time_seconds": round_or_none(profile.total_seconds),
                "effective_retrieval_mode": profile.retrieval_mode or args.retrieval_mode,
                "effective_retrieval_mode_label": profile.retrieval_mode_label or args.retrieval_mode,
                "load_duration_sec": p.get("load_duration_sec"),
                "prompt_eval_duration_sec": p.get("prompt_eval_duration_sec"),
                "eval_duration_sec": p.get("eval_duration_sec"),
                "prompt_eval_count": p.get("prompt_eval_count"),
                "eval_count": p.get("eval_count"),
                "prompt_tokens": p.get("prompt_eval_count"),
                "output_tokens": p.get("eval_count"),
                "queue_wait_seconds": p.get("queue_wait_seconds"),
                "peak_memory_mb": p.get("peak_memory_mb"),
                "parse_ok": "yes" if detect_parse_ok(result) else "no",
                "profile": p,
                **eval_row,
            }
            failure_counter.update(failure_tags)

            output_path = outputs_dir / f"{task['id']}.md"
            output_path.write_text(build_output_markdown(task, row, result), encoding="utf-8")
            row["output_file"] = str(output_path.relative_to(ROOT))
        except Exception as exc:
            row = {
                **base_row,
                "ttft_seconds": None,
                "total_response_time_seconds": None,
                "effective_retrieval_mode": args.retrieval_mode,
                "effective_retrieval_mode_label": args.retrieval_mode,
                "load_duration_sec": None,
                "prompt_eval_duration_sec": None,
                "eval_duration_sec": None,
                "prompt_eval_count": None,
                "eval_count": None,
                "prompt_tokens": None,
                "output_tokens": None,
                "queue_wait_seconds": None,
                "peak_memory_mb": current_peak_memory_mb(),
                "parse_ok": "no",
                "grounded": "no",
                "citation_present": "no" if task["task_type"] == "qa" else "n/a",
                "citation_correct": "no" if task["task_type"] == "qa" else "n/a",
                "helpful": "no",
                "too_verbose": "n/a",
                "passed_tests": "no" if task["task_type"] == "code" else "",
                "task_pass": "no",
                "notes": f"runner error: {exc}",
                "failure_tags": ["runner_error"],
                "profile": {},
                "output_file": "",
            }
            failure_counter.update(["runner_error"])

        result_rows.append(row)

    csv_path = run_dir / "results.csv"
    summary_path = run_dir / "summary.json"
    summary_markdown_path = run_dir / "summary.md"
    summary_brief_path = run_dir / "summary_brief.md"

    csv_columns = [
        "timestamp",
        "run_label",
        "model",
        "model_tier",
        "task_id",
        "category",
        "task_type",
        "cold_or_warm",
        "prompt_variant",
        "qa_discipline_profile",
        "runtime_backend",
        "deployment_profile",
        "deployment_profile_display",
        "deployment_mode",
        "deployment_mode_display",
        "requested_retrieval_mode",
        "effective_retrieval_mode_label",
        "effective_retrieval_mode",
        "semantic_status_code",
        "semantic_index_status",
        "semantic_available",
        "ocr_enabled",
        "ocr_available",
        "ocr_backend",
        "ttft_seconds",
        "total_response_time_seconds",
        "load_duration_sec",
        "prompt_eval_duration_sec",
        "eval_duration_sec",
        "prompt_eval_count",
        "eval_count",
        "prompt_tokens",
        "output_tokens",
        "queue_wait_seconds",
        "peak_memory_mb",
        "parse_ok",
        "task_pass",
        "grounded",
        "citation_present",
        "citation_correct",
        "helpful",
        "too_verbose",
        "passed_tests",
        "notes",
        "device_label",
        "device_tier",
        "device_tier_display",
        "expect_unsure",
        "citation_required",
        "prompt_or_instruction",
        "output_file",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_columns)
        writer.writeheader()
        for row in result_rows:
            writer.writerow({key: row.get(key, "") for key in csv_columns})

    passed_count = sum(row["task_pass"] == "yes" for row in result_rows)
    parse_ok_count = sum(row.get("parse_ok") == "yes" for row in result_rows)
    qa_rows = [row for row in result_rows if row["task_type"] == "qa"]
    qa_answer_rows = [row for row in qa_rows if not row.get("expect_unsure")]
    qa_citation_rows = [row for row in qa_rows if row.get("citation_required")]
    qa_abstention_rows = [row for row in qa_rows if row.get("expect_unsure")]
    code_rows = [row for row in result_rows if row["task_type"] == "code"]

    def _rate(rows: list[dict[str, Any]], *, key: str, success_value: str = "yes") -> float | None:
        if not rows:
            return None
        successes = sum(row.get(key) == success_value for row in rows)
        return round(successes / len(rows), 3)

    def _floats(key: str, source: str = "row") -> list[float]:
        if source == "row":
            return [row[key] for row in result_rows if isinstance(row.get(key), float)]
        return [
            row["profile"][key]
            for row in result_rows
            if isinstance(row["profile"].get(key), float)
        ]

    ttft_values = _floats("ttft_seconds")
    total_values = _floats("total_response_time_seconds")
    retrieval_values = _floats("retrieval_seconds", "profile")
    prompt_values = _floats("prompt_build_seconds", "profile")
    inference_values = _floats("model_inference_seconds", "profile")
    post_values = _floats("post_processing_seconds", "profile")
    code_values = _floats("code_execution_seconds", "profile")
    patched_code_values = _floats("patched_execution_seconds", "profile")
    load_values = _floats("load_duration_sec", "profile")
    prefill_values = _floats("prompt_eval_duration_sec", "profile")
    decode_values = _floats("eval_duration_sec", "profile")
    queue_wait_values = _floats("queue_wait_seconds", "profile")
    peak_memory_values = _floats("peak_memory_mb", "profile")

    def _ints(key: str) -> list[int]:
        return [
            row["profile"][key]
            for row in result_rows
            if isinstance(row["profile"].get(key), int)
        ]

    prompt_token_values = _ints("prompt_eval_count")
    eval_token_values = _ints("eval_count")

    summary = {
        "version": task_pack["version"],
        "run_id": run_id,
        "run_label": run_label,
        "cold_or_warm": cold_warm,
        # Backwards compat: prompt_variant retains the legacy single value when
        # both services use the same variant; otherwise we mark it as "mixed"
        # so downstream tools fail loudly instead of silently mis-attributing.
        "prompt_variant": qa_variant if qa_variant == code_variant else "mixed",
        "qa_prompt_variant": qa_variant,
        "code_prompt_variant": code_variant,
        "qa_discipline_profile": qa_discipline_profile,
        "qa_discipline_profile_arg": args.qa_discipline_profile,
        "categories": sorted(category_filter) if category_filter else [],
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "device": capture_device_info(args.device_label, args.device_tier),
        "model": args.model,
        "model_tier": model_tier,
        "runtime_backend": args.runtime_backend,
        "deployment_profile": deployment_profile,
        "deployment_profile_display": deployment_profile_display,
        "deployment_mode": args.deployment_mode,
        "deployment_mode_display": deployment_mode_display,
        "ollama_url": args.ollama_url,
        "requested_retrieval_mode": args.retrieval_mode,
        "retrieval_mode": retrieval_diagnostics.actual_mode,
        "retrieval_mode_display": retrieval_diagnostics.actual_mode_label,
        "semantic_model": settings.semantic_embedding_model,
        "semantic_backend": retrieval_diagnostics.semantic.backend,
        "semantic_available": bool(retrieval_diagnostics.semantic.retrieval_ready),
        "semantic_provider_ready": bool(retrieval_diagnostics.semantic.provider_ready),
        "semantic_status_code": retrieval_diagnostics.semantic.code,
        "semantic_status_label": retrieval_diagnostics.semantic.label,
        "semantic_summary": retrieval_diagnostics.semantic.summary,
        "semantic_detail": retrieval_diagnostics.semantic.detail,
        "semantic_index_status": retrieval_diagnostics.index_status.status,
        "semantic_index_label": retrieval_diagnostics.index_status.label,
        "semantic_document_count": retrieval_diagnostics.index_status.document_count,
        "semantic_chunk_count": retrieval_diagnostics.index_status.chunk_count,
        "semantic_embedded_chunk_count": retrieval_diagnostics.index_status.embedded_chunk_count,
        "semantic_missing_chunk_count": retrieval_diagnostics.index_status.missing_chunk_count,
        "semantic_last_error_code": retrieval_diagnostics.index_status.last_error_code,
        "semantic_last_error_message": retrieval_diagnostics.index_status.last_error_message,
        "ocr_enabled": settings.ocr_enabled,
        "ocr_available": ocr_available,
        "ocr_backend": ocr_backend.describe(),
        "lexical_backend": "sqlite-fts5",
        "llm_settings": llm_settings,
        "health_message": health_message,
        "documents_ingested": ingest_rows,
        "paths": {
            "run_dir": str(run_dir.relative_to(ROOT)),
            "csv": str(csv_path.relative_to(ROOT)),
            "summary": str(summary_path.relative_to(ROOT)),
            "summary_markdown": str(summary_markdown_path.relative_to(ROOT)),
            "summary_brief": str(summary_brief_path.relative_to(ROOT)),
        },
        "counts": {
            "total_tasks": len(result_rows),
            "passed_tasks": passed_count,
            "failed_tasks": len(result_rows) - passed_count,
            "pass_rate": round(passed_count / len(result_rows), 3) if result_rows else 0.0,
            "parse_ok_tasks": parse_ok_count,
            "parse_ok_rate": round(parse_ok_count / len(result_rows), 3) if result_rows else 0.0,
        },
        "latency": {
            # Wall-clock
            "avg_ttft_seconds": round(fmean(ttft_values), 3) if ttft_values else None,
            "median_ttft_seconds": round(median(ttft_values), 3) if ttft_values else None,
            "avg_total_seconds": round(fmean(total_values), 3) if total_values else None,
            "median_total_seconds": round(median(total_values), 3) if total_values else None,
            "avg_retrieval_seconds": round(fmean(retrieval_values), 3) if retrieval_values else None,
            "avg_prompt_build_seconds": round(fmean(prompt_values), 3) if prompt_values else None,
            "avg_model_inference_seconds": round(fmean(inference_values), 3) if inference_values else None,
            "avg_post_processing_seconds": round(fmean(post_values), 3) if post_values else None,
            "avg_code_execution_seconds": round(fmean(code_values), 3) if code_values else None,
            "avg_patched_execution_seconds": round(fmean(patched_code_values), 3) if patched_code_values else None,
            # Ollama-native prefill / decode breakdown
            "avg_load_duration_sec": round(fmean(load_values), 3) if load_values else None,
            "avg_prompt_eval_duration_sec": round(fmean(prefill_values), 3) if prefill_values else None,
            "median_prompt_eval_duration_sec": round(median(prefill_values), 3) if prefill_values else None,
            "avg_eval_duration_sec": round(fmean(decode_values), 3) if decode_values else None,
            "median_eval_duration_sec": round(median(decode_values), 3) if decode_values else None,
            # Token counts
            "avg_prompt_eval_count": round(fmean(prompt_token_values), 1) if prompt_token_values else None,
            "avg_eval_count": round(fmean(eval_token_values), 1) if eval_token_values else None,
            "avg_prompt_tokens": round(fmean(prompt_token_values), 1) if prompt_token_values else None,
            "avg_output_tokens": round(fmean(eval_token_values), 1) if eval_token_values else None,
            "avg_queue_wait_seconds": round(fmean(queue_wait_values), 3) if queue_wait_values else None,
            "peak_memory_mb": round(max(peak_memory_values), 1) if peak_memory_values else None,
        },
        "top_failure_modes": [
            {"tag": tag, "count": count}
            for tag, count in failure_counter.most_common(5)
        ],
        "metrics": {
            "answer_support_rate": _rate(qa_answer_rows, key="grounded"),
            "citation_presence_rate": _rate(qa_rows, key="citation_present"),
            "citation_precision": _rate(qa_citation_rows, key="citation_correct"),
            "weak_retrieval_abstention_quality": _rate(qa_abstention_rows, key="task_pass"),
            "qa_pass_rate": _rate(qa_rows, key="task_pass"),
            "code_pass_rate": _rate(code_rows, key="task_pass"),
        },
        "rows": result_rows,
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary_markdown_path.write_text(build_summary_markdown(summary), encoding="utf-8")
    summary_brief_path.write_text(build_summary_highlights(summary), encoding="utf-8")
    return summary, result_rows


def print_summary(summary: dict[str, Any]) -> None:
    counts = summary["counts"]
    latency = summary["latency"]
    sep = "-" * 60
    print(sep)
    print(f"Run:             {summary['run_id']}")
    print(f"Label:           {summary.get('run_label', '')}")
    print(f"Cold/warm:       {summary.get('cold_or_warm', 'warm')}")
    qa_v = summary.get("qa_prompt_variant", summary.get("prompt_variant", "baseline"))
    code_v = summary.get("code_prompt_variant", summary.get("prompt_variant", "baseline"))
    if qa_v == code_v:
        print(f"Prompt variant:  {qa_v} (qa+code)")
    else:
        print(f"Prompt variant:  qa={qa_v}, code={code_v}")
    qa_disc = summary.get("qa_discipline_profile", "default")
    qa_disc_arg = summary.get("qa_discipline_profile_arg", qa_disc)
    if qa_disc_arg == qa_disc or qa_disc_arg == "auto":
        print(f"QA discipline:   {qa_disc} (resolved from {qa_disc_arg!r})")
    else:
        print(f"QA discipline:   {qa_disc}")
    categories = summary.get("categories") or []
    print(f"Categories:      {', '.join(categories) if categories else 'all'}")
    print(f"Model:           {summary['model']}")
    print(f"Model tier:      {summary.get('model_tier', 'Custom')}")
    print(f"Runtime:         {summary.get('runtime_backend', 'ollama')}")
    print(
        f"Profile:         {summary.get('deployment_profile_display', summary.get('deployment_profile', 'Strong'))}"
    )
    print(
        f"Mode:            {summary.get('deployment_mode_display', summary.get('deployment_mode', 'single-user-local'))}"
    )
    print(
        f"Device tier:     {summary['device'].get('tier_display', summary['device'].get('tier', 'standard-laptop'))}"
    )
    print(
        f"Retrieval:       {summary.get('retrieval_mode_display', summary.get('retrieval_mode', 'hybrid'))} "
        f"(requested: {summary.get('requested_retrieval_mode', summary.get('retrieval_mode', 'hybrid'))})"
    )
    print(
        f"Semantic model:  {summary.get('semantic_model')} "
        f"(available: {summary.get('semantic_available')}, status: {summary.get('semantic_status_code')})"
    )
    print(f"OCR available:   {summary.get('ocr_available')} ({summary.get('ocr_enabled')})")
    print(sep)
    print(f"Tasks passed:    {counts['passed_tasks']}/{counts['total_tasks']} ({counts['pass_rate']:.1%})")
    print(f"Parse OK:        {counts.get('parse_ok_tasks', 'n/a')}/{counts['total_tasks']} ({counts.get('parse_ok_rate', 0):.1%})")
    print(sep)
    print("Latency (wall-clock):")
    print(f"  avg TTFT:           {latency['avg_ttft_seconds']}s")
    print(f"  median TTFT:        {latency['median_ttft_seconds']}s")
    print(f"  avg total:          {latency['avg_total_seconds']}s")
    print(f"  median total:       {latency['median_total_seconds']}s")
    print("Ollama-native breakdown (prefill / decode):")
    print(f"  avg load_duration:         {latency.get('avg_load_duration_sec')}s")
    print(f"  avg prompt_eval (prefill): {latency.get('avg_prompt_eval_duration_sec')}s  (median: {latency.get('median_prompt_eval_duration_sec')}s)")
    print(f"  avg eval_duration (decode):{latency.get('avg_eval_duration_sec')}s  (median: {latency.get('median_eval_duration_sec')}s)")
    print(f"  avg prompt tokens:  {latency.get('avg_prompt_eval_count')}")
    print(f"  avg output tokens:  {latency.get('avg_eval_count')}")
    print(f"  avg queue wait:     {latency.get('avg_queue_wait_seconds')}s")
    print(f"  peak memory:        {latency.get('peak_memory_mb')} MB")
    print(sep)
    print(f"Summary JSON: {summary['paths']['summary']}")
    print(f"Summary MD:   {summary['paths']['summary_markdown']}")
    print(f"Brief MD:     {summary['paths']['summary_brief']}")
    print(f"Results CSV:  {summary['paths']['csv']}")
    print(sep)


def main() -> None:
    args = parse_args()
    summary, _ = run_eval(args)
    print_summary(summary)


if __name__ == "__main__":
    main()
