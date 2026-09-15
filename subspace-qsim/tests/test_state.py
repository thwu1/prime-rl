
import pytest
import json
import sqlite3
import struct
import hashlib
import tomllib
import numpy as np
import os


# ---------------------------------------------------------------------------
# Circuit loading from SQLite + binary params file
# ---------------------------------------------------------------------------

def load_circuit_from_db(db_path, bin_path):
    """Reconstruct circuit dict from normalized SQLite database and binary params."""
    with open(bin_path, 'rb') as f:
        params_bin = f.read()

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("SELECT num_qubits FROM circuit_meta")
    num_qubits = c.fetchone()[0]

    c.execute(
        "SELECT gate_id, gate_type, custom_matrix_id "
        "FROM gates ORDER BY gate_order"
    )
    raw_gates = c.fetchall()

    gates = []
    for gid, gtype, cmid in raw_gates:
        gate = {"name": gtype}

        c.execute(
            "SELECT qubit FROM gate_targets "
            "WHERE gate_id=? ORDER BY target_order",
            (gid,),
        )
        gate["qubits"] = [r[0] for r in c.fetchall()]

        c.execute(
            "SELECT bin_offset FROM gate_params "
            "WHERE gate_id=? ORDER BY param_order",
            (gid,),
        )
        offsets = [r[0] for r in c.fetchall()]
        if offsets:
            gate["params"] = [
                struct.unpack_from('<d', params_bin, off)[0] for off in offsets
            ]

        c.execute(
            "SELECT control_qubit, control_value FROM gate_controls "
            "WHERE gate_id=?",
            (gid,),
        )
        ctrls = c.fetchall()
        if ctrls:
            gate["controls"] = [[r[0], r[1]] for r in ctrls]

        if cmid is not None:
            c.execute(
                "SELECT row_idx, col_idx, real_part, imag_part "
                "FROM custom_matrices WHERE matrix_id=?",
                (cmid,),
            )
            entries = c.fetchall()
            dim = max(r[0] for r in entries) + 1
            mr = [[0.0] * dim for _ in range(dim)]
            mi = [[0.0] * dim for _ in range(dim)]
            for ri, ci, rp, ip in entries:
                mr[ri][ci] = rp
                mi[ri][ci] = ip
            gate["matrix_real"] = mr
            gate["matrix_imag"] = mi

        gates.append(gate)

    conn.close()
    return {"num_qubits": num_qubits, "gates": gates}


def load_observables_toml(toml_path):
    """Parse TOML observables file."""
    with open(toml_path, 'rb') as f:
        data = tomllib.load(f)
    return data


# ---------------------------------------------------------------------------
# Reference simulator -- brute-force, used only for verification
# ---------------------------------------------------------------------------

GATE_MATRICES = {
    "H": np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2),
    "X": np.array([[0, 1], [1, 0]], dtype=complex),
    "Y": np.array([[0, -1j], [1j, 0]], dtype=complex),
    "Z": np.array([[1, 0], [0, -1]], dtype=complex),
    "S": np.array([[1, 0], [0, 1j]], dtype=complex),
    "T": np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=complex),
}


def _rotation_gate(name, theta):
    if name == "Rx":
        return np.array(
            [
                [np.cos(theta / 2), -1j * np.sin(theta / 2)],
                [-1j * np.sin(theta / 2), np.cos(theta / 2)],
            ],
            dtype=complex,
        )
    elif name == "Ry":
        return np.array(
            [
                [np.cos(theta / 2), -np.sin(theta / 2)],
                [np.sin(theta / 2), np.cos(theta / 2)],
            ],
            dtype=complex,
        )
    elif name == "Rz":
        return np.array(
            [[np.exp(-1j * theta / 2), 0], [0, np.exp(1j * theta / 2)]],
            dtype=complex,
        )
    raise ValueError(f"Unknown rotation: {name}")


def ref_apply_gate(state, U, targets, n_qubits, controls=None, ctrl_vals=None):
    """Brute-force reference: iterate all basis states with target bits = 0."""
    k = len(targets)
    result = state.copy()
    for base in range(2**n_qubits):
        if any((base >> t) & 1 for t in targets):
            continue
        if controls is not None:
            if not all(
                ((base >> c) & 1) == v for c, v in zip(controls, ctrl_vals)
            ):
                continue
        idxs = []
        sub = np.zeros(2**k, dtype=complex)
        for tb in range(2**k):
            j = base
            for i, t in enumerate(targets):
                if (tb >> i) & 1:
                    j |= 1 << t
            idxs.append(j)
            sub[tb] = state[j]
        new_sub = U @ sub
        for i, j in enumerate(idxs):
            result[j] = new_sub[i]
    return result


def ref_simulate(circuit):
    """Run the full circuit with the brute-force reference."""
    n = circuit["num_qubits"]
    state = np.zeros(2**n, dtype=complex)
    state[0] = 1.0

    for gate in circuit["gates"]:
        name = gate["name"]
        qubits = gate["qubits"]
        params = gate.get("params", [])
        controls_raw = gate.get("controls", None)

        controls = None
        ctrl_vals = None
        if controls_raw is not None:
            controls = [c[0] for c in controls_raw]
            ctrl_vals = [c[1] for c in controls_raw]

        if name == "CUSTOM":
            U = np.array(gate["matrix_real"], dtype=complex) + 1j * np.array(
                gate["matrix_imag"], dtype=complex
            )
        elif name in ("Rx", "Ry", "Rz"):
            U = _rotation_gate(name, params[0])
        else:
            U = GATE_MATRICES[name]

        state = ref_apply_gate(state, U, qubits, n, controls, ctrl_vals)
    return state


