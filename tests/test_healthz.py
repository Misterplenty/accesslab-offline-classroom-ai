from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import init_db
from app.models.schemas import RuntimeCapabilities
from app.main import app
from app.services.semantic import SQLiteSemanticIndex
from app.services.work_queue import LocalWorkQueue


class StubLLMProvider:
    backend_name = "ollama"
    runtime_label = "Ollama local runtime"
    model_name = "gemma4:e4b"

    def health_check(self) -> tuple[bool, str]:
        return False, "Gemma 4 not started."

    def describe_runtime(self) -> str:
        return "stub-runtime"

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


class StubOCRBackend:
    def is_available(self) -> bool:
        return False

    def describe(self) -> str:
        return "stub-ocr"


class StubEmbeddingProvider:
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


def test_healthz_reports_school_box_and_semantic_diagnostics(monkeypatch, tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        deployment_mode="school-box-shared",
        class_space="biology-lab",
        retrieval_mode="hybrid",
    )
    settings.ensure_directories()
    init_db(settings.db_path)

    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.main.create_generation_provider",
        lambda **kwargs: StubLLMProvider(),
    )

    app.state.semantic_index = SQLiteSemanticIndex(
        db_path=settings.db_path,
        embedding_provider=StubEmbeddingProvider(),
    )
    app.state.ocr_backend = StubOCRBackend()
    app.state.work_queue = LocalWorkQueue(max_concurrent_jobs=1)

    client = TestClient(app)
    response = client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deployment_mode"] == "school-box-shared"
    assert payload["class_space"] == "biology-lab"
    assert payload["semantic_status_code"] == "model_not_installed"
    assert payload["retrieval_mode"] == "lexical"
    assert payload["queue"]["max_concurrent_jobs"] == 1
    assert payload["runtime_capabilities"]["backend_name"] == "ollama"
    assert payload["preflight"]["overall_status"] == "blocked"
