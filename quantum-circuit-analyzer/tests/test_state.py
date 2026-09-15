
"""Tests for quantum circuit compilation and resource characterization."""

import json
import os
import sqlite3 as sqlite3_lib
import subprocess
import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Reference circuit definitions (ground truth, independent of agent's work)
# ---------------------------------------------------------------------------

CIRCUITS = {
    "ghz_4": {
        "name": "ghz_4", "num_qubits": 4,
        "gates": [
            {"gate": "H", "targets": [0]},
            {"gate": "CNOT", "targets": [0, 1]},
            {"gate": "CNOT", "targets": [1, 2]},
            {"gate": "CNOT", "targets": [2, 3]},
        ],
    },
    "grover_3": {
        "name": "grover_3", "num_qubits": 3,
        "gates": [
            {"gate": "H", "targets": [0]},
            {"gate": "H", "targets": [1]},
            {"gate": "H", "targets": [2]},
            {"gate": "X", "targets": [1]},
            {"gate": "H", "targets": [2]},
            {"gate": "CCX", "targets": [0, 1, 2]},
            {"gate": "H", "targets": [2]},
            {"gate": "X", "targets": [1]},
            {"gate": "H", "targets": [0]},
            {"gate": "H", "targets": [1]},
            {"gate": "H", "targets": [2]},
            {"gate": "X", "targets": [0]},
            {"gate": "X", "targets": [1]},
            {"gate": "X", "targets": [2]},
            {"gate": "H", "targets": [2]},
            {"gate": "CCX", "targets": [0, 1, 2]},
            {"gate": "H", "targets": [2]},
            {"gate": "X", "targets": [0]},
            {"gate": "X", "targets": [1]},
            {"gate": "X", "targets": [2]},
            {"gate": "H", "targets": [0]},
            {"gate": "H", "targets": [1]},
            {"gate": "H", "targets": [2]},
        ],
    },
    "deutsch_jozsa_4": {
        "name": "deutsch_jozsa_4", "num_qubits": 4,
        "gates": [
            {"gate": "X", "targets": [3]},
            {"gate": "H", "targets": [0]},
            {"gate": "H", "targets": [1]},
            {"gate": "H", "targets": [2]},
            {"gate": "H", "targets": [3]},
            {"gate": "CNOT", "targets": [0, 3]},
            {"gate": "CNOT", "targets": [1, 3]},
            {"gate": "CNOT", "targets": [2, 3]},
            {"gate": "H", "targets": [0]},
            {"gate": "H", "targets": [1]},
            {"gate": "H", "targets": [2]},
        ],
    },
    "toffoli_cascade": {
        "name": "toffoli_cascade", "num_qubits": 4,
        "gates": [
            {"gate": "H", "targets": [0]},
            {"gate": "X", "targets": [1]},
            {"gate": "CCX", "targets": [0, 1, 2]},
            {"gate": "CCX", "targets": [0, 2, 3]},
        ],
    },
    "mixed_gates_5": {
        "name": "mixed_gates_5", "num_qubits": 5,
        "gates": [
            {"gate": "H", "targets": [0]},
            {"gate": "Y", "targets": [1]},
            {"gate": "S", "targets": [2]},
            {"gate": "CNOT", "targets": [0, 1]},
            {"gate": "CZ", "targets": [1, 2]},
            {"gate": "SWAP", "targets": [2, 3]},
            {"gate": "X", "targets": [4]},
            {"gate": "CCX", "targets": [0, 3, 4]},
            {"gate": "Z", "targets": [1]},
            {"gate": "Sdg", "targets": [2]},
            {"gate": "T", "targets": [3]},
            {"gate": "Tdg", "targets": [4]},
            {"gate": "H", "targets": [0]},
            {"gate": "CNOT", "targets": [1, 4]},
        ],
    },
    "phase_gadget_4": {
        "name": "phase_gadget_4", "num_qubits": 4,
        "gates": [
            {"gate": "H", "targets": [0]},
            {"gate": "T", "targets": [0]},
            {"gate": "S", "targets": [0]},
            {"gate": "T", "targets": [0]},
            {"gate": "CNOT", "targets": [0, 1]},
            {"gate": "T", "targets": [1]},
            {"gate": "Tdg", "targets": [1]},
            {"gate": "CNOT", "targets": [1, 2]},
            {"gate": "H", "targets": [2]},
            {"gate": "T", "targets": [2]},
            {"gate": "T", "targets": [2]},
            {"gate": "CNOT", "targets": [2, 3]},
            {"gate": "H", "targets": [3]},
            {"gate": "Sdg", "targets": [3]},
            {"gate": "T", "targets": [3]},
        ],
    },
}

ALL_NAMES = list(CIRCUITS.keys())

# ---------------------------------------------------------------------------
# Compact reference statevector simulator
# ---------------------------------------------------------------------------

_GATES = {
    "H": np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2),
    "X": np.array([[0, 1], [1, 0]], dtype=complex),
    "Y": np.array([[0, -1j], [1j, 0]], dtype=complex),
    "Z": np.array([[1, 0], [0, -1]], dtype=complex),
    "S": np.array([[1, 0], [0, 1j]], dtype=complex),
    "Sdg": np.array([[1, 0], [0, -1j]], dtype=complex),
    "T": np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=complex),
    "Tdg": np.array([[1, 0], [0, np.exp(-1j * np.pi / 4)]], dtype=complex),
    "CNOT": np.array([[1, 0, 0, 0], [0, 1, 0, 0],
                      [0, 0, 0, 1], [0, 0, 1, 0]], dtype=complex),
    "CZ": np.array([[1, 0, 0, 0], [0, 1, 0, 0],
                    [0, 0, 1, 0], [0, 0, 0, -1]], dtype=complex),
    "SWAP": np.array([[1, 0, 0, 0], [0, 0, 1, 0],
                      [0, 1, 0, 0], [0, 0, 0, 1]], dtype=complex),
}
_ccx = np.eye(8, dtype=complex)
_ccx[6, 6] = 0; _ccx[7, 7] = 0; _ccx[6, 7] = 1; _ccx[7, 6] = 1
_GATES["CCX"] = _ccx


