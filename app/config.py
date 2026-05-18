from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from app.services.llm import (
    ALLOWED_GEMMA4_MODELS,
    DEFAULT_RUNTIME_BACKEND,
    FUTURE_RUNTIME_VALIDATION_TRACK,
    GENERATION_MODEL_FAMILY,
    KNOWN_RUNTIME_BACKENDS,
    RUNTIME_BACKEND_LABELS,
)
from app.services.ocr import (
    DEFAULT_OCR_DPI,
    DEFAULT_OCR_ENABLED,
    OCR_ENABLED_VALUES,
    resolve_ocr_dpi,
    resolve_ocr_enabled,
)
from app.services.semantic import (
    DEFAULT_SEMANTIC_EMBEDDING_MODEL,
    DEFAULT_SEMANTIC_ENABLED,
    SEMANTIC_ENABLED_VALUES,
    is_embeddinggemma_model,
)


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


# ---------------------------------------------------------------------------
# Deployment profiles
# ---------------------------------------------------------------------------
# AccessLab supports two evidence-based deployment profiles:
#
#   strong -> gemma4:e4b
#       Intended for stronger laptops, teacher devices, and local-hub demos.
#       This is the configuration that scored 20/20 / 20/20 on the full
#       AccessLab Eval v0.1 pack with the current defaults
#       (QA=baseline, code-tutor=hybrid). See reports/model_tier_decision_memo.md.
#
#   weak -> gemma4:e2b
#       Intended for constrained-profile experiments and as the current
#       evidence-based candidate for future weak-device deployment. Selected
#       because it was the only model whose constrained-proxy latency on the
#       M4 Pro stayed in conversational range while keeping parse 20/20 and
#       code 8/8. It is a constrained local profile, not a claim about the
#       cheapest phones or lowest-RAM devices. Real weak-device validation is
#       still required before any deployment claim — see
#       reports/deployment_profiles_decision_memo.md.
#
# Resolution rules (kept small on purpose):
#   1. ACCESSLAB_MODEL may pin either supported Gemma 4 profile model
#      (`gemma4:e4b` or `gemma4:e2b`).
#   2. ACCESSLAB_DEPLOYMENT_PROFILE (when set to a known value) wins for the
#      profile label and, when ACCESSLAB_MODEL is unset or unsupported,
#      picks the model.
#   3. Otherwise the profile is inferred from the explicit supported model.
#   4. With nothing set we default to the strong profile.
PROFILE_MODELS: dict[str, str] = {
    "strong": "gemma4:e4b",
    "weak": "gemma4:e2b",
}

DEFAULT_DEPLOYMENT_PROFILE = "strong"
KNOWN_PROFILE_LABELS = frozenset(PROFILE_MODELS.keys())


# ---------------------------------------------------------------------------
# Product deployment modes
# ---------------------------------------------------------------------------
# Profiles choose the Gemma 4 model tier. Deployment modes describe how the
# product is being used in the classroom.
#
#   single-user-local
#       One local user on one local device.
#
#   classroom-local
#       Teacher-led local classroom use on one device, still mostly personal.
#
#   school-box-shared
#       One stronger LAN-visible machine serving many browser clients inside
#       the same school/local network.
DEPLOYMENT_MODE_LABELS: dict[str, str] = {
    "single-user-local": "Single-user local",
    "classroom-local": "Classroom local",
    "school-box-shared": "School AI box",
}
DEFAULT_DEPLOYMENT_MODE = "single-user-local"
KNOWN_DEPLOYMENT_MODES = frozenset(DEPLOYMENT_MODE_LABELS.keys())


# ---------------------------------------------------------------------------
# Retrieval mode
# ---------------------------------------------------------------------------
# AccessLab keeps SQLite FTS5 as the lexical baseline and lets operators pin
# which retrieval path is requested. When the semantic path is unavailable or
# unindexed, the diagnostics layer degrades honestly to lexical-only at
# runtime instead of silently pretending hybrid is active.
RETRIEVAL_MODE_LABELS: dict[str, str] = {
    "lexical": "Lexical only",
    "semantic": "Semantic only",
    "hybrid": "Hybrid",
}
DEFAULT_RETRIEVAL_MODE = "hybrid"
KNOWN_RETRIEVAL_MODES = frozenset(RETRIEVAL_MODE_LABELS.keys())


