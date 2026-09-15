
"""
Extreme value distribution diagnostics solver.

Strategy:
1. Estimate GEV parameters via L-moments (efficient but sensitive to outliers)
2. Estimate GEV parameters via quartiles (robust to tail contamination)
3. If the two estimates diverge significantly, flag contamination
4. For contaminated data, use the robust estimate to identify outliers,
   remove them, and re-estimate with L-moments on the cleaned sample
"""

import numpy as np
from math import comb, gamma, log
from scipy.optimize import brentq
import json

EULER_MASCHERONI = 0.5772156649015329


# ---------------------------------------------------------------------------
# L-moment computation via probability weighted moments
# ---------------------------------------------------------------------------

def compute_lmoments(data, num_moments=4):
    """Sample L-moments via PWMs with shifted Legendre polynomial conversion."""
    x = np.sort(data).astype(np.float64)
    n = len(x)

    betas = []
    for r in range(num_moments):
        cn1r = comb(n - 1, r)
        b = 0.0
        for i in range(r, n):
            b += comb(i, r) / cn1r * x[i]
        b /= n
        betas.append(b)

    lmom = [betas[0]]
    if num_moments >= 2:
        lmom.append(2 * betas[1] - betas[0])
    if num_moments >= 3:
        lmom.append(6 * betas[2] - 6 * betas[1] + betas[0])
    if num_moments >= 4:
        lmom.append(20 * betas[3] - 30 * betas[2] + 12 * betas[1] - betas[0])
    return lmom


# ---------------------------------------------------------------------------
# GEV L-moment ratio relationships
# ---------------------------------------------------------------------------

def gev_tau3(xi):
    """Theoretical GEV L-skewness as function of shape parameter."""
    if abs(xi) < 1e-10:
        return 2 * log(3) / log(2) - 3
    return 2 * (1 - 3 ** xi) / (1 - 2 ** xi) - 3


# ---------------------------------------------------------------------------
# GEV fitting from L-moments
# ---------------------------------------------------------------------------

def fit_gev_from_lmom(lmom):
    """Estimate GEV (xi, sigma, mu) from sample L-moments."""
    l1, l2, l3, l4 = lmom[:4]
    tau3 = l3 / l2

    xi = brentq(lambda x: gev_tau3(x) - tau3, -0.99, 5.0, xtol=1e-12)

    if abs(xi) < 1e-8:
        sigma = l2 / log(2)
        mu = l1 - sigma * EULER_MASCHERONI
    else:
        g1 = gamma(1 - xi)
        sigma = l2 * xi / ((2 ** xi - 1) * g1)
        mu = l1 - sigma * (g1 - 1) / xi

    return xi, sigma, mu


# ---------------------------------------------------------------------------
# Robust GEV fitting from quartiles
# ---------------------------------------------------------------------------

def _h_func(xi, y):
    """GEV quantile helper: Q(p) = mu + sigma * h(xi, -ln(p))."""
    if abs(xi) < 1e-10:
        return -log(y)
    return (y ** (-xi) - 1) / xi


def fit_gev_quantiles(data):
    """Robust GEV fit using quartiles (25% breakdown point)."""
    q25, q50, q75 = float(np.percentile(data, 25)), \
                     float(np.percentile(data, 50)), \
                     float(np.percentile(data, 75))

    sample_r = (q50 - q25) / (q75 - q25)

    y25 = -log(0.25)
    y50 = -log(0.50)
    y75 = -log(0.75)

    def ratio_eq(xi):
        h25 = _h_func(xi, y25)
        h50 = _h_func(xi, y50)
        h75 = _h_func(xi, y75)
        return (h50 - h25) / (h75 - h25) - sample_r

    try:
        xi = brentq(ratio_eq, -0.99, 5.0, xtol=1e-8)
    except ValueError:
        xi = 0.0

    h25 = _h_func(xi, y25)
    h50 = _h_func(xi, y50)
    h75 = _h_func(xi, y75)

    sigma = (q75 - q25) / (h75 - h25)
    mu = q50 - sigma * h50

    return xi, sigma, mu


# ---------------------------------------------------------------------------
# GEV CDF and return level
# ---------------------------------------------------------------------------

