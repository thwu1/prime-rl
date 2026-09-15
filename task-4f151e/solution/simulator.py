#!/usr/bin/env python3
"""

Quantum Circuit Simulator — solves all 5 problems from the task spec.
Uses numpy/scipy for linear algebra; no quantum computing libraries.
"""

import json
import numpy as np
from scipy.linalg import expm


# ===================== Gate matrices =====================

I2 = np.eye(2, dtype=complex)
PAULI_X = np.array([[0, 1], [1, 0]], dtype=complex)
PAULI_Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
PAULI_Z = np.array([[1, 0], [0, -1]], dtype=complex)
H_GATE = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
PAULIS = {"I": I2, "X": PAULI_X, "Y": PAULI_Y, "Z": PAULI_Z}


def Ry(theta):
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[c, -s], [s, c]], dtype=complex)


def Rz(theta):
    return np.array(
        [[np.exp(-1j * theta / 2), 0], [0, np.exp(1j * theta / 2)]], dtype=complex
    )


# ===================== State-vector simulator =====================

def apply_single_qubit_gate(state, gate, qubit):
    """Apply a 2x2 gate to a specific qubit in the state vector.

    Convention: index = sum(q_k * 2^k), qubit 0 is LSB.
    Iterates over pairs of indices that differ only in the target qubit bit.
    """
    N = len(state)
    new_state = np.zeros(N, dtype=complex)
    step = 1 << qubit
    for i in range(N):
        if (i >> qubit) & 1 == 0:
            j = i | step  # j = i with qubit bit set to 1
            new_state[i] = gate[0, 0] * state[i] + gate[0, 1] * state[j]
            new_state[j] = gate[1, 0] * state[i] + gate[1, 1] * state[j]
    return new_state


def apply_cnot(state, control, target):
    """Apply CNOT: flip target when control is |1>."""
    N = len(state)
    new_state = np.zeros(N, dtype=complex)
    for i in range(N):
        if (i >> control) & 1:
            j = i ^ (1 << target)
            new_state[j] = state[i]
        else:
            new_state[i] = state[i]
    return new_state


def apply_cz(state, q1, q2):
    """Apply CZ: phase -1 when both qubits are |1>."""
    new_state = state.copy()
    for i in range(len(state)):
        if ((i >> q1) & 1) and ((i >> q2) & 1):
            new_state[i] = -state[i]
    return new_state


def simulate_circuit(gates, n_qubits, initial_state=None):
    """Simulate a circuit starting from |0...0> (or given initial state)."""
    dim = 2 ** n_qubits
    if initial_state is not None:
        state = initial_state.copy()
    else:
        state = np.zeros(dim, dtype=complex)
        state[0] = 1.0

    for g in gates:
        gtype = g["type"]
        if gtype == "H":
            state = apply_single_qubit_gate(state, H_GATE, g["qubit"])
        elif gtype == "Ry":
            state = apply_single_qubit_gate(state, Ry(g["angle"]), g["qubit"])
        elif gtype == "Rz":
            state = apply_single_qubit_gate(state, Rz(g["angle"]), g["qubit"])
        elif gtype == "CNOT":
            state = apply_cnot(state, g["control"], g["target"])
        elif gtype == "CZ":
            state = apply_cz(state, g["qubits"][0], g["qubits"][1])
        else:
            raise ValueError(f"Unknown gate type: {gtype}")
    return state


def state_to_pairs(state):
    """Convert complex state vector to list of [real, imag] pairs."""
    return [[float(z.real), float(z.imag)] for z in state]


# ===================== Problem 1: Circuit Simulation =====================

def solve_problem1(spec):
    p = spec["problem1"]
    state = simulate_circuit(p["gates"], p["num_qubits"])
    return {"state_vector": state_to_pairs(state)}


# ===================== Problem 2: QFT =====================

def apply_qft(state, n_qubits):
    """Apply the Quantum Fourier Transform via the DFT matrix.

    QFT|j> = (1/sqrt(N)) sum_k exp(2*pi*i*j*k/N) |k>
    """
    N = 2 ** n_qubits
    omega = np.exp(2j * np.pi / N)
    # Build QFT matrix: F[k, j] = omega^(j*k) / sqrt(N)
    indices = np.arange(N)
    F = np.array([[omega ** (j * k) for j in range(N)] for k in range(N)]) / np.sqrt(N)
    return F @ state


def solve_problem2(spec):
    p = spec["problem2"]
    outputs = []
    for inp in p["inputs"]:
        n = inp["num_qubits"]
        N = 2 ** n
        # Build initial computational basis state
        j = sum(inp["state"][k] * (2 ** k) for k in range(n))
        state = np.zeros(N, dtype=complex)
        state[j] = 1.0
        # Apply QFT
        result = apply_qft(state, n)
        outputs.append(state_to_pairs(result))
    return {"outputs": outputs}


