"""
Density-matrix simulator for entanglement distillation with LOCC constraints.
"""

import numpy as np
from itertools import product as iterproduct

# ── Bell states in computational basis {|00>, |01>, |10>, |11>} ───────

PHI_PLUS = np.array([1, 0, 0, 1], dtype=complex) / np.sqrt(2)
PHI_MINUS = np.array([1, 0, 0, -1], dtype=complex) / np.sqrt(2)
PSI_PLUS = np.array([0, 1, 1, 0], dtype=complex) / np.sqrt(2)
PSI_MINUS = np.array([0, 1, -1, 0], dtype=complex) / np.sqrt(2)

# ── Standard single-qubit gates ──────────────────────────────────────

H_GATE = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
X_GATE = np.array([[0, 1], [1, 0]], dtype=complex)
Z_GATE = np.array([[1, 0], [0, -1]], dtype=complex)
I2 = np.eye(2, dtype=complex)


def _bell_diagonal_pair(px, pz):
    """Single-pair Bell-diagonal density matrix."""
    a = (1 - px) * (1 - pz)
    b = px * (1 - pz)
    c = (1 - px) * pz
    d = px * pz
    return (a * np.outer(PHI_PLUS, PHI_PLUS.conj())
            + b * np.outer(PSI_PLUS, PSI_PLUS.conj())
            + c * np.outer(PHI_MINUS, PHI_MINUS.conj())
            + d * np.outer(PSI_MINUS, PSI_MINUS.conj()))


def initialize_pairs(n, px, pz):
    """Return 2^(2N) x 2^(2N) density matrix for N noisy Bell pairs.

    Qubit ordering: pair k -> qubit k (Alice) and qubit 2N-1-k (Bob).
    """
    pair_rho = _bell_diagonal_pair(px, pz)

    # Tensor product of N identical pairs (in pair order)
    rho = pair_rho.copy()
    for _ in range(n - 1):
        rho = np.kron(rho, pair_rho)

    if n == 1:
        return rho

    nq = 2 * n

    # Build permutation: perm[physical_pos] = tensor_pos
    # Tensor order: [pair0_A, pair0_B, pair1_A, pair1_B, ...]
    # Physical order: [q0=pair0_A, q1=pair1_A, ..., qN=pairN-1_B, ..., q2N-1=pair0_B]
    perm = [0] * nq
    for k in range(n):
        perm[k] = 2 * k              # pair k Alice -> physical k
        perm[2 * n - 1 - k] = 2 * k + 1  # pair k Bob -> physical 2N-1-k

    # Reshape to tensor, permute axes (ket + bra), reshape back
    shape = [2] * (2 * nq)
    rho_t = rho.reshape(shape)
    full_perm = perm + [p + nq for p in perm]
    rho_t = np.transpose(rho_t, full_perm)
    return rho_t.reshape(2 ** nq, 2 ** nq)


# ── Gate construction ─────────────────────────────────────────────────

def _single_qubit_unitary(gate_2x2, target, n_qubits):
    """Full 2^n x 2^n unitary for a single-qubit gate."""
    ops = [I2] * n_qubits
    ops[target] = gate_2x2
    result = ops[0]
    for op in ops[1:]:
        result = np.kron(result, op)
    return result


def _cnot_unitary(control, target, n_qubits):
    """Full unitary for CNOT(control, target)."""
    dim = 2 ** n_qubits
    U = np.zeros((dim, dim), dtype=complex)
    for i in range(dim):
        bits = [(i >> (n_qubits - 1 - q)) & 1 for q in range(n_qubits)]
        out = bits.copy()
        if bits[control] == 1:
            out[target] ^= 1
        j = sum(b << (n_qubits - 1 - q) for q, b in enumerate(out))
        U[j, i] = 1.0
    return U


def apply_gate(rho, gate_name, qubits, n_qubits):
    """Apply a named gate to the density matrix (rho -> U rho U^dag)."""
    name = gate_name.lower()
    if name == "h":
        U = _single_qubit_unitary(H_GATE, qubits[0], n_qubits)
    elif name == "x":
        U = _single_qubit_unitary(X_GATE, qubits[0], n_qubits)
    elif name == "z":
        U = _single_qubit_unitary(Z_GATE, qubits[0], n_qubits)
    elif name in ("cx", "cnot"):
        U = _cnot_unitary(qubits[0], qubits[1], n_qubits)
    else:
        raise ValueError(f"Unknown gate: {gate_name}")
    return U @ rho @ U.conj().T


