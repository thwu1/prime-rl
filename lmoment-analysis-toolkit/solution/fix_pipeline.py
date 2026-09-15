#!/usr/bin/env python3

"""
Fix the three bugs in the hydrological return level pipeline.

Bug 1 - extract.sh (awk column selection):
  The awk command uses hardcoded $4 (water_level_m column) instead of
  the $col variable which is set to the flow_column_index from the
  station JSON config. Fix: replace $4 with $col in the awk printf.

Bug 2 - analysis/lmoments.py (PWM denominator):
  The PWM normalization uses comb(n, r) but the correct unbiased
  estimator (Hosking 1990) requires comb(n-1, r). This off-by-one in
  the combinatorial coefficient biases all L-moment estimates.

Bug 3 - analysis/fit.py (GEV shape sign convention):
  The code sets shape = -kappa_h, but the return level formula uses
  Hosking's convention directly (shape = kappa_h). Negating it inverts
  the tail behavior of the distribution.
"""


def fix_extract_sh():
    """Fix awk column selection in extract.sh."""
    with open("/app/pipeline/extract.sh") as f:
        code = f.read()
    code = code.replace(", $4 }", ", $col }")
    with open("/app/pipeline/extract.sh", "w") as f:
        f.write(code)
    print("Fixed extract.sh: $4 -> $col in awk command")


def fix_lmoments():
    """Fix PWM normalization in lmoments.py."""
    with open("/app/analysis/lmoments.py") as f:
        code = f.read()
    code = code.replace("comb(n, r)", "comb(n - 1, r)")
    with open("/app/analysis/lmoments.py", "w") as f:
        f.write(code)
    print("Fixed lmoments.py: comb(n, r) -> comb(n - 1, r)")


def fix_fit():
    """Fix GEV shape sign in fit.py."""
    with open("/app/analysis/fit.py") as f:
        code = f.read()
    code = code.replace("shape = -kappa_h", "shape = kappa_h")
    with open("/app/analysis/fit.py", "w") as f:
        f.write(code)
    print("Fixed fit.py: shape = -kappa_h -> shape = kappa_h")


if __name__ == "__main__":
    fix_extract_sh()
    fix_lmoments()
    fix_fit()
    print("All pipeline bugs fixed.")
