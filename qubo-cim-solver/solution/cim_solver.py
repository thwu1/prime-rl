#!/usr/bin/env python3
"""Coherent Ising Machine (CIM) solver for Ising and QUBO instances.

Simulates measurement-feedback DOPO network dynamics:
  dx_i/dt = (-1 + p(t) - x_i^2) x_i  -  xi * (J @ x + h)_i  +  noise
where p(t) ramps linearly through the bifurcation threshold.
Post-processes with greedy single-spin-flip local search.
"""
import json
import os

import numpy as np



# ---------------------------------------------------------------------------
# QUBO <-> Ising conversion
# ---------------------------------------------------------------------------

def qubo_to_ising(Q_matrix):
    """Convert upper-triangular QUBO to Ising model.

    Via the substitution x_i = (1 + s_i) / 2:
      J_ij   = Q_ij / 4           for i < j
      h_i    = Q_ii/2 + (1/4) sum_{j!=i} Q_{min,max}
      offset = sum Q_ii/2 + sum_{i<j} Q_ij/4

    Returns (couplings_list, fields_list, offset).
    """
    n = len(Q_matrix)
    Q = [[float(Q_matrix[i][j]) for j in range(n)] for i in range(n)]

    couplings = []
    for i in range(n):
        for j in range(i + 1, n):
            if Q[i][j] != 0.0:
                couplings.append([i, j, Q[i][j] / 4.0])

    fields = []
    for i in range(n):
        h = Q[i][i] / 2.0
        for j in range(n):
            if j != i:
                mi, ma = (i, j) if i < j else (j, i)
                h += Q[mi][ma] / 4.0
        fields.append(h)

    offset = sum(Q[i][i] / 2.0 for i in range(n))
    offset += sum(Q[i][j] / 4.0 for i in range(n) for j in range(i + 1, n))

    return couplings, fields, offset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_J_h(n, couplings, fields):
    """Build symmetric coupling matrix J and field vector h."""
    J = np.zeros((n, n))
    for i, j, Jij in couplings:
        J[int(i)][int(j)] = Jij
        J[int(j)][int(i)] = Jij
    h = np.array(fields, dtype=np.float64)
    return J, h


def _ising_energy(s, J, h):
    """H = (1/2) s^T J s + h^T s  =  sum_{i<j} J_ij s_i s_j + sum h_i s_i."""
    return float(0.5 * s @ J @ s + h @ s)


def _local_search(spins, J, h, max_passes=100):
    """Greedy single-spin-flip descent to a local minimum."""
    n = len(spins)
    s = np.array(spins, dtype=np.float64)
    energy = _ising_energy(s, J, h)
    for _ in range(max_passes):
        improved = False
        for i in range(n):
            local_field = J[i] @ s + h[i]
            delta = -2.0 * s[i] * local_field
            if delta < -1e-12:
                s[i] = -s[i]
                energy += delta
                improved = True
        if not improved:
            break
    return s.astype(int).tolist(), float(energy)


# ---------------------------------------------------------------------------
# CIM solver
# ---------------------------------------------------------------------------

def cim_solve(n, couplings, fields,
              num_runs=200, num_steps=10000, dt=0.005,
              p_max=3.0, xi=0.7, sigma=0.02, seed=42):
    """Coherent Ising Machine solver with local-search refinement.

    Dynamics per oscillator i:
      dx_i/dt = (-1 + p - x_i^2) x_i        [parametric gain + saturation]
              - xi_eff * (J @ x + h)_i        [measurement-feedback coupling]
              + sqrt(2 sigma dt) eta_i        [vacuum fluctuation noise]

    Pump schedule: p(t) = p_max * t / T  (linear adiabatic ramp).
    Coupling normalised by spectral radius of J for numerical stability.
    """
    rng = np.random.RandomState(seed)
    J, h = _build_J_h(n, couplings, fields)

    # Normalise coupling by spectral radius for stability
    if n > 1 and np.any(J != 0):
        sr = np.max(np.abs(np.linalg.eigvalsh(J)))
        xi_eff = xi / max(sr, 1e-8)
    else:
        xi_eff = xi

    noise_scale = np.sqrt(2.0 * sigma * dt)

    best_energy = float("inf")
    best_spins = None

    for _ in range(num_runs):
        # Initialise amplitudes near zero with small perturbation
        x = rng.normal(0.0, 0.01, n)

        for step in range(num_steps):
            p = p_max * step / num_steps      # adiabatic pump ramp
            gain = (-1.0 + p - x * x) * x     # parametric gain with saturation
            coupling = -xi_eff * (J @ x + h)  # measurement-feedback loop
            noise = noise_scale * rng.normal(0.0, 1.0, n)

            # Euler-Maruyama step
            x = x + dt * (gain + coupling) + noise
            x = np.clip(x, -5.0, 5.0)         # soft clamp for stability

        # Extract spins from bifurcated amplitudes
        spins = np.sign(x)
        spins[spins == 0] = 1.0

        # Refine with local search
        spins_ls, energy_ls = _local_search(spins.astype(int).tolist(), J, h)
        if energy_ls < best_energy:
            best_energy = energy_ls
            best_spins = spins_ls

    return best_spins, best_energy


# ---------------------------------------------------------------------------
# Instance solvers
# ---------------------------------------------------------------------------

def solve_ising(instance):
    """Solve an Ising model instance and return {spins, energy}."""
    spins, energy = cim_solve(
        instance["n"], instance["couplings"], instance["fields"]
    )
    return {"spins": spins, "energy": round(energy, 10)}


def solve_qubo(instance):
    """Solve a QUBO instance via Ising conversion and return {bits, energy}."""
    n = instance["n"]
    Q = instance["Q"]
    couplings, fields, offset = qubo_to_ising(Q)
    spins, _ = cim_solve(n, couplings, fields)

    # Convert spins back to bits: x_i = (1 + s_i) / 2
    bits = [(1 + s) // 2 for s in spins]

    # Compute true QUBO energy from bits (avoid floating-point drift)
    Q_arr = np.array(Q, dtype=np.float64)
    b = np.array(bits, dtype=np.float64)
    qubo_e = float(b @ Q_arr @ b)

    return {"bits": bits, "energy": round(qubo_e, 10)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    inst_dir = "/app/instances"
    res_dir = "/app/results"
    os.makedirs(res_dir, exist_ok=True)

    for fname in sorted(os.listdir(inst_dir)):
        if not fname.endswith(".json"):
            continue
        name = fname[:-5]
        with open(os.path.join(inst_dir, fname)) as f:
            instance = json.load(f)

        if instance["type"] == "ising":
            result = solve_ising(instance)
        elif instance["type"] == "qubo":
            result = solve_qubo(instance)
        else:
            print(f"Skipping unknown type: {instance['type']}")
            continue

        with open(os.path.join(res_dir, f"{name}.json"), "w") as f:
            json.dump(result, f, indent=2)
        print(f"Solved {name}: energy = {result['energy']}")


if __name__ == "__main__":
    main()
