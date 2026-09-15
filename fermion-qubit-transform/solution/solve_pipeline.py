#!/usr/bin/env python3
"""
Solution: Compute qubit Hamiltonian properties for all molecular systems
in the SQLite database. Implements Jordan-Wigner, Bravyi-Kitaev, exact
diagonalization, and Z2 symmetry tapering from scratch.
"""

import json
import sqlite3
import numpy as np
from itertools import product as iter_product


# =============================================================================
# Pauli algebra utilities
# =============================================================================

PAULI_I = np.eye(2, dtype=complex)
PAULI_X = np.array([[0, 1], [1, 0]], dtype=complex)
PAULI_Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
PAULI_Z = np.array([[1, 0], [0, -1]], dtype=complex)
PAULI_MAP = {"I": PAULI_I, "X": PAULI_X, "Y": PAULI_Y, "Z": PAULI_Z}
PAULI_LIST = [PAULI_I, PAULI_X, PAULI_Y, PAULI_Z]
PAULI_LABELS = "IXYZ"

PAULI_MULT = {
    ("I", "I"): (1, "I"), ("I", "X"): (1, "X"), ("I", "Y"): (1, "Y"), ("I", "Z"): (1, "Z"),
    ("X", "I"): (1, "X"), ("X", "X"): (1, "I"), ("X", "Y"): (1j, "Z"), ("X", "Z"): (-1j, "Y"),
    ("Y", "I"): (1, "Y"), ("Y", "X"): (-1j, "Z"), ("Y", "Y"): (1, "I"), ("Y", "Z"): (1j, "X"),
    ("Z", "I"): (1, "Z"), ("Z", "X"): (1j, "Y"), ("Z", "Y"): (-1j, "X"), ("Z", "Z"): (1, "I"),
}


def pauli_string_to_matrix(pauli_str):
    result = np.array([[1.0 + 0j]])
    for ch in pauli_str:
        result = np.kron(result, PAULI_MAP[ch])
    return result


def qubit_hamiltonian_to_matrix(hamiltonian_dict, n_qubits):
    dim = 2 ** n_qubits
    matrix = np.zeros((dim, dim), dtype=complex)
    for pstr, coeff in hamiltonian_dict.items():
        if abs(coeff) < 1e-14:
            continue
        matrix += coeff * pauli_string_to_matrix(pstr)
    return matrix


def matrix_to_pauli_dict(matrix, n_qubits, tol=1e-10):
    dim = 2 ** n_qubits
    result = {}
    for indices in iter_product(range(4), repeat=n_qubits):
        trace_val = 0.0 + 0j
        for j in range(dim):
            phase = 1.0 + 0j
            i_val = 0
            for k in range(n_qubits):
                jk = (j >> k) & 1
                p = PAULI_LIST[indices[k]]
                if abs(p[0, jk]) > 0.5:
                    ik = 0
                    phase *= p[0, jk]
                else:
                    ik = 1
                    phase *= p[1, jk]
                i_val |= (ik << k)
            trace_val += phase * matrix[i_val, j]
        coeff = trace_val / dim
        if abs(coeff) > tol:
            pstr = "".join(PAULI_LABELS[idx] for idx in indices)
            result[pstr] = complex(coeff)
    return result


def add_to_hamiltonian(ham, pauli_str, coeff):
    if abs(coeff) < 1e-14:
        return
    ham[pauli_str] = ham.get(pauli_str, 0) + coeff


def clean_hamiltonian(ham, tol=1e-10):
    return {k: (v.real if abs(v.imag) < tol else v)
            for k, v in ham.items() if abs(v) > tol}


def multiply_pauli_strings(pstr1, coeff1, pstr2, coeff2):
    result_chars = []
    phase = coeff1 * coeff2
    for c1, c2 in zip(pstr1, pstr2):
        p, r = PAULI_MULT[(c1, c2)]
        phase *= p
        result_chars.append(r)
    return "".join(result_chars), phase


def multiply_operator_dicts(op1, op2):
    result = {}
    for pstr1, c1 in op1.items():
        for pstr2, c2 in op2.items():
            rstr, rcoeff = multiply_pauli_strings(pstr1, c1, pstr2, c2)
            add_to_hamiltonian(result, rstr, rcoeff)
    return result


# =============================================================================
# Jordan-Wigner transformation
# =============================================================================

