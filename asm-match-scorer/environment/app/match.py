#!/usr/bin/env python3
"""
Decompilation matching scorer for x86-64 assembly functions.
Compares target and candidate assembly, finds optimal register
renaming, aligns the instruction sequences, and computes a score.
"""
import sys
import json
from parser import parse_assembly
from registers import find_optimal_mapping, apply_mapping
from align import needleman_wunsch
from score import compute_score


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <target.s> <candidate.s>", file=sys.stderr)
        sys.exit(1)

    target = parse_assembly(sys.argv[1])
    candidate = parse_assembly(sys.argv[2])

    mapping = find_optimal_mapping(target, candidate)
    mapped_candidate = apply_mapping(candidate, mapping)

    alignment = needleman_wunsch(target, mapped_candidate)
    total_score = compute_score(alignment)

    non_identity = {k: v for k, v in mapping.items() if k != v}

    result = {
        "score": total_score,
        "num_target": len(target),
        "num_candidate": len(candidate),
        "register_mapping": non_identity,
    }

    print(json.dumps(result))


if __name__ == "__main__":
    main()
