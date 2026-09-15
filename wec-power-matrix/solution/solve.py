#!/usr/bin/env python3
"""
RM3 two-body point absorber WEC frequency-domain analysis.
Supports full analysis and single-query modes.
"""

import json
import csv
import sys
import numpy as np
from scipy.optimize import minimize_scalar
import h5py

# ============================================================
# Load parameters
# ============================================================
with open("/app/data/rm3_params.json", "r") as f:
    params = json.load(f)

rho = params["fluid"]["rho"]
g = params["fluid"]["g"]

body1 = params["bodies"][0]
body2 = params["bodies"][1]

m1 = rho * body1["volume_m3"]
m2 = rho * body2["volume_m3"]
C33_1 = body1["C33_nondim"] * rho * g
C33_2 = body2["C33_nondim"] * rho * g
K_PTO = params["pto"]["stiffness_Npm"]

# ============================================================
# Load hydrodynamic coefficients
# ============================================================
data = np.genfromtxt("/app/data/rm3_hydro_coeffs.csv", delimiter=",", skip_header=1)

omega = data[:, 0]
N_freq = len(omega)
dw = omega[1] - omega[0]

# Dimensionalize added mass: A_dim = A_bar * rho
A33 = data[:, 1] * rho
A39 = data[:, 3] * rho
A93 = data[:, 5] * rho
A99 = data[:, 7] * rho

# Dimensionalize radiation damping: B_dim = B_bar * rho * omega
B33 = data[:, 2] * rho * omega
B39 = data[:, 4] * rho * omega
B93 = data[:, 6] * rho * omega
B99 = data[:, 8] * rho * omega

# Dimensionalize excitation force: F_dim = F_bar * rho * g
ModF3 = data[:, 9] * rho * g
PhaF3 = np.deg2rad(data[:, 10])
ModF9 = data[:, 11] * rho * g
PhaF9 = np.deg2rad(data[:, 12])

F3 = ModF3 * np.exp(1j * PhaF3)
F9 = ModF9 * np.exp(1j * PhaF9)

# ============================================================
# Pierson-Moskowitz spectrum
# ============================================================
def pierson_moskowitz(w, Hs, Tp):
    wp = 2 * np.pi / Tp
    S = np.zeros_like(w)
    mask = w > 0
    S[mask] = (5.0 / 16.0) * Hs**2 * wp**4 / w[mask]**5 * np.exp(-1.25 * (wp / w[mask])**4)
    return S

# ============================================================
# Compute mean power for given B_PTO and sea state
# ============================================================
def compute_mean_power(B_PTO, Hs, Tp):
    S = pierson_moskowitz(omega, Hs, Tp)
    P_total = 0.0

    for j in range(N_freq):
        w = omega[j]
        if S[j] < 1e-30:
            continue

        pto_im = w * B_PTO

        z11 = complex(-w**2 * (m1 + A33[j]) + C33_1 + K_PTO, w * B33[j] + pto_im)
        z12 = complex(-w**2 * A39[j] - K_PTO, w * B39[j] - pto_im)
        z21 = complex(-w**2 * A93[j] - K_PTO, w * B93[j] - pto_im)
        z22 = complex(-w**2 * (m2 + A99[j]) + C33_2 + K_PTO, w * B99[j] + pto_im)

        det = z11 * z22 - z12 * z21
        X1 = (F3[j] * z22 - z12 * F9[j]) / det
        X2 = (z11 * F9[j] - F3[j] * z21) / det

        X_rel = X1 - X2
        P_total += B_PTO * w**2 * abs(X_rel)**2 * S[j] * dw

    return P_total

# ============================================================
# Optimize B_PTO for a given sea state
# ============================================================
def optimize_pto(Hs, Tp):
    B_min = 5e4
    B_max = 30e6

    B_vals = np.linspace(B_min, B_max, 500)
    powers = [compute_mean_power(B, Hs, Tp) for B in B_vals]
    best_idx = np.argmax(powers)
    best_B_coarse = B_vals[best_idx]

    lb = max(B_min, best_B_coarse - (B_max - B_min) / 50)
    ub = min(B_max, best_B_coarse + (B_max - B_min) / 50)

    result = minimize_scalar(
        lambda B: -compute_mean_power(B, Hs, Tp),
        bounds=(lb, ub),
        method="bounded",
        options={"xatol": 1e3},
    )
    return result.x, -result.fun

# ============================================================
# Radiation impulse response function
# ============================================================
def compute_radiation_irf(B_array, omega_arr, t_array):
    """K(t) = (2/pi) * integral B(w) * cos(w*t) dw"""
    dw_val = omega_arr[1] - omega_arr[0]
    K = np.zeros_like(t_array)
    for i, t in enumerate(t_array):
        K[i] = (2.0 / np.pi) * np.sum(B_array * np.cos(omega_arr * t)) * dw_val
    return K

# ============================================================
# Query mode: single sea state at fixed B_PTO
# ============================================================
def query_mode(Hs, Tp, Bpto):
    P = compute_mean_power(Bpto, Hs, Tp)
    result = {"power_kW": round(P / 1e3, 6)}
    print(json.dumps(result))

