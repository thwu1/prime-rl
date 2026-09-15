#!/usr/bin/env python3
"""
Multi-site GEV analysis with automatic contamination detection and robust estimation.

Explores the environment, diagnoses data quality issues, and applies TL-moment
estimation for contaminated sites, standard L-moment estimation for clean sites.
"""

import json
import os
import numpy as np
from math import comb, gamma as math_gamma
from scipy.optimize import brentq
from scipy.special import beta as beta_func


EULER_GAMMA = 0.5772156649015329


def compute_lmoments(data, nmom=4):
    """Compute sample L-moments via probability weighted moments (PWMs)."""
    x = np.sort(data)
    n = len(x)
    b = np.zeros(nmom)
    for r in range(nmom):
        cn = comb(n - 1, r)
        for i in range(r, n):
            b[r] += comb(i, r) * x[i] / cn
        b[r] /= n
    lmom = np.zeros(nmom)
    for r in range(1, nmom + 1):
        for k in range(r):
            p = (-1) ** (r - 1 - k) * comb(r - 1, k) * comb(r - 1 + k, k)
            lmom[r - 1] += p * b[k]
    return lmom.tolist()


def compute_tlmoments(data, s=1, t=1, nmom=4):
    """Compute sample TL-moments using Elamir-Seheult (2003) formula."""
    x = np.sort(data)
    n = len(x)
    tlmom = []
    for r in range(1, nmom + 1):
        denom = comb(n, r + s + t)
        total = 0.0
        for i in range(n):
            weight = 0
            for k in range(r):
                c1 = (-1) ** k * comb(r - 1, k)
                c2 = comb(i, r + s - 1 - k)
                c3 = comb(n - 1 - i, t + k)
                weight += c1 * c2 * c3
            total += weight * x[i]
        total /= (r * denom)
        tlmom.append(float(total))
    return tlmom


def _gev_pwm_integral(p_plus_1, c):
    """Integral of standardized GEV quantile function times u^p.

    integral_0^1 Q(u) * u^p du  where Q(u, c) = (1 - (-log u)^c) / c
    = (1/c) * [1/(p+1) - Gamma(1+c) / (p+1)^{1+c}]
    """
    if abs(c) < 1e-10:
        return (EULER_GAMMA + np.log(p_plus_1)) / p_plus_1
    gamma_cp1 = math_gamma(1.0 + c)
    return (1.0 / c) * (1.0 / p_plus_1 - p_plus_1 ** (-(c + 1.0)) * gamma_cp1)


def theoretical_tlmoment_std(r, s, t, c):
    """Theoretical TL-moment of standardized GEV(0, 1, c).

    Uses binomial expansion of order statistic density and closed-form
    PWM integral identities involving gamma functions.
    """
    m = r + s + t
    total = 0.0
    for k in range(r):
        j = r + s - k
        sign = (-1) ** k
        c1 = comb(r - 1, k)
        integral_sum = 0.0
        for i in range(m - j + 1):
            ci = comb(m - j, i)
            si = (-1) ** i
            integral_sum += ci * si * _gev_pwm_integral(j + i, c)
        expected_os = integral_sum / beta_func(j, m - j + 1)
        total += sign * c1 * expected_os
    return total / r


def fit_gev_lmom(lmom):
    """Fit GEV via L-moment matching (Hosking 1997)."""
    l1, l2 = lmom[0], lmom[1]
    t3 = lmom[2] / lmom[1]

    def tau3_residual(k):
        if abs(k) < 1e-8:
            return 2 * np.log(3) / np.log(2) - 3 - t3
        return 2.0 * (1.0 - 3.0 ** (-k)) / (1.0 - 2.0 ** (-k)) - 3.0 - t3

    try:
        k = brentq(tau3_residual, -0.99, 5.0, xtol=1e-12)
    except ValueError:
        k = 0.0

    if abs(k) < 1e-8:
        alpha = l2 / np.log(2)
        xi = l1 - alpha * EULER_GAMMA
        return {"loc": float(xi), "scale": float(alpha), "shape": 0.0}

    gk = math_gamma(1 + k)
    alpha = l2 * k / ((1 - 2 ** (-k)) * gk)
    xi = l1 - alpha * (1 - gk) / k
    return {"loc": float(xi), "scale": float(alpha), "shape": float(k)}


