from __future__ import annotations

import argparse
import os
import runpy
import sys
from pathlib import Path


POLICY_EXIT_CODE = 120
BOOTSTRAP_ERROR_EXIT_CODE = 121


class SandboxPolicyError(RuntimeError):
    """Raised when the runtime policy denies an operation."""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap AccessLab's local code runner policy.")
    parser.add_argument("--mode", choices=("script", "pytest"), required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--test-file", type=Path, default=None)
    parser.add_argument("--timeout-seconds", type=int, required=True)
    parser.add_argument("--policy-prefix", required=True)
    parser.add_argument("--error-prefix", required=True)
    parser.add_argument("--memory-limit-bytes", type=int, default=0)
    parser.add_argument("--file-size-limit-bytes", type=int, default=1_048_576)
    parser.add_argument("--open-file-limit", type=int, default=64)
    parser.add_argument("--process-limit", type=int, default=8)
    return parser.parse_args()


def _normalize_path(base_dir: Path, raw_path: object) -> Path | None:
    if isinstance(raw_path, int) or raw_path is None:
        return None
    candidate = os.fspath(raw_path)
    if isinstance(candidate, bytes):
        candidate = os.fsdecode(candidate)
    path = Path(candidate)
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def _is_within(base_dir: Path, raw_path: object) -> bool:
    normalized = _normalize_path(base_dir, raw_path)
    if normalized is None:
        return True
    try:
        normalized.relative_to(base_dir)
        return True
    except ValueError:
        return False


def _mode_requests_write(mode: object, flags: object) -> bool:
    mode_text = str(mode or "")
    if any(marker in mode_text for marker in ("w", "a", "x", "+")):
        return True

    if not isinstance(flags, int):
        return False

    write_flags = 0
    for flag_name in ("O_WRONLY", "O_RDWR", "O_APPEND", "O_CREAT", "O_TRUNC"):
        write_flags |= getattr(os, flag_name, 0)
    return bool(flags & write_flags)


def _deny(policy_prefix: str, message: str) -> None:
    print(f"{policy_prefix}{message}", file=sys.stderr, flush=True)
    raise SandboxPolicyError(message)


def _deny_path(policy_prefix: str, base_dir: Path, action: str, raw_path: object) -> None:
    normalized = _normalize_path(base_dir, raw_path)
    if normalized is not None and normalized == Path(os.devnull).resolve():
        return
    if _is_within(base_dir, raw_path):
        return
    display = str(normalized) if normalized is not None else str(raw_path)
    _deny(policy_prefix, f"Sandbox policy denied {action} outside the temporary execution directory: {display}")


def _install_runtime_policy(*, base_dir: Path, policy_prefix: str) -> None:
    def audit(event: str, args: tuple[object, ...]) -> None:
        if event == "open":
            path = args[0] if args else None
            mode = args[1] if len(args) > 1 else ""
            flags = args[2] if len(args) > 2 else 0
            if _mode_requests_write(mode, flags):
                _deny_path(policy_prefix, base_dir, "file write", path)
            return

        if event in {"os.mkdir", "os.remove", "os.rmdir", "os.unlink", "os.chmod", "os.chown", "os.utime"}:
            path = args[0] if args else None
            _deny_path(policy_prefix, base_dir, "filesystem mutation", path)
            return

        if event in {"os.rename", "os.replace"}:
            source = args[0] if args else None
            destination = args[1] if len(args) > 1 else None
            _deny_path(policy_prefix, base_dir, "filesystem mutation", source)
            _deny_path(policy_prefix, base_dir, "filesystem mutation", destination)
            return

        if event.startswith("socket."):
            _deny(policy_prefix, "Sandbox policy denied network access.")

        if event.startswith("subprocess.") or event in {
            "os.fork",
            "os.forkpty",
            "os.posix_spawn",
            "os.spawnv",
            "os.spawnve",
            "os.system",
            "pty.spawn",
        }:
            _deny(policy_prefix, "Sandbox policy denied child process creation.")

    sys.addaudithook(audit)


def _apply_posix_limits(
    *,
    timeout_seconds: int,
    memory_limit_bytes: int,
    file_size_limit_bytes: int,
    open_file_limit: int,
    process_limit: int,
) -> None:
    try:
        import resource
    except ImportError:
        return

    limit_specs: list[tuple[int, tuple[int, int]]] = []

    if hasattr(resource, "RLIMIT_CPU"):
        cpu_soft = max(1, timeout_seconds + 1)
        cpu_hard = cpu_soft + 1
        limit_specs.append((resource.RLIMIT_CPU, (cpu_soft, cpu_hard)))
    if hasattr(resource, "RLIMIT_FSIZE"):
        limit_specs.append((resource.RLIMIT_FSIZE, (file_size_limit_bytes, file_size_limit_bytes)))
    if hasattr(resource, "RLIMIT_NOFILE"):
        limit_specs.append((resource.RLIMIT_NOFILE, (open_file_limit, open_file_limit)))
    if hasattr(resource, "RLIMIT_CORE"):
        limit_specs.append((resource.RLIMIT_CORE, (0, 0)))
    if process_limit > 0 and hasattr(resource, "RLIMIT_NPROC"):
        limit_specs.append((resource.RLIMIT_NPROC, (process_limit, process_limit)))
    if memory_limit_bytes > 0 and sys.platform.startswith("linux") and hasattr(resource, "RLIMIT_AS"):
        limit_specs.append((resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes)))

    for resource_name, limits in limit_specs:
        try:
            resource.setrlimit(resource_name, limits)
        except (OSError, ValueError):
            continue


