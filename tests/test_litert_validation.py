from __future__ import annotations

import sys
from pathlib import Path

from app.services.llm import LiteRTLMValidationProvider


def test_litert_validation_provider_fails_closed_without_command():
    provider = LiteRTLMValidationProvider(model_name="gemma4:e4b", command="")

    ready, message = provider.health_check()
    capabilities = provider.capabilities()

    assert ready is False
    assert "ACCESSLAB_LITERT_LM_COMMAND" in message
    assert capabilities.validation_only is True
    assert capabilities.supports_generation is False
    assert capabilities.supports_health_probe is True


def test_litert_validation_provider_runs_executable_contract(tmp_path: Path):
    adapter = tmp_path / "adapter.py"
    adapter.write_text(
        "\n".join(
            [
                "import json, sys",
                "payload = json.loads(sys.stdin.read())",
                "print(json.dumps({'response': 'validated ' + payload['profile']}))",
            ]
        ),
        encoding="utf-8",
    )

    provider = LiteRTLMValidationProvider(
        model_name="gemma4:e4b",
        command=f"{sys.executable} {adapter}",
        profile="grounded-qa-smoke",
    )

    ready, message = provider.health_check()
    answer = provider.generate_answer("Prompt", "Context")

    assert ready is True
    assert "validation-only" in message
    assert answer == "validated grounded-qa-smoke"
    assert provider.capabilities().supports_generation is True
