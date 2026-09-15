#!/usr/bin/env python3
"""
Fix all seven numerical bugs in the SPRT statistical analysis engine.

"""


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
    # Score values for trinomial must be [0, 0.5, 1] not [0, 1/3, 2/3]
    fix_file("/app/stats/LLRcalc.py", [
        (
            "return N, [(i / count, results[i] / N) for i in range(0, count)]",
            "return N, [(i / (count - 1), results[i] / N) for i in range(0, count)]",
        ),
    ])

    # Bug 2: LLRcalc.py - LLR_drift_variance_alt2 uses v**0.5 (stdev) instead of v (variance)
    # The Brownian approximation divides by sigma^2 (variance), not sigma (stdev)
    fix_file("/app/stats/LLRcalc.py", [
        (
            "mu = (s - (s0 + s1) / 2) * (s1 - s0) / v**0.5\n"
            "    var = (s1 - s0) ** 2 / v**0.5",
            "mu = (s - (s0 + s1) / 2) * (s1 - s0) / v\n"
            "    var = (s1 - s0) ** 2 / v",
        ),
    ])

    # Bug 3: LLRcalc.py - LLR_normalized omits sqrt(2) scaling for pentanomial
    # Pentanomial entries represent game pairs, so t-value bounds need sqrt(2) adjustment
    fix_file("/app/stats/LLRcalc.py", [
        (
            "    nt0, nt1 = [nelo / nelo_divided_by_nt for nelo in (nelo0, nelo1)]\n"
            "    t0, t1 = nt0, nt1",
            "    nt0, nt1 = [nelo / nelo_divided_by_nt for nelo in (nelo0, nelo1)]\n"
            "    sqrt2 = 2**0.5\n"
            "    t0, t1 = (\n"
            "        (nt0, nt1)\n"
            "        if len(results) == 3\n"
            "        else (nt0 * sqrt2, nt1 * sqrt2)\n"
            "        if len(results) == 5\n"
            "        else None\n"
            "    )",
        ),
    ])

    # Bug 4: brownian.py - outcome_cdf_alt1 pre-factor uses 2*gamma*x
    # instead of 2*gamma*(A-x). The numerator must use the distance to the
    # upper boundary (A-x), not to the lower boundary (x).
    fix_file("/app/stats/brownian.py", [
        (
            "pre = (1 - math.exp(2 * gamma * x)) / (1 - math.exp(2 * gamma * A))",
            "pre = (1 - math.exp(2 * gamma * (A - x))) / (1 - math.exp(2 * gamma * A))",
        ),
    ])

    # Bug 5: sprt.py - set_state uses var**0.5 for pentanomial sigma_pg
    # instead of (2*var)**0.5. The factor of 2 accounts for pentanomial
    # entries representing pairs of games (variance halving).
    fix_file("/app/stats/sprt.py", [
        (
            "            if len(results) == 5:\n"
            "                self.sigma_pg = var**0.5",
            "            if len(results) == 5:\n"
            "                self.sigma_pg = (2 * var) ** 0.5",
        ),
    ])

    # Bug 6: stat_util.py - bayeselo_to_proba uses /200.0 instead of /400.0
    # The BayesElo logistic exponent denominator must be 400 (standard Elo scale)
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

    # Bug 7: stat_util.py - SPRT_elo always uses LLR_logistic for the LLR override
    # instead of selecting the model-specific LLR computation. For normalized model,
    # it must use LLR_normalized.
    fix_file("/app/stats/stat_util.py", [
        (
            '    a["LLR"] = LLRcalc.LLR_logistic(elo0, elo1, R_)\n'
            '    del a["clamped"]',
            '    if elo_model == "logistic":\n'
            '        a["LLR"] = LLRcalc.LLR_logistic(elo0, elo1, R_)\n'
            '    else:\n'
            '        a["LLR"] = LLRcalc.LLR_normalized(elo0, elo1, R_)\n'
            '    del a["clamped"]',
        ),
    ])

    print("All 7 statistical bugs fixed.")


if __name__ == "__main__":
    main()