def _build_op(mat, qubits, n):
    dim = 2 ** n
    ng = len(qubits)
    op = np.zeros((dim, dim), dtype=complex)
    for i in range(dim):
        for j in range(dim):
            ok = True
            for q in range(n):
                if q not in qubits:
                    if ((i >> (n - 1 - q)) & 1) != ((j >> (n - 1 - q)) & 1):
                        ok = False
                        break
            if not ok:
                continue
            gi = gj = 0
            for k, q in enumerate(qubits):
                gi |= ((i >> (n - 1 - q)) & 1) << (ng - 1 - k)
                gj |= ((j >> (n - 1 - q)) & 1) << (ng - 1 - k)
            op[i, j] = mat[gi, gj]
    return op


def ref_sim(circ):
    n = circ["num_qubits"]
    st = np.zeros(2 ** n, dtype=complex)
    st[0] = 1.0
    for g in circ["gates"]:
        st = _build_op(_GATES[g["gate"]], g["targets"], n) @ st
    return st


def ref_probs(state, n):
    return {format(i, f"0{n}b"): abs(a) ** 2
            for i, a in enumerate(state) if abs(a) ** 2 > 1e-10}


def ref_entropy(state, n):
    na = n // 2
    nb = n - na
    psi = state.reshape(2 ** na, 2 ** nb)
    rho = psi @ psi.conj().T
    eigs = np.linalg.eigvalsh(rho)
    return float(sum(-lam * np.log2(lam) for lam in eigs if lam > 1e-15))


# ---------------------------------------------------------------------------
# Reference decomposition
# ---------------------------------------------------------------------------

def _decompose_ccx(c1, c2, tgt):
    return [
        {"gate": "H", "targets": [tgt]},
        {"gate": "CNOT", "targets": [c2, tgt]},
        {"gate": "Tdg", "targets": [tgt]},
        {"gate": "CNOT", "targets": [c1, tgt]},
        {"gate": "T", "targets": [tgt]},
        {"gate": "CNOT", "targets": [c2, tgt]},
        {"gate": "Tdg", "targets": [tgt]},
        {"gate": "CNOT", "targets": [c1, tgt]},
        {"gate": "T", "targets": [c2]},
        {"gate": "T", "targets": [tgt]},
        {"gate": "H", "targets": [tgt]},
        {"gate": "CNOT", "targets": [c1, c2]},
        {"gate": "T", "targets": [c1]},
        {"gate": "Tdg", "targets": [c2]},
        {"gate": "CNOT", "targets": [c1, c2]},
    ]


