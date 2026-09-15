
"""Main entry point: reads TAC, optimizes, writes optimized TAC and optional DOT."""

import sys
import os
import argparse

from tac_parser import parse, emit

try:
    from optimizer import optimize
except ImportError:
    print("ERROR: optimizer.py not found. Please implement /app/optimizer.py", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='TAC Optimizer Pipeline')
    parser.add_argument('input', nargs='?', help='Input TAC file (default: stdin)')
    parser.add_argument('--dot', metavar='DIR', help='Output directory for CFG DOT files')
    args = parser.parse_args()

    if args.input:
        with open(args.input) as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    functions = parse(text)
    optimized = optimize(functions)
    print(emit(optimized), end='')

    if args.dot:
        try:
            from dot_output import cfg_to_dot
        except ImportError:
            print("ERROR: dot_output.py not found.", file=sys.stderr)
            sys.exit(1)
        os.makedirs(args.dot, exist_ok=True)
        for func in optimized:
            dot_text = cfg_to_dot(func)
            dot_path = os.path.join(args.dot, f'{func.name}.dot')
            with open(dot_path, 'w') as f:
                f.write(dot_text)


if __name__ == '__main__':
    main()
