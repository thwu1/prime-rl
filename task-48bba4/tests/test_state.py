
import pytest
import json
import os
import numpy as np
from itertools import permutations


# ============================================================
# Helpers
# ============================================================

def _coupling_edges(coupling_map):
    """Convert coupling map list to bidirectional edge set."""
    edges = set()
    for e in coupling_map:
        edges.add((e[0], e[1]))
        edges.add((e[1], e[0]))
    return edges


def _build_perm_matrix(perm, n_qubits):
    """Build permutation matrix for a qubit permutation.

    perm[k] is the physical qubit that logical qubit k maps to.
    """
    dim = 2 ** n_qubits
    P = np.zeros((dim, dim))
    for i in range(dim):
        j = 0
        for k in range(n_qubits):
            if i & (1 << k):
                j |= (1 << perm[k])
        P[j, i] = 1.0
    return P


def hs_distance_min_perm(u_ref, u_test, n_qubits):
    """Minimum Hilbert-Schmidt distance over all qubit permutations.

    Transpilation with routing may permute logical qubits via SWAPs.
    This searches over all n! permutations to find the best match.
    """
    dim = 2 ** n_qubits
    best_dist = 1.0
    for perm in permutations(range(n_qubits)):
        P = _build_perm_matrix(perm, n_qubits)
        u_corrected = P.T @ u_test
        val = abs(np.trace(u_ref.conj().T @ u_corrected)) / dim
        dist = 1.0 - val
        if dist < best_dist:
            best_dist = dist
    return best_dist


METADATA_GATES = frozenset(['barrier', 'measure', 'id', 'delay', 'reset'])


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def original_unitary():
    """Load the original 5-qubit circuit and compute its unitary."""
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import Operator
    circuit = QuantumCircuit.from_qasm_file('/app/circuit.qasm')
    return Operator(circuit).data


@pytest.fixture(scope="module")
def target_unitary():
    """Load the 2-qubit target unitary from JSON."""
    with open('/app/target_unitary.json') as f:
        data = json.load(f)
    return np.array(data['real']) + 1j * np.array(data['imag'])


@pytest.fixture(scope="module")
def hardware_specs():
    """Load hardware specifications with coupling maps."""
    with open('/app/hardware_specs.json') as f:
        return json.load(f)


# ============================================================
# Output file existence
# ============================================================

def test_target_a_circuit_exists():
    assert os.path.exists('/app/results/target_a_circuit.qasm'), \
        "Missing /app/results/target_a_circuit.qasm"


def test_target_b_circuit_exists():
    assert os.path.exists('/app/results/target_b_circuit.qasm'), \
        "Missing /app/results/target_b_circuit.qasm"


def test_target_a_synth_exists():
    assert os.path.exists('/app/results/target_a_synth.qasm'), \
        "Missing /app/results/target_a_synth.qasm"


def test_target_b_synth_exists():
    assert os.path.exists('/app/results/target_b_synth.qasm'), \
        "Missing /app/results/target_b_synth.qasm"


def test_metrics_exists():
    assert os.path.exists('/app/results/metrics.json'), \
        "Missing /app/results/metrics.json"


# ============================================================
# Target A (IBM-like): 5-qubit circuit compilation
# ============================================================

@pytest.fixture(scope="module")
def target_a_compiled():
    from qiskit import QuantumCircuit
    return QuantumCircuit.from_qasm_file('/app/results/target_a_circuit.qasm')


def test_target_a_circuit_fidelity(target_a_compiled, original_unitary):
    from qiskit.quantum_info import Operator
    compiled_u = Operator(target_a_compiled).data
    distance = hs_distance_min_perm(original_unitary, compiled_u, 5)
    assert distance < 0.01, \
        f"Target A circuit fidelity too low: HS distance = {distance:.6f}"


def test_target_a_circuit_gate_set(target_a_compiled):
    allowed = {'cx', 'u3'}
    for inst in target_a_compiled.data:
        name = inst.operation.name
        if name in METADATA_GATES:
            continue
        assert name in allowed, \
            f"Target A circuit uses gate '{name}' outside allowed set {allowed}"


def test_target_a_circuit_width(target_a_compiled):
    assert target_a_compiled.num_qubits == 5, \
        f"Target A circuit has {target_a_compiled.num_qubits} qubits, expected 5"


def test_target_a_circuit_topology(target_a_compiled, hardware_specs):
    """Verify all 2-qubit gates respect the coupling map."""
    edges = _coupling_edges(hardware_specs['target_a']['coupling_map'])
    violations = []
    for inst in target_a_compiled.data:
        if len(inst.qubits) == 2:
            q0 = target_a_compiled.find_bit(inst.qubits[0]).index
            q1 = target_a_compiled.find_bit(inst.qubits[1]).index
            if (q0, q1) not in edges:
                violations.append((q0, q1))
    assert len(violations) == 0, \
        f"Target A topology violations on non-adjacent qubits: {violations}"


# ============================================================
# Target B (Google-like): 5-qubit circuit compilation
# ============================================================

@pytest.fixture(scope="module")
def target_b_compiled():
    from qiskit import QuantumCircuit
    return QuantumCircuit.from_qasm_file('/app/results/target_b_circuit.qasm')


def test_target_b_circuit_fidelity(target_b_compiled, original_unitary):
    from qiskit.quantum_info import Operator
    compiled_u = Operator(target_b_compiled).data
    distance = hs_distance_min_perm(original_unitary, compiled_u, 5)
    assert distance < 0.01, \
        f"Target B circuit fidelity too low: HS distance = {distance:.6f}"


