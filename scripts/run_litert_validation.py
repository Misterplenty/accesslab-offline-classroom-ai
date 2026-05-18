from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.config import get_settings
from app.services.llm import (
    LITERT_LM_COMMAND_ENV,
    LITERT_LM_VALIDATION_BACKEND,
    LiteRTLMValidationProvider,
)


DEFAULT_PROMPT = (
    "Return a concise grounded answer using [S1]. If the context is insufficient, say you are unsure."
)
DEFAULT_CONTEXT = "[S1] AccessLab answers only from local classroom materials and cites uploaded sources."


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Run the experimental LiteRT-LM validation contract without changing the default runtime."
    )
    parser.add_argument("--model", default=settings.accesslab_model)
    parser.add_argument("--profile", default="grounded-qa-smoke")
    parser.add_argument("--command", default="", help=f"Overrides {LITERT_LM_COMMAND_ENV} for this run.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--context", default=DEFAULT_CONTEXT)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument(
        "--output-json",
        default=str(ROOT / "reports" / "litert_validation_latest.json"),
    )
    parser.add_argument(
        "--output-markdown",
        default=str(ROOT / "reports" / "litert_validation_latest.md"),
    )
    return parser.parse_args()


def build_markdown(report: dict[str, Any]) -> str:
    capabilities = report["capabilities"]
    lines = [
        "# AccessLab LiteRT-LM Validation",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Backend: {report['backend']}",
        f"- Model target: {report['model']}",
        f"- Profile: {report['profile']}",
        f"- Validation-only: {capabilities['validation_only']}",
        f"- Health: {'pass' if report['health_ok'] else 'fail'} - {report['health_message']}",
        f"- Command configured: {report['command_configured']}",
        f"- Generation exercised: {'yes' if report['generation_exercised'] else 'no'}",
        f"- Total seconds: {report['total_seconds']}",
        "",
        "## What This Proves",
        "",
        "- The AccessLab runtime boundary can select a non-default LiteRT-LM validation backend.",
        "- A local executable command can be probed through the provider contract when configured.",
        "- Capability reporting stays explicit about generation, streaming, timing, and validation-only limits.",
        "",
        "## What This Does Not Prove",
        "",
        "- It does not replace Ollama as the default working runtime.",
        "- It does not validate every AccessLab product flow.",
        "- It does not prove support for unsupported phones or low-memory devices.",
        "- It does not move EmbeddingGemma semantic retrieval to an edge embedding runtime.",
        "",
        "## Expected Command Contract",
        "",
        f"- Environment variable: `{report['configuration_env']}`",
        "- The command receives JSON on stdin with model, profile, prompt, context, and settings.",
        "- The command returns plain text or JSON containing `response`, `text`, or `answer`.",
        "- Non-zero exit, empty output, or missing response field is treated as validation failure.",
        "",
        "## Future Validation Will Prove",
        "",
    ]
    lines.extend(f"- {item}" for item in report["future_validation_will_prove"])
    lines.extend(
        [
            "",
            "## Response",
            "",
            report.get("response") or "(no response generated)",
            "",
        ]
    )
    if report.get("error"):
        lines.extend(["## Error", "", report["error"], ""])
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    command = args.command.strip() or None
    provider = LiteRTLMValidationProvider(
        model_name=args.model,
        command=command,
        profile=args.profile,
        timeout_seconds=args.timeout_seconds,
    )
    capabilities = provider.capabilities()
    health_ok, health_message = provider.health_check()
    response = ""
    error = ""
    generation_exercised = False
    total_seconds: float | None = None

    if health_ok and capabilities.supports_generation:
        start = perf_counter()
        try:
            response = provider.generate_answer(
                args.prompt,
                args.context,
                settings={"temperature": 0.0},
            )
            generation_exercised = True
        except Exception as exc:  # pragma: no cover - surfaced in report
            error = str(exc)
        total_seconds = perf_counter() - start

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backend": LITERT_LM_VALIDATION_BACKEND,
        "model": args.model,
        "profile": args.profile,
        "command_configured": bool(provider.command),
        "health_ok": health_ok,
        "health_message": health_message,
        "capabilities": asdict(capabilities),
        "generation_exercised": generation_exercised,
        "total_seconds": round(total_seconds, 3) if total_seconds is not None else None,
        "configuration_env": LITERT_LM_COMMAND_ENV,
        "missing_configuration": LITERT_LM_COMMAND_ENV if not provider.command else "",
        "expected_command_contract": {
            "stdin_json_fields": ["model", "profile", "prompt", "context", "settings"],
            "accepted_stdout_shapes": ["plain text", "JSON response", "JSON text", "JSON answer"],
            "fail_closed_on": ["missing command", "missing executable", "non-zero exit", "empty output", "missing response text"],
        },
        "future_validation_will_prove": [
            "The target device can execute a local LiteRT-LM generation command for the narrow AccessLab prompt contract.",
            "The validation backend can return a grounded answer without cloud fallback.",
            "The measured target can be compared against the Ollama baseline for the same prompt and context.",
            "The result remains validation-only until broader product flows are run.",
        ],
        "prompt": args.prompt,
        "context": args.context,
        "response": response,
        "error": error,
        "intended_device_class": "edge-validation-device or constrained local validation host",
        "honest_limits": [
            "validation-only",
            "non-default",
            "generation-only command contract",
            "no cloud fallback",
            "no unsupported-device support claim",
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