def jw_creation(p, n_qubits):
    terms = {}
    pstr_x = list("I" * n_qubits)
    for j in range(p):
        pstr_x[j] = "Z"
    pstr_x[p] = "X"
    add_to_hamiltonian(terms, "".join(pstr_x), 0.5)

    pstr_y = list("I" * n_qubits)
    for j in range(p):
        pstr_y[j] = "Z"
    pstr_y[p] = "Y"
    add_to_hamiltonian(terms, "".join(pstr_y), -0.5j)
    return terms


def jw_annihilation(p, n_qubits):
    terms = {}
    pstr_x = list("I" * n_qubits)
    for j in range(p):
        pstr_x[j] = "Z"
    pstr_x[p] = "X"
    add_to_hamiltonian(terms, "".join(pstr_x), 0.5)

    pstr_y = list("I" * n_qubits)
    for j in range(p):
        pstr_y[j] = "Z"
    pstr_y[p] = "Y"
    add_to_hamiltonian(terms, "".join(pstr_y), 0.5j)
    return terms


def jordan_wigner_transform(h_spin, g_spin, e_nuc, n_spin):
    ham = {}
    add_to_hamiltonian(ham, "I" * n_spin, e_nuc)

    for p in range(n_spin):
        for q in range(n_spin):
            coeff = h_spin[p, q]
            if abs(coeff) < 1e-12:
                continue
            cr_p = jw_creation(p, n_spin)
            an_q = jw_annihilation(q, n_spin)
            term = multiply_operator_dicts(cr_p, an_q)
            for pstr, c in term.items():
                add_to_hamiltonian(ham, pstr, coeff * c)

    for p in range(n_spin):
        for q in range(n_spin):
            for r in range(n_spin):
                for s in range(n_spin):
                    coeff = 0.5 * g_spin[p, q, r, s]
                    if abs(coeff) < 1e-12:
                        continue
                    term = multiply_operator_dicts(
                        jw_creation(p, n_spin), jw_creation(q, n_spin)
                    )
                    term = multiply_operator_dicts(term, jw_annihilation(s, n_spin))
                    term = multiply_operator_dicts(term, jw_annihilation(r, n_spin))
                    for pstr, c in term.items():
                        add_to_hamiltonian(ham, pstr, coeff * c)

    return clean_hamiltonian(ham)


# =============================================================================
# Bravyi-Kitaev transformation (matrix-based)
# =============================================================================

def build_bk_matrix(n):
    beta = np.zeros((n, n), dtype=int)
    for i in range(n):
        k = i + 1
        lowbit = k & (-k)
        start = k - lowbit
        for j in range(start, k):
            beta[i][j] = 1
    return beta


def build_bk_basis_change(n):
    beta = build_bk_matrix(n)
    dim = 2 ** n
    V = np.zeros((dim, dim), dtype=float)
    for f_int in range(dim):
        f_bits = np.array([(f_int >> k) & 1 for k in range(n)], dtype=int)
        b_bits = beta @ f_bits % 2
        b_int = sum(int(b_bits[k]) * (1 << k) for k in range(n))
        V[b_int, f_int] = 1.0
    return V


def bravyi_kitaev_transform(h_spin, g_spin, e_nuc, n_spin, jw_ham_dict):
    H_JW = qubit_hamiltonian_to_matrix(jw_ham_dict, n_spin)
    V = build_bk_basis_change(n_spin)
    H_BK = V @ H_JW @ V.T
    bk_ham = matrix_to_pauli_dict(H_BK, n_spin)
    return clean_hamiltonian(bk_ham)


# =============================================================================
# Z2 symmetry detection
# =============================================================================

def pauli_to_symplectic(pstr):
    n = len(pstr)
    vec = np.zeros(2 * n, dtype=int)
    for i, ch in enumerate(pstr):
        if ch == "X":
            vec[i] = 1
        elif ch == "Y":
            vec[i] = 1
            vec[n + i] = 1
        elif ch == "Z":
            vec[n + i] = 1
    return vec


def symplectic_to_pauli(vec):
    n = len(vec) // 2
    chars = []
    for i in range(n):
        x, z = vec[i], vec[n + i]
        if x == 0 and z == 0:
            chars.append("I")
        elif x == 1 and z == 0:
            chars.append("X")
        elif x == 1 and z == 1:
            chars.append("Y")
        else:
            chars.append("Z")
    return "".join(chars)


