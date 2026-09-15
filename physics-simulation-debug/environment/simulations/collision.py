#!/usr/bin/env python3
"""2D elastic collision between two unequal-mass particles.

Reads particle parameters from TOML config.  Free particles (no
external forces) interact via a single elastic collision.
"""
import math
import json
import os
import tomllib

with open("/app/config/collision.toml", "rb") as f:
    cfg = tomllib.load(f)

m1 = cfg["physics"]["mass1"]
m2 = cfg["physics"]["mass2"]
v1x = cfg["physics"]["v1x"]
v1y = cfg["physics"]["v1y"]
v2x = cfg["physics"]["v2x"]
v2y = cfg["physics"]["v2y"]
r_collision = cfg["physics"]["collision_radius"]
x1_0 = cfg["physics"]["x1"]
y1_0 = cfg["physics"]["y1"]
x2_0 = cfg["physics"]["x2"]
y2_0 = cfg["physics"]["y2"]
dt = cfg["numerical"]["dt"]
t_end = cfg["numerical"]["t_end"]

times, data = [], []
t = 0.0
vx1, vy1 = v1x, v1y
vx2, vy2 = v2x, v2y
x1, y1 = x1_0, y1_0
x2, y2 = x2_0, y2_0
collided = False

while t <= t_end:
    times.append(round(t, 6))
    data.append([round(s, 10) for s in [x1, y1, vx1, vy1, x2, y2, vx2, vy2]])

    ddx = x2 - x1
    ddy = y2 - y1
    dist = math.sqrt(ddx ** 2 + ddy ** 2)

    if not collided and dist <= r_collision:
        collided = True
        nx = ddx / dist
        ny = ddy / dist
        tx, ty = -ny, nx

        v1n = vx1 * nx + vy1 * ny
        v2n = vx2 * nx + vy2 * ny
        v1t = vx1 * tx + vy1 * ty
        v2t = vx2 * tx + vy2 * ty

        v1n_new = ((m1 + m2) * v1n + 2 * m2 * v2n) / (m1 + m2)
        v2n_new = ((m2 + m1) * v2n + 2 * m1 * v1n) / (m1 + m2)

        vx1 = v1n_new * nx + v1t * tx
        vy1 = v1n_new * ny + v1t * ty
        vx2 = v2n_new * nx + v2t * tx
        vy2 = v2n_new * ny + v2t * ty

    x1 += vx1 * dt
    y1 += vy1 * dt
    x2 += vx2 * dt
    y2 += vy2 * dt
    t += dt

os.makedirs("/app/output", exist_ok=True)
step = max(1, len(times) // 500)
with open("/app/output/collision.json", "w") as fh:
    json.dump(
        {
            "times": times[::step],
            "headers": ["x1", "y1", "vx1", "vy1", "x2", "y2", "vx2", "vy2"],
            "data": data[::step],
        },
        fh,
    )
