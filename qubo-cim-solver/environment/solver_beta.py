#!/usr/bin/env python3
"""Candidate solver 'beta' — CIM-based combinatorial optimization."""
import json
import os
import sys
import tomllib

import numpy as np

CONFIG_PATH = "/app/config.toml"


def load_config():
    with open(CONFIG_PATH, "rb") as f:
        cfg = tomllib.load(f)
    return cfg["solver"]


def qubo_to_ising(Q):
    """Convert upper-triangular QUBO matrix to Ising model parameters.

    Uses the substitution x_i = (1 + s_i) / 2 to derive:
      J_ij   = Q_ij / 4           for i < j
      h_i    = Q_ii/2 + (1/4) sum_{j!=i} Q_{min(i,j),max(i,j)}
      offset = sum Q_ii/2 + sum_{i<j} Q_ij/4
    """
    n = len(Q)
    couplings = []
    for i in range(n):
        for j in range(i + 1, n):
            if Q[i][j] != 0:
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


def build_matrices(n, couplings, fields):
    """Build symmetric coupling matrix J and field vector h."""
    J = np.zeros((n, n))
    for i, j, v in couplings:
        J[int(i)][int(j)] = v
        J[int(j)][int(i)] = v
    h = np.array(fields, dtype=np.float64)
    return J, h


def ising_energy(s, J, h):
    """Compute Ising Hamiltonian H(s) = (1/2) s^T J s + h^T s."""
    return float(0.5 * s @ J @ s + h @ s)


def local_search(spins, J, h, max_passes=200):
    """Greedy single-spin-flip descent to a local minimum."""
    n = len(spins)
    s = np.array(spins, dtype=np.float64)
    e = ising_energy(s, J, h)
    for _ in range(max_passes):
        improved = False
        for i in range(n):
            delta = -2.0 * s[i] * (J[i] @ s + h[i])
            if delta < -1e-12:
                s[i] = -s[i]
                e += delta
        if not improved:
            break
    return s.astype(int).tolist(), float(e)


def solve(n, couplings, fields, cfg):
    """Solve Ising instance using coupled oscillator dynamics with feedback."""
    rng = np.random.RandomState(42)
    J, h = build_matrices(n, couplings, fields)

    # Normalize coupling by spectral radius for stability
    sr = np.max(np.abs(np.linalg.eigvalsh(J))) if n > 1 and np.any(J) else 1.0
    xi = cfg["coupling_strength"] / max(sr, 1e-8)

    p_max = cfg["pump_max"]
    steps = cfg["num_steps"]
    dt = cfg["dt"]
    sigma = cfg["noise_scale"]
    runs = cfg["num_runs"]
    noise_amp = np.sqrt(2.0 * sigma * dt)

    best_e = float("inf")
    best_s = None

    for _ in range(runs):
        x = rng.normal(0, 0.01, n)
        for step in range(steps):
            p = p_max * step / steps
            dx = (-1.0 + p - x * x) * x - xi * (J @ x + h)
            x += dt * dx + noise_amp * rng.normal(0, 1, n)
            x = np.clip(x, -5, 5)

        spins = np.sign(x).astype(int)
        spins[spins == 0] = 1
        spins_ls, e_ls = local_search(spins.tolist(), J, h)
        if e_ls < best_e:
            best_e = e_ls
            best_s = spins_ls

    return best_s, best_e


def main(output_dir="/app/results"):
    cfg = load_config()
    inst_dir = "/app/instances"
    os.makedirs(output_dir, exist_ok=True)

    for fname in sorted(os.listdir(inst_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(inst_dir, fname)
        if os.path.isdir(fpath):
            continue

        name = fname[:-5]
        with open(fpath) as f:
            inst = json.load(f)

        if inst["type"] == "ising":
            spins, energy = solve(
                inst["n"], inst["couplings"], inst["fields"], cfg
            )
            result = {"spins": spins, "energy": energy}
        elif inst["type"] == "qubo":
            couplings, fields, offset = qubo_to_ising(inst["Q"])
            n = inst["n"]
            spins, _ = solve(n, couplings, fields, cfg)
            bits = [(1 + s) // 2 for s in spins]
            Q_arr = np.array(inst["Q"], dtype=np.float64)
            b = np.array(bits, dtype=np.float64)
            energy = float(b @ Q_arr @ b)
            result = {"bits": bits, "energy": energy}
        else:
            continue

        with open(os.path.join(output_dir, f"{name}.json"), "w") as f:
            json.dump(result, f, indent=2)
        print(f"Solved {name}: energy = {result['energy']}")


if __name__ == "__main__":
    outdir = sys.argv[1] if len(sys.argv) > 1 else "/app/results"
    main(outdir)
