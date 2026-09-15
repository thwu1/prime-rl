#!/usr/bin/env python3
"""Keplerian two-body orbit using symplectic Verlet integrator.

Delegates the velocity-Verlet integration step to the C library via
engine.verlet_step_c for symplectic energy conservation.
"""
import math
import sys
import os
import tomllib

sys.path.insert(0, "/app")
from engine import verlet_step_c, save_trajectory

with open("/app/config/orbit.toml", "rb") as f:
    cfg = tomllib.load(f)

GM = cfg["physics"]["GM"]
a = cfg["physics"]["semi_major_axis"]
e = cfg["physics"]["eccentricity"]
dt = cfg["numerical"]["dt"]
t_end = cfg["numerical"]["t_end"]

r_peri = a * (1 - e)
v_peri = math.sqrt(GM * (1 + e) / (a * (1 - e)))


def gravitational_accel(pos):
    x, y = pos[0], pos[1]
    r = math.sqrt(x * x + y * y)
    r3 = r ** 3
    return [-GM * x / r3, -GM * y / r3]


pos = [r_peri, 0.0]
vel = [0.0, v_peri]
times, data = [], []
t = 0.0
while t <= t_end:
    times.append(round(t, 6))
    data.append([round(s, 10) for s in pos + vel])
    pos, vel = verlet_step_c(pos, vel, dt, 2, gravitational_accel)
    t += dt

os.makedirs("/app/output", exist_ok=True)
step = max(1, len(times) // 500)
save_trajectory(
    "/app/output/orbit.json",
    times[::step], data[::step], ["x", "y", "vx", "vy"],
)
