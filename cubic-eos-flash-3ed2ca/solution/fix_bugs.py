#!/usr/bin/env python3
"""
Fix four thermodynamic bugs in /app/flash_solver.cpp:

1. Wrong a0 constant: uses SRK value 0.42748 instead of PR value 0.45724
2. Wrong m(omega) correlation: uses Soave (1972) instead of Peng-Robinson (1976)
3. Wrong cubic equation coefficients: uses van-der-Waals-like form instead of PR
4. Missing factor of 2 in fugacity coefficient mixing-rule derivative

"""

import sys

with open("/app/flash_solver.cpp", "r") as f:
    code = f.read()

original = code

# ── Bug 1: SRK a0 constant → PR a0 constant ──
# SRK: Omega_a = 1/(9*(2^(1/3)-1)) ≈ 0.42748
# PR:  Omega_a ≈ 0.45724
code = code.replace("0.42748023", "0.45723553")

# ── Bug 2: SRK m(omega) formula → PR m(omega) formula ──
# SRK (Soave 1972): m = 0.480 + 1.574*w - 0.176*w^2
# PR  (Peng-Robinson 1976): m = 0.37464 + 1.54226*w - 0.26992*w^2
code = code.replace(
    "0.480 + 1.574 * c.omega - 0.176 * c.omega * c.omega",
    "0.37464 + 1.54226 * c.omega - 0.26992 * c.omega * c.omega",
)

# ── Bug 3: Wrong cubic coefficients → correct PR cubic ──
# The PR EOS cubic is:
#   Z^3 - (1-B)*Z^2 + (A - 3B^2 - 2B)*Z - (AB - B^2 - B^3) = 0
# The buggy code uses the simplified form:
#   Z^3 - (1+B)*Z^2 + A*Z - A*B = 0
code = code.replace(
    "double c2 = -(1.0 + B);\n    double c1 = A;\n    double c0 = -A * B;",
    "double c2 = -(1.0 - B);\n"
    "    double c1 = A - 3.0 * B * B - 2.0 * B;\n"
    "    double c0 = -(A * B - B * B - B * B * B);",
)

# ── Bug 4: Missing factor of 2 in fugacity coefficient ──
# The correct PR fugacity coefficient has:
#   2 * sum_j(x_j * a_ij) / am - bi/bm
# The buggy code omits the factor of 2:
#   sum_j(x_j * a_ij) / am - bi/bm
code = code.replace(
    "double mix_deriv = sum_xj_aij / am - bi_bm;",
    "double mix_deriv = 2.0 * sum_xj_aij / am - bi_bm;",
)

if code == original:
    print("WARNING: No changes were made — bugs may already be fixed", file=sys.stderr)
    sys.exit(0)

with open("/app/flash_solver.cpp", "w") as f:
    f.write(code)

print("Fixed 4 thermodynamic bugs in flash_solver.cpp")
