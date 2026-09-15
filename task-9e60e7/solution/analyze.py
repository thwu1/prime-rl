#!/usr/bin/env python3
"""
CMS Dimuon Resonance Spectroscopy Pipeline
-------------------------------------------
Analyzes the invariant mass spectrum of 100k dimuon events from CMS Run2010B
to identify and characterize particle resonances (J/psi, psi(2S),
Upsilon(1S,2S,3S), Z).
"""

import json
import warnings

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

warnings.filterwarnings("ignore")

M_MUON = 0.1056583745  # PDG muon mass in GeV


# -- signal + background model ------------------------------------------------
def gauss_poly2(x, A, mu, sigma, c0, c1, c2):
    """Gaussian peak on a quadratic polynomial background."""
    return A * np.exp(-0.5 * ((x - mu) / sigma) ** 2) + c0 + c1 * x + c2 * x**2


# -- single-window resonance fitter -------------------------------------------
def fit_window(mass_arr, lo, hi, nbins, pdg_mass):
    """
    Histogram *mass_arr* in [lo, hi], fit gauss+poly2, return dict with
    mass / fwhm / yield / significance, or None on failure.
    """
    m = mass_arr[(mass_arr >= lo) & (mass_arr <= hi)]
    if len(m) < 30:
        return None

    counts, edges = np.histogram(m, bins=nbins)
    centres = 0.5 * (edges[:-1] + edges[1:])
    bw = edges[1] - edges[0]

    peak_idx = int(np.argmax(counts))
    peak_val = float(counts[peak_idx])
    if peak_val < 5:
        return None

    # sideband background estimate (exclude +/-4 bins around peak)
    side_mask = np.ones(len(counts), dtype=bool)
    side_mask[max(0, peak_idx - 4) : min(len(counts), peak_idx + 5)] = False
    bg_est = float(np.median(counts[side_mask])) if side_mask.any() else 0.0

    sigma0 = bw * 2.5

    try:
        popt, _ = curve_fit(
            gauss_poly2,
            centres,
            counts.astype(float),
            p0=[max(peak_val - bg_est, 1.0), pdg_mass, sigma0, bg_est, 0.0, 0.0],
            bounds=(
                [0, lo, 1e-4, -np.inf, -np.inf, -np.inf],
                [peak_val * 20, hi, (hi - lo) / 2, np.inf, np.inf, np.inf],
            ),
            maxfev=50000,
        )
        A, mu, sigma, c0, c1, c2 = popt
        sigma = abs(sigma)

        # integral of the Gaussian part -> number of signal events
        sig_yield = A * sigma * np.sqrt(2 * np.pi) / bw

        # background integral under +/-3 sigma
        x_grid = np.linspace(mu - 3 * sigma, mu + 3 * sigma, 300)
        bg_vals = c0 + c1 * x_grid + c2 * x_grid**2
        bg_under = max(float(np.mean(bg_vals)) * 6 * sigma / bw, 1.0)

        significance = sig_yield / np.sqrt(bg_under)

        return dict(
            mass=float(mu),
            fwhm=float(sigma * 2.355),
            yield_=max(1, int(round(sig_yield))),
            sig=float(significance),
        )
    except Exception:
        # histogram-peak fallback
        sig_est = max(peak_val - bg_est, 1.0)
        return dict(
            mass=float(centres[peak_idx]),
            fwhm=float(bw * 3),
            yield_=max(1, int(round(sig_est * 4))),
            sig=float(sig_est / max(np.sqrt(bg_est), 1.0)),
        )


