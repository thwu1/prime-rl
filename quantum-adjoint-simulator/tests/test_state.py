"""Tests for the quantum circuit simulator."""

import pytest
import numpy as np
import sys
import os
import json
import subprocess
import time
import ctypes
import sqlite3

sys.path.insert(0, '/app')


class TestRotationGates:
    def test_rx_zero(self):
        from quantum_sim.gates import Rx, I2
        assert np.allclose(Rx(0), I2)

    def test_rx_pi(self):
        from quantum_sim.gates import Rx, X
        assert np.allclose(Rx(np.pi), -1j * X)

    def test_rx_unitary(self):
        from quantum_sim.gates import Rx
        U = Rx(0.7)
        assert np.allclose(U @ U.conj().T, np.eye(2))

    def test_ry_zero(self):
        from quantum_sim.gates import Ry, I2
        assert np.allclose(Ry(0), I2)

    def test_ry_pi(self):
        from quantum_sim.gates import Ry, Y
        assert np.allclose(Ry(np.pi), -1j * Y)

    def test_rz_zero(self):
        from quantum_sim.gates import Rz, I2
        assert np.allclose(Rz(0), I2)

    def test_rz_pi(self):
        from quantum_sim.gates import Rz, Z
        assert np.allclose(Rz(np.pi), -1j * Z)


class TestRotationDerivatives:
    def test_drx_finite_diff(self):
        from quantum_sim.gates import Rx, dRx
        theta = 0.5
        eps = 1e-7
        fd = (Rx(theta + eps) - Rx(theta - eps)) / (2 * eps)
        assert np.allclose(dRx(theta), fd, atol=1e-5)

    def test_dry_finite_diff(self):
        from quantum_sim.gates import Ry, dRy
        theta = 1.2
        eps = 1e-7
        fd = (Ry(theta + eps) - Ry(theta - eps)) / (2 * eps)
        assert np.allclose(dRy(theta), fd, atol=1e-5)

    def test_drz_finite_diff(self):
        from quantum_sim.gates import Rz, dRz
        theta = -0.8
        eps = 1e-7
        fd = (Rz(theta + eps) - Rz(theta - eps)) / (2 * eps)
        assert np.allclose(dRz(theta), fd, atol=1e-5)


class TestCKernel:
    def test_libqsim_exists(self):
        """The compiled C shared library must exist."""
        assert os.path.exists('/app/quantum_sim/libqsim.so'), \
            "libqsim.so not found — run 'make build' in /app"

    def test_libqsim_loadable(self):
        """The C library must be loadable via ctypes with expected symbols."""
        lib = ctypes.CDLL('/app/quantum_sim/libqsim.so')
        assert hasattr(lib, 'apply_single_qubit_gate'), \
            "Missing symbol: apply_single_qubit_gate"
        assert hasattr(lib, 'apply_controlled_single_qubit_gate'), \
            "Missing symbol: apply_controlled_single_qubit_gate"

    def test_c_kernel_x_gate(self):
        """C kernel should correctly apply X gate to |0>."""
        lib = ctypes.CDLL('/app/quantum_sim/libqsim.so')
        lib.apply_single_qubit_gate.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int
        ]
        lib.apply_single_qubit_gate.restype = None
        from quantum_sim.gates import X
        state = np.array([1, 0], dtype=np.complex128)
        gate = np.ascontiguousarray(X.ravel(), dtype=np.complex128)
        lib.apply_single_qubit_gate(state.ctypes.data, gate.ctypes.data, 0, 1)
        assert np.allclose(state, [0, 1])

    def test_c_kernel_h_gate_2qubit(self):
        """C kernel should correctly apply H on qubit 1 of a 2-qubit system."""
        lib = ctypes.CDLL('/app/quantum_sim/libqsim.so')
        lib.apply_single_qubit_gate.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int
        ]
        lib.apply_single_qubit_gate.restype = None
        from quantum_sim.gates import H
        state = np.array([1, 0, 0, 0], dtype=np.complex128)
        gate = np.ascontiguousarray(H.ravel(), dtype=np.complex128)
        lib.apply_single_qubit_gate(state.ctypes.data, gate.ctypes.data, 1, 2)
        expected = np.array([1, 0, 1, 0], dtype=np.complex128) / np.sqrt(2)
        assert np.allclose(state, expected)

    def test_c_controlled_cnot(self):
        """C kernel should correctly apply controlled-X (CNOT): |10> -> |11>."""
        lib = ctypes.CDLL('/app/quantum_sim/libqsim.so')
        lib.apply_controlled_single_qubit_gate.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_int, ctypes.c_int, ctypes.c_int
        ]
        lib.apply_controlled_single_qubit_gate.restype = None
        from quantum_sim.gates import X
        state = np.array([0, 0, 1, 0], dtype=np.complex128)
        gate = np.ascontiguousarray(X.ravel(), dtype=np.complex128)
        lib.apply_controlled_single_qubit_gate(
            state.ctypes.data, gate.ctypes.data, 1, 0, 2
        )
        expected = np.array([0, 0, 0, 1], dtype=np.complex128)
        assert np.allclose(state, expected)

    def test_c_controlled_no_flip(self):
        """Controlled gate should not flip when control qubit is 0."""
        lib = ctypes.CDLL('/app/quantum_sim/libqsim.so')
        lib.apply_controlled_single_qubit_gate.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_int, ctypes.c_int, ctypes.c_int
        ]
        lib.apply_controlled_single_qubit_gate.restype = None
        from quantum_sim.gates import X
        state = np.array([0, 1, 0, 0], dtype=np.complex128)
        gate = np.ascontiguousarray(X.ravel(), dtype=np.complex128)
        lib.apply_controlled_single_qubit_gate(
            state.ctypes.data, gate.ctypes.data, 1, 0, 2
        )
        expected = np.array([0, 1, 0, 0], dtype=np.complex128)
        assert np.allclose(state, expected)

    def test_engine_uses_ctypes(self):
        """Engine module must load and use the C library via ctypes."""
        engine_path = '/app/quantum_sim/engine.py'
        with open(engine_path, 'r') as f:
            source = f.read()
        assert 'ctypes' in source, "engine.py must use ctypes to load libqsim.so"
        assert 'libqsim' in source, "engine.py must reference libqsim.so"


