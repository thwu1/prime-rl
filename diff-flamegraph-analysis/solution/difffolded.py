#!/usr/bin/env python3
"""Compute differential between two folded stack files.

Equivalent to FlameGraph/difffolded.pl.

Usage: difffolded.py <baseline.folded> <incident.folded>

Output (stdout): one line per stack with signed count delta.
"""

import sys


def parse_folded(path):
    stacks = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.rsplit(None, 1)
            if len(parts) != 2:
                continue
            stack, count_str = parts
            try:
                count = int(count_str)
            except ValueError:
                continue
            stacks[stack] = stacks.get(stack, 0) + count
    return stacks


def main():
    if len(sys.argv) != 3:
        print("Usage: difffolded.py <baseline.folded> <incident.folded>",
              file=sys.stderr)
        sys.exit(1)

    baseline = parse_folded(sys.argv[1])
    incident = parse_folded(sys.argv[2])

    all_stacks = sorted(set(baseline) | set(incident))
    for stack in all_stacks:
        b = baseline.get(stack, 0)
        i = incident.get(stack, 0)
        delta = i - b
        if delta != 0:
            print(f"{stack} {delta}")


if __name__ == '__main__':
    main()
