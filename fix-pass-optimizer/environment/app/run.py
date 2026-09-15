#!/usr/bin/env python3
"""Entry point for the LLVM pass sequence optimizer."""

import sys
import json
from src.optimizer import run_pipeline


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 run.py <ir_file> [config.json]")
        sys.exit(1)

    ir_file = sys.argv[1]
    config = None
    if len(sys.argv) > 2:
        with open(sys.argv[2]) as f:
            config = json.load(f)

    results = run_pipeline(ir_file, config)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
