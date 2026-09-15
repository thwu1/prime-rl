"""Tests for trapped-ion compilation pipeline."""

import sys
import os
import json
import asyncio
import pickle
import numpy as np
import pytest

sys.path.insert(0, '/app')


class TestMSGate:
    """Tests for the Molmer-Sorensen XX-interaction gate."""

    def test_attributes(self):
        from gates import MSGate
        gate = MSGate()
        assert gate._num_qudits == 2
        assert gate._num_params == 1
        assert gate._radixes == (2, 2)

    def test_unitary_values(self):
        from gates import MSGate
        gate = MSGate()
        theta = np.pi / 4
        U = np.array(gate.get_unitary([theta]))
        c, s = np.cos(theta), np.sin(theta)
        expected = np.array([
            [c, 0, 0, -1j * s],
            [0, c, -1j * s, 0],
            [0, -1j * s, c, 0],
            [-1j * s, 0, 0, c],
        ])
        assert np.allclose(U, expected, atol=1e-10)

    def test_unitarity(self):
        from gates import MSGate
        gate = MSGate()
        for theta in [0.0, 0.5, np.pi / 4, np.pi / 2, np.pi]:
            U = np.array(gate.get_unitary([theta]))
            assert np.allclose(U @ U.conj().T, np.eye(4), atol=1e-10), \
                f"Not unitary at theta={theta}"

    def test_identity_at_zero(self):
        from gates import MSGate
        gate = MSGate()
        U = np.array(gate.get_unitary([0.0]))
        assert np.allclose(U, np.eye(4), atol=1e-10)

    def test_gradient_finite_diff(self):
        from gates import MSGate
        gate = MSGate()
        theta = 0.7
        grad = np.array(gate.get_grad([theta]))
        assert grad.shape == (1, 4, 4)
        eps = 1e-7
        U_plus = np.array(gate.get_unitary([theta + eps]))
        U_minus = np.array(gate.get_unitary([theta - eps]))
        fd_grad = (U_plus - U_minus) / (2 * eps)
        assert np.allclose(grad[0], fd_grad, atol=1e-5)

    def test_unitary_and_grad_consistency(self):
        from gates import MSGate
        gate = MSGate()
        theta = 1.3
        U, grad = gate.get_unitary_and_grad([theta])
        U2 = gate.get_unitary([theta])
        grad2 = gate.get_grad([theta])
        assert np.allclose(np.array(U), np.array(U2), atol=1e-12)
        assert np.allclose(np.array(grad), np.array(grad2), atol=1e-12)


class TestGPIGate:
    """Tests for the IonQ GPI gate."""

    def test_attributes(self):
        from gates import GPIGate
        gate = GPIGate()
        assert gate._num_qudits == 1
        assert gate._num_params == 1

    def test_unitary_values(self):
        from gates import GPIGate
        gate = GPIGate()
        phi = np.pi / 3
        U = np.array(gate.get_unitary([phi]))
        expected = np.array([
            [0, np.exp(-1j * phi)],
            [np.exp(1j * phi), 0],
        ])
        assert np.allclose(U, expected, atol=1e-10)

    def test_unitarity(self):
        from gates import GPIGate
        gate = GPIGate()
        for phi in [0.0, 0.5, np.pi / 3, np.pi, 2 * np.pi]:
            U = np.array(gate.get_unitary([phi]))
            assert np.allclose(U @ U.conj().T, np.eye(2), atol=1e-10), \
                f"Not unitary at phi={phi}"

    def test_involutory(self):
        """GPI(phi)^2 = I since it is a generalized NOT gate."""
        from gates import GPIGate
        gate = GPIGate()
        phi = 1.5
        U = np.array(gate.get_unitary([phi]))
        assert np.allclose(U @ U, np.eye(2), atol=1e-10)

    def test_gradient_finite_diff(self):
        from gates import GPIGate
        gate = GPIGate()
        phi = 0.9
        grad = np.array(gate.get_grad([phi]))
        assert grad.shape == (1, 2, 2)
        eps = 1e-7
        U_plus = np.array(gate.get_unitary([phi + eps]))
        U_minus = np.array(gate.get_unitary([phi - eps]))
        fd_grad = (U_plus - U_minus) / (2 * eps)
        assert np.allclose(grad[0], fd_grad, atol=1e-5)

    def test_unitary_and_grad_consistency(self):
        from gates import GPIGate
        gate = GPIGate()
        phi = 2.1
        U, grad = gate.get_unitary_and_grad([phi])
        U2 = gate.get_unitary([phi])
        grad2 = gate.get_grad([phi])
        assert np.allclose(np.array(U), np.array(U2), atol=1e-12)
        assert np.allclose(np.array(grad), np.array(grad2), atol=1e-12)


