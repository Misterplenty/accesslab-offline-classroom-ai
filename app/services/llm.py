from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from time import perf_counter
from typing import Iterator, Protocol

import requests

from app.models.schemas import RuntimeCapabilities
from app.services.ollama_runtime import build_missing_model_store_hint


class LLMError(RuntimeError):
    """Raised when the local model provider cannot satisfy a request."""


GENERATION_MODEL_FAMILY = "Gemma 4"
ALLOWED_GEMMA4_MODELS = frozenset({"gemma4:e2b", "gemma4:e4b"})
DEFAULT_RUNTIME_BACKEND = "ollama"
LITERT_LM_VALIDATION_BACKEND = "litert-lm-validation"
LITERT_LM_COMMAND_ENV = "ACCESSLAB_LITERT_LM_COMMAND"
LITERT_LM_PROFILE_ENV = "ACCESSLAB_LITERT_LM_PROFILE"
KNOWN_RUNTIME_BACKENDS = frozenset({DEFAULT_RUNTIME_BACKEND, LITERT_LM_VALIDATION_BACKEND})
RUNTIME_BACKEND_LABELS = {
    "ollama": "Ollama local runtime",
    LITERT_LM_VALIDATION_BACKEND: "LiteRT-LM validation scaffold",
}
FUTURE_RUNTIME_VALIDATION_TRACK = "LiteRT-LM / mobile-edge validation path"
LLM_TIMEOUT_SECONDS_ENV = "ACCESSLAB_LLM_TIMEOUT_SECONDS"


