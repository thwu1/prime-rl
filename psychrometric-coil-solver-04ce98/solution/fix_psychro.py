"""
Fix four bugs in /app/psychro.c:

1. Reversed triple-point branching in GetSatVapPres and dLnPws_
   (uses ice formula above 0.01 C and liquid formula below — swapped)
2. Below-freezing branch of GetHumRatioFromTWetBulb uses the
   above-freezing formula (wrong coefficients)
3. Bisection tolerance in GetTWetBulbFromHumRatio is 100x too large
4. Molecular weight ratio coefficient in GetMoistAirVolume is
   1.007858 instead of the correct 1.607858

"""

with open("/app/psychro.c", "r") as f:
    src = f.read()

# --- Bug 1: Fix triple-point comparison direction ---
# Both GetSatVapPres and dLnPws_ use ">=" when they should use "<="
# This swaps which formula (ice vs liquid) is used for each temp range.
src = src.replace(
    "TDryBulb >= TRIPLE_POINT_WATER_SI",
    "TDryBulb <= TRIPLE_POINT_WATER_SI",
)

# --- Bug 2: Fix below-freezing formula in GetHumRatioFromTWetBulb ---
# The else branch incorrectly uses the above-freezing formula.
# Replace with the correct below-freezing coefficients (eqn 35).
src = src.replace(
    '      HumRatio = ((2501. - 2.326 * TWetBulb) * Wsstar - 1.006 * (TDryBulb - TWetBulb))\n'
    '         / (2501. + 1.86 * TDryBulb - 4.186 * TWetBulb);  /* below freezing */',
    '      HumRatio = ((2830. - 0.24 * TWetBulb) * Wsstar - 1.006 * (TDryBulb - TWetBulb))\n'
    '         / (2830. + 1.86 * TDryBulb - 2.1 * TWetBulb);',
)

# --- Bug 3: Fix bisection tolerance ---
# The tolerance multiplier makes the solver 100x too coarse.
src = src.replace(
    "100.0 * PSYCHROLIB_TOLERANCE",
    "PSYCHROLIB_TOLERANCE",
)

# --- Bug 4: Fix molecular weight ratio in GetMoistAirVolume ---
# 1.007858 should be 1.607858 (= M_da / M_w = 28.966 / 18.015)
src = src.replace("1.007858", "1.607858")

with open("/app/psychro.c", "w") as f:
    f.write(src)

print("All four bugs in psychro.c have been fixed.")
