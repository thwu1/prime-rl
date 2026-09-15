#!/usr/bin/env python3
"""Generate HDF5 trajectory data files for Physics Trajectory Forensics task."""

import json
import math
import os

import h5py
import numpy as np

OUTPUT_DIR = "/app/data"
RNG = np.random.default_rng(seed=20260612)

NOISE_SIGMA_POS = 0.001
NOISE_SIGMA_VEL = 0.005


def write_h5(filename, scenario_id, description, dt, g_decl, friction_decl,
             cor_decl, bodies, body_ids, times, trajs,
             noise_pos=NOISE_SIGMA_POS, noise_vel=NOISE_SIGMA_VEL):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)
    times_arr = np.asarray(times, dtype=np.float64)
    with h5py.File(path, "w") as f:
        f.attrs["scenario_id"] = scenario_id
        f.attrs["description"] = description
        f.attrs["dt"] = float(dt)
        f.attrs["noise_sigma_pos"] = float(noise_pos)
        f.attrs["noise_sigma_vel"] = float(noise_vel)
        f.attrs["body_order"] = json.dumps(body_ids)

        decl = f.create_group("declared")
        decl.attrs["gravity"] = float(g_decl)
        decl.attrs["friction"] = float(friction_decl)
        decl.attrs["cor"] = float(cor_decl)

        bg = decl.create_group("bodies")
        for b in bodies:
            grp = bg.create_group(b["id"])
            grp.attrs["mass"] = float(b["mass"])
            grp.attrs["radius"] = float(b["radius"])

        traj = f.create_group("trajectory")
        traj.create_dataset("time", data=times_arr)

        for bid in body_ids:
            bgrp = traj.create_group(bid)
            cp = np.asarray(trajs[bid]["pos"], dtype=np.float64)
            cv = np.asarray(trajs[bid]["vel"], dtype=np.float64)
            bgrp.create_dataset("position",
                                data=cp + RNG.normal(0, noise_pos, cp.shape))
            bgrp.create_dataset("velocity",
                                data=cv + RNG.normal(0, noise_vel, cv.shape))
    print(f"  {path}")


def gen_freefall():
    g, dt, y0, N = 9.81, 0.01, 100.0, 450
    t = np.arange(N) * dt
    pos = np.column_stack([np.zeros(N), y0 - 0.5 * g * t ** 2])
    vel = np.column_stack([np.zeros(N), -g * t])
    write_h5("freefall.h5", "freefall",
             "Single body released from height under gravity",
             dt, 9.81, 0.0, float("nan"),
             [{"id": "ball_1", "mass": 1.0, "radius": 0.5}],
             ["ball_1"], t,
             {"ball_1": {"pos": pos, "vel": vel}})


def gen_elastic_1d():
    m1, m2 = 2.0, 3.0
    v1, v2 = 5.0, -2.0
    x1_0, x2_0, r = 0.0, 10.0, 0.5
    dt = 0.01
    tc = (x2_0 - x1_0 - 2 * r) / (v1 - v2)
    v1p = ((m1 - m2) * v1 + 2 * m2 * v2) / (m1 + m2)
    v2p = ((m2 - m1) * v2 + 2 * m1 * v1) / (m1 + m2)
    xc1 = x1_0 + v1 * tc
    xc2 = x2_0 + v2 * tc
    N = 300
    t = np.arange(N) * dt
    pa, va, pb, vb = [np.zeros((N, 2)) for _ in range(4)]
    for i in range(N):
        if t[i] < tc:
            pa[i] = [x1_0 + v1 * t[i], 0]
            va[i] = [v1, 0]
            pb[i] = [x2_0 + v2 * t[i], 0]
            vb[i] = [v2, 0]
        else:
            d = t[i] - tc
            pa[i] = [xc1 + v1p * d, 0]
            va[i] = [v1p, 0]
            pb[i] = [xc2 + v2p * d, 0]
            vb[i] = [v2p, 0]
    write_h5("elastic_1d.h5", "elastic_1d",
             "Two bodies approaching head-on in one dimension",
             dt, 0.0, 0.0, 1.0,
             [{"id": "ball_A", "mass": 2.0, "radius": 0.5},
              {"id": "ball_B", "mass": 3.0, "radius": 0.5}],
             ["ball_A", "ball_B"], t,
             {"ball_A": {"pos": pa, "vel": va},
              "ball_B": {"pos": pb, "vel": vb}})


