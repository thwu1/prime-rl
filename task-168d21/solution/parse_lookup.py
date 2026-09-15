#!/usr/bin/env python3
"""
Parses hfst-lookup output and extracts one surface form per input gloss.

hfst-lookup -q output format:
    input_gloss\tsurface_form\tweight
    <blank line>
    input_gloss\tsurface_form\tweight
    <blank line>
    ...

This script reads from stdin and prints one surface form per line to stdout.
"""

import sys


def main():
    current_best = None
    for line in sys.stdin:
        line = line.rstrip('\n')
        if not line:
            if current_best is not None:
                print(current_best)
                current_best = None
        elif '\t' in line:
            parts = line.split('\t')
            if current_best is None:
                current_best = parts[1]
    # Handle final entry if no trailing blank line
    if current_best is not None:
        print(current_best)


if __name__ == '__main__':
    main()
