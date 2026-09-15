"""
Quantum Entanglement Distillation Engine — Complete Implementation
"""

import numpy as np

# ── Constants ───────────────────────────────────────────────

PHI_PLUS  = np.array([1, 0, 0, 1], dtype=complex) / np.sqrt(2)
PHI_MINUS = np.array([1, 0, 0, -1], dtype=complex) / np.sqrt(2)
PSI_PLUS  = np.array([0, 1, 1, 0], dtype=complex) / np.sqrt(2)
PSI_MINUS = np.array([0, 1, -1, 0], dtype=complex) / np.sqrt(2)

I2        = np.eye(2, dtype=complex)
X_GATE    = np.array([[0, 1], [1, 0]], dtype=complex)
Z_GATE    = np.array([[1, 0], [0, -1]], dtype=complex)
H_GATE    = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
CNOT      = np.array([[1,0,0,0],[0,1,0,0],[0,0,0,1],[0,0,1,0]], dtype=complex)
CZ        = np.diag([1, 1, 1, -1]).astype(complex)
SWAP_GATE = np.array([[1,0,0,0],[0,0,1,0],[0,1,0,0],[0,0,0,1]], dtype=complex)

SINGLE_GATES    = {"i": I2, "x": X_GATE, "z": Z_GATE, "h": H_GATE}
TWO_QUBIT_GATES = {"cx": CNOT, "cz": CZ, "swap": SWAP_GATE}


# ── Circuit ─────────────────────────────────────────────────

class Circuit:
    def __init__(self, num_qubits, num_cbits):
        self.num_qubits = num_qubits
        self.num_cbits = num_cbits
        self.operations = []
        self.flag_bit = 0

    def add_gate(self, gate_name, qubits):
        self.operations.append(("gate", gate_name, qubits))

    def add_measure(self, qubit, cbit):
        self.operations.append(("measure", qubit, cbit))

    def add_conditional(self, cbit, value, gate_name, qubits):
        self.operations.append(("if", cbit, value, gate_name, qubits))

    def add_store_xor(self, target_cbit, cbit_a, cbit_b):
        self.operations.append(("xor", target_cbit, cbit_a, cbit_b))

    def add_store_or(self, target_cbit, cbit_a, cbit_b):
        self.operations.append(("or", target_cbit, cbit_a, cbit_b))


# ── Helpers ─────────────────────────────────────────────────

def get_qubit_pairing(N):
    return [(i, 2 * N - 1 - i) for i in range(N)]


def _perm_natural_to_game(N):
    """Permutation from natural pair ordering to game qubit ordering."""
    perm = []
    for i in range(N):
        perm.append(2 * i)           # pair_i Alice qubit
    for i in range(N - 1, -1, -1):
        perm.append(2 * i + 1)       # pair_i Bob qubit (reversed)
    return perm


# ── Core functions ──────────────────────────────────────────

def initialize_bell_pairs(N, noise_params):
    a = noise_params["phi_plus"]
    b = noise_params["psi_plus"]
    c = noise_params["phi_minus"]
    d = noise_params["psi_minus"]

    rho_pair = (a * np.outer(PHI_PLUS, PHI_PLUS.conj()) +
                b * np.outer(PSI_PLUS, PSI_PLUS.conj()) +
                c * np.outer(PHI_MINUS, PHI_MINUS.conj()) +
                d * np.outer(PSI_MINUS, PSI_MINUS.conj()))

    rho_full = rho_pair.copy()
    for _ in range(N - 1):
        rho_full = np.kron(rho_full, rho_pair)

    if N == 1:
        return rho_full

    total_qubits = 2 * N
    perm = _perm_natural_to_game(N)
    shape = [2] * (2 * total_qubits)
    rho_tensor = rho_full.reshape(shape)
    perm_full = perm + [p + total_qubits for p in perm]
    rho_tensor = np.transpose(rho_tensor, perm_full)
    dim = 2 ** total_qubits
    return rho_tensor.reshape(dim, dim)


def apply_single_qubit_gate(rho, gate_name, qubit, total_qubits):
    U = SINGLE_GATES[gate_name]
    op = np.eye(1, dtype=complex)
    for i in range(total_qubits):
        op = np.kron(op, U if i == qubit else I2)
    return op @ rho @ op.conj().T


def apply_two_qubit_gate(rho, gate_name, qubit1, qubit2, total_qubits):
    gate = TWO_QUBIT_GATES[gate_name]
    dim = 2 ** total_qubits
    full_op = np.zeros((dim, dim), dtype=complex)

    for col in range(dim):
        bits = [(col >> (total_qubits - 1 - q)) & 1 for q in range(total_qubits)]
        b1, b2 = bits[qubit1], bits[qubit2]
        gate_col = b1 * 2 + b2

        for gate_row in range(4):
            coeff = gate[gate_row, gate_col]
            if abs(coeff) < 1e-15:
                continue
            new_bits = bits.copy()
            new_bits[qubit1] = (gate_row >> 1) & 1
            new_bits[qubit2] = gate_row & 1
            row = 0
            for q in range(total_qubits):
                row = (row << 1) | new_bits[q]
            full_op[row, col] += coeff

    return full_op @ rho @ full_op.conj().T


