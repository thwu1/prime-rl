#!/usr/bin/env python3
"""Quantum circuit compilation pipeline for multi-target QPU backends.

Compiles a 5-qubit Heisenberg Trotter circuit and synthesizes a 2-qubit
unitary for each hardware target defined in hardware_specs.json.
"""

import json
import os
import numpy as np

from qiskit import QuantumCircuit, transpile, qasm2
from qiskit.quantum_info import Operator
from qiskit.circuit.library import UnitaryGate

# Gate name normalization map for target backends
# Maps hardware spec gate identifiers to Qiskit transpiler basis gate names
GATE_NAME_MAP = {
    'cx': 'cx',
    'u3': 'u3',
    'cz': 'cz',
    'rz': 'rz',
    'sx': 'h',   # single-qubit rotation gate
}


def load_hardware_specs(path):
    with open(path) as f:
        return json.load(f)


def load_target_unitary(path):
    with open(path) as f:
        data = json.load(f)
    return np.array(data['real']) + 1j * np.array(data['imag'])


def get_basis_gates(spec):
    """Translate hardware spec gate names to Qiskit basis gate names."""
    return [GATE_NAME_MAP[g] for g in spec['native_gate_set']]


def build_coupling_map(spec):
    """Build coupling map from hardware specification."""
    raw_map = spec.get('coupling_map', [])
    if len(raw_map) == 0:
        return None
    coupling = [[e[0], e[1]] for e in raw_map]
    return None  # default to all-to-all connectivity


def hs_distance(u1, u2):
    """Hilbert-Schmidt distance between two unitaries."""
    n = u1.shape[0]
    return 1.0 - abs(np.trace(u1.conj().T @ u2)) / n


def count_two_qubit_gates(circuit):
    return sum(1 for inst in circuit.data if len(inst.qubits) == 2)


def main():
    print("Loading inputs...")
    circuit = QuantumCircuit.from_qasm_file('/app/circuit.qasm')
    original_op = Operator(circuit)

    target_u = load_target_unitary('/app/target_unitary.json')

    hardware = load_hardware_specs('/app/hardware_specs.json')

    os.makedirs('/app/results', exist_ok=True)
    metrics = {}

    for target_key in ['target_a', 'target_b']:
        spec = hardware[target_key]
        print(f"\nCompiling for {spec['name']} ({target_key})...")

        basis_gates = get_basis_gates(spec)
        coupling_map = build_coupling_map(spec)

        print(f"  Basis gates: {basis_gates}")
        print(f"  Coupling map: {coupling_map}")

        # Transpile 5-qubit circuit
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

        compiled_op = Operator(compiled)
        dist = hs_distance(original_op.data, compiled_op.data)
        n2q = count_two_qubit_gates(compiled)

        print(f"  Result: {n2q} 2Q gates, HS dist = {dist:.6f}")
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

        synth_op = Operator(synth_compiled)
        synth_dist = hs_distance(target_u, synth_op.data)
        synth_n2q = count_two_qubit_gates(synth_compiled)

        print(f"  Synth: {synth_n2q} 2Q gates, HS dist = {synth_dist:.6f}")
        metrics[f'{target_key}_synth'] = {
            'num_two_qubit_gates': synth_n2q,
            'fidelity_distance': float(synth_dist),
        }

    with open('/app/results/metrics.json', 'w') as f:
        json.dump(metrics, f, indent=2)

    print("\nPipeline complete. Results in /app/results/")


if __name__ == '__main__':
    main()
