#!/usr/bin/env python3
"""
Solve the stiff ODE stability analysis task.

Step 1: Read Fortran source to extract equations.
Step 2: Integrate to find the limit cycle.
Step 3: Detect the period.
Step 4: Integrate augmented variational system for monodromy matrix.
Step 5: Extract Floquet multipliers and trace integral.
"""

import numpy as np
from scipy.integrate import solve_ivp
import json

# System constants extracted from fortran/system.f
S = 77.27
Q = 8.375e-6
W = 0.161


def rhs(t, y):
    """Right-hand side extracted from FEVAL subroutine."""
    y1, y2, y3 = y[0], y[1], y[2]
    return [
        S * (y2 + y1 * (1.0 - Q * y1 - y2)),
        (y3 - (1.0 + y1) * y2) / S,
        W * (y1 - y3),
    ]


def jac(y):
    """Jacobian extracted from JEVAL subroutine."""
    y1, y2, y3 = y[0], y[1], y[2]
    J = np.zeros((3, 3))
    J[0, 0] = S * (1.0 - 2.0 * Q * y1 - y2)
    J[0, 1] = S * (1.0 - y1)
    J[0, 2] = 0.0
    J[1, 0] = -y2 / S
    J[1, 1] = -(1.0 + y1) / S
    J[1, 2] = 1.0 / S
    J[2, 0] = W
    J[2, 1] = 0.0
    J[2, 2] = -W
    return J


def augmented_rhs(t, z):
    """13D augmented system: 3 state + 9 variational + 1 trace integral."""
    y = z[:3]
    Phi = z[3:12].reshape(3, 3)

    dy = rhs(t, y)
    J = jac(y)
    dPhi = (J @ Phi).ravel()
    dI = np.trace(J)

    return np.concatenate([dy, dPhi, [dI]])


# --- Step 1: Reach the limit cycle ---
print("Step 1: Integrating to t=3000 to reach the limit cycle...")
y0 = np.array([1.0, 2.0, 3.0])
sol_trans = solve_ivp(rhs, [0, 3000], y0, method="Radau",
                      rtol=1e-12, atol=1e-14, dense_output=True)
assert sol_trans.success, f"Transient integration failed: {sol_trans.message}"

# --- Step 2: Find the period via successive y1 maxima ---
print("Step 2: Detecting period via y1 maxima...")
y_lc = sol_trans.sol(3000)
print(f"  State on limit cycle: [{y_lc[0]:.6f}, {y_lc[1]:.6f}, {y_lc[2]:.6f}]")


def dy1_event(t, y):
    """dy1/dt = 0 crossing (y1 extremum)."""
    return S * (y[1] + y[0] * (1.0 - Q * y[0] - y[1]))


dy1_event.direction = -1  # dy1/dt goes + to - at a maximum

sol_det = solve_ivp(rhs, [0, 1000], y_lc, method="Radau",
                    rtol=1e-13, atol=1e-15, events=dy1_event)
assert sol_det.success, f"Period detection failed: {sol_det.message}"

maxima_t = sol_det.t_events[0]
assert len(maxima_t) >= 2, f"Need >= 2 y1 maxima, found {len(maxima_t)}"

T = float(maxima_t[1] - maxima_t[0])
print(f"  Period T = {T:.12f}")

# --- Step 3: Integrate augmented system over one period ---
print("Step 3: Integrating 13D augmented system over one period...")
z0 = np.zeros(13)
z0[:3] = y_lc
z0[3:12] = np.eye(3).ravel()
z0[12] = 0.0

sol_aug = solve_ivp(augmented_rhs, [0, T], z0, method="Radau",
                    rtol=1e-11, atol=1e-13)
assert sol_aug.success, f"Augmented integration failed: {sol_aug.message}"

z_final = sol_aug.y[:, -1]
M = z_final[3:12].reshape(3, 3)
trace_integral = float(z_final[12])

print("  Monodromy matrix M:")
for row in M:
    print(f"    [{row[0]:14.8e}, {row[1]:14.8e}, {row[2]:14.8e}]")

# --- Step 4: Compute Floquet multipliers ---
eigenvalues = np.linalg.eigvals(M)
idx = np.argsort(-np.abs(eigenvalues))
eigenvalues = eigenvalues[idx]

print("\n  Floquet multipliers:")
for i, ev in enumerate(eigenvalues):
    print(f"    lambda_{i+1} = {ev.real:+.10e} {ev.imag:+.10e}i  "
          f"(|lambda| = {abs(ev):.10e})")

# Verify return to start
y_ret = z_final[:3]
ret_err = np.linalg.norm(y_ret - y_lc) / np.linalg.norm(y_lc)
print(f"\n  Return error: {ret_err:.2e}")
print(f"  Trace integral: {trace_integral:.6f}")
print(f"  det(M): {np.linalg.det(M):.4e}")

# --- Step 5: Write results ---
with open("/app/period.txt", "w") as f:
    f.write(f"{T:.15e}")

with open("/app/monodromy_matrix.json", "w") as f:
    json.dump(M.tolist(), f, indent=2)

fm_list = [{"real": float(ev.real), "imag": float(ev.imag)} for ev in eigenvalues]
with open("/app/floquet_multipliers.json", "w") as f:
    json.dump(fm_list, f, indent=2)

with open("/app/trace_integral.txt", "w") as f:
    f.write(f"{trace_integral:.15e}")

print("\nAll results written to /app/.")
