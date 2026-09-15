"""Shared QASM parsing and unitary matrix computation utilities."""
import re
import numpy as np


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
            params = None
            if params_str:
                params = []
                for p in params_str.split(","):
                    p = p.strip().replace("pi", str(np.pi))
                    params.append(float(eval(p)))
            qubits = [
                int(qm.group(1))
                for qm in re.finditer(r"\w+\[(\d+)\]", m.group(3))
            ]
            gates.append({"name": name, "qubits": qubits, "params": params})
    if n_qubits is None:
        raise ValueError("Could not find qreg declaration in QASM")
    return n_qubits, gates


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
    if name == "rz" and params is not None:
        theta = params[0]
        return np.array(
            [[np.exp(-1j * theta / 2), 0], [0, np.exp(1j * theta / 2)]],
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
    raise ValueError(f"Unknown single-qubit gate: {name}")


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
    dim = 2 ** n_qubits
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
    dim = 2 ** n_qubits
    U = np.eye(dim, dtype=complex)
    for gate in gates:
        if gate["name"] == "cx":
            G = cx_unitary(gate["qubits"][0], gate["qubits"][1], n_qubits)
        else:
            mat = gate_matrix(gate["name"], gate.get("params"))
            G = single_qubit_unitary(mat, gate["qubits"][0], n_qubits)
        U = G @ U
    return U


def unitaries_equivalent(U, V, tol=1e-6):
    """Check if two unitaries are equal up to a global phase factor."""
    dim = U.shape[0]
    P = U.conj().T @ V
    trace_mag = abs(np.trace(P))
    if abs(trace_mag - dim) > tol * dim:
        return False
    phase = P[0, 0]
    if abs(abs(phase) - 1.0) > tol:
        return False
    return np.allclose(P, phase * np.eye(dim), atol=tol)


def count_cx(gates):
    """Count CX (CNOT) gates in a gate list."""
    return sum(1 for g in gates if g["name"] == "cx")
