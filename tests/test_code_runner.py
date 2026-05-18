from __future__ import annotations

import sys
from pathlib import Path

from app.services.code_runner import LocalPythonRunner


def test_code_runner_reports_success():
    runner = LocalPythonRunner(timeout_seconds=2)
    code = "def add_numbers(a, b):\n    return a + b\n"
    tests = (
        "from submission import add_numbers\n\n"
        "def test_add_numbers():\n"
        "    assert add_numbers(2, 3) == 5\n"
    )

    result = runner.run(code, tests)

    assert result.passed
    assert "1 passed" in result.combined_output
    assert result.sandbox_profile.startswith("audit")


def test_code_runner_times_out():
    runner = LocalPythonRunner(timeout_seconds=1)
    code = "while True:\n    pass\n"

    result = runner.run(code)

    assert result.timed_out
    assert result.status == "timeout"


def test_code_runner_uses_temporary_execution_directory():
    runner = LocalPythonRunner(timeout_seconds=2)

    result = runner.run("def give_answer():\n    return 42\n")

    assert result.working_directory is not None
    working_directory = Path(result.working_directory)
    assert working_directory.name.startswith("accesslab-run-")
    assert not working_directory.exists()


def test_code_runner_scrubs_inherited_environment(monkeypatch):
    monkeypatch.setenv("ACCESSLAB_SECRET", "top-secret")
    runner = LocalPythonRunner(timeout_seconds=2)
    code = (
        "import sys\n\n"
        "def read_secret():\n"
        "    return sys.modules['os'].environ.get('ACCESSLAB_SECRET', 'missing')\n"
    )
    tests = (
        "from submission import read_secret\n\n"
        "def test_secret_removed():\n"
        "    assert read_secret() == 'missing'\n"
    )

    result = runner.run(code, tests)

    assert result.passed
    assert "ACCESSLAB_SECRET" not in result.combined_output


def test_code_runner_blocks_runtime_network_access():
    runner = LocalPythonRunner(timeout_seconds=2)
    code = (
        "import importlib\n\n"
        "def attempt_network():\n"
        "    socket = importlib.import_module('socket')\n"
        "    getattr(socket, 'socket')()\n"
    )
    tests = (
        "from submission import attempt_network\n\n"
        "def test_attempt_network():\n"
        "    attempt_network()\n"
    )

    result = runner.run(code, tests)

    assert result.status == "blocked"
    assert result.denied_by_policy is True
    assert "Sandbox policy denied network access." in result.combined_output


def test_code_runner_reports_platform_specific_sandbox_profile():
    runner = LocalPythonRunner(timeout_seconds=2)

    result = runner.run("def identity(value):\n    return value\n")

    if sys.platform.startswith("linux"):
        assert result.sandbox_profile == "audit-posix-linux"
        assert "memory ceiling" in result.sandbox_note.lower()
    elif result.sandbox_profile == "audit-posix":
        assert result.sandbox_profile == "audit-posix"
        assert "linux-only memory ceiling is unavailable" in result.sandbox_note.lower()
    else:
        assert result.sandbox_profile == "audit-only"
        assert "resource limits are unavailable" in result.sandbox_note.lower()
