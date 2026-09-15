#!/usr/bin/env python3

"""
Marciniak-Kuczynski (M-K) Forming Limit Curve Predictor

Computes the forming limit curve for sheet metals using the M-K model
with support for von Mises and Hill48 yield functions and Swift hardening.
The groove is assumed perpendicular to the major stress (psi0 = 0).
"""

import sys
import json
import csv
import numpy as np
from scipy.optimize import brentq


def build_yield_helpers(yf_cfg):
    """
    Build scalar helper functions for the yield surface in plane stress
    with sigma_12 = 0.

    Returns (Ss, E1, E2, ps_alpha) where:
      Ss(alpha)  = sigma_bar / sigma_11      (equivalent stress factor)
      E1(alpha)  = d(eps_11) / d(eps_bar)    (major strain rate direction)
      E2(alpha)  = d(eps_22) / d(eps_bar)    (minor strain rate direction)
      ps_alpha   = stress ratio at plane strain (E2 = 0)
    """
    yf_type = yf_cfg["type"]

    if yf_type == "von_mises":
        def Ss(a):
            return np.sqrt(a * a - a + 1.0)

        def E1(a):
            return (2.0 - a) / (2.0 * Ss(a))

        def E2(a):
            return (2.0 * a - 1.0) / (2.0 * Ss(a))

        ps_alpha = 0.5

    elif yf_type == "hill48":
        R0 = yf_cfg["R0"]
        R45 = yf_cfg["R45"]
        R90 = yf_cfg["R90"]
        H = R0 / (1.0 + R0)
        G = 1.0 / (1.0 + R0)
        F = H / R90
        # N = (R0 + R90) * (2*R45 + 1) / (2 * R90 * (1 + R0))
        # N only appears in sigma_12 terms, unused for psi0=0

        def Ss(a):
            return np.sqrt((G + H) - 2.0 * H * a + (F + H) * a * a)

        def E1(a):
            return ((G + H) - H * a) / Ss(a)

        def E2(a):
            return (-H + (F + H) * a) / Ss(a)

        ps_alpha = H / (F + H)

    else:
        raise ValueError(f"Unknown yield function type: {yf_type}")

    return Ss, E1, E2, ps_alpha


def build_hardening(h_cfg):
    """Return the hardening function sigma_bar(eps_bar)."""
    if h_cfg["type"] == "swift":
        K = h_cfg["K"]
        eps0 = h_cfg["eps0"]
        n = h_cfg["n"]

        def hard(e):
            return K * (eps0 + max(e, 0.0)) ** n

        return hard
    raise ValueError(f"Unknown hardening type: {h_cfg['type']}")


def compute_flc_point(alpha_A, Ss, E1, E2, ps_alpha, hard, f0,
                      delta_init=5e-4, max_steps=500000,
                      necking_threshold=10.0):
    """
    Compute a single FLC point using the incremental M-K model (psi0=0).

    At each step:
      1.  Increment eps_bar_B by delta.
      2a. If plane strain: fix alpha_B = ps_alpha, solve 1-D for d(eps_bar_A).
      2b. Otherwise: solve 1-D for alpha_B using force equilibrium + compatibility.
      3.  Update thickness ratio f incrementally.
      4.  Check necking: d(eps_bar_A)/delta < 1/threshold.

    Returns (minor_strain, major_strain) or None.
    """
    e1A = E1(alpha_A)
    e2A = E2(alpha_A)
    is_ps = abs(e2A) < 1e-6

    eA = 1e-7
    eB = 1e-7
    f = f0
    delta = delta_init

    for _ in range(max_steps):
        deB = delta

        if is_ps:
            # ── Plane-strain path ──
            # alpha_B is forced to ps_alpha by compatibility (E2=0).
            aB = ps_alpha
            e1B = E1(aB)

            def _feq_ps(dea, _f=f, _eA=eA, _eB=eB):
                fn = _f * np.exp(e1A * dea - e1B * deB)
                return hard(_eA + dea) - fn * hard(_eB + deB)

            try:
                deA = brentq(_feq_ps, 0.0, deB * 20.0, xtol=1e-14)
            except (ValueError, RuntimeError):
                return None

        else:
            # ── General path ──
            # Compatibility: deA = E2(aB)/E2(alpha_A) * deB
            # Force equilibrium:
            #   hard(eA+deA)/Ss(alpha_A) = f_new * hard(eB+deB)/Ss(aB)
            #   f_new = f * exp(E1(alpha_A)*deA - E1(aB)*deB)

            def _feq_ab(ab, _f=f, _eA=eA, _eB=eB):
                e2b = E2(ab)
                dea = e2b / e2A * deB
                if dea <= 0:
                    return -1e10
                fn = _f * np.exp(e1A * dea - E1(ab) * deB)
                lhs = hard(_eA + dea) / Ss(alpha_A)
                rhs = fn * hard(_eB + deB) / Ss(ab)
                return lhs - rhs

            # Bracket: aB lies between alpha_A and ps_alpha.
            if e2A < 0:
                lo = max(-0.8, alpha_A - 0.6)
                hi = ps_alpha - 1e-10
            else:
                lo = ps_alpha + 1e-10
                hi = min(2.5, alpha_A + 0.6)

            # Verify bracket encloses a root; widen if necessary.
            try:
                flo, fhi = _feq_ab(lo), _feq_ab(hi)
                if flo * fhi > 0:
                    if e2A < 0:
                        lo = max(-1.5, lo - 0.8)
                    else:
                        hi = min(4.0, hi + 0.8)
                    flo, fhi = _feq_ab(lo), _feq_ab(hi)
                    if flo * fhi > 0:
                        return None
                aB = brentq(_feq_ab, lo, hi, xtol=1e-10, maxiter=400)
            except (ValueError, RuntimeError):
                return None

            deA = E2(aB) / e2A * deB

        if deA < 0:
            return None

        # Update state
        f *= np.exp(e1A * deA - E1(aB) * deB)
        eA += deA
        eB += deB

        ratio = deA / deB

        # Adaptive step: refine near necking
        if ratio < 0.5:
            delta = max(1e-5, delta * 0.5)
        elif ratio > 0.9 and delta < delta_init:
            delta = min(delta_init, delta * 1.5)

        # Necking criterion
        if ratio < 1.0 / necking_threshold:
            minor = e2A * eA
            major = e1A * eA
            return (minor, major)

    return None


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 mk_flc.py <config_json> <output_csv>",
              file=sys.stderr)
        sys.exit(1)

    config_path, output_path = sys.argv[1], sys.argv[2]

    with open(config_path) as fh:
        cfg = json.load(fh)

    Ss, E1, E2, ps_alpha = build_yield_helpers(cfg["yield_function"])
    hard = build_hardening(cfg["hardening"])
    f0 = cfg["mk_params"]["f0"]
    alphas = cfg["alpha_range"]

    results = []
    for alpha_A in alphas:
        pt = compute_flc_point(alpha_A, Ss, E1, E2, ps_alpha, hard, f0)
        if pt is not None:
            results.append(pt)

    results.sort(key=lambda p: p[0])

    with open(output_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["minor_strain", "major_strain"])
        for mi, ma in results:
            writer.writerow([f"{mi:.6f}", f"{ma:.6f}"])

    print(f"FLC: {len(results)} points -> {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
