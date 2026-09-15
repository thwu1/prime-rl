#!/usr/bin/env python3
"""Diagnostic harness: runs the reservoir sampler and reports statistics."""

import math
import sys

from bitsource import BitSource
from sampler import StreamSampler


def run_trials(n_items, n_trials, seed_start=1):
    counts = [0] * n_items
    total_bits = 0
    for trial in range(n_trials):
        bs = BitSource(seed=seed_start + trial)
        sampler = StreamSampler(bs)
        for i in range(n_items):
            sampler.process(i)
        counts[sampler.result()] += 1
        total_bits += sampler.bits_used()
    return counts, total_bits / n_trials


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else 5000

    counts, avg_bits = run_trials(n, trials)
    expected = trials / n

    print("=== Reservoir Sampler Diagnostic ===")
    print(f"Stream length: {n}")
    print(f"Trials:        {trials}")
    print(f"Expected count per item: {expected:.1f}")
    print(f"Average bits consumed:   {avg_bits:.1f}")
    print(f"Bits per element:        {avg_bits / n:.1f}")
    print()

    max_dev = 0.0
    for i, c in enumerate(counts):
        dev = (c - expected) / expected
        max_dev = max(max_dev, abs(dev))
        flag = " *** BIASED" if abs(dev) > 0.05 else ""
        print(f"  Item {i:3d}: {c:6d}  ({dev:+.1%}){flag}")

    print(f"\nMax absolute deviation: {max_dev:.1%}")
    info_min = math.log2(n) if n > 1 else 0
    print(f"Bits consumed: {avg_bits:.1f}  "
          f"(information-theoretic minimum: ~{info_min:.1f} bits)")
    if max_dev > 0.05:
        print("WARNING: Distribution appears non-uniform!")
    if avg_bits > n * 0.5:
        print("WARNING: Bit consumption is high relative to stream length!")


if __name__ == "__main__":
    main()
