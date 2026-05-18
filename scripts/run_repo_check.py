from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 100 * 1024 * 1024
FORBIDDEN_DIR_NAMES = {".venv", "venv", "env", "__pycache__", ".pytest_cache"}
FORBIDDEN_FILE_NAMES = {".env"}
LOCAL_STATE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


def _is_under(path: Path, parent_name: str) -> bool:
    return any(part == parent_name for part in path.relative_to(ROOT).parts)


def main() -> int:
    problems: list[str] = []
    warnings: list[str] = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if ".git" in relative.parts:
            continue
        if path.is_dir():
            if path.name in FORBIDDEN_DIR_NAMES:
                problems.append(f"forbidden generated directory: {relative}")
            continue
        if path.name in FORBIDDEN_FILE_NAMES:
            problems.append(f"local secret/env file: {relative}")
        if path.stat().st_size > MAX_BYTES:
            problems.append(f"file over 100MB: {relative}")
        if _is_under(path, "data") and path.suffix.lower() in LOCAL_STATE_SUFFIXES:
            warnings.append(f"local database under data/: {relative}")
        if _is_under(path, "data") and "uploads" in relative.parts:
            warnings.append(f"generated upload under data/: {relative}")

    for message in warnings:
        print(f"warning: {message}")
    for message in problems:
        print(f"error: {message}")
    if problems:
        return 1
    print("repo-check passed: no huge files, local envs, or obvious generated cache directories found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
