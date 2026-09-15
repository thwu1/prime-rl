#!/usr/bin/env python3
"""
Robust GEV parameter estimation using Trimmed L-moments (TL-moments).

All shape parameters use scipy.stats.genextreme sign convention throughout:
  F(x, c) = exp{-(1-c*z)^{1/c}}  where z = (x-loc)/scale
  Q(u, c) = (1 - (-log u)^c) / c

  c < 0: Frechet-like (heavy right tail)
  c > 0: Weibull-like (bounded right tail)
  c = 0: Gumbel
"""
import sys
import json
import numpy as np
from math import comb, gamma as math_gamma
from scipy.optimize import brentq
from scipy.special import beta as beta_func


EULER_GAMMA = 0.5772156649015329


def compute_lmoments(data, nmom=4):
    """Compute sample L-moments using probability weighted moments (PWMs).

    PWMs: b_r = (1/n) * sum_{i=r}^{n-1} C(i,r)/C(n-1,r) * x_{i+1:n}
    Then convert to L-moments via shifted Legendre polynomial coefficients.
    """
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
    """Compute sample TL-moments with (s, t) trimming.

    Using Elamir & Seheult (2003):
    lambda_r^{(s,t)} = (1/r) * (1/C(n,r+s+t)) *
        sum_i x_{i+1:n} * sum_k (-1)^k C(r-1,k) C(i, r+s-1-k) C(n-1-i, t+k)
    """
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
    """Compute integral_0^1 Q(u) u^p du for standardized GEV(0,1,c).

    Uses scipy convention: Q(u, c) = (1 - (-log u)^c) / c.

    Result = (1/c) * [1/(p+1) - (p+1)^{-(c+1)} * Gamma(c+1)]

    Derived via substitution t = -log(u):
      integral_0^1 (-log u)^c u^p du = (p+1)^{-(c+1)} Gamma(c+1)

    Requires c > -1 for Gamma(c+1) to be finite.
    For c ~ 0 (Gumbel): returns (euler_gamma + ln(p+1)) / (p+1).
    """
    if abs(c) < 1e-10:
        return (EULER_GAMMA + np.log(p_plus_1)) / p_plus_1
    else:
        gamma_cp1 = math_gamma(1.0 + c)
        return (1.0 / c) * (1.0 / p_plus_1 - p_plus_1 ** (-(c + 1.0)) * gamma_cp1)


def theoretical_tlmoment_std(r, s, t, c):
    """Compute theoretical TL-moment of standardized GEV(0, 1, c).

    Uses scipy sign convention for c.

    Population TL-moment formula:
    lambda_r^{(s,t)} = (1/r) sum_k (-1)^k C(r-1,k) E[Q(U_{j:m})]
    where j = r+s-k, m = r+s+t.

    E[Q(U_{j:m})] is computed by expanding (1-u)^{m-j} via the binomial
    theorem and using the closed-form PWM integral for each term.
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
            p_plus_1 = j + i
            integral_sum += ci * si * _gev_pwm_integral(p_plus_1, c)

        expected_os = integral_sum / beta_func(j, m - j + 1)
        total += sign * c1 * expected_os

    return total / r


def fit_gev_lmom(lmom):
    """Fit GEV parameters using method of L-moments (Hosking 1997).

    Hosking's GEV: F(x) = exp{-[1 - k(x-xi)/alpha]^{1/k}}
    This is identical to scipy's convention with k = c.

    L-moment relations:
      tau3 = 2(1-3^{-k})/(1-2^{-k}) - 3
      alpha = lambda2 * k / ((1-2^{-k}) * Gamma(1+k))
      xi = lambda1 - alpha * (1-Gamma(1+k)) / k

    Returns (loc, scale, shape) where shape is scipy's c = k.
    """
    l1, l2 = lmom[0], lmom[1]
    t3 = lmom[2] / lmom[1]

    gumbel_tau3 = 2 * np.log(3) / np.log(2) - 3

    def tau3_residual(k):
        if abs(k) < 1e-8:
            return gumbel_tau3 - t3
        return 2.0 * (1.0 - 3.0 ** (-k)) / (1.0 - 2.0 ** (-k)) - 3.0 - t3

    try:
        k = brentq(tau3_residual, -0.99, 5.0, xtol=1e-12)
    except ValueError:
        c_approx = 2.0 / (3.0 + t3) - np.log(2) / np.log(3)
        k = 7.8590 * c_approx + 2.9554 * c_approx ** 2

    if abs(k) < 1e-8:
        alpha = l2 / np.log(2)
        xi = l1 - alpha * EULER_GAMMA
        return float(xi), float(alpha), 0.0

    gk = math_gamma(1 + k)
    alpha = l2 * k / ((1 - 2 ** (-k)) * gk)
    xi = l1 - alpha * (1 - gk) / k

    # k = c_scipy (Hosking k equals scipy c)
    return float(xi), float(alpha), float(k)


def fit_gev_tlmom(tlmom, s=1, t=1):
    """Fit GEV parameters using method of TL-moments.

    Strategy:
    1. Match TL-skewness ratio to find shape c via root-finding
    2. Recover scale from second TL-moment
    3. Recover location from first TL-moment

    Returns (loc, scale, shape) in scipy convention.
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

    return float(loc), float(scale), float(c_fit)


def main():
    data_path = sys.argv[1] if len(sys.argv) > 1 else '/app/observations.npy'
    data = np.load(data_path)

    lmom = compute_lmoments(data, nmom=4)
    tlmom = compute_tlmoments(data, s=1, t=1, nmom=4)

    lratios = [lmom[2] / lmom[1], lmom[3] / lmom[1]]
    tlratios = [tlmom[2] / tlmom[1], tlmom[3] / tlmom[1]]

    loc_l, scale_l, c_l = fit_gev_lmom(lmom)
    loc_tl, scale_tl, c_tl = fit_gev_tlmom(tlmom, s=1, t=1)

    results = {
        "lmoments": lmom,
        "tlmoments": tlmom,
        "lratios": lratios,
        "tlratios": tlratios,
        "gev_params_lmom": {"loc": loc_l, "scale": scale_l, "shape": c_l},
        "gev_params_tlmom": {"loc": loc_tl, "scale": scale_tl, "shape": c_tl}
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
