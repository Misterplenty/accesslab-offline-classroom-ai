from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.config import Settings
from app.services.judge_demo import DEMO_CLASS_SPACE, dump_demo_summary, seed_judge_demo


def _display_path(path: Path) -> str:
    try:
        return f"<workspace>/{path.relative_to(ROOT)}"
    except ValueError:
        return "<local-data-dir>"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed a deterministic AccessLab judge demo.")
    parser.add_argument("--data-dir", default=str(ROOT / "data" / "judge-demo"))
    parser.add_argument("--class-space", default=DEMO_CLASS_SPACE)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--output-json",
        default=str(ROOT / "reports" / "judge_demo_seed_latest.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir).expanduser().resolve()
    if args.reset and data_dir.exists():
        shutil.rmtree(data_dir)

    settings = Settings(
        data_dir=data_dir,
        deployment_mode="school-box-shared",
        class_space=args.class_space,
        training_capture_enabled="on",
    )
    summary = seed_judge_demo(settings, class_space=args.class_space)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_dir": _display_path(data_dir),
        "base_url": args.base_url.rstrip("/"),
        **summary,
    }

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print("Judge demo seeded.")
    print(f"Data dir: {_display_path(data_dir)}")
    print(f"Workspace: {args.base_url.rstrip('/')}/")
    print(f"Judge demo: {args.base_url.rstrip('/')}/judge-demo")
    print(f"Saved answer: {args.base_url.rstrip('/')}{summary['qa_url']}")
    print(f"Source inspection: {args.base_url.rstrip('/')}{summary['source_url']}")
    print(f"Code tutor: {args.base_url.rstrip('/')}{summary['code_url']}")
    print(f"Proof dashboard: {args.base_url.rstrip('/')}{summary['proofs_url']}")
    print(f"Seed manifest: {output_path.relative_to(ROOT)}")
    print(dump_demo_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
