from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.config import get_settings
from app.services.semantic import DEFAULT_SEMANTIC_EMBEDDING_MODEL


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install and verify the local EmbeddingGemma retrieval model for AccessLab."
    )
    parser.add_argument("--model", default=DEFAULT_SEMANTIC_EMBEDDING_MODEL)
    parser.add_argument("--ollama-url", default=get_settings().accesslab_ollama_url)
    parser.add_argument(
        "--healthz-url",
        default="http://127.0.0.1:8000/healthz",
        help="AccessLab /healthz URL to verify when the app is already running. Use empty string to skip.",
    )
    parser.add_argument("--skip-pull", action="store_true", help="Only verify the active Ollama store and /healthz.")
    parser.add_argument(
        "--output-json",
        default=str(ROOT / "reports" / "embeddinggemma_setup_latest.json"),
    )
    parser.add_argument(
        "--output-markdown",
        default=str(ROOT / "reports" / "embeddinggemma_setup_latest.md"),
    )
    return parser.parse_args()


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _run_command(command: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return {
            "command": command,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "ok": False,
        }
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "ok": completed.returncode == 0,
    }


def _ollama_tags(ollama_url: str) -> tuple[bool, str, dict[str, Any]]:
    try:
        with urlopen(f"{ollama_url.rstrip('/')}/api/tags", timeout=8) as response:
            body = json.loads(response.read().decode("utf-8"))
            return True, "", body
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return False, str(exc), {}


def _healthz(healthz_url: str) -> tuple[bool, str, dict[str, Any]]:
    if not healthz_url.strip():
        return False, "Skipped by operator.", {}
    try:
        with urlopen(healthz_url, timeout=8) as response:
            body = json.loads(response.read().decode("utf-8"))
            return True, "", body
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return False, str(exc), {}


def _installed_model_names(tags: dict[str, Any]) -> set[str]:
    return {str(model.get("name") or model.get("model") or "") for model in tags.get("models", [])}


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    pull_result = None
    if not args.skip_pull:
        pull_result = _run_command(["ollama", "pull", args.model])

    tags_ok, tags_error, tags = _ollama_tags(args.ollama_url)
    installed = _installed_model_names(tags)
    accepted = {args.model}
    if ":" not in args.model:
        accepted.add(f"{args.model}:latest")
    model_present = bool(installed & accepted)

    healthz_ok, healthz_error, health = _healthz(args.healthz_url)
    healthz_semantic_provider_ready = bool(health.get("semantic_provider_ready")) if healthz_ok else False
    healthz_semantic_retrieval_ready = bool(health.get("semantic_retrieval_ready")) if healthz_ok else False
    healthz_status_code = str(health.get("semantic_status_code") or "") if healthz_ok else ""

    if not model_present:
        overall_status = "fail"
    elif healthz_ok and not healthz_semantic_provider_ready:
        overall_status = "fail"
    elif healthz_ok and healthz_semantic_provider_ready:
        overall_status = "pass"
    else:
        overall_status = "attention"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "setup_command": f"ollama pull {args.model}",
        "ollama_url": args.ollama_url,
        "healthz_url": args.healthz_url,
        "pull_attempted": not args.skip_pull,
        "pull_result": pull_result,
        "ollama_tags_ok": tags_ok,
        "ollama_tags_error": tags_error,
        "installed_model_names": sorted(installed),
        "model_present_in_active_store": model_present,
        "healthz_ok": healthz_ok,
        "healthz_error": healthz_error,
        "healthz_semantic_provider_ready": healthz_semantic_provider_ready,
        "healthz_semantic_retrieval_ready": healthz_semantic_retrieval_ready,
        "healthz_semantic_status_code": healthz_status_code,
        "healthz_semantic_summary": str(health.get("semantic_summary") or "") if healthz_ok else "",
        "overall_status": overall_status,
        "remediation": [
            f"Run `ollama pull {args.model}`.",
            "Run `ollama list` from the same account that runs AccessLab.",
            "If the model exists in another store, restart Ollama with the correct OLLAMA_MODELS/HOME.",
            "Restart AccessLab if it was already running.",
            "Open `/healthz` and confirm semantic_provider_ready is true; semantic_retrieval_ready becomes true after materials are indexed.",
        ],
        "honest_limits": [
            "Model installation only proves the provider can be found in the active Ollama store.",
            "Semantic retrieval also requires indexed class materials.",
            "SQLite FTS5 remains the fallback when EmbeddingGemma is unavailable.",
        ],
    }


def build_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# EmbeddingGemma Setup Verification",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Model: `{report['model']}`",
        f"- Setup command: `{report['setup_command']}`",
        f"- Overall status: {report['overall_status']}",
        f"- Present in active Ollama store: {report['model_present_in_active_store']}",
        f"- `/healthz` reachable: {report['healthz_ok']}",
        f"- `/healthz` semantic provider ready: {report['healthz_semantic_provider_ready']}",
        f"- `/healthz` semantic retrieval ready: {report['healthz_semantic_retrieval_ready']}",
        f"- `/healthz` semantic status: {report['healthz_semantic_status_code'] or 'n/a'}",
        "",
        "## Remediation",
        "",
    ]
    lines.extend(f"- {item}" for item in report["remediation"])
    lines.extend(["", "## Honest Limits", ""])
    lines.extend(f"- {item}" for item in report["honest_limits"])
    lines.append("")
    if report.get("healthz_error"):
        lines.extend(["## Healthz Note", "", report["healthz_error"], ""])
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    report = build_report(args)
    json_path = Path(args.output_json)
    markdown_path = Path(args.output_markdown)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown_path.write_text(build_markdown(report), encoding="utf-8")
    print(display_path(json_path))
    print(display_path(markdown_path))
    return 0 if report["overall_status"] in {"pass", "attention"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
