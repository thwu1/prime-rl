#!/usr/bin/env python3
"""Fixed-bed adsorption breakthrough curve analysis pipeline."""

import numpy as np
from scipy.optimize import curve_fit, differential_evolution
from scipy.integrate import solve_ivp
import json
import re


# =====================================================================
# Data loading
# =====================================================================
def load_curve(filepath):
    """Load a breakthrough CSV. Returns (time_min, C_over_C0, conditions_dict)."""
    conditions = {}
    with open(filepath) as f:
        for line in f:
            if line.startswith("#"):
                for m in re.finditer(r"(\w+)=([\d.]+)", line):
                    conditions[m.group(1)] = float(m.group(2))
                break
    data = np.loadtxt(filepath, delimiter=",", skiprows=2)
    return data[:, 0], data[:, 1], conditions


def load_column_params(path="/app/column_params.json"):
    with open(path) as f:
        return json.load(f)


# =====================================================================
# Utility
# =====================================================================
def r_squared(y_true, y_pred):
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0


def interpolate_threshold(t, C, threshold):
    if C[0] >= threshold:
        return 0.0
    for i in range(1, len(C)):
        if C[i] >= threshold:
            frac = (threshold - C[i - 1]) / (C[i] - C[i - 1])
            return float(t[i - 1] + frac * (t[i] - t[i - 1]))
    return float(t[-1])


def calc_rmse(t_m, C_m, t_d, C_d):
    return float(np.sqrt(np.mean((np.interp(t_d, t_m, C_m) - C_d) ** 2)))


# =====================================================================
# 1. Yoon-Nelson
# =====================================================================
def _yn_func(t, k, tau):
    x = np.clip(k * (tau - t), -500, 500)
    return 1.0 / (1.0 + np.exp(x))


def fit_yoon_nelson(t, C):
    idx50 = int(np.argmin(np.abs(C - 0.5)))
    tau0 = t[idx50]
    if 0 < idx50 < len(t) - 1:
        dCdt = (C[idx50 + 1] - C[idx50 - 1]) / (t[idx50 + 1] - t[idx50 - 1])
        k0 = max(4.0 * dCdt, 0.005)
    else:
        k0 = 0.025
    popt, pcov = curve_fit(_yn_func, t, C, p0=[k0, tau0],
                           bounds=([1e-4, 0], [2, t[-1] * 3]), maxfev=20000)
    R2 = r_squared(C, _yn_func(t, *popt))
    perr = np.sqrt(np.diag(pcov))
    return {
        "k_YN": float(popt[0]),
        "tau": float(popt[1]),
        "R2": float(R2),
        "k_YN_ci95": [float(popt[0] - 1.96 * perr[0]),
                       float(popt[0] + 1.96 * perr[0])],
        "tau_ci95": [float(popt[1] - 1.96 * perr[1]),
                      float(popt[1] + 1.96 * perr[1])],
    }


# =====================================================================
# 2. Thomas
# =====================================================================
def fit_thomas(t, C, cond, col):
    C0_mg_mL = cond["C0_mg_L"] / 1000.0
    Q = cond["flow_rate_mL_min"]
    Z_cm = cond["bed_height_cm"]
    D_cm = col["column_diameter_m"] * 100.0
    A_cm2 = np.pi / 4.0 * D_cm ** 2
    V_cm3 = A_cm2 * Z_cm
    m_g = col["bulk_density_kg_m3"] * (V_cm3 * 1e-6) * 1000.0

    def thomas_func(t, k_Th, q_0):
        x = np.clip(k_Th * (q_0 * m_g / Q - C0_mg_mL * t), -500, 500)
        return 1.0 / (1.0 + np.exp(x))

    yn = fit_yoon_nelson(t, C)
    k0 = yn["k_YN"] / C0_mg_mL
    q0 = yn["tau"] * Q * C0_mg_mL / m_g
    try:
        popt, _ = curve_fit(thomas_func, t, C, p0=[k0, q0],
                            bounds=([1e-4, 1e-4], [100, 500]), maxfev=20000)
        R2 = r_squared(C, thomas_func(t, *popt))
        return {"k_Th": float(popt[0]), "q_0": float(popt[1]), "R2": float(R2)}
    except Exception:
        return {"k_Th": float(k0), "q_0": float(q0), "R2": float(yn["R2"])}