def ref_pauli_expectation(state, terms, n_qubits):
    """Compute <psi|P|psi> for a Pauli string P."""
    PAULI = {
        "X": np.array([[0, 1], [1, 0]], dtype=complex),
        "Y": np.array([[0, -1j], [1j, 0]], dtype=complex),
        "Z": np.array([[1, 0], [0, -1]], dtype=complex),
    }
    phi = state.copy()
    for term in terms:
        P = PAULI[term["pauli"]]
        phi = ref_apply_gate(phi, P, [term["qubit"]], n_qubits)
    return float(np.real(np.conj(state) @ phi))


def ref_entanglement_entropy(state, partition_A, n_qubits):
    """Von Neumann entropy S = -Tr(rho_A ln rho_A) via SVD."""
    n_A = len(partition_A)
    n_B = n_qubits - n_A
    partition_B = sorted(set(range(n_qubits)) - set(partition_A))
    dim_A = 2**n_A
    dim_B = 2**n_B

    M = np.zeros((dim_A, dim_B), dtype=complex)
    sorted_A = sorted(partition_A)
    for idx in range(2**n_qubits):
        a = 0
        for i, q in enumerate(sorted_A):
            a |= ((idx >> q) & 1) << i
        b = 0
        for i, q in enumerate(partition_B):
            b |= ((idx >> q) & 1) << i
        M[a, b] = state[idx]

    _, s, _ = np.linalg.svd(M, full_matrices=False)
    p = s**2
    p = p[p > 1e-30]
    return float(-np.sum(p * np.log(p)))


def compute_state_hash(state):
    """SHA-256 of state vector serialized as LE float64 (re,im) pairs."""
    buf = bytearray()
    for i in range(len(state)):
        buf.extend(struct.pack('<d', state[i].real))
        buf.extend(struct.pack('<d', state[i].imag))
    return hashlib.sha256(bytes(buf)).hexdigest()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def circuit():
    return load_circuit_from_db("/app/circuit.db", "/app/params.bin")


@pytest.fixture(scope="module")
def observables():
    return load_observables_toml("/app/observables.toml")


@pytest.fixture(scope="module")
def ref_state(circuit):
    return ref_simulate(circuit)


@pytest.fixture(scope="module")
def agent_results():
    path = "/app/results.json"
    assert os.path.exists(path), "results.json not found at /app/results.json"
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_results_file_exists():
    assert os.path.exists("/app/results.json"), "results.json not found"


def test_results_format(agent_results):
    for key in ("amplitudes", "expectation_values", "total_energy",
                "entanglement_entropy", "state_hash"):
        assert key in agent_results, f"Missing key: {key}"
    assert len(agent_results["amplitudes"]) == 1024, "Expected 1024 amplitudes"
    assert len(agent_results["expectation_values"]) == 8, "Expected 8 expectation values"
    assert isinstance(agent_results["state_hash"], str), "state_hash must be a hex string"
    assert len(agent_results["state_hash"]) == 64, "state_hash must be 64-char SHA-256 hex"


def test_normalization(agent_results):
    norm_sq = sum(
        a[0] ** 2 + a[1] ** 2 for a in agent_results["amplitudes"].values()
    )
    assert abs(norm_sq - 1.0) < 1e-8, f"State not normalized: |psi|^2 = {norm_sq}"


def test_amplitudes(agent_results, ref_state, circuit):
    n = circuit["num_qubits"]
    amps = agent_results["amplitudes"]
    mismatches = []
    for idx in range(2**n):
        got = complex(amps[str(idx)][0], amps[str(idx)][1])
        want = ref_state[idx]
        if abs(got - want) >= 1e-8:
            mismatches.append((idx, got, want))
    assert not mismatches, (
        f"{len(mismatches)} amplitude mismatches (first 5): "
        + "; ".join(
            f"idx={m[0]} got=({m[1].real:.8e},{m[1].imag:.8e}) "
            f"want=({m[2].real:.8e},{m[2].imag:.8e})"
            for m in mismatches[:5]
        )
    )


def test_expectation_values(agent_results, ref_state, observables, circuit):
    n = circuit["num_qubits"]
    for i, obs in enumerate(observables["observables"]):
        ref_val = obs["coefficient"] * ref_pauli_expectation(
            ref_state, obs["terms"], n
        )
        got = agent_results["expectation_values"][i]
        assert abs(got - ref_val) < 1e-8, (
            f"Expectation value {i} mismatch: got {got}, expected {ref_val}"
        )


def test_total_energy(agent_results, ref_state, observables, circuit):
    n = circuit["num_qubits"]
    ref_total = sum(
        obs["coefficient"] * ref_pauli_expectation(ref_state, obs["terms"], n)
        for obs in observables["observables"]
    )
    got = agent_results["total_energy"]
    assert abs(got - ref_total) < 1e-8, (
        f"Total energy mismatch: got {got}, expected {ref_total}"
    )


def test_entanglement_entropy(agent_results, ref_state, circuit):
    n = circuit["num_qubits"]
    partition_A = list(range(n // 2))
    ref_entropy = ref_entanglement_entropy(ref_state, partition_A, n)
    got = agent_results["entanglement_entropy"]
    assert abs(got - ref_entropy) < 1e-6, (
        f"Entropy mismatch: got {got}, expected {ref_entropy}"
    )


def test_state_hash(agent_results, ref_state):
    ref_hash = compute_state_hash(ref_state)
    got = agent_results["state_hash"]
    assert got == ref_hash, (
        f"State hash mismatch: got {got}, expected {ref_hash}"
    )
