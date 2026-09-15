
"""
Toric code MWPM decoder using PyMatching.

The d×d toric code on a square lattice with periodic boundary conditions:
  - 2d² qubits on edges
  - d² Z-stabilizers (star operators) on vertices
  - d² X-stabilizers (plaquette operators) on faces
  - 2 logical qubits

Qubit indexing:
  h(i,j) = i*d + j         (horizontal edge: vertex (i,j) ↔ vertex (i,(j+1)%d))
  v(i,j) = d² + i*d + j    (vertical edge:   vertex (i,j) ↔ vertex ((i+1)%d,j))

Logical operator supports for observable tracking:
  Z₁ = {h(i,0) : i}   (column of horizontal edges at j=0)  → X observable 0
  Z₂ = {v(0,j) : j}   (row of vertical edges at i=0)       → X observable 1
  X₁ = {h(0,j) : j}   (row of horizontal edges at i=0)     → Z observable 0
  X₂ = {v(i,0) : i}   (column of vertical edges at j=0)    → Z observable 1
"""

import numpy as np
import pymatching


def build_z_matching(d: int, p: float) -> pymatching.Matching:
    """Build matching graph for decoding X errors via Z-stabilizer syndrome.

    Nodes = vertices of the d×d torus.
    Edges = qubits, connecting their two incident vertices.
    fault_id 0 ↔ Z₁ support (horizontal edges at column j=0)
    fault_id 1 ↔ Z₂ support (vertical edges at row i=0)
    """
    assert d >= 3
    m = pymatching.Matching()
    pc = np.clip(p, 1e-15, 1 - 1e-15)
    w = float(np.log((1 - pc) / pc))

    for i in range(d):
        for j in range(d):
            # Horizontal edge h(i,j): vertex(i,j) ↔ vertex(i,(j+1)%d)
            n1 = i * d + j
            n2 = i * d + (j + 1) % d
            fids = {0} if j == 0 else set()
            m.add_edge(n1, n2, fault_ids=fids, weight=w, error_probability=pc)

            # Vertical edge v(i,j): vertex(i,j) ↔ vertex((i+1)%d, j)
            n1 = i * d + j
            n2 = ((i + 1) % d) * d + j
            fids = {1} if i == 0 else set()
            m.add_edge(n1, n2, fault_ids=fids, weight=w, error_probability=pc)

    m.ensure_num_fault_ids(2)
    return m


def build_x_matching(d: int, p: float) -> pymatching.Matching:
    """Build matching graph for decoding Z errors via X-stabilizer syndrome.

    Nodes = faces of the d×d torus (dual lattice).
    Edges = qubits, connecting their two adjacent faces.

    Face adjacency:
      h(i,j) borders face(i,j) and face((i-1)%d, j)
      v(i,j) borders face(i,j) and face(i, (j-1)%d)

    fault_id 0 ↔ X₁ support (horizontal edges at row i=0)
    fault_id 1 ↔ X₂ support (vertical edges at column j=0)
    """
    assert d >= 3
    m = pymatching.Matching()
    pc = np.clip(p, 1e-15, 1 - 1e-15)
    w = float(np.log((1 - pc) / pc))

    for i in range(d):
        for j in range(d):
            # Horizontal edge h(i,j): face(i,j) ↔ face((i-1)%d, j)
            f1 = i * d + j
            f2 = ((i - 1) % d) * d + j
            fids = {0} if i == 0 else set()
            m.add_edge(f1, f2, fault_ids=fids, weight=w, error_probability=pc)

            # Vertical edge v(i,j): face(i,j) ↔ face(i, (j-1)%d)
            f1 = i * d + j
            f2 = i * d + (j - 1) % d
            fids = {1} if j == 0 else set()
            m.add_edge(f1, f2, fault_ids=fids, weight=w, error_probability=pc)

    m.ensure_num_fault_ids(2)
    return m


def z_syndrome(d: int, x_errors: np.ndarray) -> np.ndarray:
    """Compute Z-stabilizer syndrome from X errors.

    Z stabilizer at vertex (i,j) is flipped by X errors on the 4 incident edges:
      h(i,j), h(i,(j-1)%d), v(i,j), v((i-1)%d, j)
    """
    n = d * d
    num_shots = x_errors.shape[0]
    syn = np.zeros((num_shots, n), dtype=np.uint8)

    for i in range(d):
        for j in range(d):
            node = i * d + j
            syn[:, node] ^= x_errors[:, i * d + j]                      # h(i,j)
            syn[:, node] ^= x_errors[:, i * d + (j - 1) % d]            # h(i,(j-1)%d)
            syn[:, node] ^= x_errors[:, n + i * d + j]                  # v(i,j)
            syn[:, node] ^= x_errors[:, n + ((i - 1) % d) * d + j]      # v((i-1)%d, j)

    return syn


