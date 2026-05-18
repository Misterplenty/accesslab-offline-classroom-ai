from __future__ import annotations

import ast
import logging
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from app.models.schemas import ExecutionResult


logger = logging.getLogger(__name__)

BLOCKED_IMPORTS = {
    "ctypes",
    "os",
    "pathlib",
    "resource",
    "shutil",
    "socket",
    "subprocess",
}

BLOCKED_CALLS = {"__import__", "compile", "eval", "exec", "open"}

SANDBOX_POLICY_PREFIX = "ACCESSLAB_SANDBOX_POLICY: "
SANDBOX_BOOTSTRAP_PREFIX = "ACCESSLAB_SANDBOX_UNAVAILABLE: "
DEFAULT_FILE_SIZE_LIMIT_BYTES = 1_048_576
DEFAULT_OPEN_FILE_LIMIT = 64
DEFAULT_PROCESS_LIMIT = 8
LINUX_MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
BOOTSTRAP_PATH = Path(__file__).with_name("code_runner_bootstrap.py")


class ExecutionBackend(Protocol):
    def run(self, code: str, tests: str | None = None) -> ExecutionResult:
        ...


def _extract_called_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return None


def find_safety_issues(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    issues: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".")[0]
                if top_level in BLOCKED_IMPORTS:
                    issues.append(f"import `{top_level}` is blocked in this local prototype runner")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top_level = node.module.split(".")[0]
                if top_level in BLOCKED_IMPORTS:
                    issues.append(f"import `{top_level}` is blocked in this local prototype runner")
        elif isinstance(node, ast.Call):
            called_name = _extract_called_name(node.func)
            if called_name in BLOCKED_CALLS:
                issues.append(f"call to `{called_name}` is blocked in this local prototype runner")
            if called_name and any(called_name.startswith(f"{name}.") for name in BLOCKED_IMPORTS):
                issues.append(f"call to `{called_name}` is blocked in this local prototype runner")
    return sorted(set(issues))


def generate_minimal_harness(code: str) -> str:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ""

    function_defs = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(function_defs) != 1:
        return ""

    function_name = function_defs[0].name
    arg_count = len(function_defs[0].args.args)
    sample_args = ", ".join("0" for _ in range(arg_count))
    call_expression = f"submission.{function_name}({sample_args})" if sample_args else f"submission.{function_name}()"
    return (
        "import submission\n\n"
        "def test_generated_smoke_check():\n"
        f"    {call_expression}\n"
    )