class TestGPI2Gate:
    """Tests for the IonQ GPI2 gate."""

    def test_attributes(self):
        from gates import GPI2Gate
        gate = GPI2Gate()
        assert gate._num_qudits == 1
        assert gate._num_params == 1

    def test_unitary_values(self):
        from gates import GPI2Gate
        gate = GPI2Gate()
        phi = np.pi / 6
        U = np.array(gate.get_unitary([phi]))
        inv_sqrt2 = 1.0 / np.sqrt(2.0)
        expected = inv_sqrt2 * np.array([
            [1, -1j * np.exp(-1j * phi)],
            [-1j * np.exp(1j * phi), 1],
        ])
        assert np.allclose(U, expected, atol=1e-10)

    def test_unitarity(self):
        from gates import GPI2Gate
        gate = GPI2Gate()
        for phi in [0.0, 0.5, np.pi / 6, np.pi, 2 * np.pi]:
            U = np.array(gate.get_unitary([phi]))
            assert np.allclose(U @ U.conj().T, np.eye(2), atol=1e-10), \
                f"Not unitary at phi={phi}"

    def test_gradient_finite_diff(self):
        from gates import GPI2Gate
        gate = GPI2Gate()
        phi = 1.5
        grad = np.array(gate.get_grad([phi]))
        assert grad.shape == (1, 2, 2)
        eps = 1e-7
        U_plus = np.array(gate.get_unitary([phi + eps]))
        U_minus = np.array(gate.get_unitary([phi - eps]))
        fd_grad = (U_plus - U_minus) / (2 * eps)
        assert np.allclose(grad[0], fd_grad, atol=1e-5)

    def test_unitary_and_grad_consistency(self):
        from gates import GPI2Gate
        gate = GPI2Gate()
        phi = 0.8
        U, grad = gate.get_unitary_and_grad([phi])
        U2 = gate.get_unitary([phi])
        grad2 = gate.get_grad([phi])
        assert np.allclose(np.array(U), np.array(U2), atol=1e-12)
        assert np.allclose(np.array(grad), np.array(grad2), atol=1e-12)


class TestGateSerializationCompat:
    """Tests for gate equality, hashing, and circuit serialization."""

    def test_gate_equality_same_type(self):
        from gates import MSGate, GPIGate, GPI2Gate
        assert MSGate() == MSGate()
        assert GPIGate() == GPIGate()
        assert GPI2Gate() == GPI2Gate()

    def test_gate_inequality_different_type(self):
        from gates import MSGate, GPIGate, GPI2Gate
        assert MSGate() != GPIGate()
        assert MSGate() != GPI2Gate()
        assert GPIGate() != GPI2Gate()

    def test_gate_hash_consistent(self):
        from gates import MSGate, GPIGate, GPI2Gate
        assert hash(MSGate()) == hash(MSGate())
        assert hash(GPIGate()) == hash(GPIGate())
        assert hash(GPI2Gate()) == hash(GPI2Gate())

    def test_gate_in_set(self):
        from gates import MSGate
        s = {MSGate()}
        assert MSGate() in s

    def test_gate_in_dict(self):
        from gates import MSGate
        d = {MSGate(): 42}
        assert d[MSGate()] == 42

    def test_circuit_pickle_roundtrip(self):
        """Circuits with custom gates must survive pickle serialization."""
        from gates import MSGate, GPIGate, GPI2Gate
        from bqskit.ir.circuit import Circuit

        circuit = Circuit(2)
        circuit.append_gate(MSGate(), (0, 1), [0.5])
        circuit.append_gate(GPIGate(), (0,), [0.3])
        circuit.append_gate(GPI2Gate(), (1,), [0.7])

        data = pickle.dumps(circuit)
        recovered = pickle.loads(data)

        assert recovered.num_operations == 3
        original_u = np.array(circuit.get_unitary())
        recovered_u = np.array(recovered.get_unitary())
        assert np.allclose(original_u, recovered_u, atol=1e-10)