def _scrub_environment(base_dir: Path) -> None:
    safe_env = {
        "HOME": str(base_dir),
        "TMPDIR": str(base_dir),
        "TMP": str(base_dir),
        "TEMP": str(base_dir),
        "PATH": "",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    if "SYSTEMROOT" in os.environ:
        safe_env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    os.environ.clear()
    os.environ.update(safe_env)


def _prepare_runtime(base_dir: Path) -> None:
    script_dir = Path(__file__).resolve().parent
    sanitized_sys_path = [str(base_dir)]
    for entry in sys.path:
        if not entry:
            continue
        try:
            entry_path = Path(entry).resolve()
        except OSError:
            sanitized_sys_path.append(entry)
            continue
        if entry_path == script_dir:
            continue
        sanitized_sys_path.append(entry)
    sys.path[:] = sanitized_sys_path
    os.chdir(base_dir)


def _run_script(submission_path: Path) -> int:
    runpy.run_path(str(submission_path), run_name="__main__")
    return 0


def _run_pytest(test_file: Path) -> int:
    import pytest

    return pytest.main(["-q", "-p", "no:cacheprovider", str(test_file.name)])


def main() -> int:
    args = _parse_args()
    base_dir = args.cwd.resolve()
    submission_path = args.submission.resolve()
    test_file = args.test_file.resolve() if args.test_file is not None else None

    try:
        _scrub_environment(base_dir)
        _prepare_runtime(base_dir)
        _apply_posix_limits(
            timeout_seconds=args.timeout_seconds,
            memory_limit_bytes=args.memory_limit_bytes,
            file_size_limit_bytes=args.file_size_limit_bytes,
            open_file_limit=args.open_file_limit,
            process_limit=args.process_limit,
        )
        _install_runtime_policy(base_dir=base_dir, policy_prefix=args.policy_prefix)
    except Exception as exc:
        print(f"{args.error_prefix}{exc.__class__.__name__}: {exc}", file=sys.stderr, flush=True)
        return BOOTSTRAP_ERROR_EXIT_CODE

    try:
        if args.mode == "pytest":
            if test_file is None:
                raise ValueError("pytest mode requires --test-file")
            return _run_pytest(test_file)
        return _run_script(submission_path)
    except SandboxPolicyError:
        return POLICY_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