def x_syndrome(d: int, z_errors: np.ndarray) -> np.ndarray:
    """Compute X-stabilizer syndrome from Z errors.

    X stabilizer at face (i,j) is flipped by Z errors on the 4 boundary edges:
      h(i,j), h((i+1)%d, j), v(i,j), v(i,(j+1)%d)
    """
    n = d * d
    num_shots = z_errors.shape[0]
    syn = np.zeros((num_shots, n), dtype=np.uint8)

    for i in range(d):
        for j in range(d):
            face = i * d + j
            syn[:, face] ^= z_errors[:, i * d + j]                      # h(i,j)
            syn[:, face] ^= z_errors[:, ((i + 1) % d) * d + j]          # h((i+1)%d, j)
            syn[:, face] ^= z_errors[:, n + i * d + j]                  # v(i,j)
            syn[:, face] ^= z_errors[:, n + i * d + (j + 1) % d]        # v(i,(j+1)%d)

    return syn


def actual_x_observables(d: int, x_errors: np.ndarray) -> np.ndarray:
    """Compute X logical observable values.

    obs 0 = parity of X errors on Z₁ support = {h(i,0) : i} (column j=0)
    obs 1 = parity of X errors on Z₂ support = {v(0,j) : j} (row i=0)
    """
    n = d * d
    num_shots = x_errors.shape[0]
    obs = np.zeros((num_shots, 2), dtype=np.uint8)

    for i in range(d):
        obs[:, 0] ^= x_errors[:, i * d]          # h(i,0)
    for j in range(d):
        obs[:, 1] ^= x_errors[:, n + j]          # v(0,j)

    return obs


def actual_z_observables(d: int, z_errors: np.ndarray) -> np.ndarray:
    """Compute Z logical observable values.

    obs 0 = parity of Z errors on X₁ support = {h(0,j) : j} (row i=0)
    obs 1 = parity of Z errors on X₂ support = {v(i,0) : i} (column j=0)
    """
    n = d * d
    num_shots = z_errors.shape[0]
    obs = np.zeros((num_shots, 2), dtype=np.uint8)

    for j in range(d):
        obs[:, 0] ^= z_errors[:, j]              # h(0,j)
    for i in range(d):
        obs[:, 1] ^= z_errors[:, n + i * d]      # v(i,0)

    return obs


def logical_error_rate(d: int, p: float, num_shots: int, seed: int) -> float:
    """Monte Carlo logical error rate under independent X/Z bit-flip noise.

    Each qubit independently gets X error with prob p and Z error with prob p.
    X errors first, then Z errors, from the same RNG.
    """
    if p == 0.0:
        return 0.0

    rng = np.random.default_rng(seed)

    z_m = build_z_matching(d, p)
    x_m = build_x_matching(d, p)

    nq = 2 * d * d
    x_errors = (rng.random((num_shots, nq)) < p).astype(np.uint8)
    z_errors = (rng.random((num_shots, nq)) < p).astype(np.uint8)

    z_syn = z_syndrome(d, x_errors)
    x_syn = x_syndrome(d, z_errors)

    x_actual = actual_x_observables(d, x_errors)
    z_actual = actual_z_observables(d, z_errors)

    x_pred = z_m.decode_batch(z_syn)
    z_pred = x_m.decode_batch(x_syn)

    x_fail = np.any(x_pred != x_actual, axis=1)
    z_fail = np.any(z_pred != z_actual, axis=1)

    return float(np.mean(x_fail | z_fail))


def estimate_threshold(
    distances: list,
    p_values: list,
    num_shots: int,
    seed: int,
) -> dict:
    """Compute logical error rate for each (d, p) pair.

    Returns dict mapping (d, p) → logical error rate.
    Per-point seed: seed + d*1000 + p_index.
    """
    results = {}
    for d in distances:
        for p_idx, p in enumerate(p_values):
            s = seed + d * 1000 + p_idx
            results[(d, p)] = logical_error_rate(d, p, num_shots, s)
    return results
