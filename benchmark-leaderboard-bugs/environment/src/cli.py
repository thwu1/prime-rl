#!/usr/bin/env python3
"""CLI entry point for the benchmark evaluation pipeline."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analyzer import Analyzer


def main():
    parser = argparse.ArgumentParser(description="Benchmark Evaluation Pipeline")
    parser.add_argument(
        "--data-dir",
        default="/app/data",
        help="Directory containing evaluation data",
    )
    parser.add_argument(
        "--output",
        default="/app/output/leaderboard.json",
        help="Output file path",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="Start date for time-window filter (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="End date for time-window filter (YYYY-MM-DD)",
    )

    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    analyzer = Analyzer(args.data_dir)
    result = analyzer.compute_leaderboard(
        start_date=args.start_date,
        end_date=args.end_date,
    )

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Leaderboard written to {args.output}")


if __name__ == "__main__":
    main()
