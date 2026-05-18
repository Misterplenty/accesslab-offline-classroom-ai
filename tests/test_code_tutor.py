from pathlib import Path

from app.db import init_db
from app.models.schemas import RuntimeCapabilities
from app.services.code_runner import LocalPythonRunner
from app.services.code_tutor import (
    DEFAULT_CODE_TUTOR_PROMPT_VARIANT,
    CodeTutorService,
    parse_code_tutor_response,
)
from app.services.prompts_experimental import parse_hybrid_code_response


def test_code_tutor_default_prompt_variant_is_hybrid():
    """The service default is hybrid as of the A/B/C code-tutor repair branch.

    Lock this in so a future refactor that touches the constructor signature
    cannot silently regress the running app back to the baseline prompt.
    """
    assert DEFAULT_CODE_TUTOR_PROMPT_VARIANT == "hybrid"


class StubLLMProvider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.backend_name = "ollama"
        self.runtime_label = "Ollama local runtime"
        self.model_name = "gemma4:e4b"

    def health_check(self) -> tuple[bool, str]:
        return True, "ready"

    def generate_answer(self, prompt: str, context: str, settings: dict | None = None) -> str:
        return self.response

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            backend_name=self.backend_name,
            runtime_label=self.runtime_label,
            validation_stage="current",
            supports_streaming=True,
            token_timings_available=True,
            model_listing_available=True,
            health_probe_shape="stub health probe",
            semantic_dependency_shape="stub semantic dependency",
        )


def test_parse_code_tutor_response_reads_explicit_evidence():
    raw_response = (
        "<what_failed>The function returns the wrong total.</what_failed>"
        '<evidence>Test evidence: "assert add_numbers(2, 3) == 5"</evidence>'
        "<smallest_next_fix>Change subtraction to addition.</smallest_next_fix>"
        "<patched_code>def add_numbers(a, b):\n    return a + b\n</patched_code>"
        "<why_it_works>The function now matches the expected sum from the test.</why_it_works>"
    )

    diagnosis, evidence, next_fix, patched_code, why_it_works = parse_code_tutor_response(
        raw_response,
        "def add_numbers(a, b):\n    return a - b\n",
        "AssertionError: assert add_numbers(2, 3) == 5",
    )

    assert "wrong total" in diagnosis
    assert "assert add_numbers(2, 3) == 5" in evidence
    assert "subtraction to addition" in next_fix
    assert "return a + b" in patched_code
    assert "expected sum" in why_it_works


def test_code_tutor_falls_back_to_initial_run_evidence(tmp_path: Path):
    db_path = tmp_path / "accesslab.db"
    init_db(db_path)

    # Pinned to "baseline" because this test exists to validate the baseline
    # parser's evidence-fallback behavior. The service-level default is
    # "hybrid" since the A/B/C benchmark; see DEFAULT_CODE_TUTOR_PROMPT_VARIANT.
    service = CodeTutorService(
        db_path=db_path,
        llm_provider=StubLLMProvider(
            (
                "<what_failed>The function is using the wrong operator.</what_failed>"
                "<smallest_next_fix>Replace subtraction with addition.</smallest_next_fix>"
                "<patched_code>def add_numbers(a, b):\n    return a + b\n</patched_code>"
                "<why_it_works>The result will match the test.</why_it_works>"
            )
        ),
        execution_backend=LocalPythonRunner(timeout_seconds=2),
        prompt_variant="baseline",
    )

    code = "def add_numbers(a, b):\n    return a - b\n"
    tests = (
        "from submission import add_numbers\n\n"
        "def test_add_numbers():\n"
        "    assert add_numbers(2, 3) == 5\n"
    )

    result = service.tutor(code, tests)

    assert result.patched_run.passed
    assert "Initial run evidence:" in result.evidence
    assert "assert" in result.evidence.lower()


# ---------------------------------------------------------------------------
# Hybrid code-tutor parser tests
# ---------------------------------------------------------------------------
# These lock in the contract for the hybrid variant: strong multi-line code
# extraction, evidence language preserved in the diagnosis, and graceful
# degradation when the model omits a tag. The original buggy code must only
# appear as a last-resort fallback, never because of a mid-parse confusion.


def test_parse_hybrid_extracts_multiline_code_and_evidence():
    raw_response = (
        "<diagnosis>The assertion assert is_even(4) is True failed because the "
        "function returned False when we expected True. The bug is checking "
        "the remainder against 1 instead of 0.</diagnosis>\n"
        "<fix>Change the comparison from == 1 to == 0.</fix>\n"
        "<patched_code>\n"
        "def is_even(number):\n"
        "    return number % 2 == 0\n"
        "</patched_code>\n"
        "<why>An even number always leaves a remainder of 0 when divided by 2, "
        "which is what the failing assertion expected.</why>"
    )

    diagnosis, evidence, next_fix, patched_code, why_it_works = parse_hybrid_code_response(
        raw_response,
        "def is_even(number):\n    return number % 2 == 1\n",
        "AssertionError: assert False is True",
    )

    assert "assertion" in diagnosis.lower()
    assert "expected" in diagnosis.lower()
    assert diagnosis == evidence
    assert "== 0" in next_fix
    assert "def is_even(number):" in patched_code
    assert "return number % 2 == 0" in patched_code
    assert "failing assertion" in why_it_works.lower()


