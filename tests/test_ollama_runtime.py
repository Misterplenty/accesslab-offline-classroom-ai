from __future__ import annotations

from pathlib import Path

from app.services.llm import OllamaProvider
from app.services.ollama_runtime import build_missing_model_store_hint
from app.services.semantic import OllamaEmbeddingProvider


class _StubTagsResponse:
    def __init__(self, models: list[dict[str, str]] | None = None) -> None:
        self._models = models or []

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"models": self._models}


def _make_manifest(models_root: Path, *parts: str) -> Path:
    manifest = models_root / "manifests" / Path(*parts)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("{}", encoding="utf-8")
    return manifest


def test_build_missing_model_store_hint_recommends_home_and_models_root(tmp_path: Path):
    real_home = tmp_path / "real-home"
    models_root = real_home / ".ollama" / "models"
    _make_manifest(models_root, "registry.ollama.ai", "library", "gemma4", "e4b")

    message = build_missing_model_store_hint(
        "gemma4:e4b",
        candidate_roots=[models_root],
        current_home=tmp_path / "sandbox-home",
    )

    assert message is not None
    assert f"HOME={real_home}" in message
    assert f"OLLAMA_MODELS={models_root}" in message
    assert "Current HOME" in message


def test_build_missing_model_store_hint_finds_latest_tag_manifest(tmp_path: Path):
    home_dir = tmp_path / "operator-home"
    models_root = home_dir / ".ollama" / "models"
    _make_manifest(models_root, "registry.ollama.ai", "library", "embeddinggemma", "latest")

    message = build_missing_model_store_hint(
        "embeddinggemma",
        candidate_roots=[models_root],
        current_home=home_dir,
    )

    assert message is not None
    assert "embeddinggemma" in message
    assert f"OLLAMA_MODELS={models_root}" in message
    assert "Current HOME" not in message


def test_llm_health_check_reports_active_store_hint(monkeypatch):
    monkeypatch.setattr("app.services.llm.requests.get", lambda *args, **kwargs: _StubTagsResponse([]))
    monkeypatch.setattr(
        "app.services.llm.build_missing_model_store_hint",
        lambda model_name: "I found it in `/Users/tedi/.ollama/models`. Restart Ollama with `HOME=/Users/tedi OLLAMA_MODELS=/Users/tedi/.ollama/models ollama serve`.",
    )

    provider = OllamaProvider(base_url="http://127.0.0.1:11434", model_name="gemma4:e4b")
    ready, message = provider.health_check()

    assert ready is False
    assert "not installed in the active store" in message
    assert "HOME=/Users/tedi" in message


def test_semantic_health_check_reports_active_store_hint(monkeypatch):
    monkeypatch.setattr("app.services.semantic.requests.get", lambda *args, **kwargs: _StubTagsResponse([]))
    monkeypatch.setattr(
        "app.services.semantic.build_missing_model_store_hint",
        lambda model_name: "I found it in `/Users/tedi/.ollama/models`. Restart Ollama with `HOME=/Users/tedi OLLAMA_MODELS=/Users/tedi/.ollama/models ollama serve`.",
    )

    provider = OllamaEmbeddingProvider(
        base_url="http://127.0.0.1:11434",
        model_name="embeddinggemma",
    )
    ok, _code, message = provider._health()

    assert ok is False
    assert "embedding model `embeddinggemma` is not installed in the active store" in message
    assert "OLLAMA_MODELS=/Users/tedi/.ollama/models" in message
