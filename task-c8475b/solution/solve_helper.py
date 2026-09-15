#!/usr/bin/env python3
"""
Solution: Battery Model Fidelity Analysis — SPM vs SPMe comparison.
Uses PyBaMM with the Chen2020 parameter set to perform multi-rate discharge
comparison, incremental capacity analysis, voltage decomposition, and
discharge energy computation.
"""

import json
import os

os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
_cfg_dir = os.path.expanduser("~/.config/pybamm")
os.makedirs(_cfg_dir, exist_ok=True)
_cfg_path = os.path.join(_cfg_dir, "config.yml")
if not os.path.exists(_cfg_path):
    with open(_cfg_path, "w") as _f:
        _f.write("pybamm:\n  enable_telemetry: false\n")

import numpy as np
import pybamm

pybamm.set_logging_level("WARNING")

_trapz = getattr(np, "trapezoid", getattr(np, "trapz", None))

C_RATES = {
    "C/20": 1 / 20, "C/5": 1 / 5, "C/2": 1 / 2,
    "1C": 1.0, "2C": 2.0, "3C": 3.0,
}
RATE_ORDER = ["C/20", "C/5", "C/2", "1C", "2C", "3C"]


def run_discharge(model_class, c_rate_numeric, n_points=500):
    """Run galvanostatic discharge at a given C-rate."""
    model = model_class()
    param = pybamm.ParameterValues("Chen2020")
    capacity = param["Nominal cell capacity [A.h]"]
    param["Current function [A]"] = capacity * c_rate_numeric

    sim = pybamm.Simulation(model, parameter_values=param)
    t_end = 3600.0 / c_rate_numeric * 1.5
    sol = sim.solve(np.linspace(0, t_end, n_points))
    return sol


def get_discharge_data(sol):
    """Extract time, voltage, current, and capacity arrays from a solution."""
    t = np.asarray(sol["Time [s]"].entries).flatten()
    V = np.asarray(sol["Voltage [V]"].entries).flatten()
    I = np.asarray(sol["Current [A]"].entries).flatten()
    Q = np.asarray(sol["Discharge capacity [A.h]"].entries).flatten()
    return t, V, I, Q


def compute_voltage_errors(Q1, V1, Q2, V2):
    """Compute max and RMS voltage error (mV) on a common capacity grid."""
    Q_hi = min(Q1[-1], Q2[-1]) * 0.99
    if Q_hi <= 0:
        return 0.0, 0.0
    Q_grid = np.linspace(0.01 * Q_hi, Q_hi, 200)
    V1_interp = np.interp(Q_grid, Q1, V1)
    V2_interp = np.interp(Q_grid, Q2, V2)
    err_V = np.abs(V1_interp - V2_interp)
    return float(np.max(err_V)) * 1000.0, float(np.sqrt(np.mean(err_V ** 2))) * 1000.0