DEFAULT_CLASS_SPACE = "default-classroom"
DEFAULT_MAX_CONCURRENT_JOBS = 1
DEFAULT_TRAINING_CAPTURE_ENABLED = "off"
TRAINING_CAPTURE_ENABLED_VALUES = frozenset({"off", "on"})


# ---------------------------------------------------------------------------
# Runtime backend
# ---------------------------------------------------------------------------
# AccessLab ships with an abstracted generation-runtime entry point even
# though Ollama is the only working backend today. This keeps the runtime
# boundary explicit for future LiteRT-LM validation work without pretending
# that a mobile-edge path already exists in the running app.


# ---------------------------------------------------------------------------
# QA output-discipline profile (decoupled from deployment profile)
# ---------------------------------------------------------------------------
# The QA service has a small "output discipline" knob that selects between
# the unmodified baseline prompt ("default") and a baseline prompt with the
# weak-tier discipline suffix appended ("weak"). The suffix exists to fix
# the e2b accessibility verbosity regression documented in
# reports/weak_tier_a11y_discipline_decision_memo.md and reports/model_tier_decision_memo.md.
#
# By default the discipline profile is "auto", meaning it follows the
# deployment profile (weak deployment -> weak discipline; everything else ->
# default). Operators can override this independently with
# ACCESSLAB_QA_DISCIPLINE_PROFILE so they can:
#   - keep the weak deployment profile but disable the suffix for triage:
#       ACCESSLAB_QA_DISCIPLINE_PROFILE=default
#   - opt the strong profile into the suffix for an experiment:
#       ACCESSLAB_QA_DISCIPLINE_PROFILE=weak
# Unrecognised values fall back to "auto".
KNOWN_DISCIPLINE_OVERRIDES = frozenset({"auto", "default", "weak"})
DEFAULT_DISCIPLINE_OVERRIDE = "auto"


# ---------------------------------------------------------------------------
# OCR fallback settings (narrow, optional feature)
# ---------------------------------------------------------------------------
# AccessLab can OCR scanned / image-based PDFs locally using the optional
# OCR extras (``pip install -r requirements-ocr.txt``). The ingest service
# only invokes OCR for pages where PyPDF returned little or no text, so
# the text-PDF fast path is preserved.
#
#   ACCESSLAB_OCR_ENABLED
#     auto -> load the backend lazily; degrade gracefully if the optional
#             packages are missing (default).
#     on   -> load the backend eagerly at startup so missing deps surface
#             in server logs immediately.
#     off  -> disable OCR entirely; scanned PDFs will report "OCR disabled".
#
#   ACCESSLAB_OCR_DPI
#     Rasterisation DPI used when handing PDF pages to RapidOCR.
#     Defaults to 200 (good balance between quality and CPU on older
#     devices). Clamped to [72, 600] by the OCR service.
#
#   ACCESSLAB_OCR_MIN_CHARS_PER_PAGE
#     Threshold below which a PyPDF-extracted page is considered "scan-
#     like" and routed to OCR fallback. Defaults to 20 characters.
DEFAULT_OCR_MIN_CHARS_PER_PAGE = 20


def resolve_semantic_enabled(env_value: str | None = None) -> str:
    raw = _normalize_env(
        env_value if env_value is not None else os.getenv("ACCESSLAB_SEMANTIC_ENABLED")
    ).lower()
    if raw in SEMANTIC_ENABLED_VALUES:
        return raw
    return DEFAULT_SEMANTIC_ENABLED


def resolve_retrieval_mode(env_value: str | None = None) -> str:
    raw = _normalize_env(
        env_value if env_value is not None else os.getenv("ACCESSLAB_RETRIEVAL_MODE")
    ).lower()
    if raw in KNOWN_RETRIEVAL_MODES:
        return raw
    return DEFAULT_RETRIEVAL_MODE


