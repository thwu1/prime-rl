#!/usr/bin/env python3
"""
Generate the CAVP conformance report by evaluating all three
vendor implementations against parsed CAVS test vectors.

"""

import json
import sys
import os

sys.path.insert(0, "/app")

from cavs_parser import parse_cavs_file
from harness import evaluate_implementation


def main():
    cavs_file = "/app/cavs_raw/CTR_DRBG_AES256.txt"
    parsed = parse_cavs_file(cavs_file)

    report = {}

    candidates = {
        "impl_A": "/app/candidates/impl_A.py",
        "impl_B": "/app/candidates/impl_B.py",
        "impl_C": "/app/candidates/impl_C.py",
    }

    best_name = None
    best_pass_count = -1

    for name, path in candidates.items():
        print(f"Evaluating {name} ({path})...")
        result = evaluate_implementation(path, parsed)
        report[name] = result

        # Count total passing vectors
        total_pass = sum(
            c.get("vectors_passed", 0)
            for c in result["configurations"].values()
        )
        print(f"  {name}: {total_pass} vectors passed, "
              f"overall={result['overall_status']}")

        if total_pass > best_pass_count:
            best_pass_count = total_pass
            best_name = name

    report["recommendation"] = best_name

    output_path = "/app/conformance_report.json"
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nConformance report written to {output_path}")
    print(f"Recommendation: {best_name}")


if __name__ == "__main__":
    main()