def ica_analysis(sol, threshold=1.0):
    """Incremental capacity analysis: find |dQ/dV| peaks above *threshold*."""
    from scipy.signal import savgol_filter

    _, V, _, Q = get_discharge_data(sol)

    dQ = np.diff(Q)
    dV = np.diff(V)
    mask = np.abs(dV) > 1e-6
    if np.sum(mask) < 10:
        return []
    abs_dqdv = np.abs(dQ[mask] / dV[mask])
    V_mid = 0.5 * (V[:-1][mask] + V[1:][mask])

    win = min(len(abs_dqdv) // 10, 51)
    if win < 5:
        win = 5
    if win % 2 == 0:
        win += 1
    polyorder = min(3, win - 1)
    smooth = savgol_filter(abs_dqdv, win, polyorder)
    smooth = np.maximum(smooth, 0)

    peaks = []
    for i in range(1, len(smooth) - 1):
        if smooth[i] > smooth[i - 1] and smooth[i] > smooth[i + 1]:
            if smooth[i] > threshold:
                peaks.append(float(V_mid[i]))
    return sorted(peaks)


def get_ocv_at_index(sol, idx):
    """Return the OCV value at a given array index from a PyBaMM solution."""
    candidates = [
        "Battery open-circuit voltage [V]",
        "X-averaged battery open-circuit voltage [V]",
        "Measured open circuit voltage [V]",
    ]
    for name in candidates:
        try:
            arr = np.asarray(sol[name].entries).flatten()
            return float(arr[idx])
        except (KeyError, Exception):
            continue
    electrode_pairs = [
        (
            "X-averaged positive electrode open-circuit potential [V]",
            "X-averaged negative electrode open-circuit potential [V]",
        ),
        (
            "Positive electrode open-circuit potential [V]",
            "Negative electrode open-circuit potential [V]",
        ),
    ]
    for pos_name, neg_name in electrode_pairs:
        try:
            Up = np.asarray(sol[pos_name].entries).flatten()
            Un = np.asarray(sol[neg_name].entries).flatten()
            return float(Up[idx] - Un[idx])
        except (KeyError, Exception):
            continue
    return None


def main():
    results = {
        "discharge_comparison": {},
        "ica_peaks": {
            "spm": {"peak_voltages_V": []},
            "spme": {"peak_voltages_V": []},
        },
        "critical_crate": None,
        "voltage_decomposition_1C_50pct": {},
        "energy_1C": {},
    }

    sol_cache = {}

    for label in RATE_ORDER:
        cr = C_RATES[label]
        print(f"[rate] {label} ...", flush=True)

        sol_spm = run_discharge(pybamm.lithium_ion.SPM, cr)
        sol_spme = run_discharge(pybamm.lithium_ion.SPMe, cr)
        sol_cache[("spm", label)] = sol_spm
        sol_cache[("spme", label)] = sol_spme

        _, V1, _, Q1 = get_discharge_data(sol_spm)
        _, V2, _, Q2 = get_discharge_data(sol_spme)

        cap_spm = float(Q1[-1])
        cap_spme = float(Q2[-1])
        max_err, rms_err = compute_voltage_errors(Q1, V1, Q2, V2)
        cap_diff = (
            abs(cap_spm - cap_spme) / cap_spme * 100.0 if cap_spme > 0 else 0.0
        )

        results["discharge_comparison"][label] = {
            "spm_capacity_Ah": round(cap_spm, 4),
            "spme_capacity_Ah": round(cap_spme, 4),
            "max_voltage_error_mV": round(max_err, 2),
            "rms_voltage_error_mV": round(rms_err, 2),
            "capacity_diff_pct": round(cap_diff, 3),
        }

    print("[ica] C/20 ...", flush=True)
    results["ica_peaks"]["spm"]["peak_voltages_V"] = ica_analysis(
        sol_cache[("spm", "C/20")]
    )
    results["ica_peaks"]["spme"]["peak_voltages_V"] = ica_analysis(
        sol_cache[("spme", "C/20")]
    )

    for label in RATE_ORDER:
        if results["discharge_comparison"][label]["rms_voltage_error_mV"] > 10.0:
            results["critical_crate"] = C_RATES[label]
            break

    print("[vdecomp] 1C @ 50% DOD ...", flush=True)
    sol_1c = sol_cache[("spme", "1C")]
    t_1c, V_1c, I_1c, Q_1c = get_discharge_data(sol_1c)
    Q_total = Q_1c[-1]
    idx_50 = int(np.argmin(np.abs(Q_1c - 0.5 * Q_total)))

    terminal_V = float(V_1c[idx_50])
    ocv_V = get_ocv_at_index(sol_1c, idx_50)
    if ocv_V is None:
        _, V_slow, _, Q_slow = get_discharge_data(sol_cache[("spme", "C/20")])
        Q_total_slow = Q_slow[-1]
        idx_50_slow = int(np.argmin(np.abs(Q_slow - 0.5 * Q_total_slow)))
        ocv_V = float(V_slow[idx_50_slow])

    total_overpot_mV = (ocv_V - terminal_V) * 1000.0

    results["voltage_decomposition_1C_50pct"] = {
        "ocv_V": round(ocv_V, 4),
        "terminal_voltage_V": round(terminal_V, 4),
        "total_overpotential_mV": round(total_overpot_mV, 2),
    }

    print("[energy] 1C ...", flush=True)
    t_spm, V_spm, I_spm, _ = get_discharge_data(sol_cache[("spm", "1C")])
    t_spme, V_spme, I_spme, _ = get_discharge_data(sol_cache[("spme", "1C")])

    e_spm_Wh = float(_trapz(V_spm * I_spm, t_spm) / 3600.0)
    e_spme_Wh = float(_trapz(V_spme * I_spme, t_spme) / 3600.0)
    e_diff_pct = (
        abs(e_spm_Wh - e_spme_Wh) / e_spme_Wh * 100.0 if e_spme_Wh > 0 else 0.0
    )

    results["energy_1C"] = {
        "spm_energy_Wh": round(e_spm_Wh, 4),
        "spme_energy_Wh": round(e_spme_Wh, 4),
        "energy_difference_pct": round(e_diff_pct, 3),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Done — results written to /app/results.json", flush=True)


if __name__ == "__main__":
    main()
