#!/usr/bin/env python3
"""
Fix all five numerical bugs in the SPRT statistical analysis engine.

"""

import re


def fix_file(path, replacements):
    """Apply a list of (old, new) replacements to a file."""
    with open(path, "r") as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            print(f"WARNING: pattern not found in {path}: {old!r}")
            continue
        count = content.count(old)
        content = content.replace(old, new)
        print(f"Fixed {path}: replaced {count} occurrence(s)")
    with open(path, "w") as f:
        f.write(content)


def main():
    # Bug 1: LLRcalc.py - results_to_pdf uses i/count instead of i/(count-1)
    # This produces wrong score values: [0, 1/3, 2/3] instead of [0, 1/2, 1]
    fix_file("/app/stats/LLRcalc.py", [
        (
            "return N, [(i / count, results[i] / N) for i in range(0, count)]",
            "return N, [(i / (count - 1), results[i] / N) for i in range(0, count)]",
        ),
    ])

    # Bug 2: LLRcalc.py - LLR_drift_variance_alt2 uses v**0.5 (stdev) instead of v (variance)
    # The formulas divide by sigma^2 (variance), not sigma (stdev)
    fix_file("/app/stats/LLRcalc.py", [
        (
            "mu = (s - (s0 + s1) / 2) * (s1 - s0) / v**0.5\n"
            "    var = (s1 - s0) ** 2 / v**0.5",
            "mu = (s - (s0 + s1) / 2) * (s1 - s0) / v\n"
            "    var = (s1 - s0) ** 2 / v",
        ),
    ])

    # Bug 3: brownian.py - outcome_cdf_alt1 pre-factor uses 2*gamma*x
    # instead of 2*gamma*(A-x) in the exponential
    fix_file("/app/stats/brownian.py", [
        (
            "pre = (1 - math.exp(2 * gamma * x)) / (1 - math.exp(2 * gamma * A))",
            "pre = (1 - math.exp(2 * gamma * (A - x))) / (1 - math.exp(2 * gamma * A))",
        ),
    ])

    # Bug 4: sprt.py - set_state uses var**0.5 for pentanomial sigma_pg
    # instead of (2*var)**0.5. The factor of 2 accounts for game pairs.
    fix_file("/app/stats/sprt.py", [
        (
            "            if len(results) == 5:\n"
            "                self.sigma_pg = var**0.5",
            "            if len(results) == 5:\n"
            "                self.sigma_pg = (2 * var) ** 0.5",
        ),
    ])

    # Bug 5: stat_util.py - bayeselo_to_proba uses /200.0 instead of /400.0
    # in the logistic exponent denominator
    fix_file("/app/stats/stat_util.py", [
        (
            "P[2] = 1.0 / (1.0 + pow(10.0, (-elo + drawelo) / 200.0))",
            "P[2] = 1.0 / (1.0 + pow(10.0, (-elo + drawelo) / 400.0))",
        ),
        (
            "P[0] = 1.0 / (1.0 + pow(10.0, (elo + drawelo) / 200.0))",
            "P[0] = 1.0 / (1.0 + pow(10.0, (elo + drawelo) / 400.0))",
        ),
    ])

    print("All 5 bugs fixed.")


if __name__ == "__main__":
    main()
