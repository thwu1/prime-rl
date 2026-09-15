#!/usr/bin/env python3
"""Compute type similarity scores for test cases.

Diagnostic tool: runs all test cases from test_cases.json and reports
computed vs expected similarity scores.
"""

import json
import sys

sys.path.insert(0, "/app")

from typesim.parser import parse_type
from typesim.similarity import type_similarity


def main():
    with open("/app/test_cases.json") as f:
        test_cases = json.load(f)

    results = {}
    all_pass = True

    for tc in test_cases:
        try:
            a = parse_type(tc["a"])
            b = parse_type(tc["b"])
            score = type_similarity(a, b)
            score_rounded = round(score, 4)
            results[tc["id"]] = score_rounded

            expected = tc["expected"]
            match = abs(score_rounded - expected) < 0.001
            status = "PASS" if match else "FAIL"
            if not match:
                all_pass = False
            print(
                f"Case {tc['id']:2d}: {tc['a']:50s} vs {tc['b']:50s}"
                f" = {score_rounded:.4f} (expected {expected:.4f}) [{status}]"
            )
        except Exception as e:
            results[tc["id"]] = None
            all_pass = False
            print(
                f"Case {tc['id']:2d}: {tc['a']:50s} vs {tc['b']:50s}"
                f" = ERROR: {e}"
            )

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'All tests passed!' if all_pass else 'Some tests failed.'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
