#!/usr/bin/env python3
"""
Automated dimuon resonance spectroscopy pipeline.
Loads CMS-format dimuon CSV, applies physics cuts, detects particle resonances
via background-subtracted peak finding, fits each peak, and matches to PDG masses.
"""

import json
import warnings
import numpy as np
import pandas as pd
from scipy import signal as sig
from scipy.ndimage import uniform_filter1d
from scipy.optimize import curve_fit

warnings.filterwarnings("ignore")

# PDG reference masses (GeV)
PDG_MASSES = {
    "rho_omega": 0.775,
    "phi": 1.019,
    "J_psi": 3.097,
    "psi_prime": 3.686,
    "Upsilon_1S": 9.460,
    "Upsilon_2S": 10.023,
    "Upsilon_3S": 10.355,
    "Z": 91.188,
}

DATA_PATH = "/app/data/dimuon_events.csv"
CATALOG_OUT = "/app/resonance_catalog.json"
SUMMARY_OUT = "/app/analysis_summary.json"


def load_data():
    df = pd.read_csv(DATA_PATH)
    df.columns = df.columns.str.strip()
    total = len(df)
    nan_rows = df.isnull().any(axis=1).sum()
    df = df.dropna().reset_index(drop=True)
    return df, total, int(nan_rows)


def apply_quality_cuts(df):
    mask = (
        (df["Q1"].astype(int) * df["Q2"].astype(int) < 0)
        & ((df["Type1"] == "G") | (df["Type2"] == "G"))
        & (df["pt1"] > 2.0)
        & (df["pt2"] > 2.0)
        & (np.abs(df["eta1"]) < 2.4)
        & (np.abs(df["eta2"]) < 2.4)
    )
    return df[mask].reset_index(drop=True)


def validate_invariant_mass(df):
    E_tot = df["E1"] + df["E2"]
    px_tot = df["px1"] + df["px2"]
    py_tot = df["py1"] + df["py2"]
    pz_tot = df["pz1"] + df["pz2"]
    M_recomp = np.sqrt(np.maximum(
        E_tot ** 2 - px_tot ** 2 - py_tot ** 2 - pz_tot ** 2, 0
    ))
    diff = np.abs(M_recomp.values - df["M"].values)
    return float(diff.max()), float(diff.mean())


def build_spectrum(masses, n_bins=400, m_min=0.25, m_max=150.0):
    log_edges = np.logspace(np.log10(m_min), np.log10(m_max), n_bins + 1)
    counts, _ = np.histogram(masses, bins=log_edges)
    centers = np.sqrt(log_edges[:-1] * log_edges[1:])
    widths = log_edges[1:] - log_edges[:-1]
    return counts.astype(float), centers, widths, log_edges


def estimate_background(counts, iterations=30):
    y = np.log1p(counts.copy())
    bg = y.copy()
    for p in range(iterations, 0, -1):
        for i in range(p, len(bg) - p):
            bg[i] = min(bg[i], 0.5 * (bg[i - p] + bg[i + p]))
    bg = uniform_filter1d(bg, size=7)
    return np.expm1(np.maximum(bg, 0))


def detect_peaks(counts, centers, background, min_sig=3.0):
    noise = np.sqrt(np.maximum(background, 1.0))
    excess = (counts - background) / noise

    peaks, props = sig.find_peaks(
        excess,
        height=min_sig,
        distance=4,
        prominence=1.5,
    )

    results = []
    for pk in peaks:
        results.append({
            "bin_idx": int(pk),
            "mass_approx": float(centers[pk]),
            "excess_sigma": float(excess[pk]),
        })
    return results


def gaussian_plus_linear(x, amp, mu, sigma, a, b):
    return amp * np.exp(-0.5 * ((x - mu) / sigma) ** 2) + a * x + b


