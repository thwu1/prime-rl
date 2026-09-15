#!/usr/bin/env python3
"""
Correct solution for lattice fermion Hamiltonian analysis task.

"""
import json

import numpy as np
from openfermion import (
    FermionOperator,
    QubitOperator,
    bravyi_kitaev,
    get_sparse_operator,
    jordan_wigner,
)
from scipy.sparse.linalg import eigsh


def idx(site, spin):
    """Interleaved spin-orbital index."""
    return 2 * site + spin


def build_extended_hubbard(params):
    """Build extended Hubbard model FermionOperator from parameters."""
    n_sites = params["n_sites"]
    t1 = params["parameters"]["t1"]
    t2 = params["parameters"]["t2"]
    U = params["parameters"]["U"]
    V = params["parameters"]["V"]
    boundary = params["boundary"]

    H = FermionOperator()

    # Nearest-neighbor hopping
    for i in range(n_sites - 1):
        j = i + 1
        for s in range(2):
            H += FermionOperator(f"{idx(i,s)}^ {idx(j,s)}", -t1)
            H += FermionOperator(f"{idx(j,s)}^ {idx(i,s)}", -t1)
    if boundary == "periodic" and n_sites > 2:
        for s in range(2):
            H += FermionOperator(f"{idx(n_sites-1,s)}^ {idx(0,s)}", -t1)
            H += FermionOperator(f"{idx(0,s)}^ {idx(n_sites-1,s)}", -t1)

    # Next-nearest-neighbor hopping
    for i in range(n_sites - 2):
        j = i + 2
        for s in range(2):
            H += FermionOperator(f"{idx(i,s)}^ {idx(j,s)}", -t2)
            H += FermionOperator(f"{idx(j,s)}^ {idx(i,s)}", -t2)

    # On-site interaction: U * n_{i,up} * n_{i,down}
    for i in range(n_sites):
        H += FermionOperator(
            f"{idx(i,0)}^ {idx(i,0)} {idx(i,1)}^ {idx(i,1)}", U
        )

    # Nearest-neighbor repulsion: V * n_i * n_j
    for i in range(n_sites - 1):
        j = i + 1
        for s1 in range(2):
            for s2 in range(2):
                H += FermionOperator(
                    f"{idx(i,s1)}^ {idx(i,s1)} {idx(j,s2)}^ {idx(j,s2)}", V
                )
    if boundary == "periodic" and n_sites > 2:
        i, j = n_sites - 1, 0
        for s1 in range(2):
            for s2 in range(2):
                H += FermionOperator(
                    f"{idx(i,s1)}^ {idx(i,s1)} {idx(j,s2)}^ {idx(j,s2)}", V
                )

    return H


def count_pauli_terms(qop):
    return len(qop.terms)


def max_pauli_weight(qop):
    return max(len(t) for t in qop.terms)


def one_norm(qop):
    return sum(abs(c) for c in qop.terms.values())


def gf2_nullspace(M):
    """Compute null space of binary matrix M over GF(2)."""
    m, n = M.shape
    A = M.copy() % 2
    pivot_cols = []
    row = 0
    for col in range(n):
        found = -1
        for r in range(row, m):
            if A[r, col] == 1:
                found = r
                break
        if found == -1:
            continue
        A[[row, found]] = A[[found, row]]
        pivot_cols.append(col)
        for r in range(m):
            if r != row and A[r, col] == 1:
                A[r] = (A[r] + A[row]) % 2
        row += 1
    free_cols = [c for c in range(n) if c not in pivot_cols]
    null_vecs = []
    for fc in free_cols:
        v = np.zeros(n, dtype=int)
        v[fc] = 1
        for i, pc in enumerate(pivot_cols):
            v[pc] = A[i, fc]
        null_vecs.append(v)
    return null_vecs


def find_z2_symmetries(qop, n_qubits):
    """Find independent Z2 symmetries via symplectic null space over GF(2)."""
    terms = [t for t in qop.terms if t]
    n_terms = len(terms)
    M = np.zeros((n_terms, 2 * n_qubits), dtype=int)
    for i, term in enumerate(terms):
        for qubit, pauli in term:
            if pauli in ("Z", "Y"):
                M[i, qubit] = 1
            if pauli in ("X", "Y"):
                M[i, n_qubits + qubit] = 1
    null_vecs = gf2_nullspace(M)
    symmetries = []
    for v in null_vecs:
        sx = v[:n_qubits]
        sz = v[n_qubits:]
        plist = []
        for q in range(n_qubits):
            if sx[q] and sz[q]:
                plist.append((q, "Y"))
            elif sx[q]:
                plist.append((q, "X"))
            elif sz[q]:
                plist.append((q, "Z"))
        if plist:
            symmetries.append(QubitOperator(tuple(plist)))
    return symmetries


def get_sector_indices(symmetries, eigenvalues, n_qubits):
    """Return computational basis state indices in a Z-type symmetry sector."""
    dim = 2 ** n_qubits
    sym_qubit_lists = []
    for sym in symmetries:
        term = list(sym.terms.keys())[0]
        sym_qubit_lists.append([q for q, _ in term])
    indices = []
    for i in range(dim):
        in_sector = True
        for qubits, eig in zip(sym_qubit_lists, eigenvalues):
            parity = sum((i >> q) & 1 for q in qubits) % 2
            if (-1) ** parity != eig:
                in_sector = False
                break
        if in_sector:
            indices.append(i)
    return indices


