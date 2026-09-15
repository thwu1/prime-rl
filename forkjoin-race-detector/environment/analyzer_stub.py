#!/usr/bin/env python3
"""
Fork-Join Parallel Program Analyzer with Phaser Synchronization

Implement this module to analyze async-finish parallel programs with
optional phaser-based point-to-point synchronization.
See /app/spec.md for the full specification.

Usage:
    python3 analyzer.py <program1.json> [program2.json ...]

Output:
    /app/results/<name>.json — analysis results
    /app/graphs/<name>.dot — computation DAG in Graphviz DOT format
"""
import json
import sys
import os


def analyze(program_path):
    """
    Analyze a parallel program with optional phaser synchronization.

    Args:
        program_path: Path to the program JSON file

    Returns:
        dict with keys: name, work, span, ideal_parallelism, data_races
    """
    with open(program_path) as f:
        program = json.load(f)

    # TODO: Build the computation DAG from the program description
    #       Handle: compute, read, write, async, finish, signal, wait, next
    # TODO: Add phaser edges based on phase matching
    # TODO: Compute WORK (sum of all node costs)
    # TODO: Compute SPAN (critical path — longest weighted path)
    # TODO: Detect data races (unordered accesses to same var, at least one write)
    # TODO: Generate Graphviz DOT output to /app/graphs/<name>.dot

    raise NotImplementedError("Implement the analyzer")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 analyzer.py <program.json> [<program2.json> ...]")
        sys.exit(1)

    os.makedirs("/app/results", exist_ok=True)
    os.makedirs("/app/graphs", exist_ok=True)

    for path in sys.argv[1:]:
        result = analyze(path)
        output_path = f"/app/results/{result['name']}.json"
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"Analyzed {result['name']}: work={result['work']}, span={result['span']}, "
              f"parallelism={result['ideal_parallelism']}, races={len(result['data_races'])}")


if __name__ == "__main__":
    main()
