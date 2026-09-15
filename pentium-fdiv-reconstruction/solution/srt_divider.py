"""
Radix-4 SRT Division Simulator -- Pentium FDIV Bug Reconstruction

Implements the Pentium's SRT division lookup table (correct and buggy versions),
SRT division algorithm, and analysis tools.
"""

import json
import math
from fractions import Fraction


def generate_table(buggy=False):
    """Generate the radix-4 SRT quotient selection lookup table.

    The table is indexed by:
    - d_idx: 0-15, representing divisor d = 1 + d_idx/16
    - p_idx: -64 to 63, representing partial remainder p = p_idx/8

    Returns a dict mapping (d_idx, p_idx) -> quotient digit q in {-2,-1,0,1,2}.
    When buggy=True, replicates Intel's boundary error on the outer boundary.

    The table accounts for the carry-save adder truncation effect: the table
    index p_hat = floor(p_actual * 8)/8, so p_actual in [p_hat, p_hat + 1/8).
    Each cell's q must be valid for ALL p_actual values in that range.

    For positive p_hat, floor truncation makes p_hat <= p_actual, so:
      - Lower bounds (p >= L*d) are satisfied automatically if p_hat >= L*d
      - Upper bounds (p <= U*d) need p_hat + 1/8 <= U*d, BUT for the
        outermost boundary (8d/3), the algorithm invariant guarantees
        p_actual <= 8d/3, so no adjustment is needed there.

    For negative p_hat, floor truncation still gives p_hat <= p_actual,
    meaning the LEAST negative value in the cell is p_hat + 1/8. So:
      - Upper bounds (p <= -L*d, i.e. |p| >= L*d) need even the LEAST
        negative value to satisfy: p_hat + 1/8 <= -L*d, i.e., p_hat <= -L*d - 1/8.

    With bias toward highest |q| (higher digit preferred):
    """
    table = {}
    adj = Fraction(1, 8)

    for d_idx in range(16):
        d = Fraction(1) + Fraction(d_idx, 16)

        for p_idx in range(-64, 64):
            p = Fraction(p_idx, 8)

            # Outer boundary (correct vs buggy)
            if buggy:
                outer = Fraction(8, 3) * d - adj
            else:
                outer = Fraction(8, 3) * d

            # Check unused region
            if p > outer or p < -outer:
                table[(d_idx, p_idx)] = 0
                continue

            # Thresholds
            t2 = Fraction(4, 3) * d    # lower bound for |q|=2
            t1 = Fraction(1, 3) * d    # lower bound for |q|=1

            if p >= 0:
                # Positive side: floor truncation means p_hat <= p_actual
                # Lower bounds need p_hat >= threshold (no adjustment)
                # Outer upper bound: guaranteed by algorithm invariant
                if p >= t2:
                    table[(d_idx, p_idx)] = 2
                elif p >= t1:
                    table[(d_idx, p_idx)] = 1
                else:
                    table[(d_idx, p_idx)] = 0
            else:
                # Negative side: floor truncation means p_hat <= p_actual
                # The least-negative value in cell is p_hat + 1/8
                # For q=-k to be valid, need p_hat + 1/8 <= -threshold
                # i.e., p_hat <= -threshold - 1/8
                if p <= -t2 - adj:
                    table[(d_idx, p_idx)] = -2
                elif p <= -t1 - adj:
                    table[(d_idx, p_idx)] = -1
                else:
                    table[(d_idx, p_idx)] = 0

    return table


def find_missing_entries(correct_table, buggy_table):
    """Find entries that differ between correct and buggy tables.
    Returns a sorted list of (d_idx, p_idx) tuples."""
    missing = []
    for key in correct_table:
        if correct_table[key] != buggy_table[key]:
            missing.append(key)
    return sorted(missing)


def srt_divide(a_sig, d_sig, table, num_steps=32):
    """Perform radix-4 SRT division of significand a_sig by d_sig.

    Both a_sig and d_sig should be floats in [1.0, 2.0).
    Uses the given lookup table for quotient digit selection.
    The partial remainder is truncated (floor to 3 fractional bits) to compute
    the table index, modeling the carry-save adder truncation effect.

    Returns the quotient as a float.
    """
    d = d_sig
    w = a_sig

    d_idx = int((d - 1.0) * 16)
    d_idx = max(0, min(15, d_idx))

    quotient = 0.0
    scale = 1.0

    for step in range(num_steps):
        p_idx = int(math.floor(w * 8))
        p_idx = max(-64, min(63, p_idx))

        q = table.get((d_idx, p_idx), 0)

        quotient += q * scale
        scale /= 4.0

        w = 4.0 * (w - q * d)

    return quotient


def demonstrate_bug(d_idx, p_idx, d_val, table):
    """Demonstrate the FDIV bug for a specific missing table cell.

    Constructs a partial remainder that maps to the cell (d_idx, p_idx),
    executes one SRT step with both q=0 (buggy) and the correct q (+/-2),
    and returns the divergence analysis.
    """
    p_actual = p_idx / 8.0 + 0.05

    q_buggy = table.get((d_idx, p_idx), 0)
    q_correct = 2 if p_idx > 0 else -2

    p_next_buggy = 4.0 * (p_actual - q_buggy * d_val)
    p_next_correct = 4.0 * (p_actual - q_correct * d_val)

    upper_bound = (8.0 / 3.0) * d_val
    diverged = abs(p_next_buggy) > upper_bound

    return {
        "p_actual": round(p_actual, 10),
        "q_buggy": q_buggy,
        "q_correct": q_correct,
        "p_next_buggy": round(p_next_buggy, 10),
        "p_next_correct": round(p_next_correct, 10),
        "diverged": diverged,
    }


def table_stats(table):
    """Compute statistics for a lookup table."""
    counts = {-2: 0, -1: 0, 0: 0, 1: 0, 2: 0}
    for v in table.values():
        counts[v] += 1
    return {
        "total_cells": len(table),
        "num_plus2": counts[2],
        "num_plus1": counts[1],
        "num_zero": counts[0],
        "num_minus1": counts[-1],
        "num_minus2": counts[-2],
    }


def main():
    correct = generate_table(buggy=False)
    buggy = generate_table(buggy=True)

    missing = find_missing_entries(correct, buggy)

    # Pick 3 positive-side missing entries for demonstrations
    pos_missing = [(d, p) for d, p in missing if p > 0]
    demonstrations = []
    for d_idx, p_idx in pos_missing[:3]:
        d_val = 1.0 + d_idx / 16.0
        demo = demonstrate_bug(d_idx, p_idx, d_val, buggy)
        demo["d_idx"] = d_idx
        demo["p_idx"] = p_idx
        demonstrations.append(demo)

    q_test = srt_divide(1.5, 1.25, correct, num_steps=32)

    stats = table_stats(correct)

    results = {
        "num_missing": len(missing),
        "missing_entries": [[d, p] for d, p in missing],
        "demonstrations": demonstrations,
        "correct_division_test": {
            "a": 1.5,
            "d": 1.25,
            "quotient": q_test,
        },
        "table_stats": stats,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Generated tables. Missing entries: {len(missing)}")
    print(f"Division test: 1.5 / 1.25 = {q_test}")
    print(f"Table stats: {stats}")


if __name__ == "__main__":
    main()