# ============================================================
# Full mode: complete analysis
# ============================================================
def full_mode():
    sea_states = []
    with open("/app/data/sea_states.csv", "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sea_states.append({
                "Hs": float(row["Hs_m"]),
                "Tp": float(row["Tp_s"]),
                "hours": float(row["hours_per_year"]),
            })

    Hs_values = sorted(set(s["Hs"] for s in sea_states))
    Tp_values = sorted(set(s["Tp"] for s in sea_states))

    # Compute power matrix and optimal PTO
    power_kW = {}
    optimal_Bpto = {}

    for ss in sea_states:
        Hs, Tp = ss["Hs"], ss["Tp"]
        key = f"{Hs}_{Tp}"
        print(f"Optimizing Hs={Hs}m, Tp={Tp}s...")
        B_opt, P_opt = optimize_pto(Hs, Tp)
        power_kW[key] = round(P_opt / 1e3, 4)
        optimal_Bpto[key] = round(B_opt / 1e6, 4)
        print(f"  B_PTO_opt = {B_opt/1e6:.4f} MN/(m/s), P_opt = {P_opt/1e3:.4f} kW")

    # Compute AEP
    aep = 0.0
    for ss in sea_states:
        key = f"{ss['Hs']}_{ss['Tp']}"
        aep += power_kW[key] * ss["hours"] / 1e3

    # Write JSON outputs
    with open("/app/power_matrix.json", "w") as f:
        json.dump({
            "Hs_values": Hs_values,
            "Tp_values": Tp_values,
            "power_kW": power_kW,
        }, f, indent=2)

    with open("/app/optimal_pto.json", "w") as f:
        json.dump({
            "optimal_Bpto_MNsm": optimal_Bpto,
        }, f, indent=2)

    with open("/app/aep.json", "w") as f:
        json.dump({
            "aep_mwh": round(aep, 2),
        }, f, indent=2)

    # Compute radiation IRFs
    t_irf = np.linspace(0, 100, 1001)
    K33 = compute_radiation_irf(B33, omega, t_irf)
    K39 = compute_radiation_irf(B39, omega, t_irf)
    K93 = compute_radiation_irf(B93, omega, t_irf)
    K99 = compute_radiation_irf(B99, omega, t_irf)

    # Build 2D result arrays
    pm_2d = np.zeros((len(Hs_values), len(Tp_values)))
    bpto_2d = np.zeros((len(Hs_values), len(Tp_values)))
    for i, Hs in enumerate(Hs_values):
        for j, Tp in enumerate(Tp_values):
            key = f"{Hs}_{Tp}"
            pm_2d[i, j] = power_kW[key]
            bpto_2d[i, j] = optimal_Bpto[key]

    # Write HDF5
    with h5py.File("/app/rm3_analysis.h5", "w") as hf:
        hf.create_dataset("/hydro/omega", data=omega)

        hf.create_dataset("/hydro/added_mass/A33", data=A33)
        hf.create_dataset("/hydro/added_mass/A39", data=A39)
        hf.create_dataset("/hydro/added_mass/A93", data=A93)
        hf.create_dataset("/hydro/added_mass/A99", data=A99)

        hf.create_dataset("/hydro/radiation_damping/B33", data=B33)
        hf.create_dataset("/hydro/radiation_damping/B39", data=B39)
        hf.create_dataset("/hydro/radiation_damping/B93", data=B93)
        hf.create_dataset("/hydro/radiation_damping/B99", data=B99)

        hf.create_dataset("/hydro/excitation/F3_real", data=F3.real)
        hf.create_dataset("/hydro/excitation/F3_imag", data=F3.imag)
        hf.create_dataset("/hydro/excitation/F9_real", data=F9.real)
        hf.create_dataset("/hydro/excitation/F9_imag", data=F9.imag)

        hf.create_dataset("/hydro/radiation_irf/time", data=t_irf)
        hf.create_dataset("/hydro/radiation_irf/K33", data=K33)
        hf.create_dataset("/hydro/radiation_irf/K39", data=K39)
        hf.create_dataset("/hydro/radiation_irf/K93", data=K93)
        hf.create_dataset("/hydro/radiation_irf/K99", data=K99)

        hf.create_dataset("/results/power_kW", data=pm_2d)
        hf.create_dataset("/results/Hs_values", data=np.array(Hs_values))
        hf.create_dataset("/results/Tp_values", data=np.array(Tp_values))
        hf.create_dataset("/results/optimal_Bpto_MNsm", data=bpto_2d)

    print(f"\nAEP = {aep:.2f} MWh/year")
    print("All outputs written.")

# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 wec_analysis.py full | query <Hs> <Tp> <Bpto>",
              file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]
    if mode == "full":
        full_mode()
    elif mode == "query":
        if len(sys.argv) != 5:
            print("Usage: python3 wec_analysis.py query <Hs> <Tp> <Bpto>",
                  file=sys.stderr)
            sys.exit(1)
        query_mode(float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]))
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)
