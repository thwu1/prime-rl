#!/usr/bin/env python3
"""Quantum circuit simulator command-line interface."""
import sys
import json
import argparse
import numpy as np

sys.path.insert(0, '/app')

from quantum_sim.gates import H, X, Y, Z, S, T_gate, CNOT_matrix, SWAP_matrix
from quantum_sim.circuit import ParameterizedCircuit
from quantum_sim.differentiation import compute_gradients


FIXED_GATES = {
    "H": H, "X": X, "Y": Y, "Z": Z, "S": S, "T": T_gate,
    "CNOT": CNOT_matrix, "SWAP": SWAP_matrix,
}

ROTATION_GATES = {"Rx": "add_rx", "Ry": "add_ry", "Rz": "add_rz"}


def build_observable(n_qubits, qubit):
    """Build Z observable on specified qubit."""
    dim = 1 << n_qubits
    obs = np.zeros((dim, dim), dtype=complex)
    for i in range(dim):
        obs[i, i] = -1.0 if (i >> qubit) & 1 else 1.0
    return obs


def load_circuit(spec):
    """Build a ParameterizedCircuit from a JSON spec dict."""
    n = spec["n_qubits"]
    circ = ParameterizedCircuit(n)
    for op in spec["operations"]:
        gate_name = op["gate"]
        targets = tuple(op["targets"])
        controls = tuple(op["controls"]) if "controls" in op else None

        if gate_name in ROTATION_GATES:
            method = getattr(circ, ROTATION_GATES[gate_name])
            method(op["param_index"], targets[0], controls=controls)
        elif gate_name in FIXED_GATES:
            circ.add_gate(FIXED_GATES[gate_name], targets, controls=controls)
        else:
            raise ValueError(f"Unknown gate: {gate_name}")
    return circ


def main():
    parser = argparse.ArgumentParser(description="Quantum circuit simulator CLI")
    parser.add_argument("circuit_file", help="Path to JSON circuit definition")
    parser.add_argument("--gradients", action="store_true",
                        help="Compute parameter gradients")
    args = parser.parse_args()

    with open(args.circuit_file) as f:
        spec = json.load(f)

    circ = load_circuit(spec)
    params = np.array(spec.get("params", []), dtype=float)
    obs = build_observable(spec["n_qubits"], spec["observable_qubit"])

    state = circ.simulate(params=params if len(params) > 0 else None)
    ev = float(np.real(state.conj() @ obs @ state))

    result = {
        "name": spec["name"],
        "expectation_value": ev,
    }

    if args.gradients:
        if len(params) > 0:
            grads = compute_gradients(circ, obs, params)
            result["gradients"] = grads.tolist()
        else:
            result["gradients"] = []

    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
