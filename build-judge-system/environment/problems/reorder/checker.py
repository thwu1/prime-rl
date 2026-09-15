#!/usr/bin/env python3
"""
Custom checker for the reorder problem.
Validates that the output is a derangement of the input array:
  1. Output must be a permutation of the input elements.
  2. No element may remain at its original position.

Usage: checker.py <input_file> <expected_output_file> <actual_output_file>
Exit code 0 = accepted, non-zero = wrong answer.
"""
import sys


def main():
    input_file = sys.argv[1]
    _expected_file = sys.argv[2]
    actual_file = sys.argv[3]

    with open(input_file) as f:
        lines = f.read().strip().split('\n')
        n = int(lines[0])
        original = list(map(int, lines[1].split()))

    with open(actual_file) as f:
        content = f.read().strip()
        if not content:
            sys.exit(1)
        try:
            result = list(map(int, content.split()))
        except ValueError:
            sys.exit(1)

    if len(result) != n:
        sys.exit(1)

    if sorted(result) != sorted(original):
        sys.exit(1)

    for i in range(n):
        if result[i] == original[i]:
            sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()