def fit_peak(masses_arr, center_guess):
    half_w = max(center_guess * 0.08, 0.04)
    lo, hi = center_guess - half_w, center_guess + half_w
    local = masses_arr[(masses_arr > lo) & (masses_arr < hi)]

    if len(local) < 30:
        return center_guess, half_w / 4, max(len(local), 1), 1.0

    n_bins = min(60, max(20, len(local) // 8))
    hist_c, edges = np.histogram(local, bins=n_bins)
    bin_c = 0.5 * (edges[:-1] + edges[1:])
    bw = edges[1] - edges[0]

    try:
        sigma_g = half_w / 6
        p0 = [hist_c.max(), center_guess, sigma_g, 0, float(np.median(hist_c))]
        lo_b = [0, lo, bw * 0.3, -np.inf, -np.inf]
        hi_b = [hist_c.max() * 5, hi, half_w, np.inf, np.inf]
        popt, _ = curve_fit(
            gaussian_plus_linear, bin_c, hist_c.astype(float),
            p0=p0, bounds=(lo_b, hi_b), maxfev=10000
        )
        amp, mu, sigma, a_coef, b_coef = popt
        sigma = abs(sigma)
        yield_n = int(max(amp * sigma * np.sqrt(2 * np.pi) / bw, 1))
        bkg_val = max(a_coef * mu + b_coef, 0.5)
        significance = amp / np.sqrt(bkg_val) if bkg_val > 0 else amp
        return float(mu), float(sigma), yield_n, float(significance)
    except Exception:
        return center_guess, half_w / 4, max(len(local), 1), 1.0


def match_pdg(measured_mass):
    best_name, best_pdg, best_frac = None, 0, float("inf")
    for name, pdg_m in PDG_MASSES.items():
        frac = abs(measured_mass - pdg_m) / pdg_m
        if frac < best_frac:
            best_frac = frac
            best_name = name
            best_pdg = pdg_m
    return best_name, best_pdg, best_frac * 100


def main():
    # 1. Load and clean
    df, total_events, n_nan = load_data()
    print(f"Loaded {total_events} events, dropped {n_nan} NaN rows")

    # 2. Validate invariant mass
    max_diff, mean_diff = validate_invariant_mass(df)
    print(f"Mass validation: max_diff={max_diff:.2e}, mean_diff={mean_diff:.2e}")

    # 3. Apply cuts
    df_cut = apply_quality_cuts(df)
    n_after = len(df_cut)
    print(f"Events after quality cuts: {n_after}")

    # 4. Build spectrum
    masses = df_cut["M"].values
    counts, centers, widths, edges = build_spectrum(masses)

    # 5. Estimate background
    bkg = estimate_background(counts)

    # 6. Detect peaks
    raw_peaks = detect_peaks(counts, centers, bkg)
    print(f"Raw peaks found: {len(raw_peaks)}")

    # 7. Fit peaks and match to PDG
    resonances = []
    for pk in raw_peaks:
        mu, sigma, yield_n, significance = fit_peak(masses, pk["mass_approx"])
        name, pdg_m, residual = match_pdg(mu)

        if residual < 15.0 and significance > 2.0 and yield_n >= 5:
            resonances.append({
                "name": name,
                "measured_mass_gev": round(mu, 4),
                "fitted_width_gev": round(sigma, 4),
                "signal_yield": max(yield_n, 1),
                "significance_sigma": round(max(significance, 0.1), 2),
                "pdg_mass_gev": pdg_m,
                "mass_residual_pct": round(residual, 2),
            })

    # Deduplicate: keep highest-significance per PDG particle
    best = {}
    for r in resonances:
        key = r["name"]
        if key not in best or r["significance_sigma"] > best[key]["significance_sigma"]:
            best[key] = r
    resonances = sorted(best.values(), key=lambda x: x["measured_mass_gev"])

    print(f"\nIdentified {len(resonances)} resonances:")
    for r in resonances:
        print(f"  {r['name']:15s}  M={r['measured_mass_gev']:.4f} GeV  "
              f"(PDG {r['pdg_mass_gev']:.3f}, res {r['mass_residual_pct']:.1f}%)  "
              f"sig={r['significance_sigma']:.1f}s  yield={r['signal_yield']}")

    # 8. Write outputs
    with open(CATALOG_OUT, "w") as f:
        json.dump({"resonances": resonances}, f, indent=2)

    summary = {
        "total_events": total_events,
        "events_after_quality_cuts": n_after,
        "events_with_nan_dropped": n_nan,
        "mass_validation_max_abs_diff": max_diff,
        "mass_validation_mean_abs_diff": mean_diff,
    }
    with open(SUMMARY_OUT, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nResults written to {CATALOG_OUT} and {SUMMARY_OUT}")


if __name__ == "__main__":
    main()
