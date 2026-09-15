#!/usr/bin/env python3
"""

Solution for the quantum program analysis pipeline.
Parses Quil circuit files and GraphViz DOT topology, simulates quantum circuits,
computes spectral/entropic/dynamical properties, and performs topology analysis.
"""

import json
import os
import re
import numpy as np
from scipy.linalg import expm


# ==================== Gate Matrices ====================

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


# ==================== Quil Parser ====================


def parse_quil(filepath):
    """Parse a Quil program file into a list of gate instruction dicts."""
    gates = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Parameterized single-qubit gate: RY(1.047) 2
            param_match = re.match(r"(\w+)\(([^)]+)\)\s+(\d+)$", line)
            if param_match:
                gate_name = param_match.group(1)
                angle = float(param_match.group(2))
                qubit = int(param_match.group(3))
                if gate_name == "RY":
                    gates.append({"type": "Ry", "angle": angle, "qubit": qubit})
                elif gate_name == "RZ":
                    gates.append({"type": "Rz", "angle": angle, "qubit": qubit})
                else:
                    raise ValueError(f"Unknown parameterized gate: {gate_name}")
                continue

            parts = line.split()
            gate_name = parts[0]

            if gate_name in ("H", "X", "Y", "Z"):
                gates.append({"type": gate_name, "qubit": int(parts[1])})
            elif gate_name == "CNOT":
                gates.append(
                    {
                        "type": "CNOT",
                        "control": int(parts[1]),
                        "target": int(parts[2]),
                    }
                )
            elif gate_name == "CZ":
                gates.append(
                    {"type": "CZ", "qubits": [int(parts[1]), int(parts[2])]}
                )
            else:
                raise ValueError(f"Unknown Quil instruction: {gate_name}")

    return gates


# ==================== DOT File Handling ====================


def parse_dot_edges(filepath):
    """Parse a GraphViz DOT file to extract undirected edges as sorted tuples."""
    edges = set()
    with open(filepath) as f:
        content = f.read()
    for match in re.finditer(r'"?(\d+)"?\s*--\s*"?(\d+)"?', content):
        a, b = int(match.group(1)), int(match.group(2))
        edges.add((min(a, b), max(a, b)))
    return edges