def resolve_deployment_mode(env_value: str | None = None) -> str:
    raw = _normalize_env(
        env_value if env_value is not None else os.getenv("ACCESSLAB_DEPLOYMENT_MODE")
    ).lower()
    if raw in KNOWN_DEPLOYMENT_MODES:
        return raw
    return DEFAULT_DEPLOYMENT_MODE


def resolve_class_space(env_value: str | None = None) -> str:
    raw = _normalize_env(
        env_value if env_value is not None else os.getenv("ACCESSLAB_CLASS_SPACE")
    )
    if not raw:
        return DEFAULT_CLASS_SPACE
    slug = "-".join(
        part
        for part in raw.replace("_", "-").replace(" ", "-").split("-")
        if part
    )
    return slug[:80] or DEFAULT_CLASS_SPACE


def resolve_max_concurrent_jobs(
    env_value: str | None = None,
    deployment_mode_env: str | None = None,
) -> int:
    raw = _normalize_env(
        env_value if env_value is not None else os.getenv("ACCESSLAB_MAX_CONCURRENT_JOBS")
    )
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            return DEFAULT_MAX_CONCURRENT_JOBS
    deployment_mode = resolve_deployment_mode(deployment_mode_env)
    if deployment_mode == "single-user-local":
        return DEFAULT_MAX_CONCURRENT_JOBS
    return 1


def resolve_training_capture_enabled(env_value: str | None = None) -> str:
    raw = _normalize_env(
        env_value
        if env_value is not None
        else os.getenv("ACCESSLAB_TRAINING_CAPTURE_ENABLED")
    ).lower()
    if raw in TRAINING_CAPTURE_ENABLED_VALUES:
        return raw
    return DEFAULT_TRAINING_CAPTURE_ENABLED


def _normalize_env(value: str | None) -> str:
    return (value or "").strip()


def _resolve_ocr_min_chars_per_page(env_value: str | None = None) -> int:
    raw = env_value if env_value is not None else os.getenv("ACCESSLAB_OCR_MIN_CHARS_PER_PAGE")
    value = _normalize_env(raw)
    if not value:
        return DEFAULT_OCR_MIN_CHARS_PER_PAGE
    try:
        parsed = int(value)
    except ValueError:
        return DEFAULT_OCR_MIN_CHARS_PER_PAGE
    return max(1, parsed)


def resolve_runtime_backend(runtime_env: str | None = None) -> str:
    raw = _normalize_env(
        runtime_env if runtime_env is not None else os.getenv("ACCESSLAB_RUNTIME_BACKEND")
    ).lower()
    if raw in KNOWN_RUNTIME_BACKENDS:
        return raw
    return DEFAULT_RUNTIME_BACKEND


def resolve_deployment_profile(
    profile_env: str | None = None,
    model_env: str | None = None,
) -> str:
    """Return one of: 'strong', 'weak'.

    Inputs default to environment variables; explicit args make this trivial
    to unit-test without touching ``os.environ``.
    """
    raw_profile = _normalize_env(
        profile_env if profile_env is not None else os.getenv("ACCESSLAB_DEPLOYMENT_PROFILE")
    ).lower()
    if raw_profile in KNOWN_PROFILE_LABELS:
        return raw_profile

    explicit_model = _normalize_env(
        model_env if model_env is not None else os.getenv("ACCESSLAB_MODEL")
    )
    if explicit_model in ALLOWED_GEMMA4_MODELS:
        for profile, model in PROFILE_MODELS.items():
            if model == explicit_model:
                return profile

    return DEFAULT_DEPLOYMENT_PROFILE


