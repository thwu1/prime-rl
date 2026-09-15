#!/usr/bin/env python3

"""
Reference solution: Robust GEV fitting with trimmed L-moments.

Uses the lmo library to perform contamination-robust extreme value analysis
on flood peak data, comparing untrimmed and trimmed L-moment estimation.

Key API notes for lmo 0.14.x:
- l_moment_cov(a, r_max, /) : r_max is positional-only
- l_moment(a, r, /) : r is positional-only
- l_ratio_influence is available on frozen rv instances via lmo's scipy extension
- error_sensitivity has optimizer issues; compute GES manually via minimize_scalar
"""

import json
import numpy as np
import lmo
import lmo.diagnostic
from lmo.theoretical import ppf_from_l_moments
from scipy.stats import genextreme
from scipy.optimize import minimize_scalar

data = np.load("/app/data.npy")
results = {}

# --- 1. Compute L-stats at three trim levels ---
l_stats_dict = {}
for trim_name, trim in [("trim_00", (0, 0)), ("trim_11", (1, 1)), ("trim_22", (2, 2))]:
    stats = lmo.l_stats(data, trim=trim)
    l_stats_dict[trim_name] = [float(x) for x in stats]
results["l_stats"] = l_stats_dict

# --- 2. Fit GEV at three trim levels and compute return levels ---
gev_fits = {}
return_levels = {}

for trim_name, trim in [("trim_00", (0, 0)), ("trim_11", (1, 1)), ("trim_22", (2, 2))]:
    params = genextreme.l_fit(data, trim=trim)
    # l_fit returns (c, loc, scale) for genextreme
    c, loc, scale = float(params[0]), float(params[-2]), float(params[-1])
    gev_fits[trim_name] = {"shape": c, "loc": loc, "scale": scale}

    fitted_dist = genextreme(c=c, loc=loc, scale=scale)
    return_levels[f"{trim_name}_100yr"] = float(fitted_dist.ppf(0.99))
    if trim_name == "trim_11":
        return_levels[f"{trim_name}_1000yr"] = float(fitted_dist.ppf(0.999))

results["gev_fits"] = gev_fits
results["return_levels"] = return_levels

# --- 3. L-moment covariance matrix for trim=(1,1) ---
# NOTE: r_max is positional-only in lmo 0.14.x
cov = lmo.l_moment_cov(data, 4, trim=(1, 1))
results["l_moment_cov_trim_11"] = cov.tolist()

# --- 4. Theoretical L-stats from the trim=(1,1) fitted GEV ---
fit_11 = gev_fits["trim_11"]
fitted_rv = genextreme(c=fit_11["shape"], loc=fit_11["loc"], scale=fit_11["scale"])
theo_lm = np.array([
    float(fitted_rv.l_moment(r, trim=(1, 1)))
    for r in range(1, 5)
])
results["theoretical_l_stats_trim_11"] = [
    float(theo_lm[0]),  # L-location
    float(theo_lm[1]),  # L-scale
    float(theo_lm[2] / theo_lm[1]),  # tau_3 (L-skewness ratio)
    float(theo_lm[3] / theo_lm[1]),  # tau_4 (L-kurtosis ratio)
]

# --- 5. Nonparametric quantile reconstruction from 8 TL(1,1)-moments ---
tl_8 = lmo.l_moment(data, np.arange(1, 9), trim=(1, 1))
ppf_np = ppf_from_l_moments(tl_8, trim=(1, 1))
results["nonparametric_rl_100yr"] = float(ppf_np(0.99))

# --- 6. Influence function diagnostics for L-skewness of trim=(1,1) GEV ---
if_tau3 = fitted_rv.l_ratio_influence(3, 2, trim=(1, 1))

# Compute GES manually using scipy.optimize.minimize_scalar
# because lmo.diagnostic.error_sensitivity's COBYLA optimizer
# starts at x0=0 where IF=0 and fails to find the global max.
# For GEV with c < 0, upper endpoint = loc - scale/c
if fit_11["shape"] < 0:
    upper_ep = fit_11["loc"] - fit_11["scale"] / fit_11["shape"]
    search_upper = upper_ep - 0.01
else:
    search_upper = 10000.0
res_ges = minimize_scalar(
    lambda x: -abs(if_tau3(x)),
    bounds=(-1000, search_upper),
    method="bounded",
)
ges = float(-res_ges.fun)

rp = float(lmo.diagnostic.rejection_point(if_tau3))

results["influence_diagnostics"] = {
    "gross_error_sensitivity_tau3": ges,
    "rejection_point_tau3": rp,
}

# --- Write output ---
with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)