_ALLOWED = {"H", "X", "CNOT", "T", "Tdg", "S", "Sdg"}


def ref_decompose(circ):
    new = []
    for g in circ["gates"]:
        gn = g["gate"]
        if gn in _ALLOWED:
            new.append(g)
        elif gn == "Y":
            q = g["targets"][0]
            new.extend([{"gate": "S", "targets": [q]},
                        {"gate": "X", "targets": [q]},
                        {"gate": "Sdg", "targets": [q]}])
        elif gn == "Z":
            q = g["targets"][0]
            new.extend([{"gate": "S", "targets": [q]},
                        {"gate": "S", "targets": [q]}])
        elif gn == "CZ":
            q1, q2 = g["targets"]
            new.extend([{"gate": "H", "targets": [q2]},
                        {"gate": "CNOT", "targets": [q1, q2]},
                        {"gate": "H", "targets": [q2]}])
        elif gn == "SWAP":
            q1, q2 = g["targets"]
            new.extend([{"gate": "CNOT", "targets": [q1, q2]},
                        {"gate": "CNOT", "targets": [q2, q1]},
                        {"gate": "CNOT", "targets": [q1, q2]}])
        elif gn == "CCX":
            c1, c2, tgt = g["targets"]
            new.extend(_decompose_ccx(c1, c2, tgt))
    return {"name": circ["name"], "num_qubits": circ["num_qubits"], "gates": new}


def ref_t_count(circ):
    return sum(1 for g in circ["gates"] if g["gate"] in ("T", "Tdg"))


# ---------------------------------------------------------------------------
# Reference: optimized T-count via phase-gate merging
# ---------------------------------------------------------------------------

_DIAG_PHASE = {
    "T": np.pi / 4, "Tdg": -np.pi / 4,
    "S": np.pi / 2, "Sdg": -np.pi / 2,
}


def ref_optimized_t_count(circuit):
    """T+Tdg count after merging consecutive diagonal single-qubit gates."""
    n = circuit["num_qubits"]
    gates = circuit["gates"]
    tl = [[] for _ in range(n)]
    for gi, g in enumerate(gates):
        for q in g["targets"]:
            tl[q].append(gi)
    total = 0
    for q in range(n):
        i = 0
        while i < len(tl[q]):
            g = gates[tl[q][i]]
            if g["gate"] in _DIAG_PHASE and len(g["targets"]) == 1:
                phase = 0.0
                while i < len(tl[q]):
                    g2 = gates[tl[q][i]]
                    if g2["gate"] in _DIAG_PHASE and len(g2["targets"]) == 1:
                        phase += _DIAG_PHASE[g2["gate"]]
                        i += 1
                    else:
                        break
                k = round(phase / (np.pi / 4)) % 8
                if k % 2 == 1:
                    total += 1
            else:
                i += 1
    return total


# ---------------------------------------------------------------------------
# Reference: entanglement analysis
# ---------------------------------------------------------------------------

def _all_bipartitions(n):
    """All non-trivial bipartitions with qubit 0 in part_a (canonical)."""
    result = []
    for mask in range(2 ** (n - 1)):
        part_a = [0]
        for bit in range(n - 1):
            if mask & (1 << bit):
                part_a.append(bit + 1)
        if len(part_a) < n:
            result.append(tuple(part_a))
    return result


def ref_entropy_bipartition(state, n, part_a):
    """Entanglement entropy for arbitrary bipartition A|B."""
    part_b = sorted(set(range(n)) - set(part_a))
    na, nb = len(part_a), len(part_b)
    perm = list(part_a) + part_b
    tensor = state.reshape([2] * n).transpose(perm)
    psi = tensor.reshape(2 ** na, 2 ** nb)
    rho = psi @ psi.conj().T
    eigs = np.linalg.eigvalsh(rho)
    return float(sum(-lam * np.log2(lam) for lam in eigs if lam > 1e-15))


def ref_max_entropy(state, n):
    """Maximum entanglement entropy over all non-trivial bipartitions."""
    return max(ref_entropy_bipartition(state, n, list(bp))
               for bp in _all_bipartitions(n))


