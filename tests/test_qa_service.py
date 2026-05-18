from pathlib import Path

from app.db import get_qa_history_entry, init_db
from app.models.schemas import RuntimeCapabilities, SearchResult
from app.services.qa import (
    DEFAULT_QA_DISCIPLINE_PROFILE,
    GROUNDED_QA_SYSTEM_PROMPT,
    WEAK_TIER_QA_DISCIPLINE_SUFFIX,
    GroundedQAService,
)


class StubRetrievalBackend:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def current_mode(self) -> tuple[str, str]:
        return "hybrid", "Hybrid"

    def search(self, query: str, *, limit: int = 4) -> list[SearchResult]:
        self.queries.append(query)
        return [
            SearchResult(
                chunk_id="chunk-1",
                source_file="worksheet.md",
                page_number=None,
                chunk_text=(
                    "Question 3 explains in simple language that the worksheet says "
                    "loops go through a list one item at a time."
                ),
                snippet=(
                    "Question 3 explains in simple language that the worksheet says "
                    "loops go through a list one item at a time."
                ),
                score=0.1,
            )
        ]


class StubLLMProvider:
    backend_name = "ollama"
    runtime_label = "Ollama local runtime"
    model_name = "gemma4:e4b"

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.contexts: list[str] = []

    def health_check(self) -> tuple[bool, str]:
        return True, "ready"

    def generate_answer(self, prompt: str, context: str, settings: dict | None = None) -> str:
        self.prompts.append(prompt)
        self.contexts.append(context)
        return (
            "<short_answer>I am unsure. I need a clearer match before I answer. [S1]</short_answer>"
            "<more_detail></more_detail>"
        )

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


def _make_service(tmp_path: Path, **kwargs) -> GroundedQAService:
    db_path = tmp_path / "accesslab.db"
    init_db(db_path)
    return GroundedQAService(
        db_path=db_path,
        retrieval_backend=StubRetrievalBackend(),
        llm_provider=StubLLMProvider(),
        **kwargs,
    )


def test_qa_language_and_plain_options_do_not_pollute_retrieval_or_saved_question(tmp_path: Path):
    clean_question = "What does the worksheet say about loops?"
    db_path = tmp_path / "accesslab.db"
    init_db(db_path)
    retrieval = StubRetrievalBackend()
    llm = StubLLMProvider()
    service = GroundedQAService(
        db_path=db_path,
        retrieval_backend=retrieval,
        llm_provider=llm,
    )

    result = service.answer(
        clean_question,
        answer_language="spanish",
        plain_language_requested=True,
    )

    assert retrieval.queries == [clean_question]
    assert result.question == clean_question
    assert llm.prompts
    prompt = llm.prompts[0]
    assert f"Question: {clean_question}" in prompt
    assert "Answer guidance:" in prompt
    assert "Answer in Spanish" in prompt
    assert "Use plain, simple language" in prompt
    assert f"Question: {clean_question}\n\nAnswer in Spanish" not in prompt

    assert result.history_id is not None
    saved = get_qa_history_entry(db_path, result.history_id)
    assert saved is not None
    assert saved["question"] == clean_question
    assert saved["session_data"]["question"] == clean_question
    assert saved["session_data"]["answer_language"] == "spanish"
    assert saved["session_data"]["answer_language_label"] == "Spanish"
    assert saved["session_data"]["plain_language_requested"] is True


def test_qa_service_marks_model_uncertainty_as_unsure(tmp_path: Path):
    service = _make_service(tmp_path)
    result = service.answer("Explain question 3 in simple language.")

    assert result.unsure is True
    assert "I am unsure" in result.short_answer


# ---------------------------------------------------------------------------
# QA output-discipline profile
# ---------------------------------------------------------------------------
#
# The weak-tier discipline suffix is the narrow fix for the e2b accessibility
# verbosity regression observed in the 2026-04-19 model-tier sweep. These
# tests pin the contract so a future refactor cannot silently:
#   - flip the default discipline profile away from "default"
#   - drop the suffix attachment when qa_discipline_profile == "weak"
#   - leak the suffix into the strong-tier prompt
#   - leak the suffix into the experimental QA variant (which is meant to
#     stay minimal as a clean prefill A/B target)


def test_default_qa_discipline_profile_is_default():
    assert DEFAULT_QA_DISCIPLINE_PROFILE == "default"


def test_default_service_uses_unmodified_baseline_prompt(tmp_path: Path):
    service = _make_service(tmp_path)
    assert service.qa_discipline_profile == "default"
    assert service._resolve_system_prompt() == GROUNDED_QA_SYSTEM_PROMPT


def test_weak_discipline_profile_appends_suffix_to_baseline_prompt(tmp_path: Path):
    service = _make_service(tmp_path, qa_discipline_profile="weak")
    assert service.qa_discipline_profile == "weak"

    resolved = service._resolve_system_prompt()
    assert resolved.startswith(GROUNDED_QA_SYSTEM_PROMPT)
    assert resolved.endswith(WEAK_TIER_QA_DISCIPLINE_SUFFIX)
    assert "ONE simple sentence" in resolved
    assert "Place every citation inside" in resolved


def test_weak_discipline_profile_normalises_unknown_input(tmp_path: Path):
    service = _make_service(tmp_path, qa_discipline_profile="bogus-tier")
    assert service.qa_discipline_profile == "default"
    assert service._resolve_system_prompt() == GROUNDED_QA_SYSTEM_PROMPT


def test_weak_discipline_profile_is_case_insensitive(tmp_path: Path):
    service = _make_service(tmp_path, qa_discipline_profile=" WEAK ")
    assert service.qa_discipline_profile == "weak"
    assert service._resolve_system_prompt().endswith(WEAK_TIER_QA_DISCIPLINE_SUFFIX)


def test_experimental_variant_ignores_discipline_suffix(tmp_path: Path):
    """The experimental QA prompt is intentionally minimal so it stays a
    clean prefill A/B target. The discipline suffix only attaches to the
    baseline prompt; verify it does not leak into the experimental path."""
    service = _make_service(
        tmp_path,
        prompt_variant="experimental",
        qa_discipline_profile="weak",
    )
    resolved = service._resolve_system_prompt()
    assert resolved != GROUNDED_QA_SYSTEM_PROMPT
    assert "ONE simple sentence" not in resolved
    assert "Place every citation inside" not in resolved