def resolve_qa_discipline_profile(
    discipline_env: str | None = None,
    profile_env: str | None = None,
    model_env: str | None = None,
) -> str:
    """Return the resolved QA discipline profile: 'default' or 'weak'.

    The override (``ACCESSLAB_QA_DISCIPLINE_PROFILE`` by default) wins when
    set to a known concrete value. The implicit ``auto`` setting binds to
    the deployment profile so weak-tier installs get the discipline suffix
    automatically while strong-tier installs stay on the unmodified prompt.
    """
    raw_override = _normalize_env(
        discipline_env if discipline_env is not None
        else os.getenv("ACCESSLAB_QA_DISCIPLINE_PROFILE")
    ).lower()
    if raw_override not in KNOWN_DISCIPLINE_OVERRIDES:
        raw_override = DEFAULT_DISCIPLINE_OVERRIDE
    if raw_override in {"default", "weak"}:
        return raw_override

    deployment = resolve_deployment_profile(
        profile_env=profile_env, model_env=model_env
    )
    return "weak" if deployment == "weak" else "default"


def resolve_active_model(
    profile_env: str | None = None,
    model_env: str | None = None,
) -> str:
    """Return the model name AccessLab should ask Ollama for.

    Explicit ``ACCESSLAB_MODEL`` wins only when it points at a supported
    Gemma 4 profile model; otherwise the model is taken from the profile
    mapping. Falls back to the strong-profile model if both inputs are
    missing or unrecognised.
    """
    explicit_model = _normalize_env(
        model_env if model_env is not None else os.getenv("ACCESSLAB_MODEL")
    )
    if explicit_model in ALLOWED_GEMMA4_MODELS:
        return explicit_model

    raw_profile = _normalize_env(
        profile_env if profile_env is not None else os.getenv("ACCESSLAB_DEPLOYMENT_PROFILE")
    ).lower()
    if raw_profile in PROFILE_MODELS:
        return PROFILE_MODELS[raw_profile]

    return PROFILE_MODELS[DEFAULT_DEPLOYMENT_PROFILE]


