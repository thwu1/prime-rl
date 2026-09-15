
import sys
import os
import json
import numpy as np
import pytest

sys.path.insert(0, '/app')


# ============================================================
# CrossResonanceGate tests
# ============================================================

class TestCrossResonanceGate:
    @pytest.fixture
    def gate(self):
        from cr_gate import CrossResonanceGate
        return CrossResonanceGate()

    def test_properties(self, gate):
        """Gate has correct number of qudits, params, and radixes."""
        assert gate._num_qudits == 2
        assert gate._num_params == 1
        assert gate._radixes == (2, 2)

    def test_unitary_at_zero(self, gate):
        """CR(0) = Identity."""
        U = np.array(gate.get_unitary([0.0]))
        np.testing.assert_allclose(U, np.eye(4), atol=1e-10)

    def test_unitary_at_pi(self, gate):
        """CR(pi) = -i * (Z tensor X)."""
        U = np.array(gate.get_unitary([np.pi]))
        ZX = np.array([
            [0, 1, 0, 0],
            [1, 0, 0, 0],
            [0, 0, 0, -1],
            [0, 0, -1, 0],
        ], dtype=complex)
        expected = -1j * ZX
        np.testing.assert_allclose(U, expected, atol=1e-10)

    def test_unitarity(self, gate):
        """U^dagger @ U = I for several theta values."""
        for theta in [0.5, 1.0, 2.0, np.pi / 3, np.pi, 4.7]:
            U = np.array(gate.get_unitary([theta]))
            product = U.conj().T @ U
            np.testing.assert_allclose(
                product, np.eye(4), atol=1e-10,
                err_msg=f"Not unitary at theta={theta}",
            )

    def test_gradient_shape(self, gate):
        """Gradient array has shape (1, 4, 4)."""
        grad = gate.get_grad([1.0])
        assert grad.shape == (1, 4, 4), f"Expected (1,4,4), got {grad.shape}"

    def test_gradient_numerical(self, gate):
        """Analytical gradient matches central finite-difference estimate."""
        for theta in [0.0, 0.7, 1.234, np.pi / 2, np.pi]:
            eps = 1e-7
            grad_analytic = gate.get_grad([theta])
            U_plus = np.array(gate.get_unitary([theta + eps]))
            U_minus = np.array(gate.get_unitary([theta - eps]))
            grad_numerical = (U_plus - U_minus) / (2 * eps)
            np.testing.assert_allclose(
                grad_analytic[0], grad_numerical, atol=1e-5,
                err_msg=f"Gradient mismatch at theta={theta}",
            )


# ============================================================
# RotationFoldingPass tests
# ============================================================

class TestRotationFolding:
    def test_merges_consecutive_rz(self):
        """Two consecutive RZ gates on the same qubit are merged into one."""
        from bqskit import Circuit
        from bqskit.ir.gates import RZGate, HGate
        from rotation_pass import fold_rotations

        circuit = Circuit(1)
        circuit.append_gate(HGate(), [0])
        circuit.append_gate(RZGate(), [0], [0.5])
        circuit.append_gate(RZGate(), [0], [0.3])
        circuit.append_gate(HGate(), [0])

        original_U = np.array(circuit.get_unitary())
        original_count = circuit.num_operations  # 4

        fold_rotations(circuit)

        assert circuit.num_operations < original_count, (
            f"Expected fewer ops after folding, got {circuit.num_operations}"
        )

        folded_U = np.array(circuit.get_unitary())
        fid = abs(np.trace(original_U.conj().T @ folded_U)) / 2
        assert fid > 0.99999, f"Unitary changed after folding: fidelity={fid}"

    def test_removes_identity_rotation(self):
        """RZ(pi) + RZ(pi) = RZ(2*pi) ~ identity, should be removed."""
        from bqskit import Circuit
        from bqskit.ir.gates import RZGate
        from rotation_pass import fold_rotations

        circuit = Circuit(1)
        circuit.append_gate(RZGate(), [0], [np.pi])
        circuit.append_gate(RZGate(), [0], [np.pi])

        fold_rotations(circuit)
        assert circuit.num_operations == 0, (
            f"Expected 0 ops after folding identity, got {circuit.num_operations}"
        )

    def test_preserves_unitary_multi_qubit(self):
        """Folding preserves unitary on a 2-qubit circuit with mixed gates."""
        from bqskit import Circuit
        from bqskit.ir.gates import RZGate, CZGate, SqrtXGate
        from rotation_pass import fold_rotations

        circuit = Circuit(2)
        circuit.append_gate(RZGate(), [0], [0.5])
        circuit.append_gate(CZGate(), [0, 1])
        circuit.append_gate(RZGate(), [1], [0.3])
        circuit.append_gate(RZGate(), [1], [0.7])
        circuit.append_gate(SqrtXGate(), [0])

        original_U = np.array(circuit.get_unitary())
        fold_rotations(circuit)
        folded_U = np.array(circuit.get_unitary())

        fid = abs(np.trace(original_U.conj().T @ folded_U)) / 4
        assert fid > 0.99999, f"Unitary changed: fidelity={fid}"

    def test_does_not_merge_across_other_gates(self):
        """RZ gates separated by a non-RZ gate on same qubit must NOT merge."""
        from bqskit import Circuit
        from bqskit.ir.gates import RZGate, SqrtXGate
        from rotation_pass import fold_rotations

        circuit = Circuit(1)
        circuit.append_gate(RZGate(), [0], [0.5])
        circuit.append_gate(SqrtXGate(), [0])
        circuit.append_gate(RZGate(), [0], [0.3])

        original_count = circuit.num_operations  # 3
        fold_rotations(circuit)

        assert circuit.num_operations == original_count, (
            "Should not merge RZ gates separated by SX"
        )

    def test_pass_class_exists(self):
        """RotationFoldingPass is a proper BQSKit BasePass subclass."""
        from rotation_pass import RotationFoldingPass
        from bqskit.compiler.basepass import BasePass
        assert issubclass(RotationFoldingPass, BasePass)


