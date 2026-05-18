from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRESETS_PATH = ROOT / "evals" / "benchmark_presets.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a named AccessLab deployment benchmark preset.")
    parser.add_argument("--preset", required=True)
    parser.add_argument("--device-label", default="local-benchmark")
    parser.add_argument("--device-tier", default="")
    parser.add_argument("--cold-warm", default="warm", choices=["cold", "warm"])
    parser.add_argument("--run-label", default="")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_presets() -> dict[str, Any]:
    return json.loads(PRESETS_PATH.read_text(encoding="utf-8"))


def build_command(args: argparse.Namespace, preset: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    kind = preset["kind"]
    env = os.environ.copy()
    env.update({str(k): str(v) for k, v in preset.get("env", {}).items()})
    device_tier = args.device_tier or preset.get("device_tier", "standard-laptop")
    run_label = args.run_label or f"preset-{preset['id']}"

    if kind == "eval":
        command = [
            sys.executable,
            str(ROOT / "scripts" / "run_accesslab_eval.py"),
            "--device-label",
            args.device_label,
            "--device-tier",
            str(device_tier),
            "--run-label",
            run_label,
            "--cold-warm",
            args.cold_warm,
            "--model",
            str(preset["model"]),
            "--retrieval-mode",
            str(preset["retrieval_mode"]),
        ]
        if preset.get("categories"):
            command.extend(["--categories", str(preset["categories"])])
        if preset.get("deployment_mode"):
            command.extend(["--deployment-mode", str(preset["deployment_mode"])])
        return command, env

    if kind == "school_box_load":
        return (
            [
                sys.executable,
                str(ROOT / "scripts" / "run_school_box_load.py"),
                "--device-label",
                args.device_label,
                "--device-tier",
                str(device_tier),
                "--jobs",
                str(preset.get("jobs", 12)),
                "--max-concurrent-jobs",
                str(preset.get("max_concurrent_jobs", 1)),
            ],
            env,
        )

    if kind == "a11y_smoke":
        return ([sys.executable, str(ROOT / "scripts" / "run_accesslab_a11y_smoke.py")], env)

    raise SystemExit(f"Unsupported preset kind: {kind}")


def main() -> None:
    args = parse_args()
    preset_bundle = load_presets()
    presets = {preset["id"]: preset for preset in preset_bundle["presets"]}
    if args.preset not in presets:
        available = ", ".join(sorted(presets))
        raise SystemExit(f"Unknown preset `{args.preset}`. Available presets: {available}")
    preset = presets[args.preset]
    command, env = build_command(args, preset)
    if args.dry_run:
        print(" ".join(command))
        if preset.get("env"):
            print(json.dumps(preset["env"], indent=2))
        return
    subprocess.run(command, cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
