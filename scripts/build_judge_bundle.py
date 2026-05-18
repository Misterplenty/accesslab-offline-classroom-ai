from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


DEFAULT_ARTIFACTS = {
    "readme": ROOT / "README.md",
    "benchmark_summary": ROOT / "reports" / "accesslab_benchmark_summary.md",
    "benchmark_bundle": ROOT / "reports" / "accesslab_benchmark_bundle.json",
    "accessibility_smoke": ROOT / "reports" / "a11y_smoke_latest.md",
    "accessibility_smoke_json": ROOT / "reports" / "a11y_smoke_latest.json",
    "operator_preflight": ROOT / "reports" / "operator_preflight_latest.md",
    "system_snapshot": ROOT / "reports" / "system_status_snapshot_latest.json",
    "deployment_snapshot": ROOT / "reports" / "deployment_mode_snapshot_latest.md",
    "embeddinggemma_setup": ROOT / "reports" / "embeddinggemma_setup_latest.md",
    "embeddinggemma_setup_json": ROOT / "reports" / "embeddinggemma_setup_latest.json",
    "semantic_retrieval_proof": ROOT / "reports" / "semantic_retrieval_proof_latest.md",
    "semantic_retrieval_proof_json": ROOT / "reports" / "semantic_retrieval_proof_latest.json",
    "school_box_load": ROOT / "reports" / "school_box_load_latest.md",
    "school_box_load_json": ROOT / "reports" / "school_box_load_latest.json",
    "school_box_demo_proof": ROOT / "reports" / "school_box_demo_proof_latest.md",
    "school_box_demo_proof_json": ROOT / "reports" / "school_box_demo_proof_latest.json",
    "semantic_retrieval": ROOT / "docs" / "semantic_retrieval.md",
    "demo_runbook": ROOT / "reports" / "demo_runbook_latest.md",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble stable judge-facing AccessLab proof artifacts.")
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "judge" / "latest"))
    return parser.parse_args()


def ensure_latest_artifacts() -> None:
    source_runbook = ROOT / "docs" / "demo_runbook.md"
    latest_runbook = ROOT / "reports" / "demo_runbook_latest.md"
    if source_runbook.exists():
        latest_runbook.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_runbook, latest_runbook)


def git_commit_hash() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    if completed.returncode != 0:
        return "unavailable-no-git-repository"
    return completed.stdout.strip() or "unavailable"


def hardware_summary() -> dict[str, str]:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
    }


def _copy_artifact(name: str, source: Path, output_dir: Path) -> dict[str, Any]:
    if not source.exists():
        return {"name": name, "source": str(source.relative_to(ROOT)), "included": False, "output": ""}
    suffix = "".join(source.suffixes) or ".txt"
    target = output_dir / f"{name}{suffix}"
    shutil.copy2(source, target)
    return {
        "name": name,
        "source": str(source.relative_to(ROOT)),
        "included": True,
        "output": str(target.relative_to(ROOT)),
    }


def build_index(
    rows: list[dict[str, Any]],
    generated_at: str,
    *,
    commit_hash: str,
    hardware: dict[str, str],
) -> str:
    included = sum(1 for row in rows if row["included"])
    missing = len(rows) - included
    lines = [
        "# AccessLab Judge Proof Bundle",
        "",
        f"- Generated at: {generated_at}",
        f"- Commit hash: `{commit_hash}`",
        f"- Hardware: {hardware['platform']} / {hardware['machine']}",
        f"- Artifact summary: {included} included, {missing} missing",
        "- Scope: local-first grounded QA, verified beginner Python repair, Ollama runtime proof, school-box load, and accessibility artifacts.",
        "- Product thesis: Gemma 4 answers from local classroom materials with visible citations and repairs beginner Python through local run, minimal patch, and rerun.",
        "- Architecture summary: server-rendered FastAPI UI, local SQLite/FTS5 storage, optional EmbeddingGemma semantic index via local Ollama, Gemma 4 generation via local Ollama, local Python execution for the narrow repair loop, and local proof scripts.",
        "- Gemma 4 centrality: `gemma4:e4b` and `gemma4:e2b` are the only accepted user-facing generation models.",
        "- EmbeddingGemma centrality: `embeddinggemma` is the default semantic retrieval model; lexical fallback is reported when it is unavailable.",
        "",
        "## Included Artifacts",
        "",
        "| Artifact | Status | Stable File |",
        "| --- | --- | --- |",
    ]
    for row in rows:
        status = "included" if row["included"] else "missing"
        output = row["output"] or row["source"]
        lines.append(f"| {row['name']} | {status} | `{output}` |")
    lines.extend(
        [
            "",
            "## Five-Minute Review Path",
            "",
            "1. Read `readme.md` for the product shape and limitations.",
            "2. Read `semantic_retrieval_proof.md` and `embeddinggemma_setup.md` for retrieval evidence.",
            "3. Read `benchmark_summary.md` for measured runtime claims.",
            "4. Read `school_box_demo_proof.md` and `school_box_load.md` for the classroom/shared-host story.",
            "5. Read `accessibility_smoke.md` for the keyboard/focus/accessibility release-gate boundary.",
            "",
            "## Honest Limits",
            "",
            "- Gemma 4 remains the only user-facing reasoning model.",
            "- EmbeddingGemma remains the default semantic retrieval model.",
            "- No cloud fallback is included or claimed.",
            "- School-box load is local synthetic proof, not a production distributed queue claim.",
            "- Benchmark evidence applies only to the hardware and model setup actually recorded in local artifacts.",
            "- The beginner Python runner is a local demo runner, not a production secure sandbox.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    ensure_latest_artifacts()
    output_dir = Path(args.output_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [_copy_artifact(name, source, output_dir) for name, source in DEFAULT_ARTIFACTS.items()]
    generated_at = datetime.now(timezone.utc).isoformat()
    commit_hash = git_commit_hash()
    hardware = hardware_summary()
    included = sum(1 for row in rows if row["included"])
    missing = len(rows) - included
    manifest = {
        "generated_at": generated_at,
        "commit_hash": commit_hash,
        "model_names": ["gemma4:e4b", "gemma4:e2b", "embeddinggemma"],
        "hardware": hardware,
        "pass_fail_summary": {
            "included_artifacts": included,
            "missing_artifacts": missing,
            "status": "pass" if missing == 0 else "attention",
        },
        "output_dir": str(output_dir.relative_to(ROOT)),
        "artifacts": rows,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output_dir / "proof_index.md").write_text(
        build_index(rows, generated_at, commit_hash=commit_hash, hardware=hardware),
        encoding="utf-8",
    )
    print((output_dir / "proof_index.md").relative_to(ROOT))
    print((output_dir / "manifest.json").relative_to(ROOT))


if __name__ == "__main__":
    main()
