from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from app.services.code_runner import LocalPythonRunner


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reproducible smoke check for AccessLab code-runner hardening.")
    parser.add_argument("--timeout-seconds", type=int, default=2, help="Runner timeout used for the smoke checks.")
    parser.add_argument(
        "--output-json",
        default=str(REPO_ROOT / "reports" / "code_runner_hardening_smoke_latest.json"),
        help="Path for the sanitized JSON proof artifact.",
    )
    parser.add_argument(
        "--output-md",
        default=str(REPO_ROOT / "reports" / "code_runner_hardening_smoke_latest.md"),
        help="Path for the sanitized Markdown proof artifact.",
    )
    return parser.parse_args()


def _write_report(
    *,
    output_json: Path,
    output_md: Path,
    report: dict[str, object],
) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    rows = [
        "# Code Runner Hardening Smoke",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Overall status: `{report['overall_status']}`",
        f"- Sandbox profile: `{report['sandbox_profile']}`",
        f"- Safe beginner code passed: `{report['safe_passed']}`",
        f"- Unsafe network attempt status: `{report['blocked_status']}`",
        f"- Unsafe network attempt denied by policy: `{report['blocked_denied_by_policy']}`",
        "",
        "This smoke checks the constrained local runner used for beginner snippets. It is not a production secure-sandbox certification.",
    ]
    if report.get("failure_reason"):
        rows.extend(["", f"Failure reason: {report['failure_reason']}"])
    output_md.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> int:
    args = _parse_args()
    runner = LocalPythonRunner(timeout_seconds=args.timeout_seconds)

    safe_code = "def add_numbers(a, b):\n    return a + b\n"
    safe_tests = (
        "from submission import add_numbers\n\n"
        "def test_add_numbers():\n"
        "    assert add_numbers(2, 3) == 5\n"
    )
    blocked_code = (
        "import importlib\n\n"
        "def attempt_network():\n"
        "    socket = importlib.import_module('socket')\n"
        "    getattr(socket, 'socket')()\n"
    )
    blocked_tests = (
        "from submission import attempt_network\n\n"
        "def test_attempt_network():\n"
        "    attempt_network()\n"
    )

    safe_result = runner.run(safe_code, safe_tests)
    blocked_result = runner.run(blocked_code, blocked_tests)

    print("Code-runner hardening smoke summary")
    print(f"  sandbox_profile: {safe_result.sandbox_profile}")
    print(f"  sandbox_note: {safe_result.sandbox_note}")
    print(f"  safe_status: {safe_result.status}")
    print(f"  safe_passed: {safe_result.passed}")
    print(f"  blocked_status: {blocked_result.status}")
    print(f"  blocked_denied_by_policy: {blocked_result.denied_by_policy}")

    if safe_result.combined_output:
        first_line = safe_result.combined_output.splitlines()[0]
        print(f"  safe_output_head: {first_line}")
    if blocked_result.combined_output:
        first_line = blocked_result.combined_output.splitlines()[0]
        print(f"  blocked_output_head: {first_line}")

    failure_code = 0
    failure_reason = ""
    if not safe_result.passed:
        failure_code = 1
        failure_reason = "Ordinary beginner code did not pass the runner."
    elif blocked_result.status != "blocked" or not blocked_result.denied_by_policy:
        failure_code = 2
        failure_reason = "Runtime policy denial was not surfaced as a sandbox block."
    elif "Sandbox policy denied network access." not in blocked_result.combined_output:
        failure_code = 3
        failure_reason = "Blocked behavior did not produce a clear sandbox-policy message."

    report = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "overall_status": "passed" if failure_code == 0 else "failed",
        "failure_reason": failure_reason,
        "sandbox_profile": safe_result.sandbox_profile,
        "sandbox_note": safe_result.sandbox_note,
        "safe_status": safe_result.status,
        "safe_passed": bool(safe_result.passed),
        "blocked_status": blocked_result.status,
        "blocked_denied_by_policy": bool(blocked_result.denied_by_policy),
        "blocked_message_present": "Sandbox policy denied network access." in blocked_result.combined_output,
    }
    _write_report(
        output_json=Path(args.output_json),
        output_md=Path(args.output_md),
        report=report,
    )

    if failure_code:
        print(f"Smoke check failed: {failure_reason}", file=sys.stderr)
        return failure_code

    print("Smoke check passed: safe code ran and runtime network access was blocked clearly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
