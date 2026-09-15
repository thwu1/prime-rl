#!/usr/bin/env python3
"""
IR Optimizer — stub implementation.
Reads a three-address code IR file and writes optimized IR to stdout.

Usage:
  python3 optimize.py <input.ir>          # Optimize and print IR
  python3 optimize.py --dot <input.ir>    # Output DOT-format CFG

TODO: Implement data-flow-analysis-based optimizations and CFG generation.
"""
import sys


def main():
    args = sys.argv[1:]
    dot_mode = False
    filename = None

    for arg in args:
        if arg == '--dot':
            dot_mode = True
        else:
            filename = arg

    if not filename:
        print("Usage: python3 optimize.py [--dot] <input.ir>", file=sys.stderr)
        sys.exit(1)

    with open(filename) as f:
        ir_text = f.read()

    if dot_mode:
        # TODO: Implement CFG generation in DOT format
        print("digraph stub {}")
    else:
        # Pass through unchanged — replace with actual optimizer
        print(ir_text, end='')


if __name__ == '__main__':
    main()
