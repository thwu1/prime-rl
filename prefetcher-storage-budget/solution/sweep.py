#!/usr/bin/env python3
"""
D-JOLT multi-budget configuration optimizer.

Derives the miss table cost formula from the D-JOLT source code, then
searches over all valid power-of-2 configurations to find optimal
parameters under 128 KB, 160 KB, and 192 KB budget constraints.

"""

import json
import math
import re


def extract_constexpr(source, name):
    """Extract a constexpr size_t value from D-JOLT source."""
    pattern = rf'(?:static\s+)?constexpr\s+size_t\s+{re.escape(name)}\s*=\s*(\d+)'
    m = re.search(pattern, source)
    return int(m.group(1)) if m else None


def main():
    with open('/app/prefetchers/DJOLT_prefetcher.cc', 'r') as f:
        source = f.read()

    # Extract core parameters
    sig_bits = extract_constexpr(source, 'SignatureBits')
    ubp_bits = extract_constexpr(source, 'UpperBitPtrBits')
    n_ways = 4
    n_vectors = 2
    vector_size = 8
    lru_bits = int(math.ceil(math.log2(n_ways)))

    # Extract siggen history lengths and distances
    lr_hist = int(re.search(
        r'#define\s+LongRangePrefetcherSiggen\s+Siggen_FifoRetCnt<(\d+)>', source
    ).group(1))
    sr_hist = int(re.search(
        r'#define\s+ShortRangePrefetcherSiggen\s+Siggen_FifoRetCnt<(\d+)>', source
    ).group(1))
    lr_dist = extract_constexpr(source, 'LongRangePrefetcherDistance')
    sr_dist = extract_constexpr(source, 'ShortRangePrefetcherDistance')

    # Compute fixed (non-table) component costs
    lr_siggen = 32 * lr_hist + int(math.ceil(math.log2(lr_hist))) + 32
    lr_sigqueue = sig_bits * lr_dist + int(math.ceil(math.log2(lr_dist)))
    sr_siggen = 32 * sr_hist + int(math.ceil(math.log2(sr_hist))) + 32
    sr_sigqueue = sig_bits * sr_dist + int(math.ceil(math.log2(sr_dist)))
    ubt = (40 + 1) * ((1 << ubp_bits) - 1)
    train = (58 + 1 + 2 + int(math.ceil(math.log2(16)))) * 16
    monitor = (58 + 1 + int(math.ceil(math.log2(16)))) * 16
    fixed_bits = lr_siggen + lr_sigqueue + sr_siggen + sr_sigqueue + ubt + train + monitor

    def table_cost(n_sets):
        l2 = int(math.log2(n_sets))
        tag = sig_bits - l2
        if tag <= 0:
            return float('inf')
        per_entry = tag + (ubp_bits + 18 + vector_size) * n_vectors + lru_bits
        return per_entry * n_sets * n_ways

    # Budget constraints
    budgets = {
        "128kb": 128 * 1024 * 8,
        "160kb": 160 * 1024 * 8,
        "192kb": 192 * 1024 * 8,
    }

    # Valid set counts: 2^6 to 2^22 (tag must be positive: log2(sets) < 23)
    powers = [1 << i for i in range(6, 23)]

    results = {}
    for budget_name, budget_bits in budgets.items():
        best_entries = -1
        best_config = None
        best_bits = None

        for lr in powers:
            lc = table_cost(lr)
            if lc + fixed_bits >= budget_bits:
                continue
            for sr in powers:
                sc = table_cost(sr)
                if lc + sc + fixed_bits >= budget_bits:
                    continue
                for ex in powers:
                    ec = table_cost(ex)
                    total_bits = int(lc + sc + ec + fixed_bits)
                    if total_bits > budget_bits:
                        continue
                    entries = (lr + sr + ex) * n_ways
                    if (entries > best_entries or
                        (entries == best_entries and lr > best_config[0]) or
                        (entries == best_entries and lr == best_config[0] and sr > best_config[1])):
                        best_entries = entries
                        best_config = (lr, sr, ex)
                        best_bits = total_bits

        results[budget_name] = {
            "lr_sets": best_config[0],
            "sr_sets": best_config[1],
            "extra_sets": best_config[2],
            "total_entries": best_entries,
            "total_bits": best_bits
        }

    with open('/app/optimal_configs.json', 'w') as f:
        json.dump(results, f, indent=2)

    for name, cfg in results.items():
        print(f"{name}: lr={cfg['lr_sets']}, sr={cfg['sr_sets']}, "
              f"ex={cfg['extra_sets']}, entries={cfg['total_entries']}, "
              f"bits={cfg['total_bits']}")


if __name__ == '__main__':
    main()