class TestMachineModel:
    """Tests for the trapped-ion machine model."""

    def test_num_qudits(self):
        from model import get_trapped_ion_model
        model = get_trapped_ion_model()
        assert model.num_qudits == 3

    def test_all_to_all_coupling(self):
        from model import get_trapped_ion_model
        model = get_trapped_ion_model()
        for i in range(3):
            for j in range(i + 1, 3):
                assert (i, j) in model.coupling_graph or \
                       (j, i) in model.coupling_graph, \
                    f"Missing coupling between qubits {i} and {j}"

    def test_gate_set_contains_custom_gates(self):
        from model import get_trapped_ion_model
        from gates import MSGate, GPIGate, GPI2Gate
        model = get_trapped_ion_model()
        gate_types = {type(g) for g in model.gate_set}
        assert MSGate in gate_types, "MSGate missing from gate set"
        assert GPIGate in gate_types, "GPIGate missing from gate set"
        assert GPI2Gate in gate_types, "GPI2Gate missing from gate set"

    def test_gate_set_contains_rz(self):
        from model import get_trapped_ion_model
        from bqskit.ir.gates.parameterized.rz import RZGate
        model = get_trapped_ion_model()
        gate_types = {type(g) for g in model.gate_set}
        assert RZGate in gate_types, "RZGate missing from gate set"


class TestNativeCheckPass:
    """Tests for the NativeGateCheckPass."""

    def test_all_native(self):
        from native_check_pass import NativeGateCheckPass
        from gates import MSGate, GPIGate
        from bqskit.ir.gates.parameterized.rz import RZGate
        from bqskit.ir.circuit import Circuit

        circuit = Circuit(2)
        circuit.append_gate(MSGate(), (0, 1), [0.5])
        circuit.append_gate(GPIGate(), (0,), [0.3])
        circuit.append_gate(RZGate(), (1,), [0.7])

        native_types = {MSGate, GPIGate, RZGate}
        pass_obj = NativeGateCheckPass(native_types)
        data = {}
        asyncio.run(pass_obj.run(circuit, data))

        assert data['all_native'] is True
        assert sum(data['gate_counts'].values()) == 3

    def test_non_native_detected(self):
        from native_check_pass import NativeGateCheckPass
        from gates import MSGate
        from bqskit.ir.gates.parameterized.rz import RZGate
        from bqskit.ir.gates.parameterized.u3 import U3Gate
        from bqskit.ir.circuit import Circuit

        circuit = Circuit(2)
        circuit.append_gate(MSGate(), (0, 1), [0.5])
        circuit.append_gate(U3Gate(), (0,), [0.1, 0.2, 0.3])

        native_types = {MSGate, RZGate}
        pass_obj = NativeGateCheckPass(native_types)
        data = {}
        asyncio.run(pass_obj.run(circuit, data))

        assert data['all_native'] is False
        assert sum(data['gate_counts'].values()) == 2


class TestPipeline:
    """Tests for the compilation pipeline output."""

    def test_report_exists(self):
        assert os.path.exists('/app/report.json'), \
            "Pipeline must produce /app/report.json"

    def test_compiled_unitary_exists(self):
        assert os.path.exists('/app/compiled_unitary.npy'), \
            "Pipeline must produce /app/compiled_unitary.npy"

    def test_report_keys(self):
        with open('/app/report.json') as f:
            report = json.load(f)
        required = [
            'original_gate_count', 'compiled_gate_count',
            'unitary_distance', 'all_native', 'gate_counts',
        ]
        for key in required:
            assert key in report, f"Missing key in report: {key}"

    def test_unitary_equivalence(self):
        from bqskit.ir.circuit import Circuit
        original = Circuit.from_file('/app/input_circuit.qasm')
        original_unitary = np.array(original.get_unitary())
        compiled_unitary = np.load('/app/compiled_unitary.npy')
        d = original_unitary.shape[0]
        fidelity = np.abs(
            np.trace(original_unitary.conj().T @ compiled_unitary)
        ) / d
        assert fidelity > 0.999, f"Process fidelity too low: {fidelity}"

    def test_compiled_unitary_is_unitary(self):
        compiled_unitary = np.load('/app/compiled_unitary.npy')
        n = compiled_unitary.shape[0]
        assert np.allclose(
            compiled_unitary @ compiled_unitary.conj().T,
            np.eye(n), atol=1e-8,
        ), "Compiled unitary is not unitary"

    def test_all_native_in_report(self):
        with open('/app/report.json') as f:
            report = json.load(f)
        assert report['all_native'] is True, \
            "Compiled circuit should only contain native gates"

    def test_unitary_distance_low(self):
        with open('/app/report.json') as f:
            report = json.load(f)
        assert report['unitary_distance'] < 1e-4, \
            f"Unitary distance too high: {report['unitary_distance']}"

    def test_gate_counts_nonempty(self):
        with open('/app/report.json') as f:
            report = json.load(f)
        assert report['compiled_gate_count'] > 0
        assert isinstance(report['gate_counts'], dict)
        assert len(report['gate_counts']) > 0
