#!/usr/bin/env python3
"""
Evaluate solver output against regenerated ground truth.

Usage: python3 evaluate.py
  Reads predictions from /app/output/ and compares against ground truth
  regenerated from the same seeds used during instance generation.
"""
import json
import os
import sys

# Import generation function from generator.py (same directory)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generator import generate_instance, SEEDS

GRID_SIZE = 20


def compute_f1(predicted, truth):
    """Compute F1 score between predicted and truth binary grids."""
    tp = fp = fn = 0
    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            p, t = predicted[r][c], truth[r][c]
            if p == 1 and t == 1:
                tp += 1
            elif p == 1 and t == 0:
                fp += 1
            elif p == 0 and t == 1:
                fn += 1
    if tp == 0:
        return 0.0
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    return 2 * precision * recall / (precision + recall)


def main():
    output_dir = "/app/output"
    if not os.path.isdir(output_dir):
        print("Error: /app/output/ directory not found. Run your solver first.")
        sys.exit(1)

    scores = []
    for i, seed in enumerate(SEEDS):
        output_path = os.path.join(output_dir, f"output_{i}.json")
        if not os.path.exists(output_path):
            print(f"Instance {i}: MISSING output file")
            scores.append(0.0)
            continue

        _, truth_grid = generate_instance(seed)
        with open(output_path) as f:
            output = json.load(f)

        f1 = compute_f1(output["grid"], truth_grid)
        scores.append(f1)
        print(f"Instance {i} (seed {seed}): F1 = {f1:.4f}")

    avg = sum(scores) / len(scores) if scores else 0.0
    print(f"\nAverage F1: {avg:.4f}")
    if avg >= 0.85:
        print("PASS (threshold: 0.85)")
    else:
        print("FAIL (threshold: 0.85)")


if __name__ == "__main__":
    main()
