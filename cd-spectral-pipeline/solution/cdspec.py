#!/usr/bin/env python3
"""CD Spectroscopy Analysis Pipeline - Reference Solution."""

import argparse
import json
import math
import os
import sys

import numpy as np
from scipy.interpolate import interp1d
from scipy.optimize import curve_fit, minimize


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def read_two_col(path):
    """Read a two-column CSV (skip '#' comments and non-numeric headers)."""
    col1, col2 = [], []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) < 2:
                continue
            try:
                col1.append(float(parts[0]))
                col2.append(float(parts[1]))
            except ValueError:
                continue
    return np.array(col1), np.array(col2)


def read_basis(path):
    """Read basis spectra CSV: wavelength, helix, strand, turn, coil."""
    wls, data = [], []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) < 5:
                continue
            try:
                vals = [float(x) for x in parts[:5]]
                wls.append(vals[0])
                data.append(vals[1:5])
            except ValueError:
                continue
    return np.array(wls), np.array(data)


def round_list(arr, decimals=4):
    """Round an array/list to *decimals* places and return a Python list."""
    return [round(float(v), decimals) for v in arr]


# ---------------------------------------------------------------------------
# Sub-command: convert
# ---------------------------------------------------------------------------

def cmd_convert(args):
    wl, vals = read_two_col(args.input)
    mrw = args.mw / args.nres
    c = args.conc
    l = args.path

    conversions = {
        ("mdeg", "de"):  lambda v: v * mrw / (32980.0 * c * l),
        ("mdeg", "mre"): lambda v: v * mrw / (10.0 * c * l),
        ("de", "mdeg"):  lambda v: v * 32980.0 * c * l / mrw,
        ("de", "mre"):   lambda v: v * 3298.0,
        ("mre", "de"):   lambda v: v / 3298.0,
        ("mre", "mdeg"): lambda v: v * 10.0 * c * l / mrw,
    }

    key = (args.from_unit, args.to_unit)
    if key[0] == key[1]:
        result_vals = vals
    elif key in conversions:
        result_vals = conversions[key](vals)
    else:
        print(f"Unsupported conversion: {key}", file=sys.stderr)
        sys.exit(1)

    out = {
        "wavelengths": round_list(wl),
        "values": round_list(result_vals),
    }
    print(json.dumps(out))


# ---------------------------------------------------------------------------
# Sub-command: deconvolve
# ---------------------------------------------------------------------------

def cmd_deconvolve(args):
    wl_spec, spec = read_two_col(args.spectrum)
    wl_basis, basis = read_basis(args.basis)

    wl_min = max(wl_spec.min(), wl_basis.min())
    wl_max = min(wl_spec.max(), wl_basis.max())

    if not np.allclose(wl_spec, wl_basis) or len(wl_spec) != len(wl_basis):
        common_wl = np.arange(wl_min, wl_max + 0.5, 1.0)
        spec_fn = interp1d(wl_spec, spec, kind="linear", fill_value="extrapolate")
        spec = spec_fn(common_wl)
        new_basis = []
        for col in range(basis.shape[1]):
            fn = interp1d(wl_basis, basis[:, col], kind="linear", fill_value="extrapolate")
            new_basis.append(fn(common_wl))
        basis = np.column_stack(new_basis)
    else:
        common_wl = wl_spec

    n_comp = basis.shape[1]

    def objective(f):
        residual = spec - basis @ f
        return float(np.sum(residual ** 2))

    constraints = [{"type": "eq", "fun": lambda f: float(np.sum(f) - 1.0)}]
    bounds = [(0.0, 1.0)] * n_comp
    x0 = np.full(n_comp, 1.0 / n_comp)

    result = minimize(objective, x0, method="SLSQP", bounds=bounds, constraints=constraints)
    fracs = result.x

    recon = basis @ fracs
    ss_res = float(np.sum((spec - recon) ** 2))
    ss_obs = float(np.sum(spec ** 2))
    nrmsd = math.sqrt(ss_res / ss_obs) if ss_obs > 0 else 0.0

    out = {
        "fractions": {
            "helix": round(float(fracs[0]), 4),
            "strand": round(float(fracs[1]), 4),
            "turn": round(float(fracs[2]), 4),
            "coil": round(float(fracs[3]), 4),
        },
        "nrmsd": round(nrmsd, 4),
        "reconstructed": round_list(recon),
    }
    print(json.dumps(out))