def test_parse_hybrid_strips_markdown_fences_inside_patched_code_tag():
    raw_response = (
        "<diagnosis>NameError: name 'num' is not defined inside square_number; "
        "the test expected square_number(5) == 25 but the call raised.</diagnosis>\n"
        "<fix>Use the parameter name number instead of num.</fix>\n"
        "<patched_code>\n"
        "```python\n"
        "def square_number(number):\n"
        "    return number * number\n"
        "```\n"
        "</patched_code>\n"
        "<why>The expression now references the defined parameter.</why>"
    )

    _, _, _, patched_code, _ = parse_hybrid_code_response(
        raw_response,
        "def square_number(number):\n    return num * num\n",
        "NameError: name 'num' is not defined",
    )

    assert patched_code.startswith("def square_number(number):")
    assert "```" not in patched_code
    assert "return number * number" in patched_code


def test_parse_hybrid_falls_back_to_markdown_fence_when_tag_missing():
    raw_response = (
        "<diagnosis>The test expected a sum of 5 but the function returned -1 "
        "because it subtracts instead of adding.</diagnosis>\n"
        "<fix>Use + instead of -.</fix>\n"
        "```python\n"
        "def add_numbers(a, b):\n"
        "    return a + b\n"
        "```\n"
        "<why>Addition produces the value the assertion expected.</why>"
    )

    _, _, _, patched_code, _ = parse_hybrid_code_response(
        raw_response,
        "def add_numbers(a, b):\n    return a - b\n",
        "AssertionError: assert -1 == 5",
    )

    assert "return a + b" in patched_code
    assert "return a - b" not in patched_code


def test_parse_hybrid_falls_back_cleanly_when_diagnosis_missing():
    raw_response = (
        "<patched_code>\n"
        "def total(items):\n"
        "    return sum(items)\n"
        "</patched_code>"
    )

    diagnosis, evidence, next_fix, patched_code, _ = parse_hybrid_code_response(
        raw_response,
        "def total(items):\n    return sum(items) - 1\n",
        "AssertionError",
    )

    assert "could not parse a structured explanation" in diagnosis.lower()
    assert diagnosis == evidence
    assert next_fix
    assert "return sum(items)" in patched_code


def test_parse_hybrid_preserves_original_code_when_everything_is_missing():
    raw_response = "The model returned free-form text with no structure at all."
    original_code = "def noop():\n    return None\n"

    diagnosis, _, _, patched_code, _ = parse_hybrid_code_response(
        raw_response,
        original_code,
        "",
    )

    assert "could not parse a structured explanation" in diagnosis.lower()
    assert patched_code == original_code


def test_code_tutor_service_with_hybrid_variant_end_to_end(tmp_path: Path):
    db_path = tmp_path / "accesslab.db"
    init_db(db_path)

    hybrid_response = (
        "<diagnosis>The assertion assert add_numbers(2, 3) == 5 failed because "
        "the function returned -1 where the test expected 5.</diagnosis>\n"
        "<fix>Replace subtraction with addition.</fix>\n"
        "<patched_code>\n"
        "def add_numbers(a, b):\n"
        "    return a + b\n"
        "</patched_code>\n"
        "<why>Addition now produces the value the failing test expected.</why>"
    )

    service = CodeTutorService(
        db_path=db_path,
        llm_provider=StubLLMProvider(hybrid_response),
        execution_backend=LocalPythonRunner(timeout_seconds=2),
        prompt_variant="hybrid",
    )

    code = "def add_numbers(a, b):\n    return a - b\n"
    tests = (
        "from submission import add_numbers\n\n"
        "def test_add_numbers():\n"
        "    assert add_numbers(2, 3) == 5\n"
    )

    result = service.tutor(code, tests)

    assert result.patched_run.passed
    assert "assertion" in result.diagnosis.lower()
    assert "expected" in result.diagnosis.lower()
    assert "return a + b" in result.patched_code
    assert result.diagnosis == result.evidence


def test_code_tutor_rejects_tests_that_import_missing_submission_name(tmp_path: Path):
    db_path = tmp_path / "accesslab.db"
    init_db(db_path)

    service = CodeTutorService(
        db_path=db_path,
        llm_provider=StubLLMProvider(
            "<diagnosis>Do not use this.</diagnosis>"
            "<fix>Do not use this.</fix>"
            "<patched_code>def add_numbers(a, b):\n    return a + b</patched_code>"
            "<why>Do not use this.</why>"
        ),
        execution_backend=LocalPythonRunner(timeout_seconds=2),
        prompt_variant="hybrid",
    )

    result = service.tutor(
        "Print(helloworld)\n",
        "from submission import add_numbers\n\n"
        "def test_add_numbers():\n"
        "    assert add_numbers(2, 3) == 5\n",
    )

    assert result.result_mode == "test_mismatch"
    assert "tests do not match" in result.diagnosis.lower()
    assert "add_numbers" in result.evidence
    assert result.patched_code == "Print(helloworld)\n"
    assert result.patched_run.status == "not_run"
