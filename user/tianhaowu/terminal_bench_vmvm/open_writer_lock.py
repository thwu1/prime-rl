#!/usr/bin/env python3
"""Open and hold an evaluator writer lock without following or blocking on special files."""

from __future__ import annotations

import argparse
import fcntl
import os
import stat
import sys
from pathlib import Path
from typing import NoReturn, Sequence

TARGET_FD = 9
ALLOWED_ENV_VARS = {"EVAL_WRITER_LOCK_FD", "KIMI_SHARED_WRITER_LOCK_FD"}


class WriterLockError(ValueError):
    """A fixed, path-free writer-lock setup error."""


def _fail(code: str) -> NoReturn:
    raise WriterLockError(code)


def _identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)


def _matching_regular_path(path: Path, descriptor: int) -> bool:
    try:
        opened = os.fstat(descriptor)
        current = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(opened.st_mode) and stat.S_ISREG(current.st_mode) and _identity(opened) == _identity(current)


def open_writer_lock(path: Path) -> int:
    """Open and exclusively lock a regular path, returning the locked descriptor."""

    existing: os.stat_result | None = None
    try:
        existing = path.lstat()
    except FileNotFoundError:
        pass
    except OSError:
        _fail("open_failed")
    else:
        if not stat.S_ISREG(existing.st_mode):
            _fail("not_same_regular_file")

    flags = os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        _fail("open_failed")
    try:
        opened = os.fstat(descriptor)
        if (existing is not None and _identity(existing) != _identity(opened)) or not _matching_regular_path(
            path, descriptor
        ):
            _fail("not_same_regular_file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _fail("already_locked")
        except OSError:
            _fail("lock_failed")
        if not _matching_regular_path(path, descriptor):
            _fail("path_changed")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock-path", required=True, type=Path)
    parser.add_argument("--env-var", required=True, choices=sorted(ALLOWED_ENV_VARS))
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> NoReturn:
    args = _parser().parse_args(argv)
    command = list(args.command)
    if command[:1] == ["--"]:
        command.pop(0)
    if not command:
        _fail("command_missing")

    descriptor = open_writer_lock(args.lock_path)
    try:
        if descriptor != TARGET_FD:
            os.dup2(descriptor, TARGET_FD, inheritable=True)
            os.close(descriptor)
        else:
            os.set_inheritable(TARGET_FD, True)
        environment = os.environ.copy()
        environment[args.env_var] = str(TARGET_FD)
        os.execvpe(command[0], command, environment)
    except OSError:
        _fail("exec_failed")


if __name__ == "__main__":
    try:
        main()
    except WriterLockError as error:
        print(f"writer_lock_error:{error}", file=sys.stderr)
        raise SystemExit(2) from None
