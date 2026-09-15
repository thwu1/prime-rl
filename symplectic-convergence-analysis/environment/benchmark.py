#!/usr/bin/env python3
"""
Symplectic Integrator Convergence Benchmark
=============================================

Benchmarks symplectic integrators on a 1D harmonic oscillator chain.

System: N particles connected by harmonic springs.
    H = sum_i p_i^2 / (2*m) + sum_{i=0}^{N-2} k/2 * (q_{i+1} - q_i - r0)^2

Three integrators are benchmarked:
  1. Velocity Verlet (2nd order) — provided, working
  2. Forest-Ruth  (4th order) — NOT YET IMPLEMENTED
  3. PEFRL        (4th order) — NOT YET IMPLEMENTED

Implement the two missing integrators, then run this script.
Results are written to /app/results.json.
"""

import math
import json


# ─── System parameters ──────────────────────────────────────────
N_PARTICLES = 12
SPRING_K = 10.0       # spring constant
MASS = 1.0            # particle mass
REST_LENGTH = 1.0     # equilibrium bond length

# ─── Benchmark parameters ───────────────────────────────────────
TIMESTEPS = [0.004, 0.008, 0.016, 0.032, 0.064]
N_STEPS = 2000


# ═════════════════════════════════════════════════════════════════
#  PHYSICS
# ═════════════════════════════════════════════════════════════════

def compute_forces(q):
    """Compute forces on all particles from harmonic bonds.

    Bond potential:  V_i = k/2 * (q_{i+1} - q_i - r0)^2
    Force on i from bond i:    F_i  =  +k * (q_{i+1} - q_i - r0)
    Force on i+1 from bond i:  F_{i+1} = -k * (q_{i+1} - q_i - r0)
    """
    n = len(q)
    f = [0.0] * n
    for i in range(n - 1):
        dx = q[i + 1] - q[i] - REST_LENGTH
        f[i] += SPRING_K * dx
        f[i + 1] -= SPRING_K * dx
    return f


def compute_energy(q, p):
    """Total energy = kinetic + potential."""
    ke = sum(pi * pi / (2.0 * MASS) for pi in p)
    pe = sum(
        0.5 * SPRING_K * (q[i + 1] - q[i] - REST_LENGTH) ** 2
        for i in range(len(q) - 1)
    )
    return ke + pe


def initial_conditions():
    """Deterministic ICs: lattice + normal-mode–like perturbation."""
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
#  INTEGRATORS  — signature: (q, p, dt) → (q, p)
# ═════════════════════════════════════════════════════════════════

def velocity_verlet(q, p, dt):
    """Velocity Verlet / Stoermer-Verlet (order 2).

    VKV (velocity–kick–velocity) splitting:
        p  += (dt/2) * F(q)
        q  += dt * p / m
        p  += (dt/2) * F(q)
    """
    n = len(q)
    f = compute_forces(q)
    p = [p[i] + 0.5 * dt * f[i] for i in range(n)]
    q = [q[i] + dt * p[i] / MASS for i in range(n)]
    f = compute_forces(q)
    p = [p[i] + 0.5 * dt * f[i] for i in range(n)]
    return q, p


def forest_ruth(q, p, dt):
    """Forest-Ruth 4th-order symplectic integrator.

    Ref: E. Forest & R.D. Ruth, Physica D 43 (1990) 105-117.

    Symmetric triple-jump composition of leapfrog:
        S4(h) = S2(theta*h)  o  S2((1 - 2*theta)*h)  o  S2(theta*h)

    where theta = 1 / (2 - 2^{1/3}).

    After merging adjacent position drifts, the scheme becomes 7 stages
    (4 drifts, 3 kicks).  Forces MUST be recomputed after every drift.

    Returns updated (q, p).
    """
    raise NotImplementedError("Forest-Ruth integrator not yet implemented")


def pefrl(q, p, dt):
    """Position-Extended Forest-Ruth-Like 4th-order symplectic integrator.

    Ref: I.P. Omelyan, I.M. Mryglod & R. Folk,
         Comp. Phys. Comm. 146 (2002) 188-199  (Table 1, "PEFRL" row).

    This is a 9-stage position-extended scheme (5 drifts, 4 kicks) whose
    error constants are significantly smaller than Forest-Ruth, at the
    cost of one additional force evaluation per step.

    Stage pattern (XVXVXVXVX):
        q += xi            * dt * p/m
        p += (1-2*lam)/2   * dt * F(q)
        q += chi            * dt * p/m
        p += lam            * dt * F(q)
        q += (1-2*(chi+xi))* dt * p/m
        p += lam            * dt * F(q)
        q += chi            * dt * p/m
        p += (1-2*lam)/2   * dt * F(q)
        q += xi            * dt * p/m

    Returns updated (q, p).
    """
    raise NotImplementedError("PEFRL integrator not yet implemented")


# ═════════════════════════════════════════════════════════════════
#  BENCHMARK HARNESS
# ═════════════════════════════════════════════════════════════════

def max_energy_error(step_fn, dt, n_steps=N_STEPS):
    """Return max |Delta E / E0| over a trajectory."""
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
    """Least-squares slope of log(err) vs log(dt)."""
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
        print(f"\n{'=' * 50}")
        print(f"  {name}")
        print(f"{'=' * 50}")
        dts_ok, errs_ok = [], []
        for dt in TIMESTEPS:
            try:
                e = max_energy_error(fn, dt)
                dts_ok.append(dt)
                errs_ok.append(e)
                print(f"  dt={dt:<10.4f}  max|dE/E0| = {e:.6e}")
            except NotImplementedError:
                print(f"  dt={dt:<10.4f}  *** NOT IMPLEMENTED ***")
            except Exception as exc:
                print(f"  dt={dt:<10.4f}  FAILED: {exc}")

        if len(dts_ok) >= 2 and all(e > 0 for e in errs_ok):
            order = fit_order(dts_ok, errs_ok)
            results[f"{name}_order"] = round(order, 4)
            print(f"  >>> convergence order = {order:.4f}")
        else:
            results[f"{name}_order"] = None

        results[f"{name}_errors"] = {
            str(d): e for d, e in zip(dts_ok, errs_ok)
        }

    # ── Error ratio at a common timestep ──
    fr_errs = results.get("forest_ruth_errors", {})
    pe_errs = results.get("pefrl_errors", {})
    # pick the largest common timestep
    common = sorted(
        set(fr_errs.keys()) & set(pe_errs.keys()), key=float, reverse=True
    )
    if common:
        dt_key = common[0]
        results["pefrl_to_fr_error_ratio"] = pe_errs[dt_key] / fr_errs[dt_key]
        results["ratio_timestep"] = dt_key

    # ── Force evaluation counts ──
    results["fr_force_evals"] = 3
    results["pefrl_force_evals"] = 4

    with open("/app/results.json", "w") as fp:
        json.dump(results, fp, indent=2)

    print(f"\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