# =====================================================================
# 3. Adams-Bohart (initial portion C/C0 < 0.15)
# =====================================================================
def fit_adams_bohart(t, C, cond, col):
    C0 = cond["C0_mg_L"]
    Z_cm = cond["bed_height_cm"]
    Q = cond["flow_rate_mL_min"]
    D_cm = col["column_diameter_m"] * 100.0
    A_cm2 = np.pi / 4.0 * D_cm ** 2
    u = Q / A_cm2

    mask = (C > 0) & (C < 0.15)
    t_f = t[mask]
    lnC = np.log(C[mask])

    if len(t_f) < 3:
        return {"k_AB": 0.0, "N_0": 0.0, "R2": 0.0}

    coeffs = np.polyfit(t_f, lnC, 1)
    a, b = coeffs

    k_AB = a / C0
    if k_AB <= 0:
        return {"k_AB": 0.0, "N_0": 0.0, "R2": 0.0}
    N0 = -b * u / (k_AB * Z_cm)

    pred = a * t_f + b
    R2 = r_squared(lnC, pred)
    return {"k_AB": float(k_AB), "N_0": float(N0), "R2": float(R2)}


# =====================================================================
# 4. Capacity (mass balance integration)
# =====================================================================
def compute_capacity(t, C, cond, col):
    C0 = cond["C0_mg_L"]
    Q = cond["flow_rate_mL_min"] / 1000.0  # L/min
    D_cm = col["column_diameter_m"] * 100.0
    A_cm2 = np.pi / 4.0 * D_cm ** 2
    Z_cm = cond["bed_height_cm"]
    V_cm3 = A_cm2 * Z_cm
    m_g = col["bulk_density_kg_m3"] * (V_cm3 * 1e-6) * 1000.0
    integral = float(np.trapz(1.0 - C, t))
    q_exp = C0 * Q * integral / m_g
    return {"q_exp_mg_g": float(q_exp)}


# =====================================================================
# 5. MTZ analysis
# =====================================================================
def compute_mtz(t, C, cond):
    Z_cm = cond["bed_height_cm"]
    t_b = interpolate_threshold(t, C, 0.05)
    t_e = interpolate_threshold(t, C, 0.95)
    H_MTZ = Z_cm * (t_e - t_b) / t_e if t_e > 0 else Z_cm

    one_minus_C = 1.0 - C

    if t_b <= 0:
        int_num = 0.0
    else:
        mask = t <= t_b
        idx = np.where(mask)[0]
        if len(idx) >= 2:
            int_num = float(np.trapz(one_minus_C[idx], t[idx]))
            last = idx[-1]
            if last < len(t) - 1 and t[last] < t_b:
                C_at_tb = np.interp(t_b, t, C)
                int_num += 0.5 * (one_minus_C[last] + (1.0 - C_at_tb)) * (
                    t_b - t[last])
        else:
            int_num = t_b * (1.0 - C[0])

    int_den = float(np.trapz(one_minus_C, t))
    f_b = int_num / int_den if int_den > 0 else 0.0

    return {
        "t_b": float(t_b),
        "t_e": float(t_e),
        "H_MTZ_cm": float(H_MTZ),
        "f_b": float(f_b),
    }


# =====================================================================
# 6. BDST analysis
# =====================================================================
def compute_bdst(curves, col):
    groups = {}
    for label in "ABCDE":
        _, _, cond = curves[label]
        key = (cond["C0_mg_L"], cond["flow_rate_mL_min"])
        groups.setdefault(key, []).append(label)

    target = None
    for key, labels in groups.items():
        heights = {curves[lb][2]["bed_height_cm"] for lb in labels}
        if len(heights) >= 2:
            target = (key, labels)
            break

    if target is None:
        return {"slope": 0, "intercept": 0, "N_0": 0, "k_a": 0, "Z_0": 0}

    (C0, Q), labels = target
    Z_vals, tb_vals = [], []
    for lb in labels:
        t, C, cond = curves[lb]
        tb = interpolate_threshold(t, C, 0.05)
        if tb > 0:
            Z_vals.append(cond["bed_height_cm"])
            tb_vals.append(tb)

    if len(Z_vals) < 2:
        return {"slope": 0, "intercept": 0, "N_0": 0, "k_a": 0, "Z_0": 0}

    Z_arr = np.array(Z_vals)
    tb_arr = np.array(tb_vals)
    coeffs = np.polyfit(Z_arr, tb_arr, 1)
    slope, intercept = float(coeffs[0]), float(coeffs[1])

    D_cm = col["column_diameter_m"] * 100.0
    A_cm2 = np.pi / 4.0 * D_cm ** 2
    u = Q / A_cm2

    N0 = slope * C0 * u
    ln19 = np.log(1.0 / 0.05 - 1.0)
    k_a = -ln19 / (intercept * C0) if intercept != 0 else 0.0
    Z0 = -intercept / slope if slope != 0 else 0.0

    return {
        "slope": slope,
        "intercept": intercept,
        "N_0": float(N0),
        "k_a": float(k_a),
        "Z_0": float(Z0),
    }


