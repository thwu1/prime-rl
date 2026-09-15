#!/usr/bin/env python3
"""
Solution: co-simulation convergence analysis for a controlled DC motor system.

Produces /app/reference.csv and /app/results.json.
"""


import sys
import json
import csv
import math

import numpy as np
from scipy.integrate import solve_ivp
from scipy.interpolate import interp1d

sys.path.insert(0, "/app")
from subsystems import PARAMS

# ── Parameters ───────────────────────────────────────────────────────────────

Ra = PARAMS["Ra"]
La = PARAMS["La"]
ke = PARAMS["ke"]
ratio = PARAMS["ratio"]
J_eff = PARAMS["J_eff"]
k_PI = PARAMS["k_PI"]
T_PI = PARAMS["T_PI"]
t_end = PARAMS["t_end"]


def w_desired(t):
    return 10.0 if t >= 0.1 else 0.0


def tau_load(t):
    return 3.0 if t >= 0.5 else 0.0


# ── 1. Monolithic reference ─────────────────────────────────────────────────

def monolithic_rhs(t, x):
    i_a, w_load, x_i = x
    wd = w_desired(t)
    tl = tau_load(t)
    w = ratio * w_load
    e = wd - w
    V = k_PI * (e + x_i / T_PI)
    di_a = (V - Ra * i_a - ke * ratio * w_load) / La
    dw_load = (ke * ratio * i_a + tl) / J_eff
    dx_i = e
    return [di_a, dw_load, dx_i]


print("Computing monolithic reference solution ...")
x0 = [0.0, 0.0, 0.0]
seg_bounds = [0.0, 0.1, 0.5, 1.0]
state = x0
t_all, y_all = [], []

for i in range(len(seg_bounds) - 1):
    ts, te = seg_bounds[i], seg_bounds[i + 1]
    n_pts = int(round((te - ts) / 0.0001)) + 1
    t_eval = np.linspace(ts, te, n_pts)
    if t_all:
        t_eval = t_eval[1:]
    sol = solve_ivp(
        monolithic_rhs, (ts, te), state,
        method="RK45", t_eval=t_eval,
        rtol=1e-12, atol=1e-14, max_step=1e-4,
    )
    if not sol.success:
        raise RuntimeError(f"solve_ivp failed on [{ts}, {te}]: {sol.message}")
    t_all.extend(sol.t.tolist())
    y_all.append(sol.y)
    state = sol.y[:, -1].tolist()

t_ref = np.array(t_all)
y_ref = np.hstack(y_all)
w_ref = ratio * y_ref[1]
ref_w_final = float(w_ref[-1])

print(f"  {len(t_ref)} points, w(1.0) = {ref_w_final:.8f}")

