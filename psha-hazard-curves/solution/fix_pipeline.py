#!/usr/bin/env python3
"""
Fix all bugs in the PSHA pipeline core modules.

Applies targeted corrections to four modules where numerical
or mathematical errors produce incorrect hazard results.

"""

import os


def fix_file(path, old, new):
    with open(path) as f:
        content = f.read()
    if old not in content:
        return False
    content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)
    return True


# --- Bug 1: mfd.py ---
# The Gutenberg-Richter discretization computes incremental rates
# using bin edges [m, m+dm] instead of the correct centered edges
# [m-dm/2, m+dm/2]. This shifts the effective magnitude of each
# bin and systematically biases all GR source rates.
fix_file(
    "/app/pipeline/mfd.py",
    "rate = 10.0 ** (a - b * m) - 10.0 ** (a - b * (m + dm))",
    "rate = 10.0 ** (a - b * (m - dm / 2.0)) - 10.0 ** (a - b * (m + dm / 2.0))",
)

# --- Bug 2: distance.py ---
# The horizontal_distance function passes the average latitude
# directly to math.cos() without converting degrees to radians.
# Python's math.cos() expects radians, so cos(37.8) is evaluated
# as cos(37.8 radians) instead of cos(37.8 degrees), distorting
# the longitudinal distance correction for all point sources.
fix_file(
    "/app/pipeline/distance.py",
    "dx = (lon2 - lon1) * math.cos(avg_lat) * km_per_deg",
    "dx = (lon2 - lon1) * math.cos(math.radians(avg_lat)) * km_per_deg",
)

# --- Bug 3: gmm.py ---
# The site amplification term uses ln(Vref/Vs30) instead of the
# correct ln(Vs30/Vref). Since the site coefficient s is negative,
# this reverses the direction of site amplification — a soft-soil
# site (Vs30 < Vref) is treated as if it de-amplifies ground motion,
# when it should amplify it.
fix_file(
    "/app/pipeline/gmm.py",
    'c["s"] * math.log(vref / vs30)',
    'c["s"] * math.log(vs30 / vref)',
)

# --- Bug 4: hazard.py ---
# The rupture length scaling uses math.exp() (base e) instead of
# 10.0** (base 10) for the Wells-Coppersmith relation. The formula
# is log10(L) = -2.44 + 0.59*M, so L = 10^(...), not e^(...).
# Using exp() produces ruptures ~4x shorter than correct, causing
# excessive floating positions and wrong average distances for
# the fault source.
fix_file(
    "/app/pipeline/hazard.py",
    "rup_len = math.exp(-2.44 + 0.59 * mag)",
    "rup_len = 10.0 ** (-2.44 + 0.59 * mag)",
)

print("All core pipeline fixes applied successfully.")