def ref_meyer_wallach(state, n):
    """Meyer-Wallach global entanglement Q = 2(1 - (1/n) sum Tr(rho_k^2))."""
    total_purity = 0.0
    for k in range(n):
        perm = [k] + sorted(set(range(n)) - {k})
        tensor = state.reshape([2] * n).transpose(perm)
        psi = tensor.reshape(2, 2 ** (n - 1))
        rho_k = psi @ psi.conj().T
        total_purity += np.real(np.trace(rho_k @ rho_k))
    return float(2.0 * (1.0 - total_purity / n))


def ref_entanglement_class(state, n):
    """Classify as product / biseparable / genuine multipartite entangled."""
    bps = _all_bipartitions(n)
    entropies = [ref_entropy_bipartition(state, n, list(bp)) for bp in bps]
    if all(s < 1e-10 for s in entropies):
        return "product"
    if all(s > 1e-10 for s in entropies):
        return "genuine"
    return "biseparable"


# ---------------------------------------------------------------------------
# Reference: non-stabilizerness (magic fraction)
# ---------------------------------------------------------------------------

def ref_magic_fraction(state, n):
    """mu = 1 - Xi/2^n where Xi = sum_P <psi|P|psi>^4 over all Pauli strings."""
    _paulis = [
        np.eye(2, dtype=complex),
        np.array([[0, 1], [1, 0]], dtype=complex),
        np.array([[0, -1j], [1j, 0]], dtype=complex),
        np.array([[1, 0], [0, -1]], dtype=complex),
    ]
    xi = 0.0
    for idx in range(4 ** n):
        P = np.array([[1.0]], dtype=complex)
        temp = idx
        for _q in range(n):
            P = np.kron(P, _paulis[temp & 3])
            temp >>= 2
        exp_val = np.real(state.conj() @ P @ state)
        xi += exp_val ** 4
    return float(1.0 - xi / (2 ** n))


# ---------------------------------------------------------------------------
# Load submitted results
# ---------------------------------------------------------------------------

RESULTS_PATH = "/app/results.json"
DB_PATH = "/app/analysis.db"


@pytest.fixture(scope="module")
def results():
    assert os.path.isfile(RESULTS_PATH), f"results.json not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_probs_close(actual, expected, tol=1e-6):
    all_keys = set(actual.keys()) | set(expected.keys())
    for k in all_keys:
        a = actual.get(k, 0.0)
        e = expected.get(k, 0.0)
        assert abs(a - e) < tol, f"State |{k}>: got {a}, expected {e}"


# ---------------------------------------------------------------------------
# Tests: output file existence and structure
# ---------------------------------------------------------------------------

def test_results_file_exists():
    assert os.path.isfile(RESULTS_PATH), "results.json must exist at /app/results.json"


def test_results_has_all_circuits(results):
    for name in ALL_NAMES:
        assert name in results, f"Missing circuit '{name}' in results.json"


def test_results_fields(results):
    required = {"probabilities", "decomposed_probabilities", "naive_t_count",
                "optimized_t_count", "bipartite_entropy", "max_bipartite_entropy",
                "meyer_wallach_measure", "entanglement_class", "magic_fraction"}
    for name, data in results.items():
        missing = required - set(data.keys())
        assert not missing, f"Circuit '{name}' missing fields: {missing}"


# ---------------------------------------------------------------------------
# Tests: SQLite database
# ---------------------------------------------------------------------------

def test_db_exists():
    assert os.path.isfile(DB_PATH), f"analysis.db not found at {DB_PATH}"


def test_db_schema():
    conn = sqlite3_lib.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(circuit_analysis)")
    cols = {row[1] for row in cur.fetchall()}
    conn.close()
    required = {"circuit_name", "num_qubits", "probabilities",
                "equiv_probabilities", "naive_t_count", "optimized_t_count",
                "bipartite_entropy", "max_bipartite_entropy",
                "meyer_wallach_measure", "entanglement_class", "magic_fraction"}
    missing = required - cols
    assert not missing, f"Missing DB columns: {missing}"


def test_db_has_all_circuits():
    conn = sqlite3_lib.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT circuit_name FROM circuit_analysis")
    names = {row[0] for row in cur.fetchall()}
    conn.close()
    for name in ALL_NAMES:
        assert name in names, f"Circuit '{name}' not in database"


