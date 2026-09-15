#!/usr/bin/env python3
"""
Program synthesizer for 16-bit bitvector DSL.

Given an oracle function, synthesize an equivalent program in the DSL.

Usage:
    python3 synthesize.py <oracle_id>
    python3 synthesize.py all

The synthesized program is written to /app/results/oracle_<id>.json
"""
import sys
import os
import json

sys.path.insert(0, '/app')
from oracle import get_oracle, ORACLES
from dsl import (evaluate_program, validate_program, program_to_string,
                 OPS, NUM_OPS, NUM_INPUTS, MASK, BITS)


def synthesize(oracle_fn, max_lines=5):
    """
    Synthesize a DSL program equivalent to the given oracle function.

    Args:
        oracle_fn: callable (a, b, c, d) -> int, all values 16-bit unsigned
        max_lines: maximum number of DSL instructions (default 5)

    Returns:
        list of instruction dicts {"op", "arg1", "arg2"}, or None
    """
    # TODO: Implement the synthesizer.
    raise NotImplementedError("Implement the synthesizer")


def main():
    os.makedirs('/app/results', exist_ok=True)

    if len(sys.argv) < 2:
        print("Usage: python3 synthesize.py <oracle_id|all>")
        sys.exit(1)

    if sys.argv[1] == 'all':
        oracle_ids = sorted(ORACLES.keys())
    else:
        oracle_ids = [int(sys.argv[1])]

    for oid in oracle_ids:
        print(f"\n{'=' * 50}")
        print(f"Synthesizing oracle {oid}...")
        print(f"{'=' * 50}")
        oracle_fn = get_oracle(oid)
        program = synthesize(oracle_fn)
        if program is None:
            print(f"FAILED to synthesize oracle {oid}")
            sys.exit(1)

        if not validate_program(program):
            print("ERROR: synthesized program is structurally invalid")
            sys.exit(1)

        print("Synthesized program:")
        print(program_to_string(program))

        outpath = f'/app/results/oracle_{oid}.json'
        with open(outpath, 'w') as f:
            json.dump(program, f, indent=2)
        print(f"Saved to {outpath}")


if __name__ == '__main__':
    main()
