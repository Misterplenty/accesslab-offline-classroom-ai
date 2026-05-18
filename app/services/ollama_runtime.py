from __future__ import annotations

import os
import pwd
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


DEFAULT_OLLAMA_REGISTRY = "registry.ollama.ai"
DEFAULT_OLLAMA_NAMESPACE = "library"


@dataclass(frozen=True, slots=True)
class LocalModelStoreMatch:
    model_name: str
    models_root: Path
    manifest_path: Path
    home_dir: Path | None


def build_missing_model_store_hint(
    model_name: str,
    *,
    candidate_roots: Sequence[Path] | None = None,
    current_home: Path | None = None,
) -> str | None:
    match = find_local_model_store(model_name, candidate_roots=candidate_roots)
    if match is None:
        return None

    resolved_home = current_home or Path.home()
    command_parts = []
    if match.home_dir is not None and match.home_dir != resolved_home:
        command_parts.append(f"HOME={match.home_dir}")
    command_parts.append(f"OLLAMA_MODELS={match.models_root}")
    command_parts.append("ollama serve")
    restart_command = " ".join(str(part) for part in command_parts)

    message = (
        f"I found `{model_name}` in the local Ollama store at `{match.models_root}`, "
        "so Ollama is likely serving a different model directory right now. "
        f"Restart it with `{restart_command}`."
    )
    if match.home_dir is not None and match.home_dir != resolved_home:
        message += f" Current HOME is `{resolved_home}`."
    return message


def find_local_model_store(
    model_name: str,
    *,
    candidate_roots: Sequence[Path] | None = None,
) -> LocalModelStoreMatch | None:
    normalized_model = (model_name or "").strip()
    if not normalized_model:
        return None

    for root in candidate_roots or discover_candidate_model_roots():
        manifest = _find_manifest_in_root(root, normalized_model)
        if manifest is None:
            continue
        return LocalModelStoreMatch(
            model_name=normalized_model,
            models_root=root,
            manifest_path=manifest,
            home_dir=_infer_home_dir(root),
        )
    return None


def discover_candidate_model_roots() -> list[Path]:
    candidates: list[Path] = []

    def add(path: Path | None) -> None:
        if path is None:
            return
        resolved = path.expanduser()
        if resolved in candidates:
            return
        candidates.append(resolved)

    env_models = (os.getenv("OLLAMA_MODELS") or "").strip()
    if env_models:
        add(Path(env_models))

    add(Path.home() / ".ollama" / "models")

    passwd_home = _passwd_home()
    if passwd_home is not None:
        add(passwd_home / ".ollama" / "models")

    user = (os.getenv("USER") or "").strip()
    if user:
        add(Path("/Users") / user / ".ollama" / "models")

    return candidates


def _find_manifest_in_root(models_root: Path, model_name: str) -> Path | None:
    if not models_root.exists():
        return None

    manifests_root = models_root / "manifests"
    if not manifests_root.exists():
        return None

    for relative_path in _candidate_manifest_paths(model_name):
        manifest_path = manifests_root / relative_path
        if manifest_path.exists():
            return manifest_path
    return None


def _candidate_manifest_paths(model_name: str) -> list[Path]:
    host, namespace_parts, repo, tag = _parse_model_reference(model_name)
    candidates = [
        Path(host, *namespace_parts, repo, tag),
    ]

    if host != DEFAULT_OLLAMA_REGISTRY:
        candidates.append(Path(DEFAULT_OLLAMA_REGISTRY, *namespace_parts, repo, tag))
    if namespace_parts != [DEFAULT_OLLAMA_NAMESPACE]:
        candidates.append(Path(host, DEFAULT_OLLAMA_NAMESPACE, repo, tag))
        if host != DEFAULT_OLLAMA_REGISTRY:
            candidates.append(Path(DEFAULT_OLLAMA_REGISTRY, DEFAULT_OLLAMA_NAMESPACE, repo, tag))
    return _dedupe_paths(candidates)


def _parse_model_reference(model_name: str) -> tuple[str, list[str], str, str]:
    reference = model_name.strip()
    path_part = reference
    tag = "latest"

    last_slash = reference.rfind("/")
    last_colon = reference.rfind(":")
    if last_colon > last_slash:
        path_part = reference[:last_colon]
        tag = reference[last_colon + 1 :] or "latest"

    pieces = [piece for piece in path_part.split("/") if piece]
    host = DEFAULT_OLLAMA_REGISTRY
    namespace_parts = [DEFAULT_OLLAMA_NAMESPACE]

    if not pieces:
        return host, namespace_parts, reference or "unknown", tag

    if _looks_like_host(pieces[0]):
        host = pieces.pop(0)

    if len(pieces) == 1:
        repo = pieces[0]
        return host, namespace_parts, repo, tag

    repo = pieces[-1]
    namespace_parts = pieces[:-1] or namespace_parts
    return host, namespace_parts, repo, tag


def _looks_like_host(value: str) -> bool:
    return "." in value or ":" in value or value == "localhost"


def _infer_home_dir(models_root: Path) -> Path | None:
    expanded = models_root.expanduser()
    parts = expanded.parts
    if len(parts) >= 3 and parts[-2:] == (".ollama", "models"):
        return expanded.parent.parent
    return None


def _passwd_home() -> Path | None:
    try:
        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (KeyError, OSError):
        return None


def _dedupe_paths(paths: Sequence[Path]) -> list[Path]:
    deduped: list[Path] = []
    for path in paths:
        if path not in deduped:
            deduped.append(path)
    return deduped
