#!/usr/bin/env python3
"""Projectile trajectory with quadratic air drag.

Reads aerodynamic parameters from TOML config and solves the ODE with
the pure-Python RK4 integrator.
"""
import math
import sys
import os
import tomllib

sys.path.insert(0, "/app")
from engine import rk4_step, save_trajectory

with open("/app/config/ballistic.toml", "rb") as f:
    cfg = tomllib.load(f)

g = cfg["physics"]["gravity"]
rho = cfg["physics"]["air_density"]
Cd = cfg["physics"]["drag_coefficient"]
A = cfg["physics"]["reference_area"]
m = cfg["physics"]["mass"]
v0 = cfg["physics"]["initial_speed"]
theta = math.radians(cfg["physics"]["launch_angle_deg"])
dt = cfg["numerical"]["dt"]


def derivatives(state, t):
    x, y, vx, vy = state
    v = math.sqrt(vx ** 2 + vy ** 2)
    if v < 1e-12:
        return [vx, vy, 0.0, -g]
    drag_accel = 0.5 * rho * Cd * A * v / m
    return [vx, vy, -drag_accel * vx, -g - drag_accel * vy]


state = [0.0, 0.0, v0 * math.cos(theta), v0 * math.sin(theta)]
times, data = [], []
t = 0.0
while True:
    times.append(round(t, 6))
    data.append([round(s, 10) for s in state])
    state = rk4_step(derivatives, state, t, dt)
    t += dt
    if t > 0.1 and state[1] < 0:
        break

os.makedirs("/app/output", exist_ok=True)
step = max(1, len(times) // 500)
save_trajectory(
    "/app/output/ballistic.json",
    times[::step], data[::step], ["x", "y", "vx", "vy"],
)