def test_db_json_consistency(results):
    conn = sqlite3_lib.connect(DB_PATH)
    cur = conn.cursor()
    for name in ALL_NAMES:
        cur.execute(
            "SELECT probabilities, equiv_probabilities, naive_t_count, "
            "optimized_t_count, bipartite_entropy, max_bipartite_entropy, "
            "meyer_wallach_measure, entanglement_class, magic_fraction "
            "FROM circuit_analysis WHERE circuit_name=?",
            (name,),
        )
        row = cur.fetchone()
        assert row is not None, f"Circuit '{name}' not in database"
        db_probs = json.loads(row[0])
        db_equiv = json.loads(row[1])
        db_naive_tc = row[2]
        db_opt_tc = row[3]
        db_ent = row[4]
        db_max_ent = row[5]
        db_mw = row[6]
        db_eclass = row[7]
        db_magic = row[8]

        json_data = results[name]
        assert_probs_close(db_probs, json_data["probabilities"], tol=1e-8)
        assert_probs_close(db_equiv, json_data["decomposed_probabilities"], tol=1e-8)
        assert db_naive_tc == json_data["naive_t_count"], (
            f"DB naive_t_count={db_naive_tc} != JSON {json_data['naive_t_count']} for {name}"
        )
        assert db_opt_tc == json_data["optimized_t_count"], (
            f"DB optimized_t_count mismatch for {name}"
        )
        assert abs(db_ent - json_data["bipartite_entropy"]) < 1e-6
        assert abs(db_max_ent - json_data["max_bipartite_entropy"]) < 1e-6
        assert abs(db_mw - json_data["meyer_wallach_measure"]) < 1e-6
        assert db_eclass == json_data["entanglement_class"]
        assert abs(db_magic - json_data["magic_fraction"]) < 1e-6
    conn.close()


# ---------------------------------------------------------------------------
# Tests: no external quantum libraries
# ---------------------------------------------------------------------------