# =====================================================================
# 7. PDE model: 1D advection-dispersion + LDF + Langmuir
# =====================================================================
def simulate_column(C0, L, Q, kLDF, qmax_kg, col, Nz=40, rtol=1e-6,
                    atol=1e-8, t_end_s=None):
    D = col["column_diameter_m"]
    dp = col["particle_diameter_m"]
    rho_p = col["particle_density_kg_m3"]
    eps_b = col["bed_void_fraction"]
    rho_f = col["fluid_density_kg_m3"]
    mu = col["fluid_viscosity_Pa_s"]
    Dm = col["molecular_diffusivity_m2_s"]
    b_SI = col["langmuir_b_L_mg"] * 1e3
    A_col = np.pi * D ** 2 / 4.0

    u_s = Q / A_col
    u = u_s / eps_b
    Re = rho_f * u_s * dp / mu
    Sc = mu / (rho_f * Dm)
    DL = (Dm / eps_b) * (20.0 + 0.5 * Re * Sc)
    dz = L / (Nz - 1)
    u_DL = u_s / DL
    inv_dz2 = 1.0 / dz ** 2
    inv_2dz = 1.0 / (2.0 * dz)
    DL_eff = DL / eps_b
    sink = (1.0 - eps_b) * rho_p / eps_b

    def rhs(t, y):
        Cv = np.maximum(y[:Nz], 0.0)
        q = y[Nz:]
        qstar = qmax_kg * b_SI * Cv / (1.0 + b_SI * Cv)
        dqdt = kLDF * (qstar - q)
        Ce = np.empty(Nz + 2)
        Ce[1:-1] = Cv
        Ce[0] = Cv[1] - 2.0 * dz * u_DL * (Cv[0] - C0)
        Ce[-1] = Cv[-1]
        d2 = (Ce[2:] - 2.0 * Ce[1:-1] + Ce[:-2]) * inv_dz2
        dCdz = np.empty(Nz)
        dCdz[0] = u_DL * (Cv[0] - C0)
        dCdz[1:-1] = (Ce[3:-1] - Ce[1:-3]) * inv_2dz
        dCdz[-1] = 0.0
        dCdt = DL_eff * d2 - u * dCdz - sink * dqdt
        return np.concatenate([dCdt, dqdt])

    if t_end_s is None:
        t_end_s = (A_col * L / Q) * 10
    y0 = np.zeros(2 * Nz)
    t_eval = np.linspace(0, t_end_s, 500)
    sol = solve_ivp(rhs, [0, t_end_s], y0, method="LSODA",
                    t_eval=t_eval, rtol=rtol, atol=atol)
    if not sol.success:
        raise RuntimeError(sol.message)
    C_out = np.maximum(sol.y[Nz - 1, :], 0.0) / C0
    return sol.t / 60.0, C_out