def _resolve_timeout_seconds(default: int) -> int:
    raw = os.getenv(LLM_TIMEOUT_SECONDS_ENV, "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            return default
    return default


def list_ollama_model_names(base_url: str, *, timeout_seconds: float = 1.0) -> tuple[list[str], str]:
    """Return locally visible Ollama model names plus a human-readable status."""
    resolved_url = (base_url or "http://127.0.0.1:11434").rstrip("/")
    try:
        response = requests.get(f"{resolved_url}/api/tags", timeout=timeout_seconds)
        response.raise_for_status()
    except requests.RequestException as exc:
        return [], f"Ollama model listing unavailable: {exc.__class__.__name__}."

    models = response.json().get("models", [])
    names = sorted(
        str(model.get("name", "")).strip()
        for model in models
        if isinstance(model, dict) and str(model.get("name", "")).strip()
    )
    return names, f"{len(names)} local model(s) visible from {resolved_url}."


class LLMProvider(Protocol):
    backend_name: str
    runtime_label: str
    model_family: str
    model_name: str

    def generate_answer(self, prompt: str, context: str, settings: dict | None = None) -> str:
        ...

    def stream_answer(self, prompt: str, context: str, settings: dict | None = None) -> Iterator[str]:
        ...

    def health_check(self) -> tuple[bool, str]:
        ...

    def describe_runtime(self) -> str:
        ...

    def capabilities(self) -> RuntimeCapabilities:
        ...


_NS_TO_SEC = 1e-9


@dataclass(slots=True)
class LLMGenerationTrace:
    text: str
    ttft_seconds: float | None
    total_seconds: float
    # Ollama-native timing and token fields (from the final streamed chunk).
    # All durations are converted from Ollama nanoseconds to seconds.
    # None means the field was not present in the response.
    load_duration_sec: float | None = None
    prompt_eval_duration_sec: float | None = None
    eval_duration_sec: float | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None


class OllamaProvider:
    backend_name = "ollama"
    runtime_label = RUNTIME_BACKEND_LABELS["ollama"]
    model_family = GENERATION_MODEL_FAMILY

    def __init__(self, *, base_url: str, model_name: str, timeout_seconds: int = 90) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout_seconds = _resolve_timeout_seconds(timeout_seconds)

    def describe_runtime(self) -> str:
        return f"{self.runtime_label} ({self.model_name})"

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            backend_name=self.backend_name,
            runtime_label=self.runtime_label,
            validation_stage="current",
            supports_generation=True,
            supports_streaming=True,
            token_timings_available=True,
            model_listing_available=True,
            health_probe_shape="GET /api/tags plus model-present check",
            semantic_dependency_shape="EmbeddingGemma uses the same Ollama host via /api/embed.",
            validation_only=False,
            supports_health_probe=True,
            supported_profiles=("grounded-qa", "beginner-python-repair", "accessibility-smoke"),
        )

    def _build_prompt(self, prompt: str, context: str) -> str:
        return f"{prompt.strip()}\n\nContext:\n{context.strip()}\n"

    def generate_answer(self, prompt: str, context: str, settings: dict | None = None) -> str:
        payload = {
            "model": self.model_name,
            "prompt": self._build_prompt(prompt, context),
            "stream": False,
            "options": settings or {},
        }
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LLMError(
                "Ollama is unavailable. Start it with `ollama serve` and pull a local model before retrying."
            ) from exc

        body = response.json()
        if "response" not in body:
            raise LLMError("Ollama returned an unexpected response.")
        return str(body["response"]).strip()

    def measure_answer(self, prompt: str, context: str, settings: dict | None = None) -> LLMGenerationTrace:
        """Stream a response and return timing, token counts, and text.

        Captures Ollama's native timing fields from the final streamed chunk
        (load_duration, prompt_eval_duration, eval_duration and token counts).
        These are separate from the wall-clock TTFT measured here.
        """
        start = perf_counter()
        ttft_seconds: float | None = None
        chunks: list[str] = []
        final_event: dict = {}

        for chunk_text, event in self._stream_events(prompt, context, settings=settings):
            if chunk_text:
                if ttft_seconds is None:
                    ttft_seconds = perf_counter() - start
                chunks.append(chunk_text)
            if event.get("done"):
                final_event = event

        def _ns(key: str) -> float | None:
            val = final_event.get(key)
            return round(val * _NS_TO_SEC, 6) if isinstance(val, (int, float)) else None

        def _int(key: str) -> int | None:
            val = final_event.get(key)
            return int(val) if isinstance(val, (int, float)) else None

        return LLMGenerationTrace(
            text="".join(chunks).strip(),
            ttft_seconds=ttft_seconds,
            total_seconds=perf_counter() - start,
            load_duration_sec=_ns("load_duration"),
            prompt_eval_duration_sec=_ns("prompt_eval_duration"),
            eval_duration_sec=_ns("eval_duration"),
            prompt_eval_count=_int("prompt_eval_count"),
            eval_count=_int("eval_count"),
        )

    def stream_answer(self, prompt: str, context: str, settings: dict | None = None) -> Iterator[str]:
        """Yield response text chunks. Discards final-chunk metadata."""
        for chunk_text, _ in self._stream_events(prompt, context, settings=settings):
            if chunk_text:
                yield chunk_text

    def _stream_events(
        self, prompt: str, context: str, settings: dict | None = None
    ) -> Iterator[tuple[str, dict]]:
        """Yield (chunk_text, raw_event) pairs for every streamed event.

        For non-done events chunk_text is the response token(s); for the final
        done=true event chunk_text is empty and raw_event contains the timing
        and token-count fields returned by Ollama.
        """
        payload = {
            "model": self.model_name,
            "prompt": self._build_prompt(prompt, context),
            "stream": True,
            "options": settings or {},
        }
        try:
            with requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                stream=True,
                timeout=self.timeout_seconds,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        event = json.loads(line.decode("utf-8", errors="ignore"))
                    except json.JSONDecodeError:
                        continue

                    if event.get("error"):
                        raise LLMError(str(event["error"]))

                    chunk_text = str(event.get("response", ""))
                    yield chunk_text, event
        except requests.RequestException as exc:
            raise LLMError(
                "Ollama streaming is unavailable. Start `ollama serve` and verify the model is installed."
            ) from exc

    def health_check(self) -> tuple[bool, str]:
        if self.model_name not in ALLOWED_GEMMA4_MODELS:
            allowed = ", ".join(sorted(ALLOWED_GEMMA4_MODELS))
            return (
                False,
                f"AccessLab keeps user-facing generation on {GENERATION_MODEL_FAMILY} only. "
                f"Choose one of: {allowed}.",
            )
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()
        except requests.RequestException:
            return False, "Ollama is not responding. Run `ollama serve` and configure one of the supported local Gemma 4 models."

        models = response.json().get("models", [])
        installed = {model.get("name", "") for model in models}
        if self.model_name not in installed:
            extra_hint = build_missing_model_store_hint(self.model_name)
            if extra_hint:
                return (
                    False,
                    f"Ollama is running, but model `{self.model_name}` is not installed in the active store. "
                    f"{extra_hint}",
                )
            return (
                False,
                f"Ollama is running, but model `{self.model_name}` is not installed. Run `ollama pull {self.model_name}`.",
            )
        return True, f"Ready with `{self.model_name}`."