def get_particle_sector_indices(n_qubits, n_electrons):
    """Return computational basis indices with exactly n_electrons occupied."""
    return [i for i in range(2**n_qubits) if bin(i).count('1') == n_electrons]


def compute_1rdm(gs_vec, n_qubits):
    """Compute 1-RDM: gamma_{pq} = <psi|a^dag_p a_q|psi>."""
    rdm = np.zeros((n_qubits, n_qubits), dtype=complex)
    for p in range(n_qubits):
        for q in range(n_qubits):
            op = FermionOperator(f"{p}^ {q}")
            qop = jordan_wigner(op)
            sop = get_sparse_operator(qop, n_qubits=n_qubits)
            rdm[p, q] = gs_vec.conj() @ sop @ gs_vec
    return rdm


def main():
    with open("/app/model_params.json") as f:
        params = json.load(f)

    n_qubits = 2 * params["n_sites"]
    n_electrons = params["n_electrons"]

    # --- Build Hamiltonian ---
    H_ferm = build_extended_hubbard(params)

    # --- Qubit transforms ---
    H_jw = jordan_wigner(H_ferm)
    H_bk = bravyi_kitaev(H_ferm)

    n_jw = count_pauli_terms(H_jw)
    n_bk = count_pauli_terms(H_bk)
    jw_mw = max_pauli_weight(H_jw)
    bk_mw = max_pauli_weight(H_bk)
    jw_1n = one_norm(H_jw)
    bk_1n = one_norm(H_bk)

    # --- Full sparse Hamiltonian ---
    sparse_H = get_sparse_operator(H_jw, n_qubits=n_qubits)

    # Verify Hermiticity
    herm_diff = sparse_H - sparse_H.conj().T
    if herm_diff.nnz > 0:
        max_herm = np.max(np.abs(herm_diff.data))
    else:
        max_herm = 0.0
    assert max_herm < 1e-10, f"Hamiltonian is not Hermitian (max diff = {max_herm})"

    # --- Exact diagonalization in particle-number sector ---
    particle_idx = get_particle_sector_indices(n_qubits, n_electrons)
    H_particle = sparse_H[np.ix_(particle_idx, particle_idx)]
    n_sector = len(particle_idx)

    n_eig = min(10, n_sector - 2)
    vals, vecs = eigsh(H_particle, k=n_eig, which="SA")
    order = np.argsort(vals)
    vals = vals[order]
    vecs = vecs[:, order]

    gs_energy = float(vals[0])
    tol = 1e-8
    degeneracy = int(np.sum(np.abs(vals - gs_energy) < tol))
    first_excited = float(vals[degeneracy])
    spectral_gap = first_excited - gs_energy

    # Expand ground state to full Hilbert space for operator measurements
    gs_vec = np.zeros(2**n_qubits, dtype=complex)
    gs_vec[particle_idx] = vecs[:, 0]

    # --- Z2 symmetries ---
    symmetries = find_z2_symmetries(H_jw, n_qubits)
    n_sym = len(symmetries)

    sector_eigs = []
    for sym in symmetries:
        sop = get_sparse_operator(sym, n_qubits=n_qubits)
        val = float(np.real(gs_vec.conj() @ sop @ gs_vec))
        sector_eigs.append(int(round(val)))

    # --- Qubit tapering ---
    sector_idx = get_sector_indices(symmetries, sector_eigs, n_qubits)
    # Intersect Z2 symmetry sector with particle-number sector
    particle_set = set(particle_idx)
    sector_idx_filtered = sorted([i for i in sector_idx if i in particle_set])
    H_red = sparse_H[np.ix_(sector_idx_filtered, sector_idx_filtered)]
    reduced_dim = len(sector_idx_filtered)
    if reduced_dim <= 4:
        red_vals = np.linalg.eigvalsh(H_red.toarray())
    else:
        red_vals, _ = eigsh(H_red, k=1, which="SA")
    tapered_energy = float(min(red_vals))

    # --- 1-RDM ---
    rdm = compute_1rdm(gs_vec, n_qubits)
    rdm_trace = float(np.real(np.trace(rdm)))

    # --- Write results ---
    results = {
        "n_qubits": n_qubits,
        "n_jw_terms": n_jw,
        "n_bk_terms": n_bk,
        "jw_max_weight": jw_mw,
        "bk_max_weight": bk_mw,
        "jw_one_norm": round(jw_1n, 10),
        "bk_one_norm": round(bk_1n, 10),
        "ground_state_energy": round(gs_energy, 10),
        "first_excited_energy": round(first_excited, 10),
        "spectral_gap": round(spectral_gap, 10),
        "ground_state_degeneracy": degeneracy,
        "n_z2_symmetries": n_sym,
        "sector_eigenvalues": sector_eigs,
        "tapered_ground_state_energy": round(tapered_energy, 10),
        "reduced_hilbert_space_dim": reduced_dim,
        "n_tapered_qubits": n_qubits - n_sym,
        "one_rdm_trace": round(rdm_trace, 10),
        "one_rdm_real": np.real(rdm).round(10).tolist(),
        "one_rdm_imag": np.imag(rdm).round(10).tolist(),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Ground state energy: {gs_energy:.10f}")
    print(f"Spectral gap: {spectral_gap:.10f}")
    print(f"Z2 symmetries found: {n_sym}")
    print(f"Sector eigenvalues: {sector_eigs}")
    print(f"Tapered GS energy: {tapered_energy:.10f}")
    print(f"Reduced Hilbert dim: {reduced_dim}")
    print(f"1-RDM trace: {rdm_trace:.6f}")
    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
