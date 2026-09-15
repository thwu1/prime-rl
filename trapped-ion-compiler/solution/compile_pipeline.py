"""Compilation pipeline targeting trapped-ion hardware via BQSKit."""
import sys
import os
import json
import numpy as np

sys.path.insert(0, '/app')
os.environ['PYTHONPATH'] = '/app:' + os.environ.get('PYTHONPATH', '')

from bqskit import compile
from bqskit.ir.circuit import Circuit
from bqskit.ir.gates.parameterized.rz import RZGate

from gates import MSGate, GPIGate, GPI2Gate
from model import get_trapped_ion_model
from native_check_pass import NativeGateCheckPass


def main():
    # Load input circuit
    circuit = Circuit.from_file('/app/input_circuit.qasm')
    original_unitary = np.array(circuit.get_unitary())
    original_gate_count = circuit.num_operations

    # Get trapped-ion machine model
    model = get_trapped_ion_model()

    # Compile the circuit targeting the trapped-ion model
    compiled = compile(
        circuit,
        model=model,
        optimization_level=1,
        max_synthesis_size=2,
        synthesis_epsilon=1e-8,
        seed=42,
    )

    # Compute compiled unitary
    compiled_unitary = np.array(compiled.get_unitary())

    # Save compiled unitary
    np.save('/app/compiled_unitary.npy', compiled_unitary)

    # Compute global-phase-invariant unitary distance
    # Using process infidelity: 1 - |Tr(U_orig^dag @ U_compiled)| / d
    d = original_unitary.shape[0]
    overlap = np.abs(np.trace(original_unitary.conj().T @ compiled_unitary))
    unitary_distance = 1.0 - overlap / d

    # Verify native gates using NativeGateCheckPass
    import asyncio
    native_types = {MSGate, GPIGate, GPI2Gate, RZGate}
    check_pass = NativeGateCheckPass(native_types)
    data = {}
    asyncio.run(check_pass.run(compiled, data))

    # Build report
    report = {
        'original_gate_count': original_gate_count,
        'compiled_gate_count': compiled.num_operations,
        'unitary_distance': float(unitary_distance),
        'all_native': data['all_native'],
        'gate_counts': data['gate_counts'],
    }

    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Original gates: {original_gate_count}")
    print(f"Compiled gates: {compiled.num_operations}")
    print(f"Unitary distance: {unitary_distance:.2e}")
    print(f"All native: {data['all_native']}")
    print(f"Gate counts: {data['gate_counts']}")


if __name__ == '__main__':
    main()
