#!/usr/bin/env python3
"""Fix all bugs in the hydrosig package.

"""


def fix_baseflow():
    """Fix two bugs in baseflow.py.

    Bug 1: Forward and backward passes use (1 - alpha) instead of (1 + alpha)
    in the filter coefficient. The correct Lyne-Hollick equation is:
        qf[i] = alpha * qf[i-1] + 0.5 * (1 + alpha) * (Q[i] - Q[i-1])

    Bug 2: Missing negative baseflow clipping. After filtering, baseflow
    values can go negative due to the recursive filter, but physically
    baseflow (groundwater contribution) cannot be negative.
    """
    with open("/app/hydrosig/baseflow.py", "r") as f:
        code = f.read()

    # Fix Bug 1: filter coefficient sign (affects both forward and backward)
    code = code.replace(
        "0.5 * (1 - alpha) * (q[i] - q[i - 1])",
        "0.5 * (1 + alpha) * (q[i] - q[i - 1])",
    )
    code = code.replace(
        "0.5 * (1 - alpha) * (q[i] - q[i + 1])",
        "0.5 * (1 + alpha) * (q[i] - q[i + 1])",
    )

    # Fix Bug 2: add negative clipping before return in separate()
    code = code.replace(
        "    qb = qb[pad_width:-pad_width]\n    return qb",
        "    qb = qb[pad_width:-pad_width]\n    qb[qb < 0] = 0.0\n    return qb",
    )

    with open("/app/hydrosig/baseflow.py", "w") as f:
        f.write(code)
    print("Fixed baseflow.py (bugs 1-2)")


def fix_signatures():
    """Fix three bugs in signatures.py.

    Bug 3: Coefficient of skewness (CS) is missing the n multiplier in
    the numerator. The Fisher-Pearson formula is:
        CS = n * sum((x - maf)^3) / ((n-1)(n-2) * s^3)

    Bug 4: Walsh seasonality index omits abs() around monthly deviations,
    causing positive and negative deviations to cancel out.

    Bug 5: Streamflow elasticity uses np.nanmean instead of np.nanmedian.
    Sankarasubramanian et al. (2001) specifies the median for robustness.
    """
    with open("/app/hydrosig/signatures.py", "r") as f:
        code = f.read()

    # Fix Bug 3: add n multiplier to CS numerator
    code = code.replace(
        "cs = float(np.sum((values - maf) ** 3) / ((n - 1) * (n - 2) * s2 ** 1.5))",
        "cs = float(n * np.sum((values - maf) ** 3) / ((n - 1) * (n - 2) * s2 ** 1.5))",
    )

    # Fix Bug 4: add abs() to Walsh seasonality
    code = code.replace(
        "deviation_sum = (year_months - r / 12).sum()",
        "deviation_sum = (year_months - r / 12).abs().sum()",
    )

    # Fix Bug 5: mean -> median in elasticity
    code = code.replace(
        "return float(np.nanmean(ratios))",
        "return float(np.nanmedian(ratios))",
    )

    with open("/app/hydrosig/signatures.py", "w") as f:
        f.write(code)
    print("Fixed signatures.py (bugs 3-5)")


if __name__ == "__main__":
    fix_baseflow()
    fix_signatures()
    print("All 5 bugs fixed successfully.")
