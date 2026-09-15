#!/usr/bin/env python3
"""Write the typesim CLI module."""

content = r'''#!/usr/bin/env python3
"""CLI for TypeSim scoring engine.

Usage:
    Single pair:
        python3 /app/typesim/cli.py "Dict[str, List[int]]" "Dict[str, List[float]]"

    Batch mode:
        python3 /app/typesim/cli.py --batch input.json --output output.json
"""

import argparse
import json
import sys
import os

# Ensure /app is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typesim.parser import parse_type
from typesim.similarity import get_type_similarity


def main():
    parser = argparse.ArgumentParser(description="TypeSim scoring engine")
    parser.add_argument("type_a", nargs="?", help="First type string")
    parser.add_argument("type_b", nargs="?", help="Second type string")
    parser.add_argument("--batch", type=str, help="Path to JSON file with type pairs")
    parser.add_argument("--output", type=str, help="Path to output JSON file")

    args = parser.parse_args()

    if args.batch:
        # Batch mode
        with open(args.batch) as f:
            pairs = json.load(f)

        results = []
        for pair in pairs:
            a = parse_type(pair["a"])
            b = parse_type(pair["b"])
            score = get_type_similarity(a, b)
            results.append({
                "a": pair["a"],
                "b": pair["b"],
                "score": round(score, 4),
            })

        if args.output:
            with open(args.output, "w") as f:
                json.dump(results, f, indent=2)
        else:
            print(json.dumps(results, indent=2))
    elif args.type_a and args.type_b:
        # Single pair mode
        a = parse_type(args.type_a)
        b = parse_type(args.type_b)
        score = get_type_similarity(a, b)
        print(f"{score:.4f}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
'''

with open("/app/typesim/cli.py", "w") as f:
    f.write(content)
