from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

WORKFLOW_DIR = Path(__file__).parents[1]
HELPER = WORKFLOW_DIR / "open_writer_lock.py"


def _run_helper(lock_path: Path, *, timeout: float = 3.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--lock-path",
            str(lock_path),
            "--env-var",
            "EVAL_WRITER_LOCK_FD",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(99)",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_writer_lock_helper_rejects_stationary_fifo_without_blocking(tmp_path: Path) -> None:
    lock_path = tmp_path / "writer.lock"
    os.mkfifo(lock_path)

    result = _run_helper(lock_path)

    assert result.returncode == 2
    assert result.stderr == "writer_lock_error:not_same_regular_file\n"


def test_writer_lock_helper_rejects_device_without_blocking() -> None:
    result = _run_helper(Path("/dev/null"))

    assert result.returncode == 2
    assert result.stderr == "writer_lock_error:not_same_regular_file\n"


def test_writer_lock_helper_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.touch()
    lock_path = tmp_path / "writer.lock"
    lock_path.symlink_to(target)

    result = _run_helper(lock_path)

    assert result.returncode == 2
    assert result.stderr == "writer_lock_error:not_same_regular_file\n"


def test_writer_lock_helper_executes_with_same_locked_file_description(tmp_path: Path) -> None:
    lock_path = tmp_path / "writer.lock"
    child = """
import fcntl
import os
import sys

assert os.environ["EVAL_WRITER_LOCK_FD"] == "9"
path = sys.argv[1]
assert os.stat(path).st_ino == os.fstat(9).st_ino
competitor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
try:
    try:
        fcntl.flock(competitor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        pass
    else:
        raise AssertionError("lock was not preserved")
finally:
    os.close(competitor)
"""

    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--lock-path",
            str(lock_path),
            "--env-var",
            "EVAL_WRITER_LOCK_FD",
            "--",
            sys.executable,
            "-c",
            child,
            str(lock_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=3,
    )

    assert result.returncode == 0, result.stderr
    assert lock_path.is_file()
