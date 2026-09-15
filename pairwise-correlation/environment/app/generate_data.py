#!/usr/bin/env python3
"""Generate test data in CORR binary format.

Usage:
    python3 generate_data.py <output.bin> <n> <m> [--missing-rate RATE] [--seed SEED]

"""
import argparse
import struct
import numpy as np


def main():
    parser = argparse.ArgumentParser(description="Generate CORR format test data")
    parser.add_argument("output", help="Output file path")
    parser.add_argument("n", type=int, help="Number of rows (variables)")
    parser.add_argument("m", type=int, help="Number of columns (observations)")
    parser.add_argument("--missing-rate", type=float, default=0.0,
                        help="Fraction of entries to set as NaN (0.0-1.0)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)

    data = rng.standard_normal((args.n, args.m))
    weights = rng.uniform(0.5, 3.0, size=args.m)

    if args.missing_rate > 0:
        mask = rng.random((args.n, args.m)) < args.missing_rate
        data[mask] = np.nan

    with open(args.output, "wb") as f:
        f.write(b"CORR")
        f.write(struct.pack("<II", args.n, args.m))
        f.write(weights.astype("<f8").tobytes())
        f.write(data.astype("<f8").tobytes())

    print(f"Wrote {args.output}: {args.n} rows x {args.m} cols, "
          f"{args.missing_rate*100:.0f}% missing")


if __name__ == "__main__":
    main()
