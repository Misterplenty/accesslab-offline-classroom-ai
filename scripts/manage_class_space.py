from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.config import get_settings
from app.db import apply_class_space_migration, init_db, preview_class_space_migration


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Preview or apply a conservative AccessLab class-space reassignment."
    )
    parser.add_argument("--from", dest="from_class_space", required=True)
    parser.add_argument("--to", dest="to_class_space", required=True)
    parser.add_argument(
        "--db-path",
        default=str(settings.db_path),
        help=f"SQLite database path (default: {settings.db_path})",
    )
    parser.add_argument(
        "--include-sessions",
        action="store_true",
        help="Also reassign saved QA/code sessions and their local review labels.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually apply the reassignment. Without this flag the command stays in dry-run preview mode.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the preview or apply result as JSON.",
    )
    return parser.parse_args()


def _print_human(summary: dict) -> None:
    mode = "APPLY" if summary.get("applied") else "DRY RUN"
    print(f"AccessLab class-space migration [{mode}]")
    print(f"  from: {summary['from_class_space']}")
    print(f"  to:   {summary['to_class_space']}")
    print(f"  include_sessions: {summary['include_sessions']}")
    print("")
    print("Affected rows / scope:")
    for key, value in summary["counts"].items():
        print(f"  - {key}: {value}")
    print("")
    print("Warnings:")
    for warning in summary["warnings"]:
        print(f"  - {warning}")
    if not summary.get("applied"):
        print("")
        print("No changes were written. Re-run with --apply after reviewing the preview.")


def main() -> None:
    args = parse_args()
    db_path = Path(args.db_path)
    init_db(db_path)

    summary = (
        apply_class_space_migration(
            db_path,
            from_class_space=args.from_class_space,
            to_class_space=args.to_class_space,
            include_sessions=args.include_sessions,
        )
        if args.apply
        else preview_class_space_migration(
            db_path,
            from_class_space=args.from_class_space,
            to_class_space=args.to_class_space,
            include_sessions=args.include_sessions,
        )
    )

    if args.json:
        print(json.dumps(summary, indent=2))
        return
    _print_human(summary)


if __name__ == "__main__":
    main()