def fit_gev_tlmom(tlmom, s=1, t=1):
    """Fit GEV via TL-moment matching.

    1. Match TL-skewness ratio to find shape c via root-finding
    2. Recover scale from TL_2
    3. Recover location from TL_1
    """
    tl1, tl2, tl3 = tlmom[0], tlmom[1], tlmom[2]
    tt3 = tl3 / tl2

    def tlratio_residual(c):
        b2 = theoretical_tlmoment_std(2, s, t, c)
        b3 = theoretical_tlmoment_std(3, s, t, c)
        if abs(b2) < 1e-15:
            return 1e10
        return b3 / b2 - tt3

    try:
        c_fit = brentq(tlratio_residual, -0.99, 0.99, xtol=1e-10)
    except ValueError:
        try:
            c_fit = brentq(tlratio_residual, -0.5, 0.5, xtol=1e-10)
        except ValueError:
            c_fit = 0.0

    b1 = theoretical_tlmoment_std(1, s, t, c_fit)
    b2 = theoretical_tlmoment_std(2, s, t, c_fit)
    scale = tl2 / b2
    loc = tl1 - scale * b1
    return {"loc": float(loc), "scale": float(scale), "shape": float(c_fit)}


def detect_contamination(lmom, tlmom):
    """Detect contamination by comparing L-moment and TL-moment GEV estimates.

    If estimates diverge significantly, the data likely contains outliers that
    affect L-moments but not TL-moments.
    """
    gev_lmom = fit_gev_lmom(lmom)
    gev_tlmom = fit_gev_tlmom(tlmom)

    shape_diff = abs(gev_lmom['shape'] - gev_tlmom['shape'])
    scale_ratio = max(gev_lmom['scale'], gev_tlmom['scale']) / max(
        min(gev_lmom['scale'], gev_tlmom['scale']), 1e-10
    )
    loc_diff = abs(gev_lmom['loc'] - gev_tlmom['loc']) / max(abs(gev_lmom['loc']), 1.0)

    return (shape_diff > 0.1) or (scale_ratio > 1.5) or (loc_diff > 0.2)


def main():
    # Read pipeline configuration
    with open('/app/config.json', 'r') as f:
        config = json.load(f)

    input_dir = config['pipeline']['input_dir']
    output_file = config['pipeline']['output_file']

    # Discover data files
    data_files = sorted([f for f in os.listdir(input_dir) if f.endswith('.npy')])
    print(f"Found {len(data_files)} data files in {input_dir}")

    results = {"sites": {}}

    for fname in data_files:
        site_name = fname.replace('.npy', '')
        data = np.load(os.path.join(input_dir, fname))
        print(f"\nAnalyzing {site_name} (n={len(data)})...")

        # Compute both L-moments and TL-moments
        lmom = compute_lmoments(data)
        tlmom = compute_tlmoments(data, s=1, t=1)

        lratios = [lmom[2] / lmom[1], lmom[3] / lmom[1]]
        tlratios = [tlmom[2] / tlmom[1], tlmom[3] / tlmom[1]]

        # Detect contamination via estimate divergence
        contaminated = detect_contamination(lmom, tlmom)

        if contaminated:
            gev_params = fit_gev_tlmom(tlmom)
            method = "tlmom"
            quality = "contaminated"
            print(f"  Data quality: CONTAMINATED - using TL-moment estimation")
        else:
            gev_params = fit_gev_lmom(lmom)
            method = "lmom"
            quality = "clean"
            print(f"  Data quality: CLEAN - using L-moment estimation")

        print(f"  GEV params: loc={gev_params['loc']:.4f}, "
              f"scale={gev_params['scale']:.4f}, shape={gev_params['shape']:.4f}")

        results["sites"][site_name] = {
            "lmoments": lmom,
            "tlmoments": tlmom,
            "lratios": lratios,
            "tlratios": tlratios,
            "gev_params": gev_params,
            "estimation_method": method,
            "data_quality": quality,
        }

    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to {output_file}")


if __name__ == '__main__':
    main()