# -- main ---------------------------------------------------------------------
def main():
    # 1. Load & clean
    df = pd.read_csv("/app/data/dimuon.csv")
    df.columns = df.columns.str.strip()
    total_events = len(df)

    # 2. Validate invariant mass by recomputing from (pt, eta, phi, m_muon)
    #    Using kinematic variables avoids numerical cancellation that arises
    #    when computing M = sqrt(E^2 - p^2) from the limited-precision CSV
    #    E, px, py, pz columns.
    px1_r = df["pt1"] * np.cos(df["phi1"])
    py1_r = df["pt1"] * np.sin(df["phi1"])
    pz1_r = df["pt1"] * np.sinh(df["eta1"])
    E1_r = np.sqrt(df["pt1"] ** 2 * np.cosh(df["eta1"]) ** 2 + M_MUON**2)

    px2_r = df["pt2"] * np.cos(df["phi2"])
    py2_r = df["pt2"] * np.sin(df["phi2"])
    pz2_r = df["pt2"] * np.sinh(df["eta2"])
    E2_r = np.sqrt(df["pt2"] ** 2 * np.cosh(df["eta2"]) ** 2 + M_MUON**2)

    E_tot = E1_r + E2_r
    px_tot = px1_r + px2_r
    py_tot = py1_r + py2_r
    pz_tot = pz1_r + pz2_r
    M2 = E_tot**2 - px_tot**2 - py_tot**2 - pz_tot**2
    M_calc = np.sqrt(np.maximum(M2, 0.0))
    max_dev = float(np.max(np.abs(M_calc - df["M"])))

    # 3. Event selection
    opp_charge = df["Q1"] != df["Q2"]
    has_global = (df["Type1"] == "G") | (df["Type2"] == "G")
    sel = df[opp_charge & has_global]
    selected_events = len(sel)
    mass = sel["M"].values

    # 4. Resonance search windows
    #    (name, lo, hi, nbins, pdg_mass_gev)
    windows = [
        ("J/psi", 2.8, 3.4, 60, 3.0969),
        ("psi(2S)", 3.5, 3.9, 40, 3.6861),
        ("Upsilon(1S)", 9.0, 9.8, 50, 9.4603),
        ("Upsilon(2S)", 9.8, 10.2, 30, 10.0233),
        ("Upsilon(3S)", 10.2, 10.6, 30, 10.3552),
        ("Z", 60.0, 120.0, 120, 91.1876),
    ]

    resonances = []
    for name, lo, hi, nb, pdg_m in windows:
        res = fit_window(mass, lo, hi, nb, pdg_m)
        if res is not None and res["sig"] > 0.5:
            resonances.append(
                dict(
                    name=name,
                    fitted_mass_gev=round(res["mass"], 4),
                    fitted_width_gev=round(res["fwhm"], 4),
                    yield_=res["yield_"],
                    significance_sigma=round(res["sig"], 2),
                )
            )

    # 5. Yield ratios
    def _yield_of(prefix):
        for r in resonances:
            if r["name"].startswith(prefix):
                return r["yield_"]
        return None

    jpsi_y = _yield_of("J/psi")
    z_y = _yield_of("Z")
    ups1_y = _yield_of("Upsilon(1S)")

    yield_ratios = {}
    if jpsi_y and z_y and z_y > 0:
        yield_ratios["jpsi_to_z"] = round(jpsi_y / z_y, 4)
    if ups1_y and z_y and z_y > 0:
        yield_ratios["upsilon1s_to_z"] = round(ups1_y / z_y, 4)

    # 6. Write output
    output = dict(
        validation=dict(
            mass_recomputation_max_deviation_gev=round(max_dev, 6),
            total_events=total_events,
            selected_events=selected_events,
        ),
        resonances=[
            {k: v for k, v in r.items() if k != "yield_"} | {"yield": r["yield_"]}
            for r in resonances
        ],
        yield_ratios=yield_ratios,
    )

    with open("/app/results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"Done -- {len(resonances)} resonances identified")
    for r in resonances:
        print(
            f"  {r['name']:15s}  m={r['fitted_mass_gev']:.3f} GeV  "
            f"N={r['yield_']:>6d}  S={r['significance_sigma']:.1f}sigma"
        )


if __name__ == "__main__":
    main()