def commutes(pstr1, pstr2):
    anti_count = sum(
        1 for c1, c2 in zip(pstr1, pstr2)
        if c1 != "I" and c2 != "I" and c1 != c2
    )
    return anti_count % 2 == 0


def gf2_nullspace(matrix):
    if matrix.shape[0] == 0:
        return []
    m, n = matrix.shape
    aug = matrix.copy() % 2
    pivot_cols = []
    row = 0

    for col in range(n):
        found = False
        for r in range(row, m):
            if aug[r, col] % 2 == 1:
                aug[[row, r]] = aug[[r, row]]
                found = True
                break
        if not found:
            continue
        pivot_cols.append(col)
        for r in range(m):
            if r != row and aug[r, col] % 2 == 1:
                aug[r] = (aug[r] + aug[row]) % 2
        row += 1

    free_cols = [c for c in range(n) if c not in pivot_cols]
    null_vecs = []
    for fc in free_cols:
        vec = np.zeros(n, dtype=int)
        vec[fc] = 1
        for i, pc in enumerate(pivot_cols):
            vec[pc] = int(aug[i, fc]) % 2
        null_vecs.append(vec)
    return null_vecs


def find_z2_symmetries(hamiltonian_dict, n_qubits):
    identity = "I" * n_qubits
    terms = [pstr for pstr, coeff in hamiltonian_dict.items()
             if abs(coeff) > 1e-10 and pstr != identity]
    if not terms:
        return []

    n = n_qubits
    rows = []
    seen = set()
    for pstr in terms:
        svec = pauli_to_symplectic(pstr)
        constraint = np.concatenate([svec[n:], svec[:n]])
        key = tuple(constraint)
        if key not in seen and any(constraint):
            seen.add(key)
            rows.append(constraint)

    if not rows:
        return []

    mat = np.array(rows, dtype=int)
    null_vecs = gf2_nullspace(mat)

    symmetries = []
    for vec in null_vecs:
        pstr = symplectic_to_pauli(vec)
        if pstr != identity:
            symmetries.append(pstr)

    selected = []
    for sym in symmetries:
        if all(commutes(sym, s) for s in selected):
            selected.append(sym)

    return selected


# =============================================================================
# Qubit tapering
# =============================================================================

def taper_hamiltonian_matrix(ham_matrix, symmetries, n_qubits):
    n_sym = len(symmetries)
    if n_sym == 0:
        eigs = np.real(np.linalg.eigvalsh(ham_matrix))
        return float(np.min(eigs)), 0, n_qubits, ()

    dim = 2 ** n_qubits
    sym_matrices = [pauli_string_to_matrix(sym) for sym in symmetries]

    best_energy = float("inf")
    best_sector = None

    for sector in iter_product([1, -1], repeat=n_sym):
        projector = np.eye(dim, dtype=complex)
        for k in range(n_sym):
            projector = projector @ (np.eye(dim) + sector[k] * sym_matrices[k]) / 2.0

        p_eigvals, p_eigvecs = np.linalg.eigh(projector)
        active_mask = p_eigvals > 0.5
        active_vecs = p_eigvecs[:, active_mask]

        if active_vecs.shape[1] == 0:
            continue

        H_restricted = active_vecs.conj().T @ ham_matrix @ active_vecs
        restricted_eigs = np.real(np.linalg.eigvalsh(H_restricted))

        min_e = float(np.min(restricted_eigs))
        if min_e < best_energy:
            best_energy = min_e
            best_sector = sector

    tapered_n_qubits = n_qubits - n_sym
    return best_energy, n_sym, tapered_n_qubits, best_sector


# =============================================================================
# Data loading from SQLite
# =============================================================================