class LocalPythonRunner:
    def __init__(self, *, timeout_seconds: int = 5) -> None:
        self.timeout_seconds = timeout_seconds
        self.sandbox_profile, self.sandbox_note = describe_sandbox_profile()
        if not BOOTSTRAP_PATH.exists():
            logger.warning("Code runner bootstrap file is missing: %s", BOOTSTRAP_PATH)

    def run(self, code: str, tests: str | None = None) -> ExecutionResult:
        safety_issues = find_safety_issues(code)
        if tests:
            safety_issues.extend(find_safety_issues(tests))
        if safety_issues:
            return ExecutionResult(
                status="blocked",
                return_code=None,
                stdout="",
                stderr="\n".join(sorted(set(safety_issues))),
                timed_out=False,
                command=[],
                mode="blocked",
                effective_test_code=tests,
                used_generated_tests=False,
                sandbox_profile=self.sandbox_profile,
                sandbox_note=self.sandbox_note,
                denied_by_policy=True,
            )

        effective_tests = tests.strip() if tests and tests.strip() else generate_minimal_harness(code)
        used_generated_tests = bool(effective_tests and not tests)
        mode = "tests" if effective_tests else "script"

        with TemporaryDirectory(prefix="accesslab-run-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            submission_path = temp_dir / "submission.py"
            submission_path.write_text(code, encoding="utf-8")

            if effective_tests:
                test_path = temp_dir / "test_submission.py"
                test_path.write_text(effective_tests, encoding="utf-8")
                command = self._build_command(
                    temp_dir=temp_dir,
                    submission_path=submission_path,
                    mode="pytest",
                    test_path=test_path,
                )
            else:
                command = self._build_command(
                    temp_dir=temp_dir,
                    submission_path=submission_path,
                    mode="script",
                )

            env = build_sandbox_environment(temp_dir)

            try:
                completed = subprocess.run(
                    command,
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    timeout=self.timeout_seconds,
                    env=env,
                )
            except subprocess.TimeoutExpired as exc:
                return ExecutionResult(
                    status="timeout",
                    return_code=None,
                    stdout=exc.stdout or "",
                    stderr=(exc.stderr or "").strip() or "Execution timed out.",
                    timed_out=True,
                    command=command,
                    mode=mode,
                    effective_test_code=effective_tests or None,
                    used_generated_tests=used_generated_tests,
                    working_directory=str(temp_dir),
                    sandbox_profile=self.sandbox_profile,
                    sandbox_note=self.sandbox_note,
                )

            policy_message = extract_prefixed_message(completed.stdout, SANDBOX_POLICY_PREFIX) or extract_prefixed_message(
                completed.stderr, SANDBOX_POLICY_PREFIX
            )
            bootstrap_message = extract_prefixed_message(
                completed.stdout, SANDBOX_BOOTSTRAP_PREFIX
            ) or extract_prefixed_message(completed.stderr, SANDBOX_BOOTSTRAP_PREFIX)
            stdout = strip_control_prefixes(completed.stdout)
            stderr = strip_control_prefixes(completed.stderr)

            if policy_message:
                logger.warning("Sandbox policy denied local code execution: %s", policy_message)
                return ExecutionResult(
                    status="blocked",
                    return_code=completed.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    timed_out=False,
                    command=command,
                    mode=mode,
                    effective_test_code=effective_tests or None,
                    used_generated_tests=used_generated_tests,
                    working_directory=str(temp_dir),
                    sandbox_profile=self.sandbox_profile,
                    sandbox_note=self.sandbox_note,
                    denied_by_policy=True,
                )

            if bootstrap_message:
                logger.warning("Sandbox bootstrap blocked execution before running user code: %s", bootstrap_message)
                return ExecutionResult(
                    status="blocked",
                    return_code=completed.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    timed_out=False,
                    command=command,
                    mode=mode,
                    effective_test_code=effective_tests or None,
                    used_generated_tests=used_generated_tests,
                    working_directory=str(temp_dir),
                    sandbox_profile=self.sandbox_profile,
                    sandbox_note=self.sandbox_note,
                    denied_by_policy=False,
                )

            return ExecutionResult(
                status="completed",
                return_code=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                timed_out=False,
                command=command,
                mode=mode,
                effective_test_code=effective_tests or None,
                used_generated_tests=used_generated_tests,
                working_directory=str(temp_dir),
                sandbox_profile=self.sandbox_profile,
                sandbox_note=self.sandbox_note,
            )

    def _build_command(
        self,
        *,
        temp_dir: Path,
        submission_path: Path,
        mode: str,
        test_path: Path | None = None,
    ) -> list[str]:
        command = [
            sys.executable,
            "-I",
            str(BOOTSTRAP_PATH),
            "--mode",
            mode,
            "--cwd",
            str(temp_dir),
            "--submission",
            str(submission_path),
            "--timeout-seconds",
            str(self.timeout_seconds),
            "--policy-prefix",
            SANDBOX_POLICY_PREFIX,
            "--error-prefix",
            SANDBOX_BOOTSTRAP_PREFIX,
            "--file-size-limit-bytes",
            str(DEFAULT_FILE_SIZE_LIMIT_BYTES),
            "--open-file-limit",
            str(DEFAULT_OPEN_FILE_LIMIT),
            "--process-limit",
            str(DEFAULT_PROCESS_LIMIT),
            "--memory-limit-bytes",
            str(LINUX_MEMORY_LIMIT_BYTES if sys.platform.startswith("linux") else 0),
        ]
        if test_path is not None:
            command.extend(["--test-file", str(test_path)])
        return command


def describe_sandbox_profile() -> tuple[str, str]:
    if os.name != "posix":
        return (
            "audit-only",
            "Best-effort local sandbox: temp directory, scrubbed environment, and Python runtime policy checks. "
            "POSIX resource limits are unavailable on this platform.",
        )

    if sys.platform.startswith("linux"):
        return (
            "audit-posix-linux",
            "Best-effort local sandbox: temp directory, scrubbed environment, Python runtime policy checks, POSIX "
            "resource limits, and a Linux-only memory ceiling.",
        )

    return (
        "audit-posix",
        "Best-effort local sandbox: temp directory, scrubbed environment, Python runtime policy checks, and POSIX "
        "resource limits. The Linux-only memory ceiling is unavailable on this platform.",
    )


def build_sandbox_environment(temp_dir: Path) -> dict[str, str]:
    env = {
        "HOME": str(temp_dir),
        "TMPDIR": str(temp_dir),
        "TMP": str(temp_dir),
        "TEMP": str(temp_dir),
        "PATH": "",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    if "SYSTEMROOT" in os.environ:
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return env


def extract_prefixed_message(text: str, prefix: str) -> str:
    messages = [line[len(prefix):].strip() for line in text.splitlines() if line.startswith(prefix)]
    return "\n".join(messages)


def strip_control_prefixes(text: str) -> str:
    cleaned_lines = []
    for line in text.splitlines():
        for prefix in (SANDBOX_POLICY_PREFIX, SANDBOX_BOOTSTRAP_PREFIX):
            if line.startswith(prefix):
                line = line[len(prefix):]
                break
        cleaned_lines.append(line)
    stripped = "\n".join(cleaned_lines).strip()
    return stripped
