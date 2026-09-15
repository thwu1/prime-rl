#!/usr/bin/env python3
"""Collapse the deterministic perf-script capture into FlameGraph stacks."""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path


HEADER = re.compile(r"^(\S+)\s+\d+\s+\[\d+\].*:\s+[^:]+:$")
FRAME = re.compile(r"^\s*[0-9a-fA-F]+\s+([^+\s]+)(?:\+0x[0-9a-fA-F]+)?\s+")


def main() -> None:
    source, destination = map(Path, sys.argv[1:3])
    counts: Counter[str] = Counter()
    command: str | None = None
    frames: list[str] = []

    def flush() -> None:
        nonlocal command, frames
        if command is not None:
            # perf script lists leaf first; folded stacks list root first.
            counts[";".join([command, *reversed(frames)])] += 1
        command = None
        frames = []

    for raw in source.read_text(errors="replace").splitlines():
        if not raw.strip():
            flush()
            continue
        header = HEADER.match(raw)
        if header:
            flush()
            command = header.group(1)
            continue
        frame = FRAME.match(raw)
        if frame and command is not None:
            frames.append(frame.group(1))
    flush()

    destination.write_text(
        "".join(f"{stack} {count}\n" for stack, count in sorted(counts.items()))
    )


if __name__ == "__main__":
    main()