# Save reference.csv
with open("/app/reference.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["time", "w"])
    for i in range(len(t_ref)):
        writer.writerow([f"{t_ref[i]:.10f}", f"{w_ref[i]:.10f}"])

# Interpolator for RMSE
w_interp = interp1d(t_ref, w_ref, kind="cubic", fill_value="extrapolate")


# ── 2. Co-simulation master algorithms ──────────────────────────────────────

def rk4_drive(i_a, w_load, h, V, tl):
    """One RK4 micro-step for the Drive subsystem."""
    def f(ia, wl):
        return (
            (V - Ra * ia - ke * ratio * wl) / La,
            (ke * ratio * ia + tl) / J_eff,
        )
    k1a, k1w = f(i_a, w_load)
    k2a, k2w = f(i_a + h / 2 * k1a, w_load + h / 2 * k1w)
    k3a, k3w = f(i_a + h / 2 * k2a, w_load + h / 2 * k2w)
    k4a, k4w = f(i_a + h * k3a, w_load + h * k3w)
    return (
        i_a + h / 6 * (k1a + 2 * k2a + 2 * k3a + k4a),
        w_load + h / 6 * (k1w + 2 * k2w + 2 * k3w + k4w),
    )


def run_cosim(H, method, n_micro=200):
    """
    Run a full co-simulation.

    Parameters
    ----------
    H : float
        Communication step size.
    method : str
        'jacobi' or 'gauss_seidel'.
    n_micro : int
        Number of RK4 micro-steps per macro step for the Drive.

    Returns
    -------
    t_out, w_out : np.ndarray
        Time and motor-side speed at each communication point.
    diverged : bool
    """
    N = int(round(t_end / H))
    h = H / n_micro

    # States
    x_i = 0.0
    i_a = 0.0
    w_load = 0.0

    # Coupling variables
    w_val = 0.0   # Drive output (motor-side speed)
    V_val = 0.0   # Controller output (voltage)

    t_out = [0.0]
    w_out = [0.0]
    diverged = False

    for n in range(N):
        t_n = n * H
        wd = w_desired(t_n)
        tl = tau_load(t_n)

        if method == "jacobi":
            # Both subsystems use coupling values from previous step
            w_held = w_val
            V_held = V_val

            # Controller: exact integration with held inputs
            x_i_new = x_i + H * (wd - w_held)

            # Drive: RK4 micro-stepping with held V
            ia_new, wl_new = i_a, w_load
            for _ in range(n_micro):
                ia_new, wl_new = rk4_drive(ia_new, wl_new, h, V_held, tl)

            # Update states
            x_i = x_i_new
            i_a, w_load = ia_new, wl_new

            # Compute new coupling outputs
            w_val = ratio * w_load
            # Controller output uses held inputs (FMI semantics)
            V_val = k_PI * ((wd - w_held) + x_i / T_PI)

        else:  # gauss_seidel: Controller first, then Drive
            # Step 1: Advance Controller with previous-step w
            x_i += H * (wd - w_val)
            V_val = k_PI * ((wd - w_val) + x_i / T_PI)

            # Step 2: Advance Drive with updated V
            for _ in range(n_micro):
                i_a, w_load = rk4_drive(i_a, w_load, h, V_val, tl)
            w_val = ratio * w_load

        t_out.append(t_n + H)
        w_out.append(w_val)

        if abs(w_val) > 1e6 or math.isnan(w_val):
            diverged = True
            break

    return np.array(t_out), np.array(w_out), diverged


# ── 3. Convergence sweep ────────────────────────────────────────────────────

H_VALUES = [0.0001, 0.0002, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05]

results = {
    "reference_w_final": ref_w_final,
    "jacobi": {"errors": {}, "convergence_order": None, "H_crit": None},
    "gauss_seidel": {"errors": {}, "convergence_order": None, "H_crit": None},
}

for method in ("jacobi", "gauss_seidel"):
    print(f"\n=== {method} ===")
    stable_H = []
    stable_rmse = []

    for H in H_VALUES:
        t_c, w_c, diverged = run_cosim(H, method)

        if diverged or np.max(np.abs(w_c)) >= 100:
            results[method]["errors"][str(H)] = None
            print(f"  H={H}: UNSTABLE")
        else:
            w_ref_c = w_interp(t_c)
            rmse = float(np.sqrt(np.mean((w_c - w_ref_c) ** 2)))
            results[method]["errors"][str(H)] = rmse
            stable_H.append(H)
            stable_rmse.append(rmse)
            results[method]["H_crit"] = H
            print(f"  H={H}: RMSE = {rmse:.6e}")

    # Convergence order: use contiguous stable range from smallest H
    # (avoids skew from stability islands at larger H)
    cont_H, cont_rmse = [], []
    for H in H_VALUES:
        h_str = str(H)
        err = results[method]["errors"].get(h_str)
        if err is not None:
            cont_H.append(H)
            cont_rmse.append(err)
        else:
            break  # stop at first unstable step size

    if len(cont_H) >= 2:
        log_H = np.log(np.array(cont_H))
        log_e = np.log(np.array(cont_rmse))
        coeffs = np.polyfit(log_H, log_e, 1)
        results[method]["convergence_order"] = round(float(coeffs[0]), 4)
        print(f"  Convergence order: {coeffs[0]:.4f} (from {len(cont_H)} points)")

# ── 4. Save ─────────────────────────────────────────────────────────────────

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print("\nResults written to /app/results.json")
