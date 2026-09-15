"""Tests for quantum circuit optimizer.

Verifies that /app/optimize.py correctly optimizes OpenQASM 2.0 circuits
by checking unitary equivalence and multi-qubit gate count reduction.
"""

import subprocess
import tempfile
import os
import re
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# QASM Parser
# ---------------------------------------------------------------------------

def parse_qasm(text):
    """Parse OpenQASM 2.0 text into (n_qubits, gate_list)."""
    lines = text.strip().split("\n")
    n_qubits = None
    gates = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        if line.startswith("OPENQASM") or line.startswith("include"):
            continue
        m = re.match(r"qreg\s+\w+\[(\d+)\]\s*;", line)
        if m:
            n_qubits = int(m.group(1))
            continue
        if line.startswith("creg") or line.startswith("barrier"):
            continue
        m = re.match(r"(\w+)\s*(?:\(([^)]*)\))?\s+(.+);", line)
        if m:
            name = m.group(1)
            params_str = m.group(2)
            qubits_str = m.group(3)
            params = None
            if params_str:
                params = []
                for p in params_str.split(","):
                    p = p.strip().replace("pi", str(np.pi))
                    params.append(float(eval(p)))  # noqa: S307
            qubits = [
                int(qm.group(1))
                for qm in re.finditer(r"\w+\[(\d+)\]", qubits_str)
            ]
            gates.append({"name": name, "qubits": qubits, "params": params})
    assert n_qubits is not None, "Could not find qreg declaration in QASM"
    return n_qubits, gates


# ---------------------------------------------------------------------------
# Gate matrices
# ---------------------------------------------------------------------------

_GATE_MATRICES = {
    "id": np.eye(2, dtype=complex),
    "h": np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2),
    "x": np.array([[0, 1], [1, 0]], dtype=complex),
    "y": np.array([[0, -1j], [1j, 0]], dtype=complex),
    "z": np.array([[1, 0], [0, -1]], dtype=complex),
    "s": np.array([[1, 0], [0, 1j]], dtype=complex),
    "sdg": np.array([[1, 0], [0, -1j]], dtype=complex),
    "t": np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=complex),
    "tdg": np.array([[1, 0], [0, np.exp(-1j * np.pi / 4)]], dtype=complex),
}


def gate_matrix(name, params=None):
    """Return the 2x2 unitary matrix for a single-qubit gate."""
    if name in _GATE_MATRICES:
        return _GATE_MATRICES[name]
    if name == "u3" and params is not None:
        theta, phi, lam = params
        return np.array(
            [
                [np.cos(theta / 2), -np.exp(1j * lam) * np.sin(theta / 2)],
                [
                    np.exp(1j * phi) * np.sin(theta / 2),
                    np.exp(1j * (phi + lam)) * np.cos(theta / 2),
                ],
            ],
            dtype=complex,
        )
    if name == "u1" and params is not None:
        lam = params[0]
        return np.array([[1, 0], [0, np.exp(1j * lam)]], dtype=complex)
    if name == "u2" and params is not None:
        phi, lam = params
        return (
            np.array(
                [[1, -np.exp(1j * lam)], [np.exp(1j * phi), np.exp(1j * (phi + lam))]],
                dtype=complex,
            )
            / np.sqrt(2)
        )
    if name == "rz" and params is not None:
        theta = params[0]
        return np.array(
            [[np.exp(-1j * theta / 2), 0], [0, np.exp(1j * theta / 2)]], dtype=complex
        )
    raise ValueError(f"Unknown single-qubit gate: {name}")


# ---------------------------------------------------------------------------
# Full-system unitary builders
# ---------------------------------------------------------------------------


def single_qubit_unitary(gate_mat, qubit, n_qubits):
    """Build the full 2^n x 2^n unitary for a single-qubit gate."""
    ops = [np.eye(2, dtype=complex)] * n_qubits
    ops[qubit] = gate_mat
    result = ops[0]
    for k in range(1, n_qubits):
        result = np.kron(result, ops[k])
    return result


def cx_unitary(control, target, n_qubits):
    """Build the full 2^n x 2^n unitary for a CNOT gate."""
    dim = 2**n_qubits
    U = np.zeros((dim, dim), dtype=complex)
    for col in range(dim):
        bits = [(col >> (n_qubits - 1 - q)) & 1 for q in range(n_qubits)]
        out_bits = list(bits)
        if bits[control] == 1:
            out_bits[target] ^= 1
        row = sum(b << (n_qubits - 1 - q) for q, b in enumerate(out_bits))
        U[row, col] = 1.0
    return U


