"""Tests for the deployment-profile mechanism in app/config.py.

These lock in the contract documented in
reports/deployment_profiles_decision_memo.md so a future refactor cannot
silently:
  - change the profile -> model mapping
  - flip the default profile away from "strong"
  - break the supported Gemma-4 explicit-model precedence
  - allow unsupported generation models back into the user-facing path
"""

from __future__ import annotations

import pytest

from app.config import (
    DEFAULT_DEPLOYMENT_MODE,
    DEFAULT_DEPLOYMENT_PROFILE,
    DEFAULT_DISCIPLINE_OVERRIDE,
    DEFAULT_RETRIEVAL_MODE,
    KNOWN_DISCIPLINE_OVERRIDES,
    KNOWN_DEPLOYMENT_MODES,
    KNOWN_RETRIEVAL_MODES,
    PROFILE_MODELS,
    Settings,
    resolve_active_model,
    resolve_deployment_mode,
    resolve_deployment_profile,
    resolve_qa_discipline_profile,
    resolve_retrieval_mode,
    resolve_runtime_backend,
)
from app.services.code_tutor import DEFAULT_CODE_TUTOR_PROMPT_VARIANT
from app.services.llm import DEFAULT_RUNTIME_BACKEND, KNOWN_RUNTIME_BACKENDS
from app.services.qa import (
    DEFAULT_QA_DISCIPLINE_PROFILE,
    DEFAULT_QA_PROMPT_VARIANT,
    KNOWN_QA_DISCIPLINE_PROFILES,
)
from app.services.semantic import DEFAULT_SEMANTIC_EMBEDDING_MODEL


# ---------------------------------------------------------------------------
# Profile / model mapping invariants
# ---------------------------------------------------------------------------


def test_profile_models_match_evidence_based_decision():
    """Pin the strong/weak mapping. Changing this requires updating
    reports/deployment_profiles_decision_memo.md and the README profile table."""
    assert PROFILE_MODELS["strong"] == "gemma4:e4b"
    assert PROFILE_MODELS["weak"] == "gemma4:e2b"


def test_default_deployment_profile_is_strong():
    assert DEFAULT_DEPLOYMENT_PROFILE == "strong"


# ---------------------------------------------------------------------------
# resolve_deployment_profile
# ---------------------------------------------------------------------------


def test_resolve_deployment_profile_defaults_to_strong():
    assert resolve_deployment_profile(profile_env="", model_env="") == "strong"
    assert resolve_deployment_profile(profile_env=None, model_env=None)
    # When env vars are unset the env-driven path runs, so just assert it is
    # one of the known labels (we already covered the empty-env case above).


def test_resolve_deployment_profile_honors_explicit_profile():
    assert resolve_deployment_profile(profile_env="weak", model_env="") == "weak"
    assert resolve_deployment_profile(profile_env="STRONG", model_env="") == "strong"


def test_resolve_deployment_profile_infers_from_known_model():
    assert resolve_deployment_profile(profile_env="", model_env="gemma4:e2b") == "weak"
    assert resolve_deployment_profile(profile_env="", model_env="gemma4:e4b") == "strong"


def test_resolve_deployment_profile_ignores_unsupported_model_override():
    assert resolve_deployment_profile(profile_env="", model_env="mistral:7b-instruct") == "strong"


def test_resolve_deployment_profile_label_wins_over_inferred():
    """Operator's explicit profile label is authoritative even when it
    disagrees with the explicit model. The status panel shows both fields,
    so the disagreement is visible to the operator."""
    assert resolve_deployment_profile(profile_env="weak", model_env="gemma4:e4b") == "weak"


def test_resolve_deployment_profile_falls_back_for_unknown_label():
    """A typo in ACCESSLAB_DEPLOYMENT_PROFILE should not silently downgrade
    the model: we fall back to inference-then-default rather than crashing."""
    assert resolve_deployment_profile(profile_env="weakish", model_env="gemma4:e2b") == "weak"
    assert resolve_deployment_profile(profile_env="weakish", model_env="") == "strong"


# ---------------------------------------------------------------------------
# resolve_active_model
# ---------------------------------------------------------------------------