def run_pde_analysis(curves, col):
    # --- Calibration on Curve A ---
    t_A, C_A, cA = curves["A"]
    C0_A = cA["C0_mg_L"] * 1e-3
    L_A = cA["bed_height_cm"] * 1e-2
    Q_A = cA["flow_rate_mL_min"] / 6e7
    t_end_A = t_A[-1] * 60 * 1.5

    def objective(x):
        kLDF = 10 ** x[0]
        qmax = 10 ** x[1] * 1e-3
        try:
            tm, Cm = simulate_column(C0_A, L_A, Q_A, kLDF, qmax, col,
                                     Nz=40, t_end_s=t_end_A)
            return calc_rmse(tm, Cm, t_A, C_A)
        except Exception:
            return 10.0

    bounds = [(-5, -1), (np.log10(0.1), np.log10(30))]
    opt = differential_evolution(objective, bounds, popsize=10, maxiter=30,
                                 tol=1e-5, seed=42, polish=True, workers=1)
    kLDF_opt = 10 ** opt.x[0]
    qmax_opt_mg = 10 ** opt.x[1]
    qmax_opt_kg = qmax_opt_mg * 1e-3

    tm_cal, Cm_cal = simulate_column(C0_A, L_A, Q_A, kLDF_opt, qmax_opt_kg,
                                     col, t_end_s=t_end_A)
    rmse_cal = calc_rmse(tm_cal, Cm_cal, t_A, C_A)
    R2_cal = r_squared(C_A, np.interp(t_A, tm_cal, Cm_cal))

    calibration = {
        "k_LDF": float(kLDF_opt),
        "q_max_mg_g": float(qmax_opt_mg),
        "R2": float(R2_cal),
        "RMSE": float(rmse_cal),
    }

    # --- Validation on B-E ---
    validation = {}
    for lb in "BCDE":
        td, Cd, co = curves[lb]
        C0v = co["C0_mg_L"] * 1e-3
        Lv = co["bed_height_cm"] * 1e-2
        Qv = co["flow_rate_mL_min"] / 6e7
        t_end_v = td[-1] * 60 * 1.5
        try:
            tmv, Cmv = simulate_column(C0v, Lv, Qv, kLDF_opt, qmax_opt_kg,
                                       col, t_end_s=t_end_v)
            rv = calc_rmse(tmv, Cmv, td, Cd)
            r2v = r_squared(Cd, np.interp(td, tmv, Cmv))
        except Exception:
            rv, r2v = 1.0, 0.0
        validation[lb] = {"R2": float(r2v), "RMSE": float(rv)}

    # --- Sensitivity analysis: perturb each param by +/-20% ---
    sensitivity = {}
    perturbations = {
        "k_LDF_plus20": (kLDF_opt * 1.2, qmax_opt_kg),
        "k_LDF_minus20": (kLDF_opt * 0.8, qmax_opt_kg),
        "q_max_plus20": (kLDF_opt, qmax_opt_kg * 1.2),
        "q_max_minus20": (kLDF_opt, qmax_opt_kg * 0.8),
    }
    for name, (k, q) in perturbations.items():
        try:
            tm, Cm = simulate_column(C0_A, L_A, Q_A, k, q, col,
                                     t_end_s=t_end_A)
            rv = calc_rmse(tm, Cm, t_A, C_A)
            r2v = r_squared(C_A, np.interp(t_A, tm, Cm))
            sensitivity[name] = {"R2": float(r2v), "RMSE": float(rv)}
        except Exception:
            sensitivity[name] = {"R2": 0.0, "RMSE": 1.0}

    return {
        "pde_model": {"calibration": calibration, "validation": validation},
        "sensitivity": sensitivity,
    }


# =====================================================================
# Main
# =====================================================================
def main():
    col = load_column_params()
    curves = {}
    for lb in "ABCDE":
        curves[lb] = load_curve(f"/app/data/curve_{lb}.csv")

    results = {}

    # Empirical models
    results["yoon_nelson"] = {
        lb: fit_yoon_nelson(*curves[lb][:2]) for lb in "ABCDE"
    }
    results["thomas"] = {
        lb: fit_thomas(*curves[lb][:2], curves[lb][2], col) for lb in "ABCDE"
    }
    results["adams_bohart"] = {
        lb: fit_adams_bohart(*curves[lb][:2], curves[lb][2], col)
        for lb in "ABCDE"
    }

    # Capacity
    results["capacity"] = {
        lb: compute_capacity(*curves[lb][:2], curves[lb][2], col)
        for lb in "ABCDE"
    }

    # MTZ
    results["mtz"] = {
        lb: compute_mtz(*curves[lb][:2], curves[lb][2]) for lb in "ABCDE"
    }

    # BDST
    results["bdst"] = compute_bdst(curves, col)

    # PDE model + sensitivity
    pde_results = run_pde_analysis(curves, col)
    results["pde_model"] = pde_results["pde_model"]
    results["sensitivity"] = pde_results["sensitivity"]

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Wrote /app/results.json")


if __name__ == "__main__":
    main()