class TestApplyGate:
    def test_x_gate_on_zero(self):
        from quantum_sim.engine import apply_gate
        from quantum_sim.gates import X
        state = np.array([1, 0], dtype=complex)
        result = apply_gate(state, X, (0,), 1)
        assert np.allclose(result, [0, 1])

    def test_hadamard(self):
        from quantum_sim.engine import apply_gate
        from quantum_sim.gates import H
        state = np.array([1, 0], dtype=complex)
        result = apply_gate(state, H, (0,), 1)
        expected = np.array([1, 1], dtype=complex) / np.sqrt(2)
        assert np.allclose(result, expected)

    def test_x_on_qubit1_of_2(self):
        from quantum_sim.engine import apply_gate
        from quantum_sim.gates import X
        # |00> -> |10>
        state = np.array([1, 0, 0, 0], dtype=complex)
        result = apply_gate(state, X, (1,), 2)
        expected = np.array([0, 0, 1, 0], dtype=complex)
        assert np.allclose(result, expected)

    def test_x_on_qubit0_of_2(self):
        from quantum_sim.engine import apply_gate
        from quantum_sim.gates import X
        # |00> -> |01>
        state = np.array([1, 0, 0, 0], dtype=complex)
        result = apply_gate(state, X, (0,), 2)
        expected = np.array([0, 1, 0, 0], dtype=complex)
        assert np.allclose(result, expected)

    def test_two_qubit_gate_cnot(self):
        from quantum_sim.engine import apply_gate
        from quantum_sim.gates import CNOT_matrix
        # CNOT on targets (0,1): qubit 1 is control, qubit 0 is target
        # |10> -> |11>
        state = np.array([0, 0, 1, 0], dtype=complex)
        result = apply_gate(state, CNOT_matrix, (0, 1), 2)
        expected = np.array([0, 0, 0, 1], dtype=complex)
        assert np.allclose(result, expected)

    def test_swap_gate(self):
        from quantum_sim.engine import apply_gate
        from quantum_sim.gates import SWAP_matrix
        # |01> -> |10>
        state = np.array([0, 1, 0, 0], dtype=complex)
        result = apply_gate(state, SWAP_matrix, (0, 1), 2)
        expected = np.array([0, 0, 1, 0], dtype=complex)
        assert np.allclose(result, expected)

    def test_gate_on_3_qubits(self):
        from quantum_sim.engine import apply_gate
        from quantum_sim.gates import X
        # Apply X on qubit 1 of 3-qubit system: |000> -> |010>
        state = np.zeros(8, dtype=complex)
        state[0] = 1
        result = apply_gate(state, X, (1,), 3)
        expected = np.zeros(8, dtype=complex)
        expected[2] = 1
        assert np.allclose(result, expected)

    def test_gate_non_contiguous_targets(self):
        from quantum_sim.engine import apply_gate
        from quantum_sim.gates import SWAP_matrix
        # SWAP qubits 0 and 2 in a 3-qubit system: |001> -> |100>
        state = np.zeros(8, dtype=complex)
        state[1] = 1  # |001>
        result = apply_gate(state, SWAP_matrix, (0, 2), 3)
        expected = np.zeros(8, dtype=complex)
        expected[4] = 1  # |100>
        assert np.allclose(result, expected)