class LiteRTLMValidationProvider:
    backend_name = LITERT_LM_VALIDATION_BACKEND
    runtime_label = RUNTIME_BACKEND_LABELS[LITERT_LM_VALIDATION_BACKEND]
    model_family = GENERATION_MODEL_FAMILY

    def __init__(
        self,
        *,
        model_name: str,
        command: str | None = None,
        profile: str | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        self.model_name = model_name
        self.command = (command if command is not None else os.getenv(LITERT_LM_COMMAND_ENV, "")).strip()
        self.profile = (
            profile if profile is not None else os.getenv(LITERT_LM_PROFILE_ENV, "grounded-qa-smoke")
        ).strip()
        self.timeout_seconds = _resolve_timeout_seconds(max(1, int(timeout_seconds)))

    def describe_runtime(self) -> str:
        return f"{self.runtime_label} ({self.model_name})"

    def capabilities(self) -> RuntimeCapabilities:
        command_configured = bool(self.command)
        return RuntimeCapabilities(
            backend_name=self.backend_name,
            runtime_label=self.runtime_label,
            validation_stage="experimental-validation",
            supports_generation=command_configured,
            supports_streaming=False,
            token_timings_available=False,
            model_listing_available=False,
            health_probe_shape=(
                f"Executable command contract via {LITERT_LM_COMMAND_ENV}."
                if command_configured
                else f"No command configured. Set {LITERT_LM_COMMAND_ENV} for an executable validation probe."
            ),
            semantic_dependency_shape=(
                "LiteRT-LM validation covers generation only. EmbeddingGemma remains the default local "
                "semantic retrieval dependency unless a separate edge embedding path is validated."
            ),
            validation_only=True,
            supports_health_probe=True,
            supported_profiles=(self.profile,),
        )

    def generate_answer(self, prompt: str, context: str, settings: dict | None = None) -> str:
        if not self.command:
            raise LLMError(
                "LiteRT-LM validation has no executable command configured. Set "
                f"{LITERT_LM_COMMAND_ENV} for the validation harness, or switch ACCESSLAB_RUNTIME_BACKEND "
                "back to `ollama` for the working local Gemma 4 runtime."
            )
        payload = {
            "model": self.model_name,
            "profile": self.profile,
            "prompt": prompt,
            "context": context,
            "settings": settings or {},
        }
        try:
            completed = subprocess.run(
                shlex.split(self.command),
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise LLMError(f"LiteRT-LM validation command failed to start: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
            raise LLMError(f"LiteRT-LM validation command failed: {detail}")
        output = completed.stdout.strip()
        if not output:
            raise LLMError("LiteRT-LM validation command returned no output.")
        try:
            body = json.loads(output)
        except json.JSONDecodeError:
            return output
        response = body.get("response") or body.get("text") or body.get("answer")
        if not isinstance(response, str) or not response.strip():
            raise LLMError("LiteRT-LM validation command did not return a response/text/answer field.")
        return response.strip()

    def measure_answer(self, prompt: str, context: str, settings: dict | None = None) -> LLMGenerationTrace:
        start = perf_counter()
        text = self.generate_answer(prompt, context, settings=settings)
        total = perf_counter() - start
        return LLMGenerationTrace(
            text=text,
            ttft_seconds=total,
            total_seconds=total,
        )

    def stream_answer(self, prompt: str, context: str, settings: dict | None = None) -> Iterator[str]:
        raise LLMError(
            "LiteRT-LM streaming is not implemented in this validation path. Use the non-streaming validation harness."
        )

    def health_check(self) -> tuple[bool, str]:
        if self.model_name not in ALLOWED_GEMMA4_MODELS:
            allowed = ", ".join(sorted(ALLOWED_GEMMA4_MODELS))
            return (
                False,
                f"AccessLab keeps user-facing generation on {GENERATION_MODEL_FAMILY} only. Choose one of: {allowed}.",
            )
        if not self.command:
            return (
                False,
                f"LiteRT-LM validation is configured but no executable probe is set. Set {LITERT_LM_COMMAND_ENV}.",
            )
        command_parts = shlex.split(self.command)
        if not command_parts:
            return False, f"{LITERT_LM_COMMAND_ENV} is empty."
        executable = command_parts[0]
        if shutil.which(executable) is None and not os.path.exists(executable):
            return False, f"LiteRT-LM validation command `{executable}` was not found on this device."
        return (
            True,
            f"LiteRT-LM validation command is configured for `{self.profile}`. This is validation-only, not the default runtime.",
        )


def create_generation_provider(
    *,
    runtime_backend: str,
    base_url: str,
    model_name: str,
    timeout_seconds: int = 90,
) -> LLMProvider:
    normalized_backend = (runtime_backend or DEFAULT_RUNTIME_BACKEND).strip().lower()
    if normalized_backend == "ollama":
        return OllamaProvider(
            base_url=base_url,
            model_name=model_name,
            timeout_seconds=timeout_seconds,
        )
    if normalized_backend == LITERT_LM_VALIDATION_BACKEND:
        return LiteRTLMValidationProvider(model_name=model_name, timeout_seconds=timeout_seconds)
    return OllamaProvider(
        base_url=base_url,
        model_name=model_name,
        timeout_seconds=timeout_seconds,
    )