def circuit_unitary(n_qubits, gates):
    """Compute the full unitary matrix of a gate sequence."""
    dim = 2**n_qubits
    U = np.eye(dim, dtype=complex)
    for gate in gates:
        if gate["name"] == "cx":
            G = cx_unitary(gate["qubits"][0], gate["qubits"][1], n_qubits)
        else:
            mat = gate_matrix(gate["name"], gate.get("params"))
            G = single_qubit_unitary(mat, gate["qubits"][0], n_qubits)
        U = G @ U
    return U


# ---------------------------------------------------------------------------
# Equivalence check
# ---------------------------------------------------------------------------


def unitaries_equivalent(U, V, tol=1e-6):
    """Check if two unitaries are equal up to a global phase factor."""
    dim = U.shape[0]
    P = U.conj().T @ V  # U†V should be e^{iθ} I
    trace_mag = abs(np.trace(P))
    if abs(trace_mag - dim) > tol * dim:
        return False
    phase = P[0, 0]
    if abs(abs(phase) - 1.0) > tol:
        return False
    return np.allclose(P, phase * np.eye(dim), atol=tol)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def count_cx(gates):
    """Count CX (CNOT) gates in a gate list."""
    return sum(1 for g in gates if g["name"] == "cx")


def run_optimizer(input_path):
    """Run /app/optimize.py on *input_path* and return stdout."""
    result = subprocess.run(
        ["python3", "/app/optimize.py", input_path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"optimize.py failed (exit {result.returncode}):\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return result.stdout


def verify_circuit(input_path, max_cx):
    """End-to-end verification of optimizer output for one circuit."""
    with open(input_path) as f:
        original_qasm = f.read()

    optimized_qasm = run_optimizer(input_path)

    n_orig, gates_orig = parse_qasm(original_qasm)
    n_opt, gates_opt = parse_qasm(optimized_qasm)

    assert n_orig == n_opt, f"Qubit count changed: {n_orig} -> {n_opt}"

    U_orig = circuit_unitary(n_orig, gates_orig)
    U_opt = circuit_unitary(n_opt, gates_opt)

    assert unitaries_equivalent(U_orig, U_opt), (
        "Optimized circuit is NOT unitarily equivalent to the original.\n"
        f"Original CX count: {count_cx(gates_orig)}, "
        f"Optimized CX count: {count_cx(gates_opt)}"
    )

    cx_count = count_cx(gates_opt)
    assert cx_count <= max_cx, (
        f"CX gate count {cx_count} exceeds threshold {max_cx}"
    )

    assert "OPENQASM" in optimized_qasm, "Missing OPENQASM header"
    assert "qreg" in optimized_qasm, "Missing qreg declaration"

    return cx_count


# ---------------------------------------------------------------------------
# Tests — provided circuits
# ---------------------------------------------------------------------------


class TestCircuitA:
    """Verify optimization of circuit_a (3-qubit, target: <=2 CX)."""

    def test_optimized(self):
        cx = verify_circuit("/app/circuits/circuit_a.qasm", max_cx=2)
        assert cx <= 2


class TestCircuitB:
    """Verify optimization of circuit_b (3-qubit, target: 0 CX)."""

    def test_optimized(self):
        cx = verify_circuit("/app/circuits/circuit_b.qasm", max_cx=0)
        assert cx == 0


class TestCircuitC:
    """Verify optimization of circuit_c (4-qubit, target: <=4 CX)."""

    def test_optimized(self):
        cx = verify_circuit("/app/circuits/circuit_c.qasm", max_cx=4)
        assert cx <= 4


class TestCircuitD:
    """Verify optimization of circuit_d (3-qubit with parameterized gates, target: 0 CX)."""

    def test_optimized(self):
        cx = verify_circuit("/app/circuits/circuit_d.qasm", max_cx=0)
        assert cx == 0


# ---------------------------------------------------------------------------
# Tests — dynamically generated circuit (anti-hardcoding)
# ---------------------------------------------------------------------------


class TestDynamicCircuit:
    """Held-out circuit generated at test time to prevent hardcoded answers."""

    DYNAMIC_QASM = (
        "OPENQASM 2.0;\n"
        'include "qelib1.inc";\n'
        "qreg q[3];\n"
        "x q[0];\n"
        "cx q[0], q[1];\n"
        "cx q[0], q[1];\n"
        "h q[2];\n"
        "cx q[2], q[0];\n"
        "rz(0.33) q[2];\n"
        "cx q[2], q[0];\n"
        "t q[1];\n"
        "h q[0];\n"
    )

    def test_dynamic(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".qasm", delete=False
        ) as f:
            f.write(self.DYNAMIC_QASM)
            tmp_path = f.name
        try:
            cx = verify_circuit(tmp_path, max_cx=0)
            assert cx == 0
        finally:
            os.unlink(tmp_path)