class TestControlledGate:
    def test_cnot_via_controlled(self):
        from quantum_sim.engine import apply_controlled_gate
        from quantum_sim.gates import X
        # CNOT: control=1, target=0; |10> -> |11>
        state = np.array([0, 0, 1, 0], dtype=complex)
        result = apply_controlled_gate(state, X, (1,), (0,), 2)
        expected = np.array([0, 0, 0, 1], dtype=complex)
        assert np.allclose(result, expected)

    def test_cnot_no_flip(self):
        from quantum_sim.engine import apply_controlled_gate
        from quantum_sim.gates import X
        # Control qubit 1 is 0 in |01>, so X should NOT apply
        state = np.array([0, 1, 0, 0], dtype=complex)
        result = apply_controlled_gate(state, X, (1,), (0,), 2)
        expected = np.array([0, 1, 0, 0], dtype=complex)
        assert np.allclose(result, expected)

    def test_toffoli(self):
        from quantum_sim.engine import apply_controlled_gate
        from quantum_sim.gates import X
        # Toffoli: control=(1,2), target=0; |110> -> |111>
        state = np.zeros(8, dtype=complex)
        state[6] = 1  # |110> = 0b110 = 6
        result = apply_controlled_gate(state, X, (1, 2), (0,), 3)
        expected = np.zeros(8, dtype=complex)
        expected[7] = 1  # |111>
        assert np.allclose(result, expected)

    def test_toffoli_no_flip(self):
        from quantum_sim.engine import apply_controlled_gate
        from quantum_sim.gates import X
        # Only one control is 1 in |100>, should NOT flip
        state = np.zeros(8, dtype=complex)
        state[4] = 1  # |100> = 0b100
        result = apply_controlled_gate(state, X, (1, 2), (0,), 3)
        expected = np.zeros(8, dtype=complex)
        expected[4] = 1
        assert np.allclose(result, expected)

    def test_controlled_on_superposition(self):
        from quantum_sim.engine import apply_gate, apply_controlled_gate
        from quantum_sim.gates import H, X
        # H on qubit 1, then CNOT control=1 target=0
        # |00> -> H_q1 -> (|00> + |10>)/sqrt(2) -> CNOT -> (|00> + |11>)/sqrt(2)
        state = np.array([1, 0, 0, 0], dtype=complex)
        apply_gate(state, H, (1,), 2)
        apply_controlled_gate(state, X, (1,), (0,), 2)
        expected = np.array([1, 0, 0, 1], dtype=complex) / np.sqrt(2)
        assert np.allclose(state, expected)


