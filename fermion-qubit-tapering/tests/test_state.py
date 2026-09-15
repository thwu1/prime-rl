"""
Independent verification of lattice fermion Hamiltonian analysis results.

"""
import json
import os

import numpy as np
import pytest
from openfermion import (
    FermionOperator,
    QubitOperator,
    bravyi_kitaev,
    count_qubits,
    get_sparse_operator,
    jordan_wigner,
)
from scipy.sparse.linalg import eigsh


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------

def _idx(site, spin):
    return 2 * site + spin


def build_reference_hamiltonian(params):
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
            H += FermionOperator(f"{_idx(i,s)}^ {_idx(j,s)}", -t1)
            H += FermionOperator(f"{_idx(j,s)}^ {_idx(i,s)}", -t1)
    if boundary == "periodic" and n_sites > 2:
        for s in range(2):
            H += FermionOperator(f"{_idx(n_sites-1,s)}^ {_idx(0,s)}", -t1)
            H += FermionOperator(f"{_idx(0,s)}^ {_idx(n_sites-1,s)}", -t1)

    # Next-nearest-neighbor hopping
    for i in range(n_sites - 2):
        j = i + 2
        for s in range(2):
            H += FermionOperator(f"{_idx(i,s)}^ {_idx(j,s)}", -t2)
            H += FermionOperator(f"{_idx(j,s)}^ {_idx(i,s)}", -t2)

    # On-site interaction
    for i in range(n_sites):
        H += FermionOperator(
            f"{_idx(i,0)}^ {_idx(i,0)} {_idx(i,1)}^ {_idx(i,1)}", U
        )

    # Nearest-neighbor repulsion
    for i in range(n_sites - 1):
        j = i + 1
        for s1 in range(2):
            for s2 in range(2):
                H += FermionOperator(
                    f"{_idx(i,s1)}^ {_idx(i,s1)} {_idx(j,s2)}^ {_idx(j,s2)}", V
                )
    if boundary == "periodic" and n_sites > 2:
        i = n_sites - 1
        j = 0
        for s1 in range(2):
            for s2 in range(2):
                H += FermionOperator(
                    f"{_idx(i,s1)}^ {_idx(i,s1)} {_idx(j,s2)}^ {_idx(j,s2)}", V
                )

    return H


def _count_terms(qop):
    return len(qop.terms)


def _max_weight(qop):
    return max(len(t) for t in qop.terms)


def _one_norm(qop):
    return sum(abs(c) for c in qop.terms.values())


def _gf2_nullspace(M):
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
    terms = [t for t in qop.terms if t]
    n_terms = len(terms)
    M = np.zeros((n_terms, 2 * n_qubits), dtype=int)
    for i, term in enumerate(terms):
        for qubit, pauli in term:
            if pauli in ("Z", "Y"):
                M[i, qubit] = 1
            if pauli in ("X", "Y"):
                M[i, n_qubits + qubit] = 1
    null_vecs = _gf2_nullspace(M)
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
    dim = 2 ** n_qubits
    indices = []
    sym_data = []
    for sym in symmetries:
        term = list(sym.terms.keys())[0]
        qubits = []
        for q, p in term:
            qubits.append(q)
        sym_data.append(qubits)

    for i in range(dim):
        in_sector = True
        for qubits, eig in zip(sym_data, eigenvalues):
            parity = sum((i >> q) & 1 for q in qubits) % 2
            sym_eig = (-1) ** parity
            if sym_eig != eig:
                in_sector = False
                break
        if in_sector:
            indices.append(i)
    return indices


def get_particle_sector_indices(n_qubits, n_electrons):
    return [i for i in range(2**n_qubits) if bin(i).count('1') == n_electrons]


