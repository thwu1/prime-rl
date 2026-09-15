"""
Tests for the quantum circuit simulation pipeline.

"""
import json
import os
import sqlite3
import subprocess
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, "/app")

from qcsim.gates import H_GATE, X_GATE, Z_GATE, rx_gate, ry_gate, rz_gate
from qcsim.engine import apply_gate, apply_controlled_gate, simulate
from qcsim.circuit import Circuit
from qcsim.differentiation import expectation_value, compute_gradient


# ---------------------------------------------------------------------------
# Gate application
# ---------------------------------------------------------------------------


class TestGateApplication:
    def test_x_gate_qubit0(self):
        """X on qubit 0 of |00> gives |01> (index 1)."""
        state = np.zeros(4, dtype=complex)
        state[0] = 1.0
        result = apply_gate(state.copy(), X_GATE, (0,))
        expected = np.zeros(4, dtype=complex)
        expected[1] = 1.0
        np.testing.assert_allclose(result, expected, atol=1e-10)

    def test_x_gate_higher_qubit(self):
        """X on qubit 2 of |000> gives |100> (index 4)."""
        state = np.zeros(8, dtype=complex)
        state[0] = 1.0
        result = apply_gate(state.copy(), X_GATE, (2,))
        expected = np.zeros(8, dtype=complex)
        expected[4] = 1.0
        np.testing.assert_allclose(result, expected, atol=1e-10)

    def test_hadamard(self):
        """H|0> = (|0>+|1>)/sqrt(2)."""
        state = np.array([1.0, 0.0], dtype=complex)
        result = apply_gate(state.copy(), H_GATE, (0,))
        expected = np.array([1 / np.sqrt(2), 1 / np.sqrt(2)], dtype=complex)
        np.testing.assert_allclose(result, expected, atol=1e-10)

    def test_swap_nonadjacent(self):
        """SWAP qubits 0 and 2 in a 3-qubit system: |001> -> |100>."""
        SWAP = np.array(
            [[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=complex
        )
        state = np.zeros(8, dtype=complex)
        state[1] = 1.0  # |001>
        result = apply_gate(state.copy(), SWAP, (0, 2))
        expected = np.zeros(8, dtype=complex)
        expected[4] = 1.0  # |100>
        np.testing.assert_allclose(result, expected, atol=1e-10)


# ---------------------------------------------------------------------------
# Controlled gates
# ---------------------------------------------------------------------------


class TestControlledGate:
    def test_cnot_control_off(self):
        """CNOT with control qubit 0 = 0 does nothing."""
        state = np.zeros(4, dtype=complex)
        state[0] = 1.0  # |00>
        result = apply_controlled_gate(state.copy(), X_GATE, (0,), (1,))
        np.testing.assert_allclose(result, state, atol=1e-10)

    def test_cnot_control_on(self):
        """CNOT with control qubit 0 = 1 flips target qubit 1."""
        state = np.zeros(4, dtype=complex)
        state[1] = 1.0  # |01> (q0=1)
        result = apply_controlled_gate(state.copy(), X_GATE, (0,), (1,))
        expected = np.zeros(4, dtype=complex)
        expected[3] = 1.0  # |11>
        np.testing.assert_allclose(result, expected, atol=1e-10)

    def test_toffoli(self):
        """CCX: controls 0,1 target 2 on |111> gives |011>."""
        state = np.zeros(8, dtype=complex)
        state[7] = 1.0  # |111>
        result = apply_controlled_gate(state.copy(), X_GATE, (0, 1), (2,))
        expected = np.zeros(8, dtype=complex)
        expected[3] = 1.0  # |011>
        np.testing.assert_allclose(result, expected, atol=1e-10)


# ---------------------------------------------------------------------------
# Full circuit simulation
# ---------------------------------------------------------------------------


class TestCircuitSimulation:
    def test_bell_state(self):
        """H(0) + CNOT(0,1) produces (|00>+|11>)/sqrt(2)."""
        circ = Circuit(2)
        circ.h(0)
        circ.cnot(0, 1)
        state = simulate(circ)
        expected = np.zeros(4, dtype=complex)
        expected[0] = 1 / np.sqrt(2)
        expected[3] = 1 / np.sqrt(2)
        np.testing.assert_allclose(state, expected, atol=1e-10)

    def test_ghz_3qubit(self):
        """H(0) + CNOT(0,1) + CNOT(0,2) produces (|000>+|111>)/sqrt(2)."""
        circ = Circuit(3)
        circ.h(0)
        circ.cnot(0, 1)
        circ.cnot(0, 2)
        state = simulate(circ)
        expected = np.zeros(8, dtype=complex)
        expected[0] = 1 / np.sqrt(2)
        expected[7] = 1 / np.sqrt(2)
        np.testing.assert_allclose(state, expected, atol=1e-10)


# ---------------------------------------------------------------------------
# Differentiation
# ---------------------------------------------------------------------------


class TestDifferentiation:
    def test_single_ry_analytic(self):
        """d/dtheta <0|RY(-t)Z RY(t)|0> = -sin(theta)."""
        theta = 0.7
        circ = Circuit(1)
        circ.ry(0, 0)  # param 0 on qubit 0
        params = np.array([theta])
        grad = compute_gradient(circ, params, Z_GATE, (0,))
        np.testing.assert_allclose(grad[0], -np.sin(theta), atol=1e-8)

    def test_multi_param_finite_diff(self):
        """Gradient of a 2-qubit parameterized circuit matches finite differences."""
        circ = Circuit(2)
        circ.ry(0, 0)
        circ.cnot(0, 1)
        circ.ry(1, 1)
        circ.rz(2, 0)

        params = np.array([0.5, 1.2, 0.3])
        obs = Z_GATE
        obs_q = (0,)

        grad = compute_gradient(circ, params, obs, obs_q)

        eps = 1e-5
        fd = np.zeros(len(params))
        for i in range(len(params)):
            pp = params.copy(); pp[i] += eps
            pm = params.copy(); pm[i] -= eps
            ep = expectation_value(simulate(circ, pp), obs, obs_q)
            em = expectation_value(simulate(circ, pm), obs, obs_q)
            fd[i] = (ep - em) / (2 * eps)

        np.testing.assert_allclose(grad, fd, atol=1e-6)

    def test_deeper_circuit_finite_diff(self):
        """Gradient of a 3-qubit variational circuit matches finite differences."""
        np.random.seed(42)
        n_qubits = 3
        circ = Circuit(n_qubits)
        pidx = 0
        for q in range(n_qubits):
            circ.ry(pidx, q); pidx += 1
        for q in range(n_qubits - 1):
            circ.cnot(q, q + 1)
        for q in range(n_qubits):
            circ.ry(pidx, q); pidx += 1
            circ.rz(pidx, q); pidx += 1

        params = np.random.uniform(0, 2 * np.pi, pidx)
        obs = Z_GATE
        obs_q = (1,)

        grad = compute_gradient(circ, params, obs, obs_q)

        eps = 1e-5
        fd = np.zeros(len(params))
        for i in range(len(params)):
            pp = params.copy(); pp[i] += eps
            pm = params.copy(); pm[i] -= eps
            ep = expectation_value(simulate(circ, pp), obs, obs_q)
            em = expectation_value(simulate(circ, pm), obs, obs_q)
            fd[i] = (ep - em) / (2 * eps)

        np.testing.assert_allclose(grad, fd, atol=1e-5)


# ---------------------------------------------------------------------------
# QASM Parser
# ---------------------------------------------------------------------------


class TestQasmParser:
    def test_parse_bell(self):
        """Parse bell.qasm and verify simulation produces Bell state."""
        from qcsim.qasm_parser import parse_qasm
        circ = parse_qasm("/app/circuits/bell.qasm")
        assert circ.n_qubits == 2
        assert len(circ.operations) == 2
        state = simulate(circ)
        expected = np.zeros(4, dtype=complex)
        expected[0] = 1 / np.sqrt(2)
        expected[3] = 1 / np.sqrt(2)
        np.testing.assert_allclose(state, expected, atol=1e-10)

    def test_parse_ghz3(self):
        """Parse ghz3.qasm and verify simulation produces GHZ state."""
        from qcsim.qasm_parser import parse_qasm
        circ = parse_qasm("/app/circuits/ghz3.qasm")
        assert circ.n_qubits == 3
        assert len(circ.operations) == 3
        state = simulate(circ)
        expected = np.zeros(8, dtype=complex)
        expected[0] = 1 / np.sqrt(2)
        expected[7] = 1 / np.sqrt(2)
        np.testing.assert_allclose(state, expected, atol=1e-10)

    def test_parse_variational(self):
        """Parse variational2.qasm (RY+CNOT+RZ) and verify amplitudes."""
        from qcsim.qasm_parser import parse_qasm
        circ = parse_qasm("/app/circuits/variational2.qasm")
        assert circ.n_qubits == 2
        assert len(circ.operations) == 3
        state = simulate(circ)
        probs = np.abs(state) ** 2
        np.testing.assert_allclose(probs[0], 0.5, atol=1e-10)
        np.testing.assert_allclose(probs[3], 0.5, atol=1e-10)
        # Verify relative phase from RZ(pi/4)
        np.testing.assert_allclose(
            np.angle(state[3]) - np.angle(state[0]),
            np.pi / 4,
            atol=1e-10,
        )


# ---------------------------------------------------------------------------
# Pipeline (SQLite + jq integration)
# ---------------------------------------------------------------------------


class TestPipeline:
    @classmethod
    def setup_class(cls):
        """Run the pipeline once before all tests in this class."""
        for f in ["/app/results.db", "/app/report.json"]:
            if os.path.exists(f):
                os.remove(f)
        subprocess.run(
            ["bash", "/app/pipeline.sh"],
            timeout=120,
            capture_output=True,
        )

    def test_pipeline_uses_required_tools(self):
        """pipeline.sh must invoke both sqlite3 and jq."""
        with open("/app/pipeline.sh") as f:
            content = f.read()
        assert "sqlite3" in content, "pipeline.sh must use the sqlite3 CLI"
        assert "jq" in content, "pipeline.sh must use jq"

    def test_database_schema_and_data(self):
        """results.db must contain circuits and amplitudes tables with correct data."""
        assert os.path.isfile("/app/results.db"), "results.db not created"
        db = sqlite3.connect("/app/results.db")
        rows = db.execute(
            "SELECT name, n_qubits, n_gates FROM circuits ORDER BY name"
        ).fetchall()
        names = [r[0] for r in rows]
        assert "bell" in names
        assert "ghz3" in names
        assert "variational2" in names
        bell = db.execute(
            "SELECT n_qubits, n_gates FROM circuits WHERE name = 'bell'"
        ).fetchone()
        assert bell[0] == 2
        assert bell[1] == 2
        ghz = db.execute(
            "SELECT n_qubits, n_gates FROM circuits WHERE name = 'ghz3'"
        ).fetchone()
        assert ghz[0] == 3
        assert ghz[1] == 3
        db.close()

    def test_bell_amplitudes_in_db(self):
        """Bell state amplitudes in the database must be correct."""
        db = sqlite3.connect("/app/results.db")
        rows = db.execute(
            """SELECT a.basis_state, a.probability
               FROM amplitudes a JOIN circuits c ON a.circuit_id = c.id
               WHERE c.name = 'bell' AND a.probability > 0.001
               ORDER BY a.basis_state"""
        ).fetchall()
        db.close()
        assert len(rows) == 2
        assert rows[0][0] == 0
        assert rows[1][0] == 3
        np.testing.assert_allclose(rows[0][1], 0.5, atol=1e-4)
        np.testing.assert_allclose(rows[1][1], 0.5, atol=1e-4)

    def test_report_json_structure(self):
        """report.json must be a valid JSON array with correct structure."""
        assert os.path.isfile("/app/report.json"), "report.json not created"
        with open("/app/report.json") as f:
            report = json.load(f)
        assert isinstance(report, list)
        assert len(report) >= 3
        names = {r["name"] for r in report}
        assert "bell" in names
        assert "ghz3" in names
        assert "variational2" in names
        for entry in report:
            assert "n_qubits" in entry
            assert "n_gates" in entry
            assert "states" in entry
            assert isinstance(entry["states"], list)
            for s in entry["states"]:
                assert "basis" in s
                assert "prob" in s
                assert "re" in s
                assert "im" in s

    def test_ghz_amplitudes_in_report(self):
        """GHZ state in report.json must have correct amplitudes."""
        with open("/app/report.json") as f:
            report = json.load(f)
        ghz = [r for r in report if r["name"] == "ghz3"][0]
        assert ghz["n_qubits"] == 3
        assert ghz["n_gates"] == 3
        assert len(ghz["states"]) == 2
        bases = {s["basis"] for s in ghz["states"]}
        assert bases == {0, 7}
        for s in ghz["states"]:
            np.testing.assert_allclose(s["prob"], 0.5, atol=1e-4)


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------


class TestPerformance:
    def test_16qubit_circuit(self):
        """16-qubit circuit with 160 RY + 80 CNOT gates finishes in < 30 s."""
        np.random.seed(123)
        n_qubits = 16
        circ = Circuit(n_qubits)
        pidx = 0
        for _ in range(10):
            for q in range(n_qubits):
                circ.ry(pidx, q); pidx += 1
            for q in range(0, n_qubits - 1, 2):
                circ.cnot(q, q + 1)

        params = np.random.uniform(0, 2 * np.pi, pidx)

        start = time.time()
        state = simulate(circ, params)
        elapsed = time.time() - start

        assert elapsed < 30.0, f"Took {elapsed:.1f}s, limit 30s"
        assert len(state) == 2 ** n_qubits
        assert abs(np.linalg.norm(state) - 1.0) < 1e-10, "State not normalised"
