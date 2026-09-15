#!/usr/bin/env python3
"""1D thermal diffusion solved with FTCS finite-difference scheme.

Delegates the stencil computation to the C library via engine.ftcs_step_c.
"""
import json
import os
import sys
import tomllib

sys.path.insert(0, "/app")
from engine import ftcs_step_c

with open("/app/config/diffusion.toml", "rb") as f:
    cfg = tomllib.load(f)

alpha = cfg["physics"]["thermal_diffusivity"]
L = cfg["physics"]["length"]
T_left = cfg["physics"]["T_left"]
T_right = cfg["physics"]["T_right"]
nx = cfg["numerical"]["grid_points"]
t_end = cfg["numerical"]["t_end"]
save_interval = cfg["numerical"]["save_interval"]

dx = L / (nx - 1)
dt = 0.4 * dx ** 2 / alpha
r = alpha * dt / dx ** 2

x = [i * dx for i in range(nx)]
u = [T_left * (1.0 - xi / L) + T_right * (xi / L) for xi in x]
u[0] = T_left
u[-1] = T_right

times = []
snapshots = []
t = 0.0
next_save = 0.0

while t <= t_end + 1e-10:
    if t >= next_save - 1e-10:
        times.append(round(t, 6))
        snapshots.append([round(ui, 10) for ui in u])
        next_save += save_interval

    u_new = ftcs_step_c(u, nx, r)
    u_new[0] = T_left
    u_new[-1] = T_right
    u = u_new
    t += dt

os.makedirs("/app/output", exist_ok=True)
with open("/app/output/diffusion.json", "w") as fh:
    json.dump(
        {"times": times, "headers": [f"x={round(xi, 4)}" for xi in x], "data": snapshots},
        fh,
    )
