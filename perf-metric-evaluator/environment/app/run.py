#!/usr/bin/env python3
"""Entry point for the benchmark evaluation pipeline."""

from pipeline.evaluator import build_leaderboard
from pipeline.ranking import rank_and_output


def main():
    data_path = "/app/data/results.json"
    output_path = "/app/output/leaderboard.json"

    leaderboard, details = build_leaderboard(data_path)
    rank_and_output(leaderboard, details, output_path)
    print(f"Leaderboard written to {output_path}")


if __name__ == "__main__":
    main()
