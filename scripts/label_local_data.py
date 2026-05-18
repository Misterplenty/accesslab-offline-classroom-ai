from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.config import get_settings
from app.db import (
    get_code_session_entry,
    get_qa_history_entry,
    init_db,
    save_session_label,
)
from app.services.session_review import KNOWN_SESSION_LABELS


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Attach a lightweight local quality label to a saved QA or code session."
    )
    parser.add_argument("--source-type", choices=["qa", "code"], required=True)
    parser.add_argument("--id", type=int, required=True, help="Saved QA or code session ID.")
    parser.add_argument("--label", required=True, choices=sorted(KNOWN_SESSION_LABELS))
    parser.add_argument("--note", default="", help="Optional short local note.")
    parser.add_argument("--actor-role", default="teacher", choices=["teacher", "admin"])
    parser.add_argument("--actor-key", default="local-operator")
    parser.add_argument("--db-path", default=str(settings.db_path))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db_path)
    init_db(db_path)

    if args.source_type == "qa":
        entry = get_qa_history_entry(db_path, args.id)
    else:
        entry = get_code_session_entry(db_path, args.id)
    if entry is None:
        raise SystemExit(f"No saved {args.source_type} session exists with id={args.id}.")

    label_id = save_session_label(
        db_path,
        source_type=args.source_type,
        source_id=args.id,
        label=args.label,
        note=args.note,
        actor_role=args.actor_role,
        actor_key=args.actor_key,
        class_space=str(entry.get("class_space", "default-classroom")),
    )
    print(
        f"Saved label #{label_id}: {args.source_type} #{args.id} -> {args.label}"
    )


if __name__ == "__main__":
    main()
