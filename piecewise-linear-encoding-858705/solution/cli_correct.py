#!/usr/bin/env python3
"""CLI for PLE encoding — corrected."""

import argparse
import sys

import numpy as np

sys.path.insert(0, '/app')
from ple.encoder import compute_bins, PiecewiseLinearEncoder


def main():
    parser = argparse.ArgumentParser(description='PLE encoding CLI')
    parser.add_argument('--input', required=True, help='Input .npy file')
    parser.add_argument('--n-bins', type=int, default=48, help='Number of bins')
    parser.add_argument('--format', choices=['structured', 'flat'],
                        default='structured', help='Output format')
    parser.add_argument('--output', required=True, help='Output .npy file')
    args = parser.parse_args()

    X = np.load(args.input)
    bins = compute_bins(X, n_bins=args.n_bins)
    enc = PiecewiseLinearEncoder(bins)

    if args.format == 'structured':
        result = enc.encode_structured(X)
    else:
        result = enc.encode_flat(X)

    np.save(args.output, result)


if __name__ == '__main__':
    main()