class TestCircuit:
    def test_bell_state(self):
        from quantum_sim.circuit import ParameterizedCircuit
        from quantum_sim.gates import H, X
        circ = ParameterizedCircuit(2)
        circ.add_gate(H, (0,))
        circ.add_gate(X, (1,), controls=(0,))
        state = circ.simulate()
        expected = np.array([1, 0, 0, 1], dtype=complex) / np.sqrt(2)
        assert np.allclose(state, expected)

    def test_ghz_3(self):
        from quantum_sim.circuit import ParameterizedCircuit
        from quantum_sim.gates import H, X
        circ = ParameterizedCircuit(3)
        circ.add_gate(H, (0,))
        circ.add_gate(X, (1,), controls=(0,))
        circ.add_gate(X, (2,), controls=(0,))
        state = circ.simulate()
        expected = np.zeros(8, dtype=complex)
        expected[0] = 1 / np.sqrt(2)
        expected[7] = 1 / np.sqrt(2)
        assert np.allclose(state, expected)

    def test_parameterized_rx(self):
        from quantum_sim.circuit import ParameterizedCircuit
        from quantum_sim.gates import Rx
        circ = ParameterizedCircuit(1)
        circ.add_rx(0, 0)
        theta = 0.7
        state = circ.simulate(params=[theta])
        expected = Rx(theta) @ np.array([1, 0], dtype=complex)
        assert np.allclose(state, expected)

    def test_parameterized_multi(self):
        from quantum_sim.circuit import ParameterizedCircuit
        from quantum_sim.gates import Rx, Ry
        circ = ParameterizedCircuit(1)
        circ.add_rx(0, 0)
        circ.add_ry(1, 0)
        params = [0.5, 1.2]
        state = circ.simulate(params=params)
        expected = Ry(1.2) @ Rx(0.5) @ np.array([1, 0], dtype=complex)
        assert np.allclose(state, expected)

    def test_n_params(self):
        from quantum_sim.circuit import ParameterizedCircuit
        from quantum_sim.gates import H
        circ = ParameterizedCircuit(3)
        circ.add_gate(H, (0,))
        circ.add_rx(0, 0)
        circ.add_ry(1, 1)
        circ.add_rz(2, 2)
        assert circ.n_params == 3

    def test_state_normalization(self):
        from quantum_sim.circuit import ParameterizedCircuit
        from quantum_sim.gates import H, X
        circ = ParameterizedCircuit(4)
        for i in range(4):
            circ.add_gate(H, (i,))
        for i in range(3):
            circ.add_gate(X, (i + 1,), controls=(i,))
        for i in range(4):
            circ.add_rx(i, i)
        state = circ.simulate(params=[0.3, -0.7, 1.1, -0.2])
        assert np.allclose(np.linalg.norm(state), 1.0, atol=1e-12)


