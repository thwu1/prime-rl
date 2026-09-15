#!/usr/bin/env python3
"""
Solution: implement Forest-Ruth and PEFRL integrators,
then run the convergence benchmark.

"""

import math
import json
import sys
import os

# ─── Replicate system parameters from /app/benchmark.py ─────────
N_PARTICLES = 12
SPRING_K = 10.0
MASS = 1.0
REST_LENGTH = 1.0
TIMESTEPS = [0.004, 0.008, 0.016, 0.032, 0.064]
N_STEPS = 2000


def compute_forces(q):
    n = len(q)
    f = [0.0] * n
    for i in range(n - 1):
        dx = q[i + 1] - q[i] - REST_LENGTH
        f[i] += SPRING_K * dx
        f[i + 1] -= SPRING_K * dx
    return f


def compute_energy(q, p):
    ke = sum(pi * pi / (2.0 * MASS) for pi in p)
    pe = sum(
        0.5 * SPRING_K * (q[i + 1] - q[i] - REST_LENGTH) ** 2
        for i in range(len(q) - 1)
    )
    return ke + pe


def initial_conditions():
    q = [
        i * REST_LENGTH + 0.08 * math.sin(math.pi * i / N_PARTICLES)
        for i in range(N_PARTICLES)
    ]
    p = [
        MASS * 0.12 * math.cos(math.pi * (2 * i + 1) / (2 * N_PARTICLES))
        for i in range(N_PARTICLES)
    ]
    return q, p


# ═════════════════════════════════════════════════════════════════
#  Integrator implementations
# ═════════════════════════════════════════════════════════════════

def velocity_verlet(q, p, dt):
    n = len(q)
    f = compute_forces(q)
    p = [p[i] + 0.5 * dt * f[i] for i in range(n)]
    q = [q[i] + dt * p[i] / MASS for i in range(n)]
    f = compute_forces(q)
    p = [p[i] + 0.5 * dt * f[i] for i in range(n)]
    return q, p


def forest_ruth(q, p, dt):
    """Forest-Ruth 4th-order symplectic integrator.

    theta = 1 / (2 - 2^{1/3})

    Merged 7-stage scheme (XVXVXVX):
        c1 = c4 = theta / 2
        c2 = c3 = (1 - theta) / 2
        d1 = d3 = theta
        d2 = 1 - 2 * theta
    """
    theta = 1.0 / (2.0 - 2.0 ** (1.0 / 3.0))
    c1 = theta / 2.0
    c2 = (1.0 - theta) / 2.0
    d1 = theta
    d2 = 1.0 - 2.0 * theta

    n = len(q)

    # Stage 1: drift c1
    q = [q[i] + c1 * dt * p[i] / MASS for i in range(n)]
    # Stage 2: kick d1
    f = compute_forces(q)
    p = [p[i] + d1 * dt * f[i] for i in range(n)]
    # Stage 3: drift c2
    q = [q[i] + c2 * dt * p[i] / MASS for i in range(n)]
    # Stage 4: kick d2
    f = compute_forces(q)
    p = [p[i] + d2 * dt * f[i] for i in range(n)]
    # Stage 5: drift c3 = c2
    q = [q[i] + c2 * dt * p[i] / MASS for i in range(n)]
    # Stage 6: kick d3 = d1
    f = compute_forces(q)
    p = [p[i] + d1 * dt * f[i] for i in range(n)]
    # Stage 7: drift c4 = c1
    q = [q[i] + c1 * dt * p[i] / MASS for i in range(n)]

    return q, p


def pefrl(q, p, dt):
    """PEFRL 4th-order symplectic integrator.

    Optimised coefficients from Omelyan, Mryglod & Folk (2002):
        xi  = +0.1786178958448091
        lam = -0.2123418310626054
        chi = -0.6626458266981849e-1

    9-stage scheme (XVXVXVXVX): 5 drifts, 4 kicks.
    """
    xi = 0.1786178958448091
    lam = -0.2123418310626054
    chi = -0.06626458266981849

    half_lam_comp = (1.0 - 2.0 * lam) / 2.0
    mid_drift = 1.0 - 2.0 * (chi + xi)

    n = len(q)

    # 1: drift xi
    q = [q[i] + xi * dt * p[i] / MASS for i in range(n)]
    # 2: kick (1-2*lam)/2
    f = compute_forces(q)
    p = [p[i] + half_lam_comp * dt * f[i] for i in range(n)]
    # 3: drift chi
    q = [q[i] + chi * dt * p[i] / MASS for i in range(n)]
    # 4: kick lam
    f = compute_forces(q)
    p = [p[i] + lam * dt * f[i] for i in range(n)]
    # 5: drift (1-2*(chi+xi))
    q = [q[i] + mid_drift * dt * p[i] / MASS for i in range(n)]
    # 6: kick lam
    f = compute_forces(q)
    p = [p[i] + lam * dt * f[i] for i in range(n)]
    # 7: drift chi
    q = [q[i] + chi * dt * p[i] / MASS for i in range(n)]
    # 8: kick (1-2*lam)/2
    f = compute_forces(q)
    p = [p[i] + half_lam_comp * dt * f[i] for i in range(n)]
    # 9: drift xi
    q = [q[i] + xi * dt * p[i] / MASS for i in range(n)]

    return q, p


# ═════════════════════════════════════════════════════════════════
#  Benchmark harness
# ═════════════════════════════════════════════════════════════════

def max_energy_error(step_fn, dt, n_steps=N_STEPS):
    q, p = initial_conditions()
    E0 = compute_energy(q, p)
    worst = 0.0
    for _ in range(n_steps):
        q, p = step_fn(q, p, dt)
        E = compute_energy(q, p)
        rel = abs(E - E0) / abs(E0)
        if rel > worst:
            worst = rel
    return worst


def fit_order(dts, errs):
    lx = [math.log(d) for d in dts]
    ly = [math.log(e) for e in errs]
    n = len(lx)
    sx = sum(lx)
    sy = sum(ly)
    sxx = sum(x * x for x in lx)
    sxy = sum(x * y for x, y in zip(lx, ly))
    return (n * sxy - sx * sy) / (n * sxx - sx * sx)


def main():
    integrators = [
        ("velocity_verlet", velocity_verlet),
        ("forest_ruth", forest_ruth),
        ("pefrl", pefrl),
    ]

    results = {}

    for name, fn in integrators:
        print(f"\n--- {name} ---")
        dts_ok, errs_ok = [], []
        for dt in TIMESTEPS:
            e = max_energy_error(fn, dt)
            dts_ok.append(dt)
            errs_ok.append(e)
            print(f"  dt={dt:<10.4f}  max|dE/E0| = {e:.6e}")

        order = fit_order(dts_ok, errs_ok)
        results[f"{name}_order"] = round(order, 4)
        results[f"{name}_errors"] = {
            str(d): e for d, e in zip(dts_ok, errs_ok)
        }
        print(f"  convergence order = {order:.4f}")

    # Error ratio at the largest common timestep
    fr_errs = results["forest_ruth_errors"]
    pe_errs = results["pefrl_errors"]
    common = sorted(
        set(fr_errs.keys()) & set(pe_errs.keys()), key=float, reverse=True
    )
    dt_key = common[0]
    results["pefrl_to_fr_error_ratio"] = pe_errs[dt_key] / fr_errs[dt_key]
    results["ratio_timestep"] = dt_key

    results["fr_force_evals"] = 3
    results["pefrl_force_evals"] = 4

    with open("/app/results.json", "w") as fp:
        json.dump(results, fp, indent=2)
    print(f"\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