def test_target_b_circuit_gate_set(target_b_compiled):
    allowed = {'cz', 'rz', 'sx'}
    for inst in target_b_compiled.data:
        name = inst.operation.name
        if name in METADATA_GATES:
            continue
        assert name in allowed, \
            f"Target B circuit uses gate '{name}' outside allowed set {allowed}"


def test_target_b_circuit_width(target_b_compiled):
    assert target_b_compiled.num_qubits == 5, \
        f"Target B circuit has {target_b_compiled.num_qubits} qubits, expected 5"


def test_target_b_circuit_topology(target_b_compiled, hardware_specs):
    """Verify all 2-qubit gates respect the coupling map."""
    edges = _coupling_edges(hardware_specs['target_b']['coupling_map'])
    violations = []
    for inst in target_b_compiled.data:
        if len(inst.qubits) == 2:
            q0 = target_b_compiled.find_bit(inst.qubits[0]).index
            q1 = target_b_compiled.find_bit(inst.qubits[1]).index
            if (q0, q1) not in edges:
                violations.append((q0, q1))
    assert len(violations) == 0, \
        f"Target B topology violations on non-adjacent qubits: {violations}"


# ============================================================
# Target A: 2-qubit unitary synthesis
# ============================================================

@pytest.fixture(scope="module")
def target_a_synth():
    from qiskit import QuantumCircuit
    return QuantumCircuit.from_qasm_file('/app/results/target_a_synth.qasm')


def test_target_a_synth_fidelity(target_a_synth, target_unitary):
    from qiskit.quantum_info import Operator
    synth_u = Operator(target_a_synth).data
    distance = hs_distance_min_perm(target_unitary, synth_u, 2)
    assert distance < 0.01, \
        f"Target A synthesis fidelity too low: HS distance = {distance:.6f}"


def test_target_a_synth_gate_set(target_a_synth):
    allowed = {'cx', 'u3'}
    for inst in target_a_synth.data:
        name = inst.operation.name
        if name in METADATA_GATES:
            continue
        assert name in allowed, \
            f"Target A synth uses gate '{name}' outside allowed set {allowed}"


def test_target_a_synth_width(target_a_synth):
    assert target_a_synth.num_qubits == 2, \
        f"Target A synth has {target_a_synth.num_qubits} qubits, expected 2"


# ============================================================
# Target B: 2-qubit unitary synthesis
# ============================================================

@pytest.fixture(scope="module")
def target_b_synth():
    from qiskit import QuantumCircuit
    return QuantumCircuit.from_qasm_file('/app/results/target_b_synth.qasm')


def test_target_b_synth_fidelity(target_b_synth, target_unitary):
    from qiskit.quantum_info import Operator
    synth_u = Operator(target_b_synth).data
    distance = hs_distance_min_perm(target_unitary, synth_u, 2)
    assert distance < 0.01, \
        f"Target B synthesis fidelity too low: HS distance = {distance:.6f}"


def test_target_b_synth_gate_set(target_b_synth):
    allowed = {'cz', 'rz', 'sx'}
    for inst in target_b_synth.data:
        name = inst.operation.name
        if name in METADATA_GATES:
            continue
        assert name in allowed, \
            f"Target B synth uses gate '{name}' outside allowed set {allowed}"


def test_target_b_synth_width(target_b_synth):
    assert target_b_synth.num_qubits == 2, \
        f"Target B synth has {target_b_synth.num_qubits} qubits, expected 2"


# ============================================================
# Metrics JSON validation
# ============================================================

@pytest.fixture(scope="module")
def metrics():
    with open('/app/results/metrics.json') as f:
        return json.load(f)


def test_metrics_has_all_keys(metrics):
    required = ['target_a_circuit', 'target_b_circuit',
                 'target_a_synth', 'target_b_synth']
    for key in required:
        assert key in metrics, f"Missing key '{key}' in metrics.json"


def test_target_a_circuit_metrics(metrics):
    m = metrics['target_a_circuit']
    assert 'num_two_qubit_gates' in m
    assert 'fidelity_distance' in m
    assert isinstance(m['num_two_qubit_gates'], int)
    assert m['num_two_qubit_gates'] > 0
    assert isinstance(m['fidelity_distance'], float)
    assert m['fidelity_distance'] < 0.01


def test_target_b_circuit_metrics(metrics):
    m = metrics['target_b_circuit']
    assert 'num_two_qubit_gates' in m
    assert 'fidelity_distance' in m
    assert isinstance(m['num_two_qubit_gates'], int)
    assert m['num_two_qubit_gates'] > 0
    assert isinstance(m['fidelity_distance'], float)
    assert m['fidelity_distance'] < 0.01


def test_target_a_synth_metrics(metrics):
    m = metrics['target_a_synth']
    assert 'num_two_qubit_gates' in m
    assert 'fidelity_distance' in m
    assert isinstance(m['num_two_qubit_gates'], int)
    assert m['num_two_qubit_gates'] > 0
    assert isinstance(m['fidelity_distance'], float)
    assert m['fidelity_distance'] < 0.01


def test_target_b_synth_metrics(metrics):
    m = metrics['target_b_synth']
    assert 'num_two_qubit_gates' in m
    assert 'fidelity_distance' in m
    assert isinstance(m['num_two_qubit_gates'], int)
    assert m['num_two_qubit_gates'] > 0
    assert isinstance(m['fidelity_distance'], float)
    assert m['fidelity_distance'] < 0.01
