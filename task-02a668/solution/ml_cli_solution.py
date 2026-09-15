#!/usr/bin/env python3
"""CLI driver for the Mini-ML type inference system."""
import sys
from ml_parser import parse
from ml_infer import infer_program, InferenceError


def main():
    if len(sys.argv) != 2:
        print("Usage: ml_cli.py <file.ml>", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]
    try:
        with open(filepath) as f:
            source = f.read()
        ast = parse(source)
        t = infer_program(ast)
        print(t)
    except InferenceError as e:
        print(f"Type error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