# ---------------------------------------------------------------------------
# Compute reference values
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ref():
    with open("/app/model_params.json") as f:
        params = json.load(f)

    H_ferm = build_reference_hamiltonian(params)
    n_qubits = 2 * params["n_sites"]
    n_electrons = params["n_electrons"]

    H_jw = jordan_wigner(H_ferm)
    H_bk = bravyi_kitaev(H_ferm)

    sparse_H = get_sparse_operator(H_jw, n_qubits=n_qubits)

    # Verify Hermiticity numerically
    herm_diff = sparse_H - sparse_H.conj().T
    if herm_diff.nnz > 0:
        assert np.max(np.abs(herm_diff.data)) < 1e-10, "Reference Hamiltonian is not Hermitian"

    # Restrict to particle-number sector
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

    # Expand ground state to full Hilbert space
    gs_vec = np.zeros(2**n_qubits, dtype=complex)
    gs_vec[particle_idx] = vecs[:, 0]

    # 1-RDM
    rdm = np.zeros((n_qubits, n_qubits), dtype=complex)
    for p in range(n_qubits):
        for q in range(n_qubits):
            op = FermionOperator(f"{p}^ {q}")
            qop = jordan_wigner(op)
            sop = get_sparse_operator(qop, n_qubits=n_qubits)
            rdm[p, q] = gs_vec.conj() @ sop @ gs_vec
    rdm_trace = float(np.real(np.trace(rdm)))

    # Z2 symmetries
    symmetries = find_z2_symmetries(H_jw, n_qubits)
    n_sym = len(symmetries)
    sector_eigs = []
    for sym in symmetries:
        sop = get_sparse_operator(sym, n_qubits=n_qubits)
        val = float(np.real(gs_vec.conj() @ sop @ gs_vec))
        sector_eigs.append(int(round(val)))

    # Tapered energy: intersect Z2 sector with particle-number sector
    sector_idx = get_sector_indices(symmetries, sector_eigs, n_qubits)
    particle_set = set(particle_idx)
    sector_idx_filtered = sorted([i for i in sector_idx if i in particle_set])
    H_red = sparse_H[np.ix_(sector_idx_filtered, sector_idx_filtered)]
    reduced_dim = len(sector_idx_filtered)
    if reduced_dim <= 4:
        red_vals = np.linalg.eigvalsh(H_red.toarray())
    else:
        red_vals, _ = eigsh(H_red, k=1, which="SA")
    tapered_energy = float(min(red_vals))

    return {
        "n_qubits": n_qubits,
        "n_jw_terms": _count_terms(H_jw),
        "n_bk_terms": _count_terms(H_bk),
        "jw_max_weight": _max_weight(H_jw),
        "bk_max_weight": _max_weight(H_bk),
        "jw_one_norm": _one_norm(H_jw),
        "bk_one_norm": _one_norm(H_bk),
        "ground_state_energy": gs_energy,
        "first_excited_energy": first_excited,
        "spectral_gap": first_excited - gs_energy,
        "ground_state_degeneracy": degeneracy,
        "n_z2_symmetries": n_sym,
        "sector_eigenvalues": sector_eigs,
        "tapered_ground_state_energy": tapered_energy,
        "reduced_hilbert_space_dim": reduced_dim,
        "n_tapered_qubits": n_qubits - n_sym,
        "one_rdm_trace": rdm_trace,
        "one_rdm_real": np.real(rdm),
        "one_rdm_imag": np.imag(rdm),
    }


@pytest.fixture(scope="module")
def results():
    path = "/app/results.json"
    assert os.path.exists(path), "results.json not found at /app/results.json"
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json")

    def test_required_keys(self, results):
        required = [
            "n_qubits", "n_jw_terms", "n_bk_terms",
            "jw_max_weight", "bk_max_weight",
            "jw_one_norm", "bk_one_norm",
            "ground_state_energy", "first_excited_energy",
            "spectral_gap", "ground_state_degeneracy",
            "n_z2_symmetries", "sector_eigenvalues",
            "tapered_ground_state_energy",
            "reduced_hilbert_space_dim", "n_tapered_qubits",
            "one_rdm_trace", "one_rdm_real", "one_rdm_imag",
        ]
        for key in required:
            assert key in results, f"Missing key: {key}"