def test_no_quantum_libraries():
    result = subprocess.run(
        ["grep", "-rE", "--include=*.py",
         r"(import\s+(qiskit|cirq|pennylane|projectq|pyquil)"
         r"|from\s+(qiskit|cirq|pennylane|projectq|pyquil))",
         "/app/"],
        capture_output=True, text=True,
    )
    assert result.stdout.strip() == "", (
        f"External quantum library imports found:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# Tests: GHZ-4
# ---------------------------------------------------------------------------

class TestGHZ4:
    NAME = "ghz_4"

    def test_probabilities(self, results):
        circ = CIRCUITS[self.NAME]
        state = ref_sim(circ)
        expected = ref_probs(state, circ["num_qubits"])
        assert_probs_close(results[self.NAME]["probabilities"], expected)

    def test_known_probabilities(self, results):
        probs = results[self.NAME]["probabilities"]
        assert abs(probs.get("0000", 0) - 0.5) < 1e-6
        assert abs(probs.get("1111", 0) - 0.5) < 1e-6
        nonzero = {k: v for k, v in probs.items() if v > 1e-8}
        assert len(nonzero) == 2

    def test_decomposed(self, results):
        circ = CIRCUITS[self.NAME]
        state = ref_sim(circ)
        expected = ref_probs(state, circ["num_qubits"])
        assert_probs_close(results[self.NAME]["decomposed_probabilities"], expected)

    def test_naive_t_count(self, results):
        assert results[self.NAME]["naive_t_count"] == 0

    def test_optimized_t_count(self, results):
        assert results[self.NAME]["optimized_t_count"] == 0

    def test_entropy(self, results):
        assert abs(results[self.NAME]["bipartite_entropy"] - 1.0) < 1e-4

    def test_max_entropy(self, results):
        assert abs(results[self.NAME]["max_bipartite_entropy"] - 1.0) < 1e-4

    def test_meyer_wallach(self, results):
        assert abs(results[self.NAME]["meyer_wallach_measure"] - 1.0) < 1e-4

    def test_entanglement_class(self, results):
        assert results[self.NAME]["entanglement_class"] == "genuine"

    def test_magic_fraction(self, results):
        assert abs(results[self.NAME]["magic_fraction"]) < 1e-4


# ---------------------------------------------------------------------------
# Tests: Grover-3
# ---------------------------------------------------------------------------

class TestGrover3:
    NAME = "grover_3"

    def test_probabilities(self, results):
        circ = CIRCUITS[self.NAME]
        state = ref_sim(circ)
        expected = ref_probs(state, circ["num_qubits"])
        assert_probs_close(results[self.NAME]["probabilities"], expected)

    def test_marked_state(self, results):
        p = results[self.NAME]["probabilities"].get("101", 0)
        assert abs(p - 25.0 / 32.0) < 1e-6

    def test_unmarked_states(self, results):
        probs = results[self.NAME]["probabilities"]
        for label in ["000", "001", "010", "011", "100", "110", "111"]:
            p = probs.get(label, 0)
            assert abs(p - 1.0 / 32.0) < 1e-6

    def test_decomposed(self, results):
        circ = CIRCUITS[self.NAME]
        state = ref_sim(circ)
        expected = ref_probs(state, circ["num_qubits"])
        assert_probs_close(results[self.NAME]["decomposed_probabilities"], expected)

    def test_naive_t_count(self, results):
        assert results[self.NAME]["naive_t_count"] == 14

    def test_optimized_t_count(self, results):
        circ = CIRCUITS[self.NAME]
        decomposed = ref_decompose(circ)
        expected = ref_optimized_t_count(decomposed)
        assert results[self.NAME]["optimized_t_count"] == expected

    def test_entropy(self, results):
        circ = CIRCUITS[self.NAME]
        state = ref_sim(circ)
        expected = ref_entropy(state, circ["num_qubits"])
        actual = results[self.NAME]["bipartite_entropy"]
        assert abs(actual - expected) < 1e-4

    def test_magic_fraction_positive(self, results):
        """Grover output is a non-stabilizer state — magic fraction must be > 0."""
        assert results[self.NAME]["magic_fraction"] > 0.01

    def test_entanglement_class(self, results):
        assert results[self.NAME]["entanglement_class"] == "genuine"


# ---------------------------------------------------------------------------
# Tests: Deutsch-Jozsa-4
# ---------------------------------------------------------------------------

class TestDJ4:
    NAME = "deutsch_jozsa_4"

    def test_probabilities(self, results):
        circ = CIRCUITS[self.NAME]
        state = ref_sim(circ)
        expected = ref_probs(state, circ["num_qubits"])
        assert_probs_close(results[self.NAME]["probabilities"], expected)

    def test_balanced_detection(self, results):
        probs = results[self.NAME]["probabilities"]
        p_zero = probs.get("0000", 0) + probs.get("0001", 0)
        assert p_zero < 1e-8
        assert abs(probs.get("1110", 0) - 0.5) < 1e-6
        assert abs(probs.get("1111", 0) - 0.5) < 1e-6

    def test_decomposed(self, results):
        circ = CIRCUITS[self.NAME]
        state = ref_sim(circ)
        expected = ref_probs(state, circ["num_qubits"])
        assert_probs_close(results[self.NAME]["decomposed_probabilities"], expected)

    def test_naive_t_count(self, results):
        assert results[self.NAME]["naive_t_count"] == 0

    def test_optimized_t_count(self, results):
        assert results[self.NAME]["optimized_t_count"] == 0

    def test_entropy_zero(self, results):
        assert abs(results[self.NAME]["bipartite_entropy"]) < 1e-4

    def test_product_state(self, results):
        """DJ output is |111>|-> which is a product state."""
        assert results[self.NAME]["entanglement_class"] == "product"
        assert abs(results[self.NAME]["meyer_wallach_measure"]) < 1e-4
        assert abs(results[self.NAME]["max_bipartite_entropy"]) < 1e-4

    def test_magic_fraction_zero(self, results):
        """DJ output is a stabilizer state."""
        assert abs(results[self.NAME]["magic_fraction"]) < 1e-4


# ---------------------------------------------------------------------------
# Tests: Toffoli cascade
# ---------------------------------------------------------------------------

class TestToffoliCascade:
    NAME = "toffoli_cascade"

    def test_probabilities(self, results):
        circ = CIRCUITS[self.NAME]
        state = ref_sim(circ)
        expected = ref_probs(state, circ["num_qubits"])
        assert_probs_close(results[self.NAME]["probabilities"], expected)

    def test_known_probabilities(self, results):
        probs = results[self.NAME]["probabilities"]
        assert abs(probs.get("0100", 0) - 0.5) < 1e-6
        assert abs(probs.get("1111", 0) - 0.5) < 1e-6
        nonzero = {k: v for k, v in probs.items() if v > 1e-8}
        assert len(nonzero) == 2

    def test_decomposed(self, results):
        circ = CIRCUITS[self.NAME]
        state = ref_sim(circ)
        expected = ref_probs(state, circ["num_qubits"])
        assert_probs_close(results[self.NAME]["decomposed_probabilities"], expected)

    def test_naive_t_count(self, results):
        assert results[self.NAME]["naive_t_count"] == 14

    def test_optimized_t_count(self, results):
        assert results[self.NAME]["optimized_t_count"] == 14

    def test_entropy(self, results):
        assert abs(results[self.NAME]["bipartite_entropy"] - 1.0) < 1e-4

    def test_biseparable(self, results):
        """Output is |1>_1 tensor GHZ_{0,2,3} — biseparable."""
        assert results[self.NAME]["entanglement_class"] == "biseparable"

    def test_magic_fraction_zero(self, results):
        """Output is a stabilizer state (product of stabilizer states)."""
        assert abs(results[self.NAME]["magic_fraction"]) < 1e-4


# ---------------------------------------------------------------------------
# Tests: Mixed gates 5-qubit
# ---------------------------------------------------------------------------

class TestMixedGates5:
    NAME = "mixed_gates_5"

    def test_probabilities(self, results):
        circ = CIRCUITS[self.NAME]
        state = ref_sim(circ)
        expected = ref_probs(state, circ["num_qubits"])
        assert_probs_close(results[self.NAME]["probabilities"], expected)

    def test_decomposed(self, results):
        circ = CIRCUITS[self.NAME]
        state = ref_sim(circ)
        expected = ref_probs(state, circ["num_qubits"])
        assert_probs_close(results[self.NAME]["decomposed_probabilities"], expected)

    def test_naive_t_count(self, results):
        circ = CIRCUITS[self.NAME]
        decomposed = ref_decompose(circ)
        expected_tc = ref_t_count(decomposed)
        assert results[self.NAME]["naive_t_count"] == expected_tc

    def test_optimized_t_count(self, results):
        circ = CIRCUITS[self.NAME]
        decomposed = ref_decompose(circ)
        expected = ref_optimized_t_count(decomposed)
        assert results[self.NAME]["optimized_t_count"] == expected

    def test_entropy(self, results):
        circ = CIRCUITS[self.NAME]
        state = ref_sim(circ)
        expected = ref_entropy(state, circ["num_qubits"])
        actual = results[self.NAME]["bipartite_entropy"]
        assert abs(actual - expected) < 1e-4


# ---------------------------------------------------------------------------
# Tests: Phase gadget 4-qubit (tests optimization)
# ---------------------------------------------------------------------------

class TestPhaseGadget4:
    NAME = "phase_gadget_4"

    def test_probabilities(self, results):
        circ = CIRCUITS[self.NAME]
        state = ref_sim(circ)
        expected = ref_probs(state, circ["num_qubits"])
        assert_probs_close(results[self.NAME]["probabilities"], expected)

    def test_decomposed(self, results):
        circ = CIRCUITS[self.NAME]
        state = ref_sim(circ)
        expected = ref_probs(state, circ["num_qubits"])
        assert_probs_close(results[self.NAME]["decomposed_probabilities"], expected)

    def test_naive_t_count(self, results):
        """All gates are in the restricted set already; naive count = 7."""
        assert results[self.NAME]["naive_t_count"] == 7

    def test_optimized_t_count(self, results):
        """Phase merging: T·S·T=Z (0T), T·Tdg=I (0T), T·T=S (0T), Sdg·T=Tdg (1T)."""
        assert results[self.NAME]["optimized_t_count"] == 1

    def test_optimization_reduces_count(self, results):
        """Optimization must strictly reduce the T-count for this circuit."""
        assert results[self.NAME]["optimized_t_count"] < results[self.NAME]["naive_t_count"]

    def test_magic_fraction_positive(self, results):
        """Circuit has one surviving Tdg gate — output is a magic state."""
        assert results[self.NAME]["magic_fraction"] > 0.001

    def test_entropy(self, results):
        circ = CIRCUITS[self.NAME]
        state = ref_sim(circ)
        expected = ref_entropy(state, circ["num_qubits"])
        actual = results[self.NAME]["bipartite_entropy"]
        assert abs(actual - expected) < 1e-4


# ---------------------------------------------------------------------------
# Parametrized tests: all new metrics across all circuits
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ALL_NAMES)
def test_max_bipartite_entropy(name, results):
    circ = CIRCUITS[name]
    state = ref_sim(circ)
    expected = ref_max_entropy(state, circ["num_qubits"])
    actual = results[name]["max_bipartite_entropy"]
    assert abs(actual - expected) < 1e-4, (
        f"{name}: max_bipartite_entropy got {actual}, expected {expected}"
    )


