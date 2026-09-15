#!/usr/bin/env python3
"""Count LLVM IR instructions in a .ll file.

Counts non-empty, non-comment, non-label, non-metadata lines inside
function definition bodies (between 'define ...' and '}').
This provides a deterministic instruction count metric.
"""
import sys


def count_instructions(ll_file):
    """Count LLVM IR instructions in the given .ll file."""
    count = 0
    in_function = False
    with open(ll_file) as f:
        for line in f:
            stripped = line.strip()
            if not in_function:
                if stripped.startswith('define '):
                    in_function = True
                continue
            if stripped == '}':
                in_function = False
                continue
            if not stripped:
                continue
            if stripped.startswith(';'):
                continue
            if stripped.startswith('!'):
                continue
            if stripped.endswith(':'):
                continue
            count += 1
    return count


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <file.ll>", file=sys.stderr)
        sys.exit(1)
    print(count_instructions(sys.argv[1]))