class TestQubitOperatorAnalysis:
    def test_n_qubits(self, results, ref):
        assert results["n_qubits"] == ref["n_qubits"]

    def test_jw_term_count(self, results, ref):
        assert results["n_jw_terms"] == ref["n_jw_terms"]

    def test_bk_term_count(self, results, ref):
        assert results["n_bk_terms"] == ref["n_bk_terms"]

    def test_jw_max_weight(self, results, ref):
        assert results["jw_max_weight"] == ref["jw_max_weight"]

    def test_bk_max_weight(self, results, ref):
        assert results["bk_max_weight"] == ref["bk_max_weight"]

    def test_jw_one_norm(self, results, ref):
        assert abs(results["jw_one_norm"] - ref["jw_one_norm"]) < 1e-6

    def test_bk_one_norm(self, results, ref):
        assert abs(results["bk_one_norm"] - ref["bk_one_norm"]) < 1e-6


class TestEigenvalues:
    def test_ground_state_energy(self, results, ref):
        assert abs(results["ground_state_energy"] - ref["ground_state_energy"]) < 1e-6

    def test_first_excited_energy(self, results, ref):
        assert abs(results["first_excited_energy"] - ref["first_excited_energy"]) < 1e-6

    def test_spectral_gap(self, results, ref):
        assert abs(results["spectral_gap"] - ref["spectral_gap"]) < 1e-6

    def test_ground_state_degeneracy(self, results, ref):
        assert results["ground_state_degeneracy"] == ref["ground_state_degeneracy"]


class TestSymmetries:
    def test_n_z2_symmetries(self, results, ref):
        assert results["n_z2_symmetries"] >= 2, \
            "Should find at least 2 Z2 symmetries (spin-up and spin-down parity)"
        assert results["n_z2_symmetries"] == ref["n_z2_symmetries"]

    def test_n_tapered_qubits(self, results, ref):
        assert results["n_tapered_qubits"] == ref["n_tapered_qubits"]

    def test_reduced_hilbert_dim(self, results, ref):
        assert results["reduced_hilbert_space_dim"] == ref["reduced_hilbert_space_dim"]

    def test_tapered_energy_matches(self, results, ref):
        assert abs(
            results["tapered_ground_state_energy"] - ref["tapered_ground_state_energy"]
        ) < 1e-6

    def test_tapered_energy_matches_full(self, results, ref):
        assert abs(
            results["tapered_ground_state_energy"] - ref["ground_state_energy"]
        ) < 1e-6, "Tapered ground state energy must match full diagonalization"


class TestOneRDM:
    def test_trace(self, results, ref):
        with open("/app/model_params.json") as f:
            params = json.load(f)
        n_electrons = params["n_electrons"]
        assert abs(results["one_rdm_trace"] - n_electrons) < 1e-4

    def test_hermitian(self, results):
        rdm_re = np.array(results["one_rdm_real"])
        rdm_im = np.array(results["one_rdm_imag"])
        rdm = rdm_re + 1j * rdm_im
        diff = np.max(np.abs(rdm - rdm.conj().T))
        assert diff < 1e-6, f"1-RDM not Hermitian (max diff = {diff})"

    def test_eigenvalue_bounds(self, results):
        rdm_re = np.array(results["one_rdm_real"])
        rdm_im = np.array(results["one_rdm_imag"])
        rdm = rdm_re + 1j * rdm_im
        evals = np.linalg.eigvalsh(rdm)
        assert np.all(evals > -1e-6), f"1-RDM has negative eigenvalue: {min(evals)}"
        assert np.all(evals < 1 + 1e-6), f"1-RDM eigenvalue exceeds 1: {max(evals)}"

    def test_rdm_elements(self, results, ref):
        rdm_agent = np.array(results["one_rdm_real"]) + 1j * np.array(results["one_rdm_imag"])
        rdm_ref = ref["one_rdm_real"] + 1j * ref["one_rdm_imag"]
        max_diff = np.max(np.abs(rdm_agent - rdm_ref))
        assert max_diff < 1e-4, f"1-RDM elements differ (max diff = {max_diff})"
