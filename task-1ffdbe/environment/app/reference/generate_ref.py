#!/usr/bin/env python3
"""Generate reference solution using scipy high-order solver."""
import numpy as np
from scipy.integrate import solve_ivp

N = 50
Du, Dv = 0.02, 0.02
A, B = 1.0, 3.0
t_end = 10.0

dx = 1.0 / (N + 1)
x_grid = np.linspace(dx, 1.0 - dx, N)
n = 2 * N

y0 = np.zeros(n)
y0[0::2] = 1.0 + np.sin(2.0 * np.pi * x_grid)
y0[1::2] = 3.0


def rhs(t, y):
    u = y[0::2]
    v = y[1::2]
    u_pad = np.concatenate(([A], u, [A]))
    v_pad = np.concatenate(([B / A], v, [B / A]))
    dx2 = dx * dx
    dydt = np.zeros_like(y)
    dydt[0::2] = (Du * (u_pad[:-2] - 2 * u_pad[1:-1] + u_pad[2:]) / dx2
                  + A - (B + 1) * u + u * u * v)
    dydt[1::2] = (Dv * (v_pad[:-2] - 2 * v_pad[1:-1] + v_pad[2:]) / dx2
                  + B * u - u * u * v)
    return dydt


sol = solve_ivp(rhs, [0, t_end], y0, method='Radau',
                rtol=1e-10, atol=1e-12)
assert sol.success, f"Reference solver failed: {sol.message}"

y_final = sol.y[:, -1]
np.savez('/app/reference/solution_ref.npz', y_final=y_final)
print(f"Reference generated: u_max={y_final[0::2].max():.6f}, v_max={y_final[1::2].max():.6f}")