def gev_cdf(x, xi, sigma, mu):
    """GEV cumulative distribution function (scalar)."""
    if abs(xi) < 1e-10:
        z = (x - mu) / sigma
        return float(np.exp(-np.exp(-z)))
    t = 1 + xi * (x - mu) / sigma
    if t <= 0:
        return 0.0 if xi > 0 else 1.0
    return float(np.exp(-t ** (-1.0 / xi)))


def gev_return_level(xi, sigma, mu, T):
    """GEV return level for return period T."""
    p = 1 - 1.0 / T
    if abs(xi) < 1e-10:
        return mu - sigma * log(-log(p))
    return mu + sigma * ((-log(p)) ** (-xi) - 1) / xi


# ---------------------------------------------------------------------------
# Station analysis
# ---------------------------------------------------------------------------

def analyze_station(data):
    """Full diagnostic for a single station dataset."""
    n = len(data)

    # ---- L-moment estimate (efficient, outlier-sensitive) ----
    lmom = compute_lmoments(data, 4)
    xi_lmom, sigma_lmom, mu_lmom = fit_gev_from_lmom(lmom)

    # ---- Quartile-based estimate (robust, 25% breakdown) ----
    xi_quant, sigma_quant, mu_quant = fit_gev_quantiles(data)

    # ---- Contamination detection ----
    # Use multiple criteria; require substantial evidence of contamination.
    contaminated = False

    # Criterion 1: L-moment vs quartile shape parameter divergence.
    # Clean data with n=800 typically has |diff| < 0.10. Contaminated data
    # produces |diff| > 0.3 because outliers inflate L-moment estimates
    # while quartiles remain stable.
    xi_divergence = abs(xi_lmom - xi_quant)
    if xi_divergence > 0.15:
        contaminated = True

    # Criterion 2: relative scale divergence (sigma)
    sigma_divergence = abs(sigma_lmom - sigma_quant) / max(sigma_lmom, sigma_quant)
    if sigma_divergence > 0.25 and xi_divergence > 0.10:
        contaminated = True

    # ---- Final parameter estimation ----
    if contaminated:
        # Use robust estimate to identify outliers, then re-fit L-moments
        # on cleaned data for better precision
        mask = np.ones(n, dtype=bool)
        for i in range(n):
            p = gev_cdf(data[i], xi_quant, sigma_quant, mu_quant)
            if p > 0.999 or p < 0.001:
                mask[i] = False

        clean_data = data[mask]
        if len(clean_data) > 50:
            lmom_clean = compute_lmoments(clean_data, 4)
            xi, sigma, mu = fit_gev_from_lmom(lmom_clean)
        else:
            xi, sigma, mu = xi_quant, sigma_quant, mu_quant

        suspect_fraction = round(float(np.sum(~mask)) / n, 4)
    else:
        xi, sigma, mu = xi_lmom, sigma_lmom, mu_lmom
        suspect_fraction = 0.0

    # ---- Family classification ----
    if xi > 0.05:
        family = "frechet"
    elif xi < -0.05:
        family = "weibull"
    else:
        family = "gumbel"

    # ---- Return levels ----
    T100 = gev_return_level(xi, sigma, mu, 100)
    T500 = gev_return_level(xi, sigma, mu, 500)

    return {
        "family": family,
        "params": {"xi": float(xi), "sigma": float(sigma), "mu": float(mu)},
        "return_levels": {"T100": float(T100), "T500": float(T500)},
        "contaminated": bool(contaminated),
        "suspect_fraction": float(suspect_fraction),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    stations = ['station_A', 'station_B', 'station_C', 'station_D', 'station_E']
    report = {}

    for name in stations:
        data = np.loadtxt(f'/data/{name}.csv')
        result = analyze_station(data)
        report[name] = result
        print(f"{name}: family={result['family']}, "
              f"xi={result['params']['xi']:.4f}, "
              f"sigma={result['params']['sigma']:.4f}, "
              f"mu={result['params']['mu']:.4f}, "
              f"contaminated={result['contaminated']}, "
              f"suspect_fraction={result['suspect_fraction']:.4f}")

    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print("\nReport written to /app/report.json")


if __name__ == '__main__':
    main()
