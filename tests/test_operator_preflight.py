from pathlib import Path

from app.config import Settings
from app.db import init_db
from app.models.schemas import RuntimeCapabilities
from app.services.operator_preflight import build_operator_preflight
from app.services.semantic import SQLiteSemanticIndex
from app.services.work_queue import LocalWorkQueue


class ReadyLLMProvider:
    backend_name = "ollama"
    runtime_label = "Ollama local runtime"
    model_name = "gemma4:e4b"

    def health_check(self) -> tuple[bool, str]:
        return True, "Ready with `gemma4:e4b`."

    def describe_runtime(self) -> str:
        return "Ollama local runtime (gemma4:e4b)"

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


class MissingEmbeddingProvider:
    model_name = "embeddinggemma"

    def is_available(self) -> bool:
        return False

    def unavailable_reason(self) -> str:
        return "embeddinggemma is not installed"

    def health_status(self) -> tuple[str, str]:
        return "model_not_installed", "embeddinggemma is not installed"

    def describe(self) -> str:
        return "stub-semantic"

    def embed_texts(self, texts):
        return []


class StubOCRBackend:
    def is_available(self) -> bool:
        return False

    def describe(self) -> str:
        return "stub-ocr"


def test_operator_preflight_reports_attention_when_semantic_is_missing(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        deployment_mode="school-box-shared",
        class_space="biology-lab",
        retrieval_mode="hybrid",
    )
    settings.ensure_directories()
    init_db(settings.db_path)
    semantic_index = SQLiteSemanticIndex(
        db_path=settings.db_path,
        embedding_provider=MissingEmbeddingProvider(),
        class_space=settings.class_space,
    )

    report = build_operator_preflight(
        settings,
        llm_provider=ReadyLLMProvider(),
        semantic_index=semantic_index,
        ocr_backend=StubOCRBackend(),
        work_queue=LocalWorkQueue(max_concurrent_jobs=1),
    )

    assert report["overall_status"] == "blocked"
    assert report["dataset_counts"]["documents"] == 0
    assert any(check["label"] == "EmbeddingGemma model" for check in report["checks"])
    assert report["runtime_capabilities"].backend_name == "ollama"