def gen_projectile():
    g, v0, angle, dt = 9.81, 20.0, math.pi / 4, 0.01
    vx0, vy0 = v0 * math.cos(angle), v0 * math.sin(angle)
    t_land = 2 * vy0 / g
    N = int(t_land / dt)
    t = np.arange(N) * dt
    pos = np.column_stack([vx0 * t, vy0 * t - 0.5 * g * t ** 2])
    vel = np.column_stack([np.full(N, vx0), vy0 - g * t])
    write_h5("projectile.h5", "projectile",
             "Single body launched at an angle under gravity",
             dt, 9.81, 0.0, float("nan"),
             [{"id": "projectile", "mass": 1.0, "radius": 0.25}],
             ["projectile"], t,
             {"projectile": {"pos": pos, "vel": vel}})


def gen_friction_slide():
    g, mu, v0, dt = 9.81, 0.3, 10.0, 0.01
    decel = mu * g
    t_stop = v0 / decel
    x_stop = v0 * t_stop - 0.5 * decel * t_stop ** 2
    N = 380
    t = np.arange(N) * dt
    pos, vel = np.zeros((N, 2)), np.zeros((N, 2))
    for i in range(N):
        if t[i] <= t_stop:
            vel[i, 0] = v0 - decel * t[i]
            pos[i, 0] = v0 * t[i] - 0.5 * decel * t[i] ** 2
        else:
            vel[i, 0] = 0.0
            pos[i, 0] = x_stop
    write_h5("friction_slide.h5", "friction_slide",
             "Object moving along a horizontal surface, decelerating",
             dt, 9.81, 0.3, float("nan"),
             [{"id": "slider", "mass": 1.0, "radius": 0.25}],
             ["slider"], t,
             {"slider": {"pos": pos, "vel": vel}})


def gen_oblique_elastic():
    mA, mB = 2.0, 1.0
    rA, rB = 0.5, 0.5
    vA, vB = [4.0, 1.0], [-2.0, -1.0]
    pA, pB = [0.0, 0.0], [6.0, 2.0]
    dt = 0.01
    d0 = [pA[0] - pB[0], pA[1] - pB[1]]
    dv = [vA[0] - vB[0], vA[1] - vB[1]]
    a = dv[0] ** 2 + dv[1] ** 2
    b = 2 * (d0[0] * dv[0] + d0[1] * dv[1])
    c = d0[0] ** 2 + d0[1] ** 2 - (rA + rB) ** 2
    tc = (-b - math.sqrt(b ** 2 - 4 * a * c)) / (2 * a)
    pcA = [pA[0] + vA[0] * tc, pA[1] + vA[1] * tc]
    pcB = [pB[0] + vB[0] * tc, pB[1] + vB[1] * tc]
    nx = pcB[0] - pcA[0]
    ny = pcB[1] - pcA[1]
    nl = math.sqrt(nx ** 2 + ny ** 2)
    nx /= nl
    ny /= nl
    tx, ty = -ny, nx
    vAn = vA[0] * nx + vA[1] * ny
    vBn = vB[0] * nx + vB[1] * ny
    vAt = vA[0] * tx + vA[1] * ty
    vBt = vB[0] * tx + vB[1] * ty
    vAnp = ((mA - mB) * vAn + 2 * mB * vBn) / (mA + mB)
    vBnp = ((mB - mA) * vBn + 2 * mA * vAn) / (mA + mB)
    vAp = [vAnp * nx + vAt * tx, vAnp * ny + vAt * ty]
    vBp = [vBnp * nx + vBt * tx, vBnp * ny + vBt * ty]
    N = 250
    t = np.arange(N) * dt
    pa, va, pb, vb = [np.zeros((N, 2)) for _ in range(4)]
    for i in range(N):
        if t[i] < tc:
            pa[i] = [pA[0] + vA[0] * t[i], pA[1] + vA[1] * t[i]]
            va[i] = vA
            pb[i] = [pB[0] + vB[0] * t[i], pB[1] + vB[1] * t[i]]
            vb[i] = vB
        else:
            d = t[i] - tc
            pa[i] = [pcA[0] + vAp[0] * d, pcA[1] + vAp[1] * d]
            va[i] = vAp
            pb[i] = [pcB[0] + vBp[0] * d, pcB[1] + vBp[1] * d]
            vb[i] = vBp
    write_h5("oblique_elastic.h5", "oblique_elastic",
             "Two bodies approaching at an angle in two dimensions",
             dt, 0.0, 0.0, 1.0,
             [{"id": "ball_A", "mass": 2.0, "radius": 0.5},
              {"id": "ball_B", "mass": 1.0, "radius": 0.5}],
             ["ball_A", "ball_B"], t,
             {"ball_A": {"pos": pa, "vel": va},
              "ball_B": {"pos": pb, "vel": vb}})