# ---------------------------------------------------------------------------
# Sub-command: thermomelt
# ---------------------------------------------------------------------------

R_KJ = 8.314e-3  # kJ/(mol*K)


def _melt_model(T, a_N, b_N, a_U, b_U, Tm, dH):
    """Two-state unfolding with linear baselines."""
    theta_N = a_N + b_N * T
    theta_U = a_U + b_U * T
    exponent = dH / R_KJ * (1.0 / Tm - 1.0 / T)
    exponent = np.clip(exponent, -500.0, 500.0)
    K = np.exp(exponent)
    return (theta_N + theta_U * K) / (1.0 + K)


def cmd_thermomelt(args):
    T, signal = read_two_col(args.input)

    n = len(T)
    k = min(5, n // 4)

    p_N = np.polyfit(T[:k], signal[:k], 1)
    slope_N, intercept_N = float(p_N[0]), float(p_N[1])

    p_U = np.polyfit(T[-k:], signal[-k:], 1)
    slope_U, intercept_U = float(p_U[0]), float(p_U[1])

    mid_signal = (signal[0] + signal[-1]) / 2.0
    tm_est = float(T[np.argmin(np.abs(signal - mid_signal))])

    p0 = [intercept_N, slope_N, intercept_U, slope_U, tm_est, 200.0]

    lower = [-1e8, -1e4, -1e8, -1e4, T.min(), 10.0]
    upper = [1e8, 1e4, 1e8, 1e4, T.max(), 2000.0]

    popt, _ = curve_fit(
        _melt_model, T, signal, p0=p0,
        bounds=(lower, upper), maxfev=50000,
    )
    _, _, _, _, Tm_fit, dH_fit = popt

    exponent = dH_fit / R_KJ * (1.0 / Tm_fit - 1.0 / T)
    exponent = np.clip(exponent, -500.0, 500.0)
    K = np.exp(exponent)
    f_folded = 1.0 / (1.0 + K)

    out = {
        "tm_K": round(float(Tm_fit), 4),
        "dh_kj_mol": round(float(dH_fit), 4),
        "fraction_folded": round_list(f_folded),
    }
    print(json.dumps(out))


# ---------------------------------------------------------------------------
# Sub-command: validate
# ---------------------------------------------------------------------------

def cmd_validate(args):
    wl, vals = read_two_col(args.input)
    with open(args.metadata) as f:
        meta = json.load(f)

    checks = {}

    # HT voltage check
    ht_max = meta.get("ht_voltage_max", 0.0)
    instrument = meta.get("instrument_type", "benchtop")
    ht_threshold = 700.0 if instrument == "synchrotron" else 600.0
    checks["ht_voltage"] = {
        "passed": ht_max <= ht_threshold,
        "value": round(float(ht_max), 4),
        "threshold": round(float(ht_threshold), 4),
    }

    # Wavelength range check
    min_wl = float(wl.min()) if len(wl) > 0 else 999.0
    wl_threshold = 200.0
    checks["wavelength_range"] = {
        "passed": min_wl <= wl_threshold,
        "value": round(float(min_wl), 4),
        "threshold": round(float(wl_threshold), 4),
    }

    # Baseline flatness check
    long_wl_mask = wl >= 250.0
    if long_wl_mask.any():
        baseline_val = float(np.mean(np.abs(vals[long_wl_mask])))
    else:
        baseline_val = 0.0
    baseline_threshold = 2.0
    checks["baseline_flatness"] = {
        "passed": baseline_val < baseline_threshold,
        "value": round(float(baseline_val), 4),
        "threshold": round(float(baseline_threshold), 4),
    }

    # CSA calibration check
    csa_ratio = meta.get("csa_ratio", None)
    if csa_ratio is not None:
        csa_passed = 1.95 <= float(csa_ratio) <= 2.05
        checks["csa_calibration"] = {
            "passed": csa_passed,
            "value": round(float(csa_ratio), 4),
            "threshold": [1.95, 2.05],
        }
    else:
        checks["csa_calibration"] = {
            "passed": True,
            "value": None,
            "threshold": [1.95, 2.05],
        }

    overall = all(c["passed"] for c in checks.values())
    out = {"passed": overall, "checks": checks}
    print(json.dumps(out))


# ---------------------------------------------------------------------------
# Sub-command: match
# ---------------------------------------------------------------------------

def cmd_match(args):
    wl_q, spec_q = read_two_col(args.query)
    rankings = []

    for fname in sorted(os.listdir(args.library)):
        if not fname.endswith(".csv"):
            continue
        fpath = os.path.join(args.library, fname)
        if not os.path.isfile(fpath):
            continue
        wl_r, spec_r = read_two_col(fpath)

        if len(wl_r) == 0 or len(wl_q) == 0:
            continue

        wl_min = max(wl_q.min(), wl_r.min())
        wl_max = min(wl_q.max(), wl_r.max())
        if wl_min >= wl_max:
            continue

        common_wl = np.arange(wl_min, wl_max + 0.5, 1.0)
        common_wl = common_wl[common_wl <= wl_max]

        q_fn = interp1d(wl_q, spec_q, kind="linear", fill_value="extrapolate")
        r_fn = interp1d(wl_r, spec_r, kind="linear", fill_value="extrapolate")

        q_vals = q_fn(common_wl)
        r_vals = r_fn(common_wl)

        diff = q_vals - r_vals
        ss_diff = float(np.sum(diff ** 2))
        ss_q = float(np.sum(q_vals ** 2))
        nrmsd = math.sqrt(ss_diff / ss_q) if ss_q > 0 else 0.0

        rankings.append({"file": fname, "nrmsd": round(nrmsd, 4)})

    rankings.sort(key=lambda x: x["nrmsd"])
    print(json.dumps({"rankings": rankings}))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="CD Spectroscopy Analysis Pipeline",
    )
    sub = parser.add_subparsers(dest="command")

    # convert
    p_c = sub.add_parser("convert", help="Convert between CD units")
    p_c.add_argument("--input", required=True)
    p_c.add_argument("--from-unit", required=True, choices=["mdeg", "mre", "de"])
    p_c.add_argument("--to-unit", required=True, choices=["mdeg", "mre", "de"])
    p_c.add_argument("--conc", type=float, required=True)
    p_c.add_argument("--mw", type=float, required=True)
    p_c.add_argument("--nres", type=int, required=True)
    p_c.add_argument("--path", type=float, required=True)

    # deconvolve
    p_d = sub.add_parser("deconvolve", help="Secondary structure deconvolution")
    p_d.add_argument("--spectrum", required=True)
    p_d.add_argument("--basis", required=True)

    # thermomelt
    p_t = sub.add_parser("thermomelt", help="Thermal melt fitting")
    p_t.add_argument("--input", required=True)

    # validate
    p_v = sub.add_parser("validate", help="Validate CD data quality")
    p_v.add_argument("--input", required=True)
    p_v.add_argument("--metadata", required=True)

    # match
    p_m = sub.add_parser("match", help="Spectral similarity matching")
    p_m.add_argument("--query", required=True)
    p_m.add_argument("--library", required=True)

    args = parser.parse_args()

    if args.command == "convert":
        cmd_convert(args)
    elif args.command == "deconvolve":
        cmd_deconvolve(args)
    elif args.command == "thermomelt":
        cmd_thermomelt(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "match":
        cmd_match(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