@dataclass(slots=True)
class Settings:
    app_name: str = "AccessLab"
    runtime_backend: str = field(default_factory=resolve_runtime_backend)
    deployment_profile: str = field(default_factory=resolve_deployment_profile)
    deployment_mode: str = field(default_factory=resolve_deployment_mode)
    accesslab_model: str = field(default_factory=resolve_active_model)
    requested_generation_model: str = field(
        default_factory=lambda: _normalize_env(os.getenv("ACCESSLAB_MODEL"))
    )
    retrieval_mode: str = field(default_factory=resolve_retrieval_mode)
    qa_discipline_profile: str = field(default_factory=resolve_qa_discipline_profile)
    qa_discipline_explicitly_set: bool = field(
        default_factory=lambda: _normalize_env(
            os.getenv("ACCESSLAB_QA_DISCIPLINE_PROFILE")
        ).lower() in {"default", "weak"}
    )
    model_explicitly_set: bool = field(
        default_factory=lambda: _normalize_env(os.getenv("ACCESSLAB_MODEL")) in ALLOWED_GEMMA4_MODELS
    )
    generation_model_override_ignored: bool = field(
        default_factory=lambda: bool(
            _normalize_env(os.getenv("ACCESSLAB_MODEL"))
            and _normalize_env(os.getenv("ACCESSLAB_MODEL")) not in ALLOWED_GEMMA4_MODELS
        )
    )
    accesslab_ollama_url: str = field(
        default_factory=lambda: os.getenv("ACCESSLAB_OLLAMA_URL", "http://127.0.0.1:11434")
    )
    semantic_enabled: str = field(default_factory=resolve_semantic_enabled)
    semantic_embedding_model: str = field(
        default_factory=lambda: _normalize_env(
            os.getenv("ACCESSLAB_SEMANTIC_MODEL", DEFAULT_SEMANTIC_EMBEDDING_MODEL)
        )
        or DEFAULT_SEMANTIC_EMBEDDING_MODEL
    )
    ocr_enabled: str = field(default_factory=resolve_ocr_enabled)
    ocr_dpi: int = field(default_factory=resolve_ocr_dpi)
    ocr_min_chars_per_page: int = field(default_factory=_resolve_ocr_min_chars_per_page)
    class_space: str = field(default_factory=resolve_class_space)
    max_concurrent_jobs: int = field(default_factory=resolve_max_concurrent_jobs)
    training_capture_enabled: str = field(default_factory=resolve_training_capture_enabled)
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("ACCESSLAB_DATA_DIR", str(BASE_DIR / "data"))).expanduser()
    )
    secret_key: str = field(
        default_factory=lambda: os.getenv("ACCESSLAB_SECRET_KEY", "accesslab-local-dev")
    )
    base_dir: Path = BASE_DIR
    uploads_dir: Path = field(init=False)
    db_path: Path = field(init=False)
    templates_dir: Path = field(init=False)
    static_dir: Path = field(init=False)
    sample_data_dir: Path = field(init=False)
    sample_code_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.runtime_backend = (
            self.runtime_backend.strip().lower()
            if isinstance(self.runtime_backend, str)
            else DEFAULT_RUNTIME_BACKEND
        )
        if self.runtime_backend not in KNOWN_RUNTIME_BACKENDS:
            self.runtime_backend = DEFAULT_RUNTIME_BACKEND

        self.deployment_profile = (
            self.deployment_profile.strip().lower()
            if isinstance(self.deployment_profile, str)
            else DEFAULT_DEPLOYMENT_PROFILE
        )
        if self.deployment_profile not in KNOWN_PROFILE_LABELS:
            self.deployment_profile = DEFAULT_DEPLOYMENT_PROFILE
        self.deployment_mode = (
            self.deployment_mode.strip().lower()
            if isinstance(self.deployment_mode, str)
            else DEFAULT_DEPLOYMENT_MODE
        )
        if self.deployment_mode not in KNOWN_DEPLOYMENT_MODES:
            self.deployment_mode = DEFAULT_DEPLOYMENT_MODE
        self.requested_generation_model = self.requested_generation_model.strip()
        if self.accesslab_model not in ALLOWED_GEMMA4_MODELS:
            self.accesslab_model = PROFILE_MODELS[self.deployment_profile]
        self.model_explicitly_set = self.requested_generation_model in ALLOWED_GEMMA4_MODELS
        self.generation_model_override_ignored = (
            bool(self.requested_generation_model)
            and self.requested_generation_model not in ALLOWED_GEMMA4_MODELS
        )
        self.retrieval_mode = (
            self.retrieval_mode.strip().lower()
            if isinstance(self.retrieval_mode, str)
            else DEFAULT_RETRIEVAL_MODE
        )
        if self.retrieval_mode not in KNOWN_RETRIEVAL_MODES:
            self.retrieval_mode = DEFAULT_RETRIEVAL_MODE

        normalised_semantic = (self.semantic_enabled or "").strip().lower()
        if normalised_semantic not in SEMANTIC_ENABLED_VALUES:
            normalised_semantic = DEFAULT_SEMANTIC_ENABLED
        self.semantic_enabled = normalised_semantic
        self.semantic_embedding_model = self.semantic_embedding_model.strip() or DEFAULT_SEMANTIC_EMBEDDING_MODEL

        normalised_ocr = (self.ocr_enabled or "").strip().lower()
        if normalised_ocr not in OCR_ENABLED_VALUES:
            normalised_ocr = DEFAULT_OCR_ENABLED
        self.ocr_enabled = normalised_ocr
        self.ocr_dpi = max(72, min(600, int(self.ocr_dpi or DEFAULT_OCR_DPI)))
        self.ocr_min_chars_per_page = max(1, int(self.ocr_min_chars_per_page or DEFAULT_OCR_MIN_CHARS_PER_PAGE))
        self.class_space = self.class_space.strip() or DEFAULT_CLASS_SPACE
        self.max_concurrent_jobs = max(1, int(self.max_concurrent_jobs or DEFAULT_MAX_CONCURRENT_JOBS))
        normalized_training_capture = (self.training_capture_enabled or "").strip().lower()
        if normalized_training_capture not in TRAINING_CAPTURE_ENABLED_VALUES:
            normalized_training_capture = DEFAULT_TRAINING_CAPTURE_ENABLED
        self.training_capture_enabled = normalized_training_capture

        self.data_dir = self.data_dir.resolve()
        self.uploads_dir = self.data_dir / "uploads"
        self.db_path = self.data_dir / "accesslab.db"
        self.templates_dir = self.base_dir / "app" / "templates"
        self.static_dir = self.base_dir / "app" / "static"
        self.sample_data_dir = self.base_dir / "sample_data"
        self.sample_code_dir = self.base_dir / "sample_code"

    @property
    def deployment_profile_display(self) -> str:
        """Human-friendly profile label for templates."""
        if self.deployment_profile == "weak":
            return "Constrained"
        return "Strong"

    @property
    def deployment_profile_summary(self) -> str:
        """One-liner description used for the home-page status panel."""
        if self.deployment_profile == "strong":
            return "stronger laptops, teacher devices, and local-hub demos"
        if self.deployment_profile == "weak":
            return "constrained local profile based on proxy benchmarking; not a cheapest-phone or lowest-RAM guarantee"
        return "local Gemma 4 profile"

    @property
    def deployment_mode_display(self) -> str:
        return DEPLOYMENT_MODE_LABELS.get(
            self.deployment_mode,
            self.deployment_mode.replace("-", " ").title(),
        )

    @property
    def deployment_mode_summary(self) -> str:
        if self.deployment_mode == "single-user-local":
            return "one local browser on one local machine"
        if self.deployment_mode == "classroom-local":
            return "teacher-led local classroom use on one device"
        if self.deployment_mode == "school-box-shared":
            return "one stronger LAN machine serving many classroom browsers"
        return "local classroom deployment"

    @property
    def retrieval_mode_display(self) -> str:
        return RETRIEVAL_MODE_LABELS.get(
            self.retrieval_mode,
            self.retrieval_mode.replace("-", " ").title(),
        )

    @property
    def runtime_backend_display(self) -> str:
        return RUNTIME_BACKEND_LABELS.get(self.runtime_backend, self.runtime_backend.title())

    @property
    def generation_model_family(self) -> str:
        return GENERATION_MODEL_FAMILY

    @property
    def generation_model_policy(self) -> str:
        allowed = ", ".join(sorted(ALLOWED_GEMMA4_MODELS))
        return f"{GENERATION_MODEL_FAMILY} only ({allowed})"

    @property
    def generation_model_notice(self) -> str:
        if not self.generation_model_override_ignored:
            return ""
        return (
            f"ACCESSLAB_MODEL={self.requested_generation_model} was ignored. "
            f"AccessLab keeps user-facing generation on {GENERATION_MODEL_FAMILY} only, "
            f"so it fell back to {self.accesslab_model}."
        )

    @property
    def semantic_model_family(self) -> str:
        if is_embeddinggemma_model(self.semantic_embedding_model):
            return "EmbeddingGemma"
        return "Custom local embedding model"

    @property
    def semantic_model_summary(self) -> str:
        if is_embeddinggemma_model(self.semantic_embedding_model):
            return "EmbeddingGemma powers multilingual local semantic retrieval when available."
        return (
            f"{self.semantic_embedding_model} is configured for local semantic retrieval; "
            "SQLite FTS5 remains the lexical baseline."
        )

    @property
    def class_space_display(self) -> str:
        return self.class_space.replace("-", " ")

    @property
    def future_runtime_validation_track(self) -> str:
        return FUTURE_RUNTIME_VALIDATION_TRACK

    @property
    def training_capture_enabled_bool(self) -> bool:
        return self.training_capture_enabled == "on"

    @property
    def training_capture_display(self) -> str:
        return "Opt-in local capture on" if self.training_capture_enabled_bool else "Opt-in local capture off"

    @property
    def training_capture_summary(self) -> str:
        if self.training_capture_enabled_bool:
            return "Structured QA/code examples are being captured locally for future tuning export."
        return "Structured tuning capture is off; saved sessions can still be exported manually."

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
