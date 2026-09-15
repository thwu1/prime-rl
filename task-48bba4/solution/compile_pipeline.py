#!/usr/bin/env python3

"""
Corrected quantum circuit compilation pipeline.

Fixes from the buggy /app/pipeline.py:
1. GATE_NAME_MAP: 'sx' mapped to 'sx' instead of 'h' (Hadamard != sqrt-X)
2. build_coupling_map: returns the constructed coupling map instead of None
"""

import json
import os
import numpy as np
from itertools import permutations

from qiskit import QuantumCircuit, transpile, qasm2
from qiskit.quantum_info import Operator
from qiskit.circuit.library import UnitaryGate

# Corrected gate mapping: 'sx' -> 'sx' (NOT 'h')
GATE_NAME_MAP = {
    'cx': 'cx',
    'u3': 'u3',
    'cz': 'cz',
    'rz': 'rz',
    'sx': 'sx',
}


def load_target_unitary(path):
    with open(path) as f:
        data = json.load(f)
    return np.array(data['real']) + 1j * np.array(data['imag'])


def get_basis_gates(spec):
    return [GATE_NAME_MAP[g] for g in spec['native_gate_set']]


def build_coupling_map(spec):
    """Build coupling map — FIXED: actually returns the coupling map."""
    raw_map = spec.get('coupling_map', [])
    if len(raw_map) == 0:
        return None
    return [[e[0], e[1]] for e in raw_map]


def _build_perm_matrix(perm, n_qubits):
    dim = 2 ** n_qubits
    P = np.zeros((dim, dim))
    for i in range(dim):
        j = 0
        for k in range(n_qubits):
            if i & (1 << k):
                j |= (1 << perm[k])
        P[j, i] = 1.0
    return P


def hs_distance_min_perm(u_ref, u_test, n_qubits):
    """Minimum HS distance over all qubit permutations."""
    dim = 2 ** n_qubits
    best_dist = 1.0
    for perm in permutations(range(n_qubits)):
        P = _build_perm_matrix(perm, n_qubits)
        u_corrected = P.T @ u_test
        val = abs(np.trace(u_ref.conj().T @ u_corrected)) / dim
        dist = 1.0 - val
        if dist < best_dist:
            best_dist = dist
    return best_dist


def count_two_qubit_gates(circuit):
    return sum(1 for inst in circuit.data if len(inst.qubits) == 2)


def main():
    print("Loading inputs...")
    circuit = QuantumCircuit.from_qasm_file('/app/circuit.qasm')
    original_u = Operator(circuit).data

    target_u = load_target_unitary('/app/target_unitary.json')

    with open('/app/hardware_specs.json') as f:
        hardware = json.load(f)

    os.makedirs('/app/results', exist_ok=True)
    metrics = {}

    for target_key in ['target_a', 'target_b']:
        spec = hardware[target_key]
        print(f"\nCompiling for {spec['name']} ({target_key})...")

        basis_gates = get_basis_gates(spec)
        coupling_map = build_coupling_map(spec)

        print(f"  Basis gates: {basis_gates}")
        print(f"  Coupling map: {coupling_map}")

        # Transpile 5-qubit circuit with topology constraints
        compiled = transpile(
            circuit,
            basis_gates=basis_gates,
            coupling_map=coupling_map,
            initial_layout=list(range(circuit.num_qubits)),
            optimization_level=2,
            seed_transpiler=42,
        )

        with open(f'/app/results/{target_key}_circuit.qasm', 'w') as f:
            f.write(qasm2.dumps(compiled))

        compiled_u = Operator(compiled).data
        dist = hs_distance_min_perm(original_u, compiled_u, 5)
        n2q = count_two_qubit_gates(compiled)

        print(f"  {target_key}_circuit: {n2q} 2Q gates, HS dist = {dist:.6f}")
        metrics[f'{target_key}_circuit'] = {
            'num_two_qubit_gates': n2q,
            'fidelity_distance': float(dist),
        }

        # Synthesize 2-qubit unitary
        synth_qc = QuantumCircuit(2)
        synth_qc.append(UnitaryGate(target_u), [0, 1])

        synth_compiled = transpile(
            synth_qc,
            basis_gates=basis_gates,
            optimization_level=2,
            seed_transpiler=42,
        )

        with open(f'/app/results/{target_key}_synth.qasm', 'w') as f:
            f.write(qasm2.dumps(synth_compiled))

        synth_u = Operator(synth_compiled).data
        synth_dist = hs_distance_min_perm(target_u, synth_u, 2)
        synth_n2q = count_two_qubit_gates(synth_compiled)

        print(f"  {target_key}_synth: {synth_n2q} 2Q gates, HS dist = {synth_dist:.6f}")
        metrics[f'{target_key}_synth'] = {
            'num_two_qubit_gates': synth_n2q,
            'fidelity_distance': float(synth_dist),
        }

    with open('/app/results/metrics.json', 'w') as f:
        json.dump(metrics, f, indent=2)

    print("\nCompilation complete. Results saved to /app/results/")


if __name__ == '__main__':
    main()