# ===================== Problem 3: Entanglement Entropy =====================

def partial_trace(state_vec, n_qubits, keep_qubits):
    """Compute reduced density matrix rho_A = tr_B(|psi><psi|).

    Uses tensor reshape. After reshaping the state into a (2,)*n tensor,
    axis k corresponds to qubit (n-1-k) due to C-order memory layout.
    """
    psi = state_vec.reshape([2] * n_qubits)

    # Map qubit index -> tensor axis: qubit q -> axis (n-1-q)
    keep_axes = sorted([n_qubits - 1 - q for q in keep_qubits])
    trace_axes = sorted(
        [n_qubits - 1 - q for q in range(n_qubits) if q not in keep_qubits]
    )

    psi = np.transpose(psi, keep_axes + trace_axes)

    n_keep = len(keep_qubits)
    n_trace = n_qubits - n_keep
    psi = psi.reshape(2 ** n_keep, 2 ** n_trace)

    return psi @ psi.conj().T


def von_neumann_entropy(rho):
    """S = -tr(rho * ln(rho)), natural log. Zero eigenvalues are ignored."""
    eigenvalues = np.linalg.eigvalsh(rho)
    eigenvalues = eigenvalues[eigenvalues > 1e-15]
    return float(-np.sum(eigenvalues * np.log(eigenvalues)))


def solve_problem3(spec):
    p = spec["problem3"]
    entropies = []
    for circ in p["circuits"]:
        n = circ["num_qubits"]
        state = simulate_circuit(circ["gates"], n)
        rho_A = partial_trace(state, n, circ["partition_A"])
        S = von_neumann_entropy(rho_A)
        entropies.append(S)
    return {"entropies": entropies}


# ===================== Problem 4: Grover's Search =====================

def solve_problem4(spec):
    p = spec["problem4"]
    n = p["num_qubits"]
    N = 2 ** n
    target_idx = sum(p["target"][k] * (2 ** k) for k in range(n))

    # Optimal number of iterations
    theta = np.arcsin(1 / np.sqrt(N))
    k_opt = int(np.floor(np.pi / (4 * theta)))

    # Initial state: uniform superposition
    state = np.ones(N, dtype=complex) / np.sqrt(N)

    for _ in range(k_opt):
        # Oracle: flip phase of target state
        state[target_idx] = -state[target_idx]

        # Diffusion: 2|s><s| - I
        mean = np.mean(state)
        state = 2 * mean - state

    probability = float(np.abs(state[target_idx]) ** 2)
    return {"iterations": k_opt, "probability": probability}


# ===================== Problem 5: Hamiltonian Analysis =====================

def pauli_string_matrix(pauli_str, n_qubits):
    """Build full 2^n x 2^n matrix from a Pauli string.

    Character k acts on qubit k. Kronecker product: P_{n-1} x ... x P_0.
    """
    ops = [PAULIS[c] for c in pauli_str]
    result = ops[0]
    for k in range(1, n_qubits):
        result = np.kron(ops[k], result)
    return result


def build_hamiltonian(terms, n_qubits):
    """Construct Hamiltonian matrix from list of Pauli terms."""
    dim = 2 ** n_qubits
    H = np.zeros((dim, dim), dtype=complex)
    for term in terms:
        H += term["coeff"] * pauli_string_matrix(term["pauli"], n_qubits)
    return H


def solve_problem5(spec):
    p = spec["problem5"]
    n = p["num_qubits"]

    # Build Hamiltonian
    H = build_hamiltonian(p["hamiltonian"], n)

    # Ground state energy
    eigenvalues = np.linalg.eigvalsh(H)
    ground_energy = float(eigenvalues[0])

    # Time evolution
    te = p["time_evolution"]
    init_state = simulate_circuit(te["initial_state_prep"], n)
    t = te["time"]
    U = expm(-1j * H * t)
    evolved = U @ init_state

    # Observable expectation value
    obs = pauli_string_matrix(te["observable"], n)
    evolved_expectation = float(np.real(evolved.conj() @ obs @ evolved))

    return {"ground_energy": ground_energy, "evolved_expectation": evolved_expectation}


# ===================== Main =====================

def main():
    with open("/app/problem_spec.json") as f:
        spec = json.load(f)

    results = {
        "problem1": solve_problem1(spec),
        "problem2": solve_problem2(spec),
        "problem3": solve_problem3(spec),
        "problem4": solve_problem4(spec),
        "problem5": solve_problem5(spec),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
