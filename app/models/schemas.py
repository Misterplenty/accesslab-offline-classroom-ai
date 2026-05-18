from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SearchResult:
    chunk_id: str
    source_file: str
    page_number: int | None
    chunk_text: str
    snippet: str
    score: float
    match_source: str = "lexical"
    semantic_similarity: float | None = None


@dataclass(slots=True)
class Citation:
    label: str
    source_file: str
    page_number: int | None
    chunk_id: str
    snippet: str

    @property
    def display(self) -> str:
        location = self.source_file
        if self.page_number is not None:
            location = f"{location}, page {self.page_number}"
        return f"[{self.label}] {location} · {self.chunk_id}"


@dataclass(slots=True)
class SemanticAvailability:
    provider_ready: bool
    retrieval_ready: bool
    code: str
    label: str
    summary: str
    detail: str
    backend: str
    model_name: str
    model_family: str
    embeddinggemma_configured: bool = False


@dataclass(slots=True)
class SemanticIndexStatus:
    status: str
    label: str
    summary: str
    document_count: int
    chunk_count: int
    embedded_chunk_count: int
    missing_chunk_count: int
    last_error_code: str = ""
    last_error_message: str = ""
    last_attempted_at: str = ""
    last_completed_at: str = ""


@dataclass(slots=True)
class RetrievalDiagnostics:
    requested_mode: str
    requested_mode_label: str
    actual_mode: str
    actual_mode_label: str
    lexical_backend_label: str
    semantic: SemanticAvailability
    index_status: SemanticIndexStatus


@dataclass(slots=True)
class RuntimeCapabilities:
    backend_name: str
    runtime_label: str
    validation_stage: str
    supports_streaming: bool
    token_timings_available: bool
    model_listing_available: bool
    health_probe_shape: str
    semantic_dependency_shape: str
    supports_generation: bool = True
    validation_only: bool = False
    supports_health_probe: bool = True
    supported_profiles: tuple[str, ...] = field(default_factory=tuple)
    supports_model_listing: bool | None = None
    supports_token_timings: bool | None = None

    def __post_init__(self) -> None:
        if self.supports_model_listing is None:
            self.supports_model_listing = self.model_listing_available
        if self.supports_token_timings is None:
            self.supports_token_timings = self.token_timings_available


@dataclass(slots=True)
class ResponseProfile:
    # Wall-clock timings measured by AccessLab
    ttft_seconds: float | None = None
    retrieval_seconds: float = 0.0
    prompt_build_seconds: float = 0.0
    model_inference_seconds: float = 0.0
    post_processing_seconds: float = 0.0
    code_execution_seconds: float = 0.0
    patched_execution_seconds: float = 0.0
    total_seconds: float = 0.0
    prompt_characters: int = 0
    context_characters: int = 0
    response_characters: int = 0
    retrieved_chunks: int = 0
    # Ollama-native telemetry (from the final streamed chunk).
    # Durations are in seconds (Ollama reports nanoseconds; converted on capture).
    # None means the field was absent or not applicable for this request.
    load_duration_sec: float | None = None
    prompt_eval_duration_sec: float | None = None
    eval_duration_sec: float | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None
    retrieval_mode: str = "lexical"
    retrieval_mode_label: str = "Lexical only"
    semantic_status_code: str = ""
    semantic_index_status: str = ""
    queue_wait_seconds: float = 0.0
    peak_memory_mb: float | None = None


@dataclass(slots=True)
class IngestSummary:
    document_id: int
    file_name: str
    file_type: str
    chunks_created: int
    stored_path: str
    # OCR fallback bookkeeping (populated by DocumentIngestService when a
    # scanned PDF is detected). These fields default to values that mean
    # "no OCR was involved" so text-only PDFs and plain TXT/MD uploads
    # keep the original, unchanged summary shape.
    ocr_pages_applied: int = 0
    ocr_status: str = "not_needed"
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class QAResult:
    question: str
    short_answer: str
    more_detail: str
    citations: list[Citation] = field(default_factory=list)
    unsure: bool = False
    result_mode: str = "answered"
    history_id: int | None = None
    raw_response: str = ""
    profile: ResponseProfile | None = None
    retrieval_mode: str = "lexical"
    retrieval_mode_label: str = "Lexical only"


@dataclass(slots=True)
class ExecutionResult:
    status: str
    return_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    command: list[str]
    mode: str
    effective_test_code: str | None = None
    used_generated_tests: bool = False
    working_directory: str | None = None
    sandbox_profile: str = "none"
    sandbox_note: str = ""
    denied_by_policy: bool = False

    @property
    def passed(self) -> bool:
        return self.status == "completed" and not self.timed_out and self.return_code == 0

    @property
    def combined_output(self) -> str:
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout.strip())
        if self.stderr.strip():
            parts.append(self.stderr.strip())
        return "\n\n".join(parts)


@dataclass(slots=True)
class CodeTutorResult:
    diagnosis: str
    evidence: str
    next_fix: str
    patched_code: str
    why_it_works: str
    initial_run: ExecutionResult
    patched_run: ExecutionResult
    result_mode: str = "completed"
    session_id: int | None = None
    raw_response: str = ""
    profile: ResponseProfile | None = None