# ============================================================
# MachineModel tests
# ============================================================

class TestMachineModel:
    def _load_model(self):
        """Helper to build model from QPU spec the same way pipeline.py should."""
        from bqskit.compiler.machine import MachineModel
        from bqskit.ir.gates import CZGate, RZGate, SqrtXGate

        with open('/app/qpu_spec.json') as f:
            spec = json.load(f)

        model = MachineModel(
            num_qudits=spec['num_qubits'],
            coupling_graph=[tuple(e) for e in spec['coupling_edges']],
            gate_set={CZGate(), RZGate(), SqrtXGate()},
        )
        return model, spec

    def test_topology(self):
        model, spec = self._load_model()
        edges = {tuple(sorted(e)) for e in spec['coupling_edges']}
        model_edges = set()
        for pair in model.coupling_graph:
            model_edges.add(tuple(sorted(pair)))
        assert edges == model_edges

    def test_num_qudits(self):
        model, spec = self._load_model()
        assert model.num_qudits == spec['num_qubits']


# ============================================================
# Compiled circuit tests
# ============================================================

def _qubit_perm_matrix(perm, n_qubits):
    """Build the 2^n x 2^n permutation matrix for a qubit reordering."""
    dim = 2 ** n_qubits
    P = np.zeros((dim, dim))
    for i in range(dim):
        j = 0
        for k in range(n_qubits):
            if i & (1 << k):
                j |= (1 << perm[k])
        P[j, i] = 1
    return P


class TestCompilation:
    def test_compiled_exists(self):
        assert os.path.exists('/app/compiled.qasm'), "compiled.qasm not found"

    def test_metrics_exists(self):
        assert os.path.exists('/app/metrics.json'), "metrics.json not found"

    def test_metrics_keys_and_types(self):
        with open('/app/metrics.json') as f:
            m = json.load(f)
        for key in ['input_gate_count', 'output_gate_count', 'output_depth',
                     'two_qubit_gate_count', 'native_gates_only', 'coupling_respected']:
            assert key in m, f"Missing key: {key}"
        assert isinstance(m['input_gate_count'], int)
        assert isinstance(m['output_gate_count'], int)
        assert isinstance(m['output_depth'], int)
        assert isinstance(m['two_qubit_gate_count'], int)
        assert isinstance(m['native_gates_only'], bool)
        assert isinstance(m['coupling_respected'], bool)
        assert m['native_gates_only'] is True, "Compiled circuit has non-native gates"
        assert m['coupling_respected'] is True, "Compiled circuit violates coupling"

    def test_compiled_native_gates(self):
        """Every gate in the compiled circuit must be CZ, RZ, or SX."""
        from bqskit import Circuit
        from bqskit.ir.gates import CZGate, RZGate, SqrtXGate

        # SXGate may be the same class or an alias
        try:
            from bqskit.ir.gates import SXGate
        except ImportError:
            SXGate = SqrtXGate

        compiled = Circuit.from_file('/app/compiled.qasm')
        for op in compiled:
            assert isinstance(op.gate, (CZGate, RZGate, SqrtXGate, SXGate)), (
                f"Non-native gate: {type(op.gate).__name__}"
            )

    def test_compiled_coupling(self):
        """All two-qubit gates respect the linear-chain coupling graph."""
        from bqskit import Circuit

        compiled = Circuit.from_file('/app/compiled.qasm')
        allowed = {(0, 1), (1, 0), (1, 2), (2, 1), (2, 3), (3, 2)}

        for op in compiled:
            if op.gate.num_qudits >= 2:
                loc = tuple(op.location)
                assert len(loc) == 2, f"Unexpected gate width: {len(loc)}"
                edge = (loc[0], loc[1])
                assert edge in allowed, (
                    f"Coupling violation: {type(op.gate).__name__} on qubits {loc}"
                )

    def test_compiled_qubit_count(self):
        """Compiled circuit should have the same number of qubits as input."""
        from bqskit import Circuit

        inp = Circuit.from_file('/app/input.qasm')
        comp = Circuit.from_file('/app/compiled.qasm')
        assert comp.num_qudits == inp.num_qudits, (
            f"Qubit count mismatch: compiled={comp.num_qudits}, input={inp.num_qudits}"
        )

    def test_compiled_equivalence(self):
        """Compiled unitary matches input up to qubit permutation and global phase."""
        from bqskit import Circuit
        from itertools import permutations

        inp = Circuit.from_file('/app/input.qasm')
        comp = Circuit.from_file('/app/compiled.qasm')

        U_in = np.array(inp.get_unitary())
        U_out = np.array(comp.get_unitary())

        n = inp.num_qudits
        dim = 2 ** n

        best_fid = 0.0
        for p1 in permutations(range(n)):
            P1 = _qubit_perm_matrix(p1, n)
            for p2 in permutations(range(n)):
                P2 = _qubit_perm_matrix(p2, n)
                fid = abs(np.trace(U_in.conj().T @ P2.T @ U_out @ P1)) / dim
                if fid > best_fid:
                    best_fid = fid
                if best_fid > 0.99:
                    break
            if best_fid > 0.99:
                break

        assert best_fid > 0.99, (
            f"Compiled circuit not unitarily equivalent to input. "
            f"Best fidelity across qubit permutations: {best_fid:.6f}"
        )
