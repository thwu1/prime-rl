
import pytest
import numpy as np
import json
import subprocess
import tempfile
import os
import cmath


# ============ Reference Implementation (for verification only) ============

def ref_apply_gate(state, matrix, target_qubits, n_qubits):
    """Apply gate using direct subspace enumeration."""
    state = state.copy()
    k = len(target_qubits)
    other_qubits = sorted([q for q in range(n_qubits) if q not in target_qubits])
    n_other = len(other_qubits)

    offsets = []
    for j in range(1 << k):
        off = 0
        for b in range(k):
            if j & (1 << b):
                off |= (1 << target_qubits[b])
        offsets.append(off)

    for sub_idx in range(1 << n_other):
        base = 0
        for bit_pos, qubit in enumerate(other_qubits):
            if sub_idx & (1 << bit_pos):
                base |= (1 << qubit)
        indices = [base | off for off in offsets]
        sub_vec = state[indices].copy()
        state[indices] = matrix @ sub_vec

    return state


def ref_apply_controlled_gate(state, matrix, target_qubits, control_qubits,
                              control_values, n_qubits):
    """Apply controlled gate using subspace enumeration."""
    state = state.copy()
    k = len(target_qubits)
    all_special = sorted(set(list(target_qubits) + list(control_qubits)))
    other_qubits = sorted([q for q in range(n_qubits) if q not in all_special])
    n_other = len(other_qubits)

    ctrl_offset = 0
    for q, v in zip(control_qubits, control_values):
        if v == 1:
            ctrl_offset |= (1 << q)

    offsets = []
    for j in range(1 << k):
        off = 0
        for b in range(k):
            if j & (1 << b):
                off |= (1 << target_qubits[b])
        offsets.append(off)

    for sub_idx in range(1 << n_other):
        base = ctrl_offset
        for bit_pos, qubit in enumerate(other_qubits):
            if sub_idx & (1 << bit_pos):
                base |= (1 << qubit)
        indices = [base | off for off in offsets]
        sub_vec = state[indices].copy()
        state[indices] = matrix @ sub_vec

    return state


def ref_get_gate_matrix(name, params=None):
    """Get standard gate matrix by name."""
    if name == "H":
        return np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
    elif name == "X":
        return np.array([[0, 1], [1, 0]], dtype=complex)
    elif name == "Y":
        return np.array([[0, -1j], [1j, 0]], dtype=complex)
    elif name == "Z":
        return np.array([[1, 0], [0, -1]], dtype=complex)
    elif name == "S":
        return np.array([[1, 0], [0, 1j]], dtype=complex)
    elif name == "T":
        return np.array([[1, 0], [0, cmath.exp(1j * cmath.pi / 4)]], dtype=complex)
    elif name == "RX":
        theta = params["theta"]
        c, s = np.cos(theta / 2), np.sin(theta / 2)
        return np.array([[c, -1j * s], [-1j * s, c]], dtype=complex)
    elif name == "RY":
        theta = params["theta"]
        c, s = np.cos(theta / 2), np.sin(theta / 2)
        return np.array([[c, -s], [s, c]], dtype=complex)
    elif name == "RZ":
        theta = params["theta"]
        return np.array([[cmath.exp(-1j * theta / 2), 0],
                         [0, cmath.exp(1j * theta / 2)]], dtype=complex)
    elif name == "SWAP":
        return np.array([[1, 0, 0, 0], [0, 0, 1, 0],
                         [0, 1, 0, 0], [0, 0, 0, 1]], dtype=complex)
    else:
        raise ValueError(f"Unknown gate: {name}")