def gen_gravity_mismatch():
    g_actual = 5.0
    dt, y0 = 0.01, 100.0
    t_land = math.sqrt(2 * y0 / g_actual)
    N = int(t_land / dt)
    t = np.arange(N) * dt
    pos = np.column_stack([np.zeros(N), y0 - 0.5 * g_actual * t ** 2])
    vel = np.column_stack([np.zeros(N), -g_actual * t])
    write_h5("gravity_mismatch.h5", "gravity_mismatch",
             "Single body released from height under gravity",
             dt, 9.81, 0.0, float("nan"),
             [{"id": "ball_1", "mass": 1.0, "radius": 0.5}],
             ["ball_1"], t,
             {"ball_1": {"pos": pos, "vel": vel}})


def gen_energy_gain():
    m1, m2 = 1.0, 1.0
    v1, v2 = 4.0, -2.0
    x10, x20, r = 0.0, 8.0, 0.5
    dt = 0.01
    tc = (x20 - x10 - 2 * r) / (v1 - v2)
    # Post-collision velocities: momentum conserved (p=2) but energy gained
    v1p, v2p = -3.0, 5.0
    xc1, xc2 = x10 + v1 * tc, x20 + v2 * tc
    N = 250
    t = np.arange(N) * dt
    pa, va, pb, vb = [np.zeros((N, 2)) for _ in range(4)]
    for i in range(N):
        if t[i] < tc:
            pa[i] = [x10 + v1 * t[i], 0]
            va[i] = [v1, 0]
            pb[i] = [x20 + v2 * t[i], 0]
            vb[i] = [v2, 0]
        else:
            d = t[i] - tc
            pa[i] = [xc1 + v1p * d, 0]
            va[i] = [v1p, 0]
            pb[i] = [xc2 + v2p * d, 0]
            vb[i] = [v2p, 0]
    write_h5("energy_gain.h5", "energy_gain",
             "Two equal-mass bodies approaching head-on",
             dt, 0.0, 0.0, 1.0,
             [{"id": "ball_A", "mass": 1.0, "radius": 0.5},
              {"id": "ball_B", "mass": 1.0, "radius": 0.5}],
             ["ball_A", "ball_B"], t,
             {"ball_A": {"pos": pa, "vel": va},
              "ball_B": {"pos": pb, "vel": vb}})


def gen_momentum_change():
    mA, mB = 2.0, 1.0
    v1, v2 = 5.0, 0.0
    x10, x20, r = 0.0, 8.0, 0.5
    dt = 0.01
    tc = (x20 - x10 - 2 * r) / (v1 - v2)
    v1p, v2p = 5.0 / 3.0, 35.0 / 3.0
    xc1, xc2 = x10 + v1 * tc, x20 + v2 * tc
    N = 250
    t = np.arange(N) * dt
    pa, va, pb, vb = [np.zeros((N, 2)) for _ in range(4)]
    for i in range(N):
        if t[i] < tc:
            pa[i] = [x10 + v1 * t[i], 0]
            va[i] = [v1, 0]
            pb[i] = [x20 + v2 * t[i], 0]
            vb[i] = [v2, 0]
        else:
            d = t[i] - tc
            pa[i] = [xc1 + v1p * d, 0]
            va[i] = [v1p, 0]
            pb[i] = [xc2 + v2p * d, 0]
            vb[i] = [v2p, 0]
    write_h5("momentum_change.h5", "momentum_change",
             "Two bodies of different mass, one initially at rest",
             dt, 0.0, 0.0, 1.0,
             [{"id": "ball_A", "mass": 2.0, "radius": 0.5},
              {"id": "ball_B", "mass": 1.0, "radius": 0.5}],
             ["ball_A", "ball_B"], t,
             {"ball_A": {"pos": pa, "vel": va},
              "ball_B": {"pos": pb, "vel": vb}})


if __name__ == "__main__":
    gen_freefall()
    gen_elastic_1d()
    gen_projectile()
    gen_friction_slide()
    gen_oblique_elastic()
    gen_gravity_mismatch()
    gen_energy_gain()
    gen_momentum_change()
    print("All HDF5 trajectory files generated.")
