#!/usr/bin/env python3
"""
Quantum Hamiltonian analysis pipeline for lattice fermion models.
Reads model specification from /app/model_params.json.
Writes analysis to /app/results.json.
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


def orbital_index(site, spin, n_sites):
    """Map (site, spin) to spin-orbital index using standard ordering."""
    return spin * n_sites + site


def build_hamiltonian(params):
    """Construct extended Hubbard FermionOperator from model parameters."""
    n_sites = params["n_sites"]
    t1 = params["parameters"]["t1"]
    t2 = params["parameters"]["t2"]
    U = params["parameters"]["U"]
    V = params["parameters"]["V"]
    boundary = params["boundary"]

    H = FermionOperator()

    # Nearest-neighbor hopping: -t1 * sum_{<i,j>,s} (c+_is c_js + h.c.)
    for i in range(n_sites - 1):
        j = i + 1
        for s in range(2):
            p, q = orbital_index(i, s, n_sites), orbital_index(j, s, n_sites)
            H += FermionOperator(f"{p}^ {q}", -t1)
            H += FermionOperator(f"{q}^ {p}", -t1)
    if boundary == "periodic" and n_sites > 2:
        for s in range(2):
            p = orbital_index(n_sites - 1, s, n_sites)
            q = orbital_index(0, s, n_sites)
            H += FermionOperator(f"{p}^ {q}", -t1)
            H += FermionOperator(f"{q}^ {p}", -t1)

    # Next-nearest-neighbor hopping: -t2 * sum_{<<i,j>>,s} (c+_is c_js + h.c.)
    for i in range(n_sites):
        j = (i + 2) % n_sites
        if i == j:
            continue
        for s in range(2):
            p, q = orbital_index(i, s, n_sites), orbital_index(j, s, n_sites)
            H += FermionOperator(f"{p}^ {q}", -t2)
            H += FermionOperator(f"{q}^ {p}", -t2)

    # On-site Coulomb: U * sum_i n_{i,up} n_{i,down}
    for i in range(n_sites):
        p_up = orbital_index(i, 0, n_sites)
        p_dn = orbital_index(i, 1, n_sites)
        H += FermionOperator(f"{p_up}^ {p_up} {p_dn}^ {p_dn}", U)

    # Nearest-neighbor repulsion: V * sum_{<i,j>} n_i n_j
    for i in range(n_sites - 1):
        j = i + 1
        for s1 in range(2):
            for s2 in range(2):
                p = orbital_index(i, s1, n_sites)
                q = orbital_index(j, s2, n_sites)
                H += FermionOperator(f"{p}^ {p} {q}^ {q}", V)
    if boundary == "periodic" and n_sites > 2:
        i, j = n_sites - 1, 0
        for s1 in range(2):
            for s2 in range(2):
                p = orbital_index(i, s1, n_sites)
                q = orbital_index(j, s2, n_sites)
                H += FermionOperator(f"{p}^ {p} {q}^ {q}", V)

    return H


def count_terms(qop):
    return len(qop.terms)


def max_weight(qop):
    return max(len(t) for t in qop.terms)


def one_norm(qop):
    return sum(abs(c) for c in qop.terms.values())


def gf2_nullspace(M):
    """Null space of binary matrix over GF(2)."""
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
    """Find independent Z2 symmetry generators of a QubitOperator."""
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
    """Indices of computational basis states in the given Z-symmetry sector."""
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


def get_particle_indices(n_qubits, n_electrons):
    """Indices of computational basis states with given particle number."""
    return [i for i in range(2**n_qubits) if bin(i).count('1') == n_electrons]


def main():
    with open("/app/model_params.json") as f:
        params = json.load(f)

    n_qubits = 2 * params["n_sites"]
    n_electrons = params["n_electrons"]

    # Build Hamiltonian
    H_ferm = build_hamiltonian(params)

    # Qubit mappings
    H_jw = jordan_wigner(H_ferm)
    H_bk = bravyi_kitaev(H_ferm)

    sparse_H = get_sparse_operator(H_jw, n_qubits=n_qubits)

    # Diagonalize for low-lying spectrum
    n_eig = min(10, 2**n_qubits - 2)
    vals, vecs = eigsh(sparse_H, k=n_eig, which="SA")
    order = np.argsort(vals)
    vals = vals[order]
    vecs = vecs[:, order]

    gs_energy = float(vals[0])
    tol = 1e-8
    degeneracy = int(np.sum(np.abs(vals - gs_energy) < tol))
    first_excited = float(vals[degeneracy])
    spectral_gap = first_excited - gs_energy

    gs_vec = vecs[:, 0]

    # Z2 symmetries
    symmetries = find_z2_symmetries(H_jw, n_qubits)
    n_sym = len(symmetries)

    sector_eigs = []
    for sym in symmetries:
        sop = get_sparse_operator(sym, n_qubits=n_qubits)
        val = float(np.real(gs_vec.conj() @ sop @ gs_vec))
        sector_eigs.append(int(round(val)))

    # Symmetry-reduced subspace
    if n_sym > 0:
        sector_idx = get_sector_indices(symmetries, sector_eigs, n_qubits)
    else:
        sector_idx = list(range(2**n_qubits))

    H_red = sparse_H[np.ix_(sector_idx, sector_idx)]
    reduced_dim = len(sector_idx)
    if reduced_dim <= 4:
        red_vals = np.linalg.eigvalsh(H_red.toarray())
    else:
        red_vals, _ = eigsh(H_red, k=1, which="SA")
    tapered_energy = float(min(red_vals))

    # 1-RDM: gamma_{pq} = <psi|a+_p a_q|psi>
    rdm = np.zeros((n_qubits, n_qubits), dtype=complex)
    for p in range(n_qubits):
        for q in range(n_qubits):
            op = FermionOperator(f"{p}^ {q}")
            qop = jordan_wigner(op)
            sop = get_sparse_operator(qop, n_qubits=n_qubits)
            rdm[p, q] = gs_vec.conj() @ sop @ gs_vec
    rdm_trace = float(np.real(np.trace(rdm)))

    results = {
        "n_qubits": n_qubits,
        "n_jw_terms": count_terms(H_jw),
        "n_bk_terms": count_terms(H_bk),
        "jw_max_weight": max_weight(H_jw),
        "bk_max_weight": max_weight(H_bk),
        "jw_one_norm": round(one_norm(H_jw), 10),
        "bk_one_norm": round(one_norm(H_bk), 10),
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

    print("Analysis complete. Results written to /app/results.json")


if __name__ == "__main__":
    main()
