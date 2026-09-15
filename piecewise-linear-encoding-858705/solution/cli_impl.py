#!/usr/bin/env python3
"""CLI for piecewise-linear encoding of tabular data.

"""
import argparse
import sys

import numpy as np

sys.path.insert(0, '/app')
from ple.encoder import compute_bins, PiecewiseLinearEncoder


def main():
    parser = argparse.ArgumentParser(
        description="Piecewise-linear encoding for tabular data"
    )
    parser.add_argument("--input", required=True, help="Input .npy file path")
    parser.add_argument("--n-bins", type=int, default=48,
                        help="Number of bins (default: 48)")
    parser.add_argument("--format", choices=["structured", "flat"],
                        required=True, help="Output format")
    parser.add_argument("--output", required=True,
                        help="Output .npy file path")
    args = parser.parse_args()

    X = np.load(args.input).astype(np.float64)
    if X.ndim != 2:
        print(f"Error: input must be 2-dimensional, got {X.ndim}D",
              file=sys.stderr)
        sys.exit(1)

    bins = compute_bins(X, n_bins=args.n_bins)
    encoder = PiecewiseLinearEncoder(bins)

    if args.format == "structured":
        result = encoder.encode_structured(X)
    else:
        result = encoder.encode_flat(X)

    np.save(args.output, result)


if __name__ == "__main__":
    main()