def load_all_systems(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, name, n_spatial_orbitals, n_electrons, nuclear_repulsion "
        "FROM molecular_systems"
    )
    systems = cursor.fetchall()

    all_data = {}
    for sys_id, name, n_so, n_elec, nuc_rep in systems:
        h = np.zeros((n_so, n_so))
        cursor.execute("SELECT p, q, value FROM one_body WHERE system_id = ?", (sys_id,))
        for p, q, v in cursor.fetchall():
            h[p, q] = v

        g = np.zeros((n_so, n_so, n_so, n_so))
        cursor.execute(
            "SELECT p, q, r, s, value FROM two_body WHERE system_id = ?", (sys_id,)
        )
        for p, q, r, s, v in cursor.fetchall():
            g[p, q, r, s] = v

        all_data[name] = {
            "n_spatial_orbitals": n_so,
            "n_electrons": n_elec,
            "nuclear_repulsion_energy": nuc_rep,
            "one_body_integrals": h,
            "two_body_integrals": g,
        }

    conn.close()
    return all_data


def to_spin_orbital_basis(data):
    n_so = data["n_spatial_orbitals"]
    n_spin = 2 * n_so
    h_spatial = data["one_body_integrals"]
    g_spatial = data["two_body_integrals"]

    h_spin = np.zeros((n_spin, n_spin))
    g_spin = np.zeros((n_spin, n_spin, n_spin, n_spin))

    for p in range(n_spin):
        for q in range(n_spin):
            if p % 2 == q % 2:
                h_spin[p, q] = h_spatial[p // 2, q // 2]

    for p in range(n_spin):
        for q in range(n_spin):
            for r in range(n_spin):
                for s in range(n_spin):
                    if p % 2 == r % 2 and q % 2 == s % 2:
                        g_spin[p, q, r, s] = g_spatial[p // 2, q // 2, r // 2, s // 2]

    return h_spin, g_spin, n_spin


# =============================================================================
# Main
# =============================================================================

def main():
    all_data = load_all_systems("/app/molecules.db")
    all_results = {}

    for name, data in all_data.items():
        print(f"\n=== Processing {name} ===")
        h_spin, g_spin, n_spin = to_spin_orbital_basis(data)
        e_nuc = data["nuclear_repulsion_energy"]

        print(f"  {data['n_spatial_orbitals']} spatial orbitals, {n_spin} qubits")

        # Jordan-Wigner
        print("  JW transformation...")
        jw_ham = jordan_wigner_transform(h_spin, g_spin, e_nuc, n_spin)
        jw_num_terms = len(jw_ham)
        print(f"    {jw_num_terms} terms")

        # Bravyi-Kitaev
        print("  BK transformation...")
        bk_ham = bravyi_kitaev_transform(h_spin, g_spin, e_nuc, n_spin, jw_ham)
        bk_num_terms = len(bk_ham)
        print(f"    {bk_num_terms} terms")

        # Diagonalize
        print("  Diagonalizing...")
        jw_matrix = qubit_hamiltonian_to_matrix(jw_ham, n_spin)
        bk_matrix = qubit_hamiltonian_to_matrix(bk_ham, n_spin)

        jw_eigenvalues = np.sort(np.real(np.linalg.eigvalsh(jw_matrix)))
        bk_eigenvalues = np.sort(np.real(np.linalg.eigvalsh(bk_matrix)))

        spectral_match = bool(np.allclose(jw_eigenvalues, bk_eigenvalues, atol=1e-8))
        ground_state_energy = float(jw_eigenvalues[0])
        print(f"    Ground state energy: {ground_state_energy:.10f}")
        print(f"    Spectral match: {spectral_match}")

        # Z2 symmetries
        print("  Z2 symmetry detection...")
        symmetries = find_z2_symmetries(jw_ham, n_spin)
        n_symmetries = len(symmetries)
        print(f"    {n_symmetries} symmetries found")

        # Tapering
        print("  Tapering...")
        tapered_energy, _, tapered_n_qubits, best_sector = taper_hamiltonian_matrix(
            jw_matrix, symmetries, n_spin
        )
        print(f"    Tapered energy: {tapered_energy:.10f}")
        print(f"    Tapered qubits: {tapered_n_qubits}")

        result = {
            "ground_state_energy": ground_state_energy,
            "n_qubits": n_spin,
            "encoding_a_num_terms": jw_num_terms,
            "encoding_b_num_terms": bk_num_terms,
            "eigenvalues_sorted": [float(x) for x in jw_eigenvalues],
            "spectral_match": spectral_match,
            "n_symmetries": n_symmetries,
            "tapered_n_qubits": tapered_n_qubits,
            "tapered_ground_state_energy": float(tapered_energy),
        }
        all_results[name] = result

    with open("/app/results.json", "w") as f:
        json.dump(all_results, f, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
