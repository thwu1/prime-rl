#!/usr/bin/env python3
"""
D-JOLT Miss Table Parameter Optimizer

Finds the (lr_sets, sr_sets, extra_sets) configuration that maximizes total
entries across all three D-JOLT miss tables under a 160KB budget constraint.

"""

import json
import math
import re


def extract_constexpr(source, name):
    """Extract a constexpr size_t value."""
    pattern = rf'(?:static\s+)?constexpr\s+size_t\s+{re.escape(name)}\s*=\s*(\d+)'
    m = re.search(pattern, source)
    if m:
        return int(m.group(1))
    return None


def log2_int(n):
    """Integer log2 for powers of 2."""
    result = 0
    while n > 1:
        n >>= 1
        result += 1
    return result


def main():
    # Read D-JOLT source
    with open('/app/prefetchers/DJOLT_prefetcher.cc', 'r') as f:
        source = f.read()

    # Extract fixed parameters
    sig_bits = extract_constexpr(source, 'SignatureBits')  # 23
    ubp_bits = extract_constexpr(source, 'UpperBitPtrBits')  # 4
    n_ways = 4
    n_vectors = 2
    vector_size = 8
    lru_bits_per_entry = int(math.ceil(math.log2(n_ways)))  # 2

    # Compute fixed (non-table) component costs
    # Long-range siggen: Siggen_FifoRetCnt<7>
    lr_siggen_match = re.search(r'#define\s+LongRangePrefetcherSiggen\s+Siggen_FifoRetCnt<(\d+)>', source)
    lr_hist = int(lr_siggen_match.group(1))  # 7
    lr_siggen_bits = 32 * lr_hist + int(math.ceil(math.log2(lr_hist))) + 32  # 259

    # Long-range sig queue: SignatureQueue<12>
    lr_dist = extract_constexpr(source, 'LongRangePrefetcherDistance')  # 12
    lr_sq_bits = sig_bits * lr_dist + int(math.ceil(math.log2(lr_dist)))  # 280

    # Short-range siggen: Siggen_FifoRetCnt<4>
    sr_siggen_match = re.search(r'#define\s+ShortRangePrefetcherSiggen\s+Siggen_FifoRetCnt<(\d+)>', source)
    sr_hist = int(sr_siggen_match.group(1))  # 4
    sr_siggen_bits = 32 * sr_hist + int(math.ceil(math.log2(sr_hist))) + 32  # 162

    # Short-range sig queue: SignatureQueue<4>
    sr_dist = extract_constexpr(source, 'ShortRangePrefetcherDistance')  # 4
    sr_sq_bits = sig_bits * sr_dist + int(math.ceil(math.log2(sr_dist)))  # 94

    # Upper bit table: (2^UpperBitPtrBits - 1) entries, (40+1) bits each
    ubt_entries = (1 << ubp_bits) - 1  # 15
    ubt_bits = (40 + 1) * ubt_entries  # 615

    # Training table: 16 entries, (58+1+2+4) bits each
    train_bits = (58 + 1 + 2 + int(math.ceil(math.log2(16)))) * 16  # 1040

    # Monitoring table: 16 entries, (58+1+4) bits each
    monitor_bits = (58 + 1 + int(math.ceil(math.log2(16)))) * 16  # 1008

    fixed_bits = (lr_siggen_bits + lr_sq_bits +
                  sr_siggen_bits + sr_sq_bits +
                  ubt_bits + train_bits + monitor_bits)  # 3458

    def miss_table_bits(n_sets):
        """Compute miss table cost for given number of sets."""
        l2s = log2_int(n_sets)
        tag = sig_bits - l2s
        if tag <= 0:
            return float('inf')
        per_entry = tag + (ubp_bits + 18 + vector_size) * n_vectors + lru_bits_per_entry
        return per_entry * n_sets * n_ways

    # Budget: 160KB = 1,310,720 bits
    budget = 160 * 1024 * 8  # 1310720

    # Search over all valid power-of-2 combinations
    # Valid set counts: 2^6 to 2^22 (tag bits must be positive, so log2(sets) < 23)
    min_exp = 6   # minimum 64 sets
    max_exp = 22  # sig_bits - 1 = 22, so max log2(sets) = 22
    powers = [1 << i for i in range(min_exp, max_exp + 1)]

    best_entries = -1
    best_config = None

    for lr in powers:
        lr_cost = miss_table_bits(lr)
        if lr_cost == float('inf') or lr_cost + fixed_bits >= budget:
            continue
        for sr in powers:
            sr_cost = miss_table_bits(sr)
            if sr_cost == float('inf') or lr_cost + sr_cost + fixed_bits >= budget:
                continue
            for ex in powers:
                ex_cost = miss_table_bits(ex)
                if ex_cost == float('inf'):
                    continue
                total_cost = lr_cost + sr_cost + ex_cost + fixed_bits
                if total_cost > budget:
                    continue
                entries = (lr + sr + ex) * n_ways
                # Update best: maximize entries, tiebreak larger lr, then larger sr
                if (entries > best_entries or
                    (entries == best_entries and lr > best_config[0]) or
                    (entries == best_entries and lr == best_config[0] and sr > best_config[1])):
                    best_entries = entries
                    best_config = (lr, sr, ex)
                    best_cost = total_cost

    lr_opt, sr_opt, ex_opt = best_config

    result = {
        "lr_sets": lr_opt,
        "sr_sets": sr_opt,
        "extra_sets": ex_opt,
        "total_entries": best_entries,
        "total_bits": best_cost
    }

    with open('/app/optimal_config.json', 'w') as f:
        json.dump(result, f, indent=2)

    print(f"Optimal configuration for 160KB budget:")
    print(f"  LR sets: {lr_opt} ({lr_opt * n_ways} entries)")
    print(f"  SR sets: {sr_opt} ({sr_opt * n_ways} entries)")
    print(f"  Extra sets: {ex_opt} ({ex_opt * n_ways} entries)")
    print(f"  Total entries: {best_entries}")
    print(f"  Total bits: {best_cost} ({best_cost / 8192:.2f} KB)")


if __name__ == '__main__':
    main()