def generate_dot(edges, filepath, num_qubits):
    """Generate a GraphViz DOT file for an interaction graph."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        f.write("graph interaction {\n")
        for q in range(num_qubits):
            f.write(f"    {q};\n")
        for a, b in sorted(edges):
            f.write(f"    {a} -- {b};\n")
        f.write("}\n")


# ==================== State-Vector Simulator ====================


def apply_single_qubit_gate(state, gate, qubit):
    """Apply a 2x2 gate to a specific qubit using index-based amplitude manipulation."""
    N = len(state)
    new_state = np.zeros(N, dtype=complex)
    step = 1 << qubit
    for i in range(N):
        if (i >> qubit) & 1 == 0:
            j = i | step
            new_state[i] = gate[0, 0] * state[i] + gate[0, 1] * state[j]
            new_state[j] = gate[1, 0] * state[i] + gate[1, 1] * state[j]
    return new_state


def apply_cnot(state, control, target):
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
    new_state = state.copy()
    for i in range(len(state)):
        if ((i >> q1) & 1) and ((i >> q2) & 1):
            new_state[i] = -state[i]
    return new_state


def simulate_circuit(gates, n_qubits, initial_state=None):
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
        elif gtype == "X":
            state = apply_single_qubit_gate(state, PAULI_X, g["qubit"])
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
    return [[float(z.real), float(z.imag)] for z in state]


# ==================== Pauli String Matrix ====================


def pauli_string_matrix(pauli_str, n_qubits):
    """Build full 2^n x 2^n matrix from a Pauli string."""
    ops = [PAULIS[c] for c in pauli_str]
    result = ops[0]
    for k in range(1, n_qubits):
        result = np.kron(ops[k], result)
    return result


# ==================== Task Solvers ====================


def solve_simulate(task):
    gates = parse_quil(os.path.join("/app", task["circuit_file"]))
    state = simulate_circuit(gates, task["num_qubits"])
    return {"state_vector": state_to_pairs(state)}


def solve_spectral_transform(task):
    outputs = []
    for circ_spec in task["circuits"]:
        n = circ_spec["num_qubits"]
        N = 2 ** n
        gates = parse_quil(os.path.join("/app", circ_spec["file"]))
        state = simulate_circuit(gates, n)

        # Build and apply DFT unitary matrix
        omega = np.exp(2j * np.pi / N)
        F = np.array(
            [[omega ** (j * k) for j in range(N)] for k in range(N)]
        ) / np.sqrt(N)
        result = F @ state
        outputs.append(state_to_pairs(result))
    return {"outputs": outputs}


def solve_subsystem_entropy(task):
    entropies = []
    for circ_spec in task["circuits"]:
        n = circ_spec["num_qubits"]
        gates = parse_quil(os.path.join("/app", circ_spec["file"]))
        state = simulate_circuit(gates, n)

        keep = circ_spec["subsystem_A"]

        # Reduced density matrix via tensor reshape
        psi = state.reshape([2] * n)
        keep_axes = sorted([n - 1 - q for q in keep])
        trace_axes = sorted([n - 1 - q for q in range(n) if q not in keep])
        psi = np.transpose(psi, keep_axes + trace_axes)
        n_keep = len(keep)
        n_trace = n - n_keep
        psi = psi.reshape(2 ** n_keep, 2 ** n_trace)
        rho_A = psi @ psi.conj().T

        # Entropy from eigenvalues
        eigenvalues = np.linalg.eigvalsh(rho_A)
        eigenvalues = eigenvalues[eigenvalues > 1e-15]
        S = float(-np.sum(eigenvalues * np.log(eigenvalues)))
        entropies.append(S)
    return {"entropies": entropies}


def solve_hamiltonian_analysis(task):
    n = task["num_qubits"]
    dim = 2 ** n

    # Build Hamiltonian matrix
    H = np.zeros((dim, dim), dtype=complex)
    for term in task["hamiltonian"]:
        H += term["coeff"] * pauli_string_matrix(term["pauli"], n)

    # Minimum eigenvalue
    eigenvalues = np.linalg.eigvalsh(H)
    min_eigenvalue = float(eigenvalues[0])

    # Time evolution
    gates = parse_quil(os.path.join("/app", task["initial_state_circuit"]))
    init_state = simulate_circuit(gates, n)
    t = task["evolution_time"]
    U = expm(-1j * H * t)
    evolved = U @ init_state

    # Observable expectation value
    obs = pauli_string_matrix(task["observable_pauli"], n)
    expectation = float(np.real(evolved.conj() @ obs @ evolved))

    return {"min_eigenvalue": min_eigenvalue, "evolved_expectation": expectation}


def solve_topology_analysis(task):
    # Extract interaction edges from circuit
    gates = parse_quil(os.path.join("/app", task["circuit_file"]))
    interaction_edges = set()
    for g in gates:
        gtype = g["type"]
        if gtype == "CNOT":
            a, b = g["control"], g["target"]
            interaction_edges.add((min(a, b), max(a, b)))
        elif gtype == "CZ":
            a, b = g["qubits"]
            interaction_edges.add((min(a, b), max(a, b)))

    # Parse hardware topology from DOT file
    topology_edges = parse_dot_edges(os.path.join("/app", task["topology_file"]))

    # Compatibility analysis
    compatible = interaction_edges & topology_edges
    directly_executable = interaction_edges <= topology_edges

    # Generate interaction graph DOT file
    dot_path = "/app/graphs/interaction_circuit_a.dot"
    generate_dot(interaction_edges, dot_path, task["num_qubits"])

    return {
        "interaction_edges": len(interaction_edges),
        "topology_edges": len(topology_edges),
        "compatible_edges": len(compatible),
        "directly_executable": directly_executable,
        "interaction_graph_file": dot_path,
    }


# ==================== Main ====================


TASK_SOLVERS = {
    "simulate": solve_simulate,
    "spectral_transform": solve_spectral_transform,
    "subsystem_entropy": solve_subsystem_entropy,
    "hamiltonian_analysis": solve_hamiltonian_analysis,
    "topology_analysis": solve_topology_analysis,
}


def main():
    with open("/app/spec.json") as f:
        spec = json.load(f)

    results = {}
    for task in spec["tasks"]:
        task_id = task["id"]
        output_key = task["output"]["key"]
        solver = TASK_SOLVERS[task_id]
        results[output_key] = solver(task)
        print(f"Solved task: {task_id}")

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("All results written to /app/results.json")


if __name__ == "__main__":
    main()
