"""Compilation pipeline for trapped-ion hardware."""
import sys
import json
import numpy as np

sys.path.insert(0, '/app')

from bqskit import compile
from bqskit.ir.circuit import Circuit

from gates import MSGate, GPIGate, GPI2Gate
from model import get_trapped_ion_model
from native_check_pass import NativeGateCheckPass


def main():
    # Load input circuit
    circuit = Circuit.from_file('/app/input_circuit.qasm')
    original_unitary = np.array(circuit.get_unitary())
    original_gate_count = circuit.num_operations

    # Build hardware model and compile
    model = get_trapped_ion_model()
    compiled = compile(circuit, model=model, optimization_level=1)

    compiled_unitary = np.array(compiled.get_unitary())

    # Compute unitary distance
    dist = np.linalg.norm(original_unitary - compiled_unitary)

    # Build report
    report = {
        'original_gate_count': original_gate_count,
        'compiled_gate_count': compiled.num_operations,
        'unitary_distance': float(dist),
    }

    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print("Compilation complete.")


if __name__ == '__main__':
    main()