class TestGradientComputation:
    def _build_observable_z0(self, n_qubits):
        """Z on qubit 0, I on rest."""
        dim = 1 << n_qubits
        obs = np.zeros((dim, dim), dtype=complex)
        for i in range(dim):
            obs[i, i] = -1.0 if (i & 1) else 1.0
        return obs

    def _finite_diff_gradient(self, circuit, observable, params, eps=1e-5):
        params = np.asarray(params, dtype=float)
        grads = np.zeros(len(params))
        for k in range(len(params)):
            p_plus = params.copy()
            p_minus = params.copy()
            p_plus[k] += eps
            p_minus[k] -= eps
            psi_plus = circuit.simulate(params=p_plus)
            psi_minus = circuit.simulate(params=p_minus)
            e_plus = np.real(psi_plus.conj() @ observable @ psi_plus)
            e_minus = np.real(psi_minus.conj() @ observable @ psi_minus)
            grads[k] = (e_plus - e_minus) / (2 * eps)
        return grads

    def test_single_rx_analytic(self):
        from quantum_sim.circuit import ParameterizedCircuit
        from quantum_sim.differentiation import compute_gradients
        from quantum_sim.gates import Z
        circ = ParameterizedCircuit(1)
        circ.add_rx(0, 0)
        params = np.array([0.7])
        grad = compute_gradients(circ, Z, params)
        # E = cos(theta), dE/dtheta = -sin(theta)
        assert np.allclose(grad[0], -np.sin(0.7), atol=1e-10)

    def test_single_ry_analytic(self):
        from quantum_sim.circuit import ParameterizedCircuit
        from quantum_sim.differentiation import compute_gradients
        from quantum_sim.gates import Z
        circ = ParameterizedCircuit(1)
        circ.add_ry(0, 0)
        params = np.array([1.3])
        grad = compute_gradients(circ, Z, params)
        assert np.allclose(grad[0], -np.sin(1.3), atol=1e-10)

    def test_multi_param_gradient(self):
        from quantum_sim.circuit import ParameterizedCircuit
        from quantum_sim.differentiation import compute_gradients
        from quantum_sim.gates import H, X
        circ = ParameterizedCircuit(2)
        circ.add_rx(0, 0)
        circ.add_gate(H, (1,))
        circ.add_gate(X, (0,), controls=(1,))
        circ.add_ry(1, 1)
        circ.add_rz(2, 0)
        obs = self._build_observable_z0(2)
        params = np.array([0.3, -0.5, 1.1])
        grad_comp = compute_gradients(circ, obs, params)
        grad_fd = self._finite_diff_gradient(circ, obs, params)
        assert np.allclose(grad_comp, grad_fd, atol=1e-5)

    def test_entangled_gradient(self):
        from quantum_sim.circuit import ParameterizedCircuit
        from quantum_sim.differentiation import compute_gradients
        from quantum_sim.gates import X
        circ = ParameterizedCircuit(2)
        circ.add_ry(0, 0)
        circ.add_gate(X, (1,), controls=(0,))
        circ.add_rx(1, 1)
        obs = self._build_observable_z0(2)
        params = np.array([0.8, -0.4])
        grad_comp = compute_gradients(circ, obs, params)
        grad_fd = self._finite_diff_gradient(circ, obs, params)
        assert np.allclose(grad_comp, grad_fd, atol=1e-5)

    def test_controlled_parameterized_gradient(self):
        from quantum_sim.circuit import ParameterizedCircuit
        from quantum_sim.differentiation import compute_gradients
        from quantum_sim.gates import H
        circ = ParameterizedCircuit(2)
        circ.add_gate(H, (0,))
        circ.add_rx(0, 1, controls=(0,))
        obs = self._build_observable_z0(2)
        params = np.array([0.9])
        grad_comp = compute_gradients(circ, obs, params)
        grad_fd = self._finite_diff_gradient(circ, obs, params)
        assert np.allclose(grad_comp, grad_fd, atol=1e-5)

    def test_gradient_same_param_multiple_gates(self):
        """Same parameter used in multiple gates -- gradients must accumulate."""
        from quantum_sim.circuit import ParameterizedCircuit
        from quantum_sim.differentiation import compute_gradients
        circ = ParameterizedCircuit(2)
        circ.add_rx(0, 0)
        circ.add_rx(0, 1)
        obs = self._build_observable_z0(2)
        params = np.array([0.6])
        grad_comp = compute_gradients(circ, obs, params)
        grad_fd = self._finite_diff_gradient(circ, obs, params)
        assert np.allclose(grad_comp, grad_fd, atol=1e-5)

    def test_deep_circuit_gradient(self):
        """Stress test: deeper variational circuit with entanglement."""
        from quantum_sim.circuit import ParameterizedCircuit
        from quantum_sim.differentiation import compute_gradients
        from quantum_sim.gates import X
        circ = ParameterizedCircuit(3)
        # Layer 1
        circ.add_rx(0, 0)
        circ.add_ry(1, 1)
        circ.add_rz(2, 2)
        # Entangling
        circ.add_gate(X, (1,), controls=(0,))
        circ.add_gate(X, (2,), controls=(1,))
        # Layer 2
        circ.add_rx(3, 0)
        circ.add_ry(4, 1)
        circ.add_rz(5, 2)
        # Cross-entangle
        circ.add_gate(X, (0,), controls=(2,))
        # Layer 3
        circ.add_rx(6, 1)
        obs = self._build_observable_z0(3)
        params = np.array([0.1, -0.3, 0.7, 1.2, -0.5, 0.9, -1.1])
        grad_comp = compute_gradients(circ, obs, params)
        grad_fd = self._finite_diff_gradient(circ, obs, params)
        assert np.allclose(grad_comp, grad_fd, atol=1e-5)


class TestNoKron:
    def test_engine_no_kron(self):
        """Engine must use subspace iteration, not Kronecker products."""
        engine_path = '/app/quantum_sim/engine.py'
        with open(engine_path, 'r') as f:
            source = f.read()
        assert 'kron' not in source, "engine.py must not use np.kron or any kron variant"


class TestPerformance:
    def test_12_qubit_simulation(self):
        from quantum_sim.circuit import ParameterizedCircuit
        from quantum_sim.gates import H, X
        n = 12
        circ = ParameterizedCircuit(n)
        for i in range(n):
            circ.add_gate(H, (i,))
        for i in range(n - 1):
            circ.add_gate(X, (i + 1,), controls=(i,))
        for i in range(n):
            circ.add_rx(i, i)
        params = np.random.RandomState(42).randn(n)
        start = time.time()
        state = circ.simulate(params=params)
        elapsed = time.time() - start
        assert elapsed < 10.0, f"12-qubit simulation took {elapsed:.1f}s (limit: 10s)"
        assert np.allclose(np.linalg.norm(state), 1.0, atol=1e-10)


