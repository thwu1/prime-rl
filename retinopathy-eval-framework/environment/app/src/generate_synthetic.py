#!/usr/bin/env python3
"""
IDRiD Synthetic Data Generator
Generates paired ground-truth and prediction data for evaluation testing.

"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="IDRiD Synthetic Data Generator")
    parser.add_argument("--task", required=True,
                        choices=["lesion_segmentation", "disease_grading", "localization"])
    parser.add_argument("--num-images", required=True, type=int)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise-level", type=float, default=0.0)
    args = parser.parse_args()

    raise NotImplementedError(
        "Synthetic data generator not yet implemented. "
        "See /app/config/eval_spec.yaml for data format specifications."
    )


if __name__ == "__main__":
    main()