def compute_reference_circuit():
    """Compute the full circuit output using the reference implementation."""
    with open('/app/circuit.json') as f:
        circuit = json.load(f)

    n = circuit["n_qubits"]
    state = np.zeros(1 << n, dtype=complex)
    state[0] = 1.0

    for gate_def in circuit["gates"]:
        name = gate_def["gate"]
        targets = gate_def["targets"]
        params = gate_def.get("params")

        if name == "CUSTOM":
            mr = np.array(gate_def["matrix_real"], dtype=float)
            mi = np.array(gate_def["matrix_imag"], dtype=float)
            matrix = mr + 1j * mi
        else:
            matrix = ref_get_gate_matrix(name, params)

        if "controls" in gate_def and gate_def["controls"]:
            ctrl_qubits = [c["qubit"] for c in gate_def["controls"]]
            ctrl_values = [c["value"] for c in gate_def["controls"]]
            state = ref_apply_controlled_gate(state, matrix, targets,
                                              ctrl_qubits, ctrl_values, n)
        else:
            state = ref_apply_gate(state, matrix, targets, n)

    return state, n


# ============ Subprocess Helper ============

def run_simulator(circuit_dict, timeout=120):
    """Run the agent's Julia simulator on a circuit, return output state."""
    input_fd, input_path = tempfile.mkstemp(suffix='.json', dir='/tmp')
    output_path = input_path + '.out'
    try:
        with os.fdopen(input_fd, 'w') as f:
            json.dump(circuit_dict, f)

        result = subprocess.run(
            ['julia', '/app/simulate.jl', input_path, output_path],
            capture_output=True, text=True, timeout=timeout
        )
        assert result.returncode == 0, \
            f"Simulator exited with code {result.returncode}.\nstderr: {result.stderr}\nstdout: {result.stdout}"

        with open(output_path) as f:
            output = json.load(f)

        state = np.array([complex(r, i) for r, i in output['state']])
        return state, output
    finally:
        if os.path.exists(input_path):
            os.unlink(input_path)
        if os.path.exists(output_path):
            os.unlink(output_path)


# ============ Tests: Entry Point ============

class TestEntryPoint:
    def test_simulate_jl_exists(self):
        """The Julia entry point must exist."""
        assert os.path.exists('/app/simulate.jl'), \
            "simulate.jl not found at /app/simulate.jl"


# ============ Tests: Gate Application ============

class TestGateApplication:
    def test_hadamard_and_rotation(self):
        """H then RZ on qubit 0: tests basic gate and parameterized rotation."""
        theta = 1.5707963267948966  # pi/2
        circuit = {"n_qubits": 2, "gates": [
            {"gate": "H", "targets": [0]},
            {"gate": "RZ", "targets": [0], "params": {"theta": theta}}
        ]}
        state, _ = run_simulator(circuit)
        expected = np.zeros(4, dtype=complex)
        expected[0] = cmath.exp(-1j * theta / 2) / np.sqrt(2)
        expected[1] = cmath.exp(1j * theta / 2) / np.sqrt(2)
        np.testing.assert_allclose(state, expected, atol=1e-10)

    def test_cnot_and_inverse_control(self):
        """CNOT fires when control=1; inverse control fires when control=0."""
        # CNOT: prepare |1> on qubit 0, then CNOT -> |11>
        circuit1 = {"n_qubits": 2, "gates": [
            {"gate": "X", "targets": [0]},
            {"gate": "X", "targets": [1], "controls": [{"qubit": 0, "value": 1}]}
        ]}
        state1, _ = run_simulator(circuit1)
        expected1 = np.zeros(4, dtype=complex)
        expected1[3] = 1.0
        np.testing.assert_allclose(state1, expected1, atol=1e-10)

        # Inverse control: X on qubit 1 when qubit 0=0 (fires from |00>)
        circuit2 = {"n_qubits": 2, "gates": [
            {"gate": "X", "targets": [1], "controls": [{"qubit": 0, "value": 0}]}
        ]}
        state2, _ = run_simulator(circuit2)
        expected2 = np.zeros(4, dtype=complex)
        expected2[2] = 1.0  # qubit 1 flipped
        np.testing.assert_allclose(state2, expected2, atol=1e-10)

    def test_toffoli(self):
        """Toffoli: X on qubit 2, controlled by qubits 0,1 both=1."""
        circuit = {"n_qubits": 3, "gates": [
            {"gate": "X", "targets": [0]},
            {"gate": "X", "targets": [1]},
            {"gate": "X", "targets": [2], "controls": [
                {"qubit": 0, "value": 1},
                {"qubit": 1, "value": 1}
            ]}
        ]}
        state, _ = run_simulator(circuit)
        expected = np.zeros(8, dtype=complex)
        expected[7] = 1.0  # |111>
        np.testing.assert_allclose(state, expected, atol=1e-10)

    def test_swap_non_adjacent(self):
        """SWAP qubits [0,2] in 4-qubit system: moves qubit 0 to qubit 2."""
        circuit = {"n_qubits": 4, "gates": [
            {"gate": "X", "targets": [0]},
            {"gate": "SWAP", "targets": [0, 2]}
        ]}
        state, _ = run_simulator(circuit)
        expected = np.zeros(16, dtype=complex)
        expected[4] = 1.0
        np.testing.assert_allclose(state, expected, atol=1e-10)

    def test_custom_2qubit_gate(self):
        """Custom 4x4 unitary (H tensor H) on non-adjacent qubits [0,2]."""
        HH = 0.5 * np.array([[1, 1, 1, 1], [1, -1, 1, -1],
                              [1, 1, -1, -1], [1, -1, -1, 1]], dtype=complex)
        circuit = {"n_qubits": 3, "gates": [{
            "gate": "CUSTOM",
            "targets": [0, 2],
            "matrix_real": HH.real.tolist(),
            "matrix_imag": HH.imag.tolist()
        }]}
        state, _ = run_simulator(circuit)
        expected = np.zeros(8, dtype=complex)
        expected[0] = 0.5
        expected[1] = 0.5
        expected[4] = 0.5
        expected[5] = 0.5
        np.testing.assert_allclose(state, expected, atol=1e-10)