class TestCLI:
    def test_bell_circuit_expectation(self):
        """CLI should compute correct expectation value for Bell state."""
        result = subprocess.run(
            ["python3", "/app/run_circuit.py", "/app/circuits/bell_z0.json"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        output = json.loads(result.stdout)
        assert "expectation_value" in output
        assert abs(output["expectation_value"] - 0.0) < 1e-6

    def test_rx_circuit_expectation(self):
        """CLI should compute cos(0.7) for Rx(0.7) with Z observable."""
        result = subprocess.run(
            ["python3", "/app/run_circuit.py", "/app/circuits/rx_z0.json"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        output = json.loads(result.stdout)
        assert abs(output["expectation_value"] - np.cos(0.7)) < 1e-6

    def test_gradients_flag(self):
        """CLI with --gradients should include gradient array."""
        result = subprocess.run(
            ["python3", "/app/run_circuit.py", "--gradients", "/app/circuits/rx_z0.json"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        output = json.loads(result.stdout)
        assert "gradients" in output
        assert len(output["gradients"]) == 1
        assert abs(output["gradients"][0] - (-np.sin(0.7))) < 1e-5

    def test_jq_compatibility(self):
        """CLI output must be valid JSON parseable by jq."""
        sim_result = subprocess.run(
            ["python3", "/app/run_circuit.py", "/app/circuits/bell_z0.json"],
            capture_output=True, text=True, cwd="/app"
        )
        assert sim_result.returncode == 0
        jq_result = subprocess.run(
            ["jq", ".expectation_value"],
            input=sim_result.stdout, capture_output=True, text=True
        )
        assert jq_result.returncode == 0, f"jq failed to parse CLI output: {jq_result.stderr}"


class TestMakeBenchmark:
    def test_make_benchmark(self):
        """make benchmark should build, process circuits, produce JSON + SQLite."""
        subprocess.run(["make", "clean"], cwd="/app", capture_output=True)
        result = subprocess.run(
            ["make", "benchmark"],
            capture_output=True, text=True, cwd="/app", timeout=120
        )
        assert result.returncode == 0, \
            f"make benchmark failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

        # Verify JSON result files
        for name in ["bell_z0", "rx_z0", "vqe_2q"]:
            path = f"/app/results/{name}.json"
            assert os.path.exists(path), f"Missing result file: {path}"
            with open(path) as f:
                data = json.load(f)
            assert "expectation_value" in data, f"Result {name} missing expectation_value"

        # Verify SQLite database
        db_path = "/app/results/benchmark.db"
        assert os.path.exists(db_path), "benchmark.db not created"
        conn = sqlite3.connect(db_path)

        cursor = conn.execute("PRAGMA table_info(results)")
        columns = {row[1]: row[2] for row in cursor}
        assert 'name' in columns, "Missing 'name' column in results table"
        assert 'n_qubits' in columns, "Missing 'n_qubits' column"
        assert 'expectation_value' in columns, "Missing 'expectation_value' column"
        assert 'n_params' in columns, "Missing 'n_params' column"
        assert 'n_gradients' in columns, "Missing 'n_gradients' column"

        cursor = conn.execute("SELECT COUNT(*) FROM results")
        count = cursor.fetchone()[0]
        assert count == 3, f"Expected 3 rows in results table, got {count}"

        cursor = conn.execute(
            "SELECT expectation_value FROM results WHERE name='bell_z0'"
        )
        row = cursor.fetchone()
        assert row is not None, "bell_z0 not found in database"
        assert abs(row[0] - 0.0) < 1e-6, f"bell_z0 expectation wrong: {row[0]}"

        cursor = conn.execute(
            "SELECT expectation_value FROM results WHERE name='rx_z0'"
        )
        row = cursor.fetchone()
        assert row is not None, "rx_z0 not found in database"
        assert abs(row[0] - np.cos(0.7)) < 1e-5, f"rx_z0 expectation wrong: {row[0]}"

        conn.close()


class TestMakeReport:
    def test_make_report(self):
        """make report should query SQLite and produce formatted output."""
        subprocess.run(["make", "benchmark"], cwd="/app",
                       capture_output=True, timeout=120)
        result = subprocess.run(
            ["make", "report"],
            capture_output=True, text=True, cwd="/app", timeout=30
        )
        assert result.returncode == 0, f"make report failed:\n{result.stderr}"
        assert len(result.stdout.strip()) > 0, "make report produced no output"
        assert "bell_z0" in result.stdout, "report should mention bell_z0"
        assert "rx_z0" in result.stdout, "report should mention rx_z0"
