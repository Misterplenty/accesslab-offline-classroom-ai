import json
from pathlib import Path

from scripts.build_benchmark_summary import build_bundle, build_markdown


ROOT = Path(__file__).resolve().parent.parent


def test_benchmark_summary_includes_runtime_profile_and_token_columns():
    markdown = build_markdown(
        [
            {
                "run_id": "run-1",
                "run_label": "hybrid-check",
                "model": "gemma4:e4b",
                "runtime_backend": "ollama",
                "deployment_profile": "strong",
                "deployment_profile_display": "Strong",
                "requested_retrieval_mode": "hybrid",
                "retrieval_mode_display": "Hybrid",
                "semantic_status_label": "Ready",
                "counts": {"pass_rate": 0.9},
                "metrics": {
                    "answer_support_rate": 1.0,
                    "citation_precision": 0.8,
                    "weak_retrieval_abstention_quality": 1.0,
                    "code_pass_rate": 0.75,
                },
                "latency": {
                    "avg_ttft_seconds": 1.2,
                    "avg_total_seconds": 3.4,
                    "avg_prompt_eval_duration_sec": 0.8,
                    "avg_eval_duration_sec": 1.7,
                    "avg_prompt_eval_count": 120.0,
                    "avg_eval_count": 48.0,
                },
                "paths": {"summary": "reports/runs/run-1/summary.json"},
            }
        ],
        [],
    )

    assert "Runtime" in markdown
    assert "Profile" in markdown
    assert "Semantic" in markdown
    assert "Avg Prefill" in markdown
    assert "Avg Decode" in markdown
    assert "Avg Prompt Tokens" in markdown
    assert "Avg Output Tokens" in markdown
    assert "hybrid-check" in markdown
    assert "Strong" in markdown
    assert "Ready" in markdown


def test_benchmark_summary_keeps_a11y_section_scan_friendly():
    markdown = build_markdown(
        [],
        [
            {
                "base_url": "http://127.0.0.1:8000",
                "checks": [
                    {
                        "title": "QA flow and saved-answer focus",
                        "passed": True,
                        "detail": "Grounded QA returns focus to the status region.",
                    }
                ],
                "counts": {"passed": 1, "total": 1},
                "path": "reports/a11y_smoke_latest.json",
            }
        ],
    )

    assert "Accessibility smoke" in markdown
    assert "1/1 checks passed" in markdown
    assert "QA flow and saved-answer focus" in markdown
    assert "reports/a11y_smoke_latest.json" in markdown


def test_benchmark_bundle_keeps_runs_and_accessibility_reports_together():
    bundle = build_bundle(
        [
            {
                "run_id": "run-1",
                "runtime_backend": "ollama",
                "deployment_mode_display": "School AI box",
                "device": {"tier_display": "Shared school-box host"},
            }
        ],
        [{"base_url": "http://127.0.0.1:8000"}],
    )

    assert bundle["run_count"] == 1
    assert bundle["a11y_report_count"] == 1
    assert bundle["runtime_backends"] == ["ollama"]
    assert bundle["deployment_modes"] == ["School AI box"]


def test_inclusive_classroom_benchmark_presets_are_registered():
    payload = json.loads((ROOT / "evals" / "benchmark_presets.json").read_text(encoding="utf-8"))
    presets = {preset["id"]: preset for preset in payload["presets"]}

    assert presets["inclusive-classroom-smoke"]["kind"] == "a11y_smoke"
    assert "visual" in presets["inclusive-classroom-smoke"]["description"]
    assert presets["inclusive-school-box-stress"]["kind"] == "school_box_load"
    assert presets["inclusive-school-box-stress"]["jobs"] == 24