# ── Measurement and post-selection ────────────────────────────────────

def measure_and_postselect(rho, measured_qubits, flag_func, n_qubits):
    """Measure qubits, keep outcomes where flag_func(outcome_dict) is True.

    flag_func: dict{qubit: 0|1} -> bool
    Returns (rho_postselected, success_probability).
    """
    dim = 2 ** n_qubits
    n_meas = len(measured_qubits)
    rho_kept = np.zeros_like(rho)
    p_success = 0.0

    for outcomes in iterproduct([0, 1], repeat=n_meas):
        outcome_dict = dict(zip(measured_qubits, outcomes))

        # Diagonal projector
        proj = np.zeros(dim)
        for i in range(dim):
            ok = True
            for q, val in zip(measured_qubits, outcomes):
                if ((i >> (n_qubits - 1 - q)) & 1) != val:
                    ok = False
                    break
            if ok:
                proj[i] = 1.0

        rho_proj = rho * np.outer(proj, proj)
        p = np.real(np.trace(rho_proj))

        if p < 1e-15:
            continue

        if flag_func(outcome_dict):
            rho_kept += rho_proj
            p_success += p

    if p_success < 1e-15:
        return rho_kept, 0.0

    rho_kept /= p_success
    return rho_kept, p_success


# ── Partial trace and fidelity ────────────────────────────────────────

def _partial_trace(rho, keep_qubits, n_qubits):
    """Trace out everything except keep_qubits."""
    keep = sorted(keep_qubits)
    n_keep = len(keep)
    traced = [q for q in range(n_qubits) if q not in keep]
    n_tr = len(traced)
    dim_keep = 2 ** n_keep

    rho_red = np.zeros((dim_keep, dim_keep), dtype=complex)

    for i in range(dim_keep):
        bits_i = [(i >> (n_keep - 1 - k)) & 1 for k in range(n_keep)]
        for j in range(dim_keep):
            bits_j = [(j >> (n_keep - 1 - k)) & 1 for k in range(n_keep)]
            for t in range(2 ** n_tr):
                t_bits = [(t >> (n_tr - 1 - k)) & 1 for k in range(n_tr)]

                ket = [0] * n_qubits
                bra = [0] * n_qubits
                for k, q in enumerate(keep):
                    ket[q] = bits_i[k]
                    bra[q] = bits_j[k]
                for k, q in enumerate(traced):
                    ket[q] = t_bits[k]
                    bra[q] = t_bits[k]

                ki = sum(b << (n_qubits - 1 - q) for q, b in enumerate(ket))
                bi = sum(b << (n_qubits - 1 - q) for q, b in enumerate(bra))
                rho_red[i, j] += rho[ki, bi]

    return rho_red


def compute_fidelity(rho, qubit_a, qubit_b, n_qubits):
    """Fidelity of the reduced state on (qubit_a, qubit_b) w.r.t. |Phi+>."""
    rho_red = _partial_trace(rho, [qubit_a, qubit_b], n_qubits)
    return float(np.real(PHI_PLUS.conj() @ rho_red @ PHI_PLUS))


# ── LOCC constraint checking ─────────────────────────────────────────

def check_locc(gates, n):
    """Validate LOCC: two-qubit gates must stay within Alice or Bob side.

    gates: list of (gate_name, [qubit_indices])
    n: number of Bell pairs  (Alice: 0..n-1, Bob: n..2n-1)
    Returns (is_valid, reason_string).
    """
    alice = set(range(n))
    two_q = {"cx", "cnot", "cz", "swap"}

    for name, qubits in gates:
        if name.lower() in two_q and len(qubits) >= 2:
            q1, q2 = qubits[0], qubits[1]
            if (q1 in alice) != (q2 in alice):
                return False, (f"Gate {name}({q1},{q2}) crosses "
                               "Alice/Bob boundary")
    return True, "Valid LOCC circuit"