@pytest.mark.parametrize("name", ALL_NAMES)
def test_meyer_wallach_measure(name, results):
    circ = CIRCUITS[name]
    state = ref_sim(circ)
    expected = ref_meyer_wallach(state, circ["num_qubits"])
    actual = results[name]["meyer_wallach_measure"]
    assert abs(actual - expected) < 1e-4, (
        f"{name}: meyer_wallach got {actual}, expected {expected}"
    )


@pytest.mark.parametrize("name", ALL_NAMES)
def test_entanglement_class(name, results):
    circ = CIRCUITS[name]
    state = ref_sim(circ)
    expected = ref_entanglement_class(state, circ["num_qubits"])
    actual = results[name]["entanglement_class"]
    assert actual == expected, (
        f"{name}: entanglement_class got '{actual}', expected '{expected}'"
    )


@pytest.mark.parametrize("name", ALL_NAMES)
def test_magic_fraction(name, results):
    circ = CIRCUITS[name]
    state = ref_sim(circ)
    expected = ref_magic_fraction(state, circ["num_qubits"])
    actual = results[name]["magic_fraction"]
    assert abs(actual - expected) < 1e-4, (
        f"{name}: magic_fraction got {actual}, expected {expected}"
    )


@pytest.mark.parametrize("name", ALL_NAMES)
def test_naive_t_count_all(name, results):
    circ = CIRCUITS[name]
    decomposed = ref_decompose(circ)
    expected = ref_t_count(decomposed)
    assert results[name]["naive_t_count"] == expected, (
        f"{name}: naive_t_count got {results[name]['naive_t_count']}, expected {expected}"
    )


