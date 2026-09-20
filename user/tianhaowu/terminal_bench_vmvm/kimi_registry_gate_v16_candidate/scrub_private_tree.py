#!/usr/bin/python3.12 -I -S -B
from __future__ import annotations

import os
import stat
import sys


class UnsafeTree(Exception):
    pass


def require(condition: bool) -> None:
    if not condition:
        raise UnsafeTree


def inode_signature(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode), value.st_uid, value.st_nlink)


def directory_signature(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode), value.st_uid)


def scrub_file(parent_fd: int, name: str, expected_uid: int, expected_dev: int) -> None:
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    require(stat.S_ISREG(before.st_mode))
    require(before.st_uid == expected_uid and before.st_dev == expected_dev and before.st_nlink == 1)
    source_fd = os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        opened = os.fstat(source_fd)
        require(inode_signature(opened) == inode_signature(before))
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        require(inode_signature(named) == inode_signature(opened))
        os.fchmod(source_fd, 0o600)
        write_fd = os.open(f"/proc/self/fd/{source_fd}", os.O_RDWR | os.O_CLOEXEC)
        try:
            writable = os.fstat(write_fd)
            require((writable.st_dev, writable.st_ino) == (opened.st_dev, opened.st_ino))
            require(writable.st_uid == expected_uid and writable.st_nlink == 1 and stat.S_ISREG(writable.st_mode))
            os.ftruncate(write_fd, 0)
            os.fsync(write_fd)
            scrubbed = os.fstat(write_fd)
            require(scrubbed.st_size == 0 and scrubbed.st_nlink == 1)
            named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            require((named.st_dev, named.st_ino) == (scrubbed.st_dev, scrubbed.st_ino))
            require(named.st_size == 0 and named.st_nlink == 1 and stat.S_ISREG(named.st_mode))
            os.unlink(name, dir_fd=parent_fd)
            unlinked = os.fstat(write_fd)
            require(unlinked.st_size == 0 and unlinked.st_nlink == 0)
        finally:
            os.close(write_fd)
    finally:
        os.close(source_fd)


def scrub_directory(
    directory_fd: int,
    expected_uid: int,
    expected_dev: int,
    exclusions: frozenset[str],
    seen: set[tuple[int, int]],
) -> None:
    opened = os.fstat(directory_fd)
    require(stat.S_ISDIR(opened.st_mode) and opened.st_uid == expected_uid and opened.st_dev == expected_dev)
    key = (opened.st_dev, opened.st_ino)
    if key in seen:
        return
    seen.add(key)
    os.fchmod(directory_fd, 0o700)
    previous: tuple[tuple[str, int, int, int, int], ...] | None = None
    for _round in range(3):
        for name in sorted(os.listdir(directory_fd)):
            require(name not in {"", ".", ".."} and "/" not in name and "\0" not in name)
            if name in exclusions:
                continue
            before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            require(before.st_uid == expected_uid and before.st_dev == expected_dev)
            if stat.S_ISREG(before.st_mode):
                scrub_file(directory_fd, name, expected_uid, expected_dev)
                continue
            require(stat.S_ISDIR(before.st_mode))
            child_fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            try:
                child = os.fstat(child_fd)
                require(directory_signature(child) == directory_signature(before))
                scrub_directory(child_fd, expected_uid, expected_dev, frozenset(), seen)
                after = os.fstat(child_fd)
                named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                require(directory_signature(after) == directory_signature(child))
                require(directory_signature(named) == directory_signature(child))
            finally:
                os.close(child_fd)
        os.fsync(directory_fd)
        projection: list[tuple[str, int, int, int, int]] = []
        for name in sorted(os.listdir(directory_fd)):
            if name in exclusions:
                continue
            item = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            require(stat.S_ISDIR(item.st_mode) and item.st_uid == expected_uid and item.st_dev == expected_dev)
            projection.append((name, item.st_dev, item.st_ino, stat.S_IFMT(item.st_mode), item.st_uid))
        current = tuple(projection)
        if current == previous:
            return
        previous = current
    raise UnsafeTree


def main() -> int:
    require(len(sys.argv) >= 4)
    expected_uid = int(sys.argv[1])
    expected_dev = int(sys.argv[2])
    require(expected_uid >= 0 and expected_dev > 0)
    seen: set[tuple[int, int]] = set()
    for specification in sys.argv[3:]:
        raw_fd, separator, raw_exclusions = specification.partition(":")
        require(separator == ":" and raw_fd.isdigit())
        exclusions = frozenset(filter(None, raw_exclusions.split(",")))
        scrub_directory(int(raw_fd), expected_uid, expected_dev, exclusions, seen)
    return 0


if __name__ == "__main__":
    try:
        status = main()
    except BaseException:
        status = 41
    raise SystemExit(status)