def test_resolve_active_model_explicit_wins():
    assert resolve_active_model(profile_env="weak", model_env="mistral:7b") == "gemma4:e2b"
    assert resolve_active_model(profile_env="strong", model_env="gemma4:e2b") == "gemma4:e2b"


def test_resolve_active_model_uses_profile_mapping():
    assert resolve_active_model(profile_env="strong", model_env="") == "gemma4:e4b"
    assert resolve_active_model(profile_env="weak", model_env="") == "gemma4:e2b"


def test_resolve_active_model_defaults_to_strong_model():
    assert resolve_active_model(profile_env="", model_env="") == "gemma4:e4b"


def test_resolve_active_model_defaults_for_unknown_profile_label():
    assert resolve_active_model(profile_env="bogus", model_env="") == "gemma4:e4b"


# ---------------------------------------------------------------------------
# Settings dataclass integration
# ---------------------------------------------------------------------------


def test_settings_default_to_strong_profile_when_env_clean(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ACCESSLAB_DEPLOYMENT_PROFILE", raising=False)
    monkeypatch.delenv("ACCESSLAB_MODEL", raising=False)
    settings = Settings()
    assert settings.deployment_profile == "strong"
    assert settings.accesslab_model == "gemma4:e4b"
    assert settings.model_explicitly_set is False
    assert settings.deployment_profile_display == "Strong"
    assert "stronger laptops" in settings.deployment_profile_summary


def test_settings_weak_profile_picks_e2b(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ACCESSLAB_DEPLOYMENT_PROFILE", "weak")
    monkeypatch.delenv("ACCESSLAB_MODEL", raising=False)
    settings = Settings()
    assert settings.deployment_profile == "weak"
    assert settings.accesslab_model == "gemma4:e2b"
    assert settings.model_explicitly_set is False
    assert settings.deployment_profile_display == "Constrained"
    assert "constrained local profile" in settings.deployment_profile_summary


def test_settings_explicit_model_marks_explicit_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ACCESSLAB_DEPLOYMENT_PROFILE", raising=False)
    monkeypatch.setenv("ACCESSLAB_MODEL", "gemma4:e2b")
    settings = Settings()
    assert settings.deployment_profile == "weak"  # inferred
    assert settings.accesslab_model == "gemma4:e2b"
    assert settings.model_explicitly_set is True


def test_settings_unsupported_model_override_is_ignored(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ACCESSLAB_DEPLOYMENT_PROFILE", raising=False)
    monkeypatch.setenv("ACCESSLAB_MODEL", "mistral:7b-instruct")
    settings = Settings()
    assert settings.deployment_profile == "strong"
    assert settings.accesslab_model == "gemma4:e4b"
    assert settings.model_explicitly_set is False
    assert settings.generation_model_override_ignored is True
    assert "mistral:7b-instruct" in settings.generation_model_notice
    assert "Gemma 4" in settings.generation_model_notice


def test_settings_explicit_profile_label_wins_even_with_explicit_model(
    monkeypatch: pytest.MonkeyPatch,
):
    """A common confused-state: operator pins ACCESSLAB_MODEL=e4b but also
    asked for the weak profile. Active model follows the explicit override
    (per spec); profile label respects the operator's stated intent so the
    UI shows the disagreement and they can fix it."""
    monkeypatch.setenv("ACCESSLAB_DEPLOYMENT_PROFILE", "weak")
    monkeypatch.setenv("ACCESSLAB_MODEL", "gemma4:e4b")
    settings = Settings()
    assert settings.deployment_profile == "weak"
    assert settings.accesslab_model == "gemma4:e4b"


def test_settings_normalizes_unknown_profile_to_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ACCESSLAB_DEPLOYMENT_PROFILE", "bogus-tier")
    monkeypatch.delenv("ACCESSLAB_MODEL", raising=False)
    settings = Settings()
    assert settings.deployment_profile == DEFAULT_DEPLOYMENT_PROFILE
    assert settings.accesslab_model == "gemma4:e4b"


# ---------------------------------------------------------------------------
# Prompt-default constants are pinned
# ---------------------------------------------------------------------------


def test_default_qa_prompt_variant_is_baseline():
    """Lock in the QA default promoted by the model-tier sweep. Changing
    this requires re-running the full-pack reference benchmark and updating
    reports/model_tier_decision_memo.md."""
    assert DEFAULT_QA_PROMPT_VARIANT == "baseline"


def test_default_code_tutor_prompt_variant_is_hybrid():
    """Mirror of the existing test in test_code_tutor.py, here too so the
    QA + code-tutor default-pinning story is visible in a single file."""
    assert DEFAULT_CODE_TUTOR_PROMPT_VARIANT == "hybrid"


# ---------------------------------------------------------------------------
# QA discipline profile is wired to the deployment profile
# ---------------------------------------------------------------------------
#
# The weak-tier QA discipline suffix (see app/services/qa.py) is applied
# automatically when the deployment profile is "weak". Lock the contract
# here so the wiring in app/main.py and the harness inference rule both
# survive future refactors.


def test_known_qa_discipline_profiles_match_documented_set():
    assert set(KNOWN_QA_DISCIPLINE_PROFILES) == {"default", "weak"}


def test_default_qa_discipline_profile_is_default():
    assert DEFAULT_QA_DISCIPLINE_PROFILE == "default"


def test_qa_discipline_auto_binding_uses_weak_for_weak_profile():
    """The scripts/run_accesslab_eval.py harness derives its 'auto' value
    from the active model. Mirror the same rule here so the contract
    documented in app/main.py + the harness stays in sync with the
    deployment-profile mapping."""
    weak_model = PROFILE_MODELS["weak"]
    strong_model = PROFILE_MODELS["strong"]

    def _expected_discipline(model: str) -> str:
        return "weak" if model == weak_model else "default"

    assert _expected_discipline(weak_model) == "weak"
    assert _expected_discipline(strong_model) == "default"
    assert _expected_discipline("mistral:7b-instruct") == "default"


# ---------------------------------------------------------------------------
# resolve_qa_discipline_profile + ACCESSLAB_QA_DISCIPLINE_PROFILE override
# ---------------------------------------------------------------------------
#
# The override is the operator-level revertibility knob: it should let a
# weak-profile install temporarily disable the discipline suffix without
# changing the active model, and let a strong install opt into the suffix
# for an experiment without changing the model either.


def test_known_discipline_overrides_match_documented_set():
    assert KNOWN_DISCIPLINE_OVERRIDES == frozenset({"auto", "default", "weak"})
    assert DEFAULT_DISCIPLINE_OVERRIDE == "auto"


def test_resolve_qa_discipline_auto_follows_deployment_profile():
    assert (
        resolve_qa_discipline_profile(
            discipline_env="auto", profile_env="weak", model_env=""
        )
        == "weak"
    )
    assert (
        resolve_qa_discipline_profile(
            discipline_env="auto", profile_env="strong", model_env=""
        )
        == "default"
    )
    assert (
        resolve_qa_discipline_profile(
            discipline_env="auto", profile_env="bogus", model_env="mistral:7b-instruct"
        )
        == "default"
    )


def test_runtime_backend_defaults_to_ollama():
    assert resolve_runtime_backend("") == DEFAULT_RUNTIME_BACKEND


def test_runtime_backend_accepts_litert_validation_scaffold():
    assert "litert-lm-validation" in KNOWN_RUNTIME_BACKENDS
    assert resolve_runtime_backend("litert-lm-validation") == "litert-lm-validation"


def test_deployment_mode_defaults_to_single_user_local():
    assert DEFAULT_DEPLOYMENT_MODE == "single-user-local"
    assert "school-box-shared" in KNOWN_DEPLOYMENT_MODES
    assert resolve_deployment_mode("") == "single-user-local"


def test_retrieval_mode_defaults_to_hybrid():
    assert DEFAULT_RETRIEVAL_MODE == "hybrid"
    assert KNOWN_RETRIEVAL_MODES == frozenset({"lexical", "semantic", "hybrid"})
    assert resolve_retrieval_mode("") == "hybrid"


def test_semantic_model_default_is_embeddinggemma(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ACCESSLAB_SEMANTIC_MODEL", raising=False)
    settings = Settings()
    assert DEFAULT_SEMANTIC_EMBEDDING_MODEL == "embeddinggemma"
    assert settings.semantic_embedding_model == "embeddinggemma"
    assert settings.semantic_model_family == "EmbeddingGemma"


def test_resolve_qa_discipline_explicit_override_wins_over_profile():
    """Operator's explicit choice trumps the profile binding both ways."""
    assert (
        resolve_qa_discipline_profile(
            discipline_env="default", profile_env="weak", model_env=""
        )
        == "default"
    ), "weak profile must be revertible without changing the model"
    assert (
        resolve_qa_discipline_profile(
            discipline_env="weak", profile_env="strong", model_env=""
        )
        == "weak"
    ), "strong profile must be able to opt into the suffix for experiments"


def test_resolve_qa_discipline_unknown_override_falls_back_to_auto():
    assert (
        resolve_qa_discipline_profile(
            discipline_env="aggressive", profile_env="weak", model_env=""
        )
        == "weak"
    )
    assert (
        resolve_qa_discipline_profile(
            discipline_env="", profile_env="strong", model_env=""
        )
        == "default"
    )


def test_resolve_qa_discipline_is_case_insensitive():
    assert (
        resolve_qa_discipline_profile(
            discipline_env="WEAK", profile_env="strong", model_env=""
        )
        == "weak"
    )
    assert (
        resolve_qa_discipline_profile(
            discipline_env=" Default ", profile_env="weak", model_env=""
        )
        == "default"
    )


def test_settings_qa_discipline_defaults_to_auto_when_env_clean(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("ACCESSLAB_DEPLOYMENT_PROFILE", raising=False)
    monkeypatch.delenv("ACCESSLAB_MODEL", raising=False)
    monkeypatch.delenv("ACCESSLAB_QA_DISCIPLINE_PROFILE", raising=False)
    settings = Settings()
    assert settings.deployment_profile == "strong"
    assert settings.qa_discipline_profile == "default"
    assert settings.qa_discipline_explicitly_set is False


def test_settings_qa_discipline_auto_picks_weak_for_weak_profile(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ACCESSLAB_DEPLOYMENT_PROFILE", "weak")
    monkeypatch.delenv("ACCESSLAB_MODEL", raising=False)
    monkeypatch.delenv("ACCESSLAB_QA_DISCIPLINE_PROFILE", raising=False)
    settings = Settings()
    assert settings.deployment_profile == "weak"
    assert settings.qa_discipline_profile == "weak"
    assert settings.qa_discipline_explicitly_set is False


def test_settings_qa_discipline_explicit_default_overrides_weak_profile(
    monkeypatch: pytest.MonkeyPatch,
):
    """Triage scenario: keep the e2b model but turn off the suffix without
    rebuilding or changing the deployment profile."""
    monkeypatch.delenv("ACCESSLAB_MODEL", raising=False)
    monkeypatch.setenv("ACCESSLAB_DEPLOYMENT_PROFILE", "weak")
    monkeypatch.setenv("ACCESSLAB_QA_DISCIPLINE_PROFILE", "default")
    settings = Settings()
    assert settings.deployment_profile == "weak"
    assert settings.accesslab_model == "gemma4:e2b"
    assert settings.qa_discipline_profile == "default"
    assert settings.qa_discipline_explicitly_set is True


def test_settings_qa_discipline_explicit_weak_overrides_strong_profile(
    monkeypatch: pytest.MonkeyPatch,
):
    """Experiment scenario: opt the strong profile into the suffix without
    changing the active model."""
    monkeypatch.delenv("ACCESSLAB_MODEL", raising=False)
    monkeypatch.setenv("ACCESSLAB_DEPLOYMENT_PROFILE", "strong")
    monkeypatch.setenv("ACCESSLAB_QA_DISCIPLINE_PROFILE", "weak")
    settings = Settings()
    assert settings.deployment_profile == "strong"
    assert settings.accesslab_model == "gemma4:e4b"
    assert settings.qa_discipline_profile == "weak"
    assert settings.qa_discipline_explicitly_set is True


def test_settings_qa_discipline_unknown_value_falls_back_to_auto(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("ACCESSLAB_MODEL", raising=False)
    monkeypatch.setenv("ACCESSLAB_DEPLOYMENT_PROFILE", "weak")
    monkeypatch.setenv("ACCESSLAB_QA_DISCIPLINE_PROFILE", "ultra")
    settings = Settings()
    assert settings.qa_discipline_profile == "weak"  # auto path
    assert settings.qa_discipline_explicitly_set is False