# ============ Tests: Full Circuit ============

class TestFullCircuit:
    def test_output_exists(self):
        """Output file must exist."""
        assert os.path.exists('/app/output.json'), \
            "output.json not found at /app/output.json"

    def test_output_format(self):
        """Output must have correct format and dimensions."""
        with open('/app/output.json') as f:
            output = json.load(f)
        assert 'n_qubits' in output, "Missing 'n_qubits' field"
        assert 'state' in output, "Missing 'state' field"
        assert output['n_qubits'] == 12, \
            f"Expected 12 qubits, got {output['n_qubits']}"
        assert len(output['state']) == 2 ** 12, \
            f"Expected {2 ** 12} state entries, got {len(output['state'])}"
        for i, entry in enumerate(output['state'][:10]):
            assert isinstance(entry, list) and len(entry) == 2, \
                f"State entry {i} must be [real, imag] pair"

    def test_normalization(self):
        """Output state vector must be normalized (sum |a|^2 = 1)."""
        with open('/app/output.json') as f:
            output = json.load(f)
        state = np.array([complex(r, i) for r, i in output['state']])
        norm_sq = np.sum(np.abs(state) ** 2)
        np.testing.assert_allclose(norm_sq, 1.0, atol=1e-8,
                                   err_msg="State vector is not normalized")

    def test_circuit_correctness(self):
        """Output must match independently computed reference."""
        ref_state, n = compute_reference_circuit()

        with open('/app/output.json') as f:
            output = json.load(f)
        agent_state = np.array([complex(r, i) for r, i in output['state']])

        np.testing.assert_allclose(
            agent_state, ref_state, atol=1e-8,
            err_msg="Circuit output does not match reference computation")


# ============ Tests: Scalability ============

class TestScalability:
    def test_20_qubit_single_gate(self):
        """Must handle 20-qubit system without excessive memory."""
        circuit = {"n_qubits": 20, "gates": [{"gate": "H", "targets": [0]}]}
        state, output = run_simulator(circuit, timeout=180)
        assert output['n_qubits'] == 20
        assert len(output['state']) == 2 ** 20
        np.testing.assert_allclose(state[0], 1 / np.sqrt(2), atol=1e-10)
        np.testing.assert_allclose(state[1], 1 / np.sqrt(2), atol=1e-10)
        assert np.allclose(state[2:100], 0, atol=1e-15), \
            "Non-target entries should remain zero"