@pytest.mark.parametrize("name", ALL_NAMES)
def test_optimized_t_count_all(name, results):
    circ = CIRCUITS[name]
    decomposed = ref_decompose(circ)
    expected = ref_optimized_t_count(decomposed)
    assert results[name]["optimized_t_count"] == expected, (
        f"{name}: optimized_t_count got {results[name]['optimized_t_count']}, expected {expected}"
    )


# ---------------------------------------------------------------------------
# Cross-circuit consistency
# ---------------------------------------------------------------------------

def test_decomposition_preserves_state(results):
    for name in ALL_NAMES:
        orig = results[name]["probabilities"]
        decomp = results[name]["decomposed_probabilities"]
        assert_probs_close(orig, decomp, tol=1e-5)


def test_probabilities_sum_to_one(results):
    for name, data in results.items():
        for key in ("probabilities", "decomposed_probabilities"):
            total = sum(data[key].values())
            assert abs(total - 1.0) < 1e-6, (
                f"Circuit '{name}' {key} sums to {total}, expected 1.0"
            )


def test_entropy_non_negative(results):
    for name, data in results.items():
        assert data["bipartite_entropy"] >= -1e-10
        assert data["max_bipartite_entropy"] >= -1e-10


def test_optimized_leq_naive(results):
    """Optimized T-count must be <= naive T-count."""
    for name, data in results.items():
        assert data["optimized_t_count"] <= data["naive_t_count"], (
            f"{name}: optimized ({data['optimized_t_count']}) > naive ({data['naive_t_count']})"
        )


def test_max_entropy_geq_standard_entropy(results):
    """Max bipartite entropy must be >= the standard-cut entropy."""
    for name, data in results.items():
        assert data["max_bipartite_entropy"] >= data["bipartite_entropy"] - 1e-10


def test_meyer_wallach_non_negative(results):
    for name, data in results.items():
        assert data["meyer_wallach_measure"] >= -1e-10


def test_magic_fraction_non_negative(results):
    for name, data in results.items():
        assert data["magic_fraction"] >= -1e-10


def test_entanglement_class_valid(results):
    valid = {"product", "biseparable", "genuine"}
    for name, data in results.items():
        assert data["entanglement_class"] in valid, (
            f"{name}: invalid entanglement_class '{data['entanglement_class']}'"
        )