def measure_qubit(rho, qubit, total_qubits):
    dim = 2 ** total_qubits
    results = []
    for outcome in [0, 1]:
        proj = np.zeros((dim, dim), dtype=complex)
        for i in range(dim):
            if (i >> (total_qubits - 1 - qubit)) & 1 == outcome:
                proj[i, i] = 1.0
        rho_post = proj @ rho @ proj
        prob = np.real(np.trace(rho_post))
        if prob > 1e-15:
            rho_post = rho_post / prob
        results.append((prob, rho_post))
    return results


def partial_trace(rho, keep_qubits, total_qubits):
    n = total_qubits
    keep = sorted(keep_qubits)
    trace_out = [q for q in range(n) if q not in keep]

    rho_tensor = rho.reshape([2] * (2 * n))
    row_labels = list(range(n))
    col_labels = list(range(n, 2 * n))
    for q in trace_out:
        col_labels[q] = row_labels[q]

    input_labels = row_labels + col_labels
    output_labels = [row_labels[q] for q in keep] + [col_labels[q] for q in keep]
    result = np.einsum(rho_tensor, input_labels, output_labels)

    k = len(keep)
    return result.reshape(2 ** k, 2 ** k)


def compute_fidelity(rho_2qubit):
    return float(np.real(PHI_PLUS.conj() @ rho_2qubit @ PHI_PLUS))


def validate_locc(circuit, N):
    alice = set(range(N))
    bob = set(range(N, 2 * N))
    for op in circuit.operations:
        if op[0] == "gate" and op[1] in TWO_QUBIT_GATES:
            q1, q2 = op[2][0], op[2][1]
            if not ((q1 in alice and q2 in alice) or (q1 in bob and q2 in bob)):
                return False
        elif op[0] == "if" and op[3] in TWO_QUBIT_GATES:
            q1, q2 = op[4][0], op[4][1]
            if not ((q1 in alice and q2 in alice) or (q1 in bob and q2 in bob)):
                return False
    return True


def run_distillation(circuit, N, noise_params):
    total_qubits = 2 * N
    rho = initialize_bell_pairs(N, noise_params)
    branches = [(1.0, rho, {})]

    for op in circuit.operations:
        new_branches = []
        if op[0] == "gate":
            _, gn, qubits = op
            for prob, rb, cb in branches:
                if len(qubits) == 1:
                    rb = apply_single_qubit_gate(rb, gn, qubits[0], total_qubits)
                else:
                    rb = apply_two_qubit_gate(rb, gn, qubits[0], qubits[1], total_qubits)
                new_branches.append((prob, rb, cb))

        elif op[0] == "measure":
            _, qubit, cbit = op
            for prob, rb, cb in branches:
                for outcome, (p, rp) in enumerate(measure_qubit(rb, qubit, total_qubits)):
                    if p > 1e-15:
                        nc = dict(cb)
                        nc[cbit] = outcome
                        new_branches.append((prob * p, rp, nc))

        elif op[0] == "if":
            _, cbit, value, gn, qubits = op
            for prob, rb, cb in branches:
                if cb.get(cbit) == value:
                    if len(qubits) == 1:
                        rb = apply_single_qubit_gate(rb, gn, qubits[0], total_qubits)
                    else:
                        rb = apply_two_qubit_gate(rb, gn, qubits[0], qubits[1], total_qubits)
                new_branches.append((prob, rb, cb))

        elif op[0] == "xor":
            _, target, a, b = op
            for prob, rb, cb in branches:
                nc = dict(cb)
                nc[target] = cb[a] ^ cb[b]
                new_branches.append((prob, rb, nc))

        elif op[0] == "or":
            _, target, a, b = op
            for prob, rb, cb in branches:
                nc = dict(cb)
                nc[target] = cb[a] | cb[b]
                new_branches.append((prob, rb, nc))

        branches = new_branches

    flag_bit = circuit.flag_bit
    success_prob = 0.0
    dim = 2 ** total_qubits
    rho_success = np.zeros((dim, dim), dtype=complex)

    for prob, rb, cb in branches:
        if cb.get(flag_bit) == 0:
            success_prob += prob
            rho_success += prob * rb

    if success_prob < 1e-15:
        return {"fidelity": 0.0, "success_probability": 0.0}

    rho_success /= success_prob
    rho_output = partial_trace(rho_success, [N - 1, N], total_qubits)
    fidelity = compute_fidelity(rho_output)

    return {"fidelity": float(fidelity), "success_probability": float(success_prob)}
