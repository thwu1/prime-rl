#!/usr/bin/env python3
"""Coupled spring-mass oscillator system.

System: wall --k1-- m1 --kc-- m2 --k2-- wall
Reads parameters from TOML config; integrates with pure-Python RK4.
"""
import math
import sys
import os
import tomllib

sys.path.insert(0, "/app")
from engine import rk4_step, save_trajectory

with open("/app/config/oscillator.toml", "rb") as f:
    cfg = tomllib.load(f)

m1 = cfg["physics"]["mass1"]
m2 = cfg["physics"]["mass2"]
k1 = cfg["physics"]["k1"]
k2 = cfg["physics"]["k2"]
k_c = cfg["physics"]["k_coupling"]
dt = cfg["numerical"]["dt"]
t_end = cfg["numerical"]["t_end"]


def derivatives(state, t):
    q1, q2, v1, v2 = state
    f1 = (-k1 * q1 + k_c * (q2 - q1)) / m1
    f2 = (-k2 * q2 + k_c * (q2 - q1)) / m2
    return [v1, v2, f1, f2]


state = [
    cfg["physics"]["q1_init"],
    cfg["physics"]["q2_init"],
    cfg["physics"]["v1_init"],
    cfg["physics"]["v2_init"],
]
times, data = [], []
t = 0.0
while t <= t_end:
    times.append(round(t, 6))
    data.append([round(s, 10) for s in state])
    state = rk4_step(derivatives, state, t, dt)
    t += dt

os.makedirs("/app/output", exist_ok=True)
step = max(1, len(times) // 500)
save_trajectory(
    "/app/output/oscillator.json",
    times[::step], data[::step], ["q1", "q2", "v1", "v2"],
)
