
"""
Main compilation pipeline: reads QPU spec, compiles input circuit, applies
rotation folding, writes compiled circuit and metrics.
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, '/app')

from bqskit import compile, Circuit
from bqskit.compiler.machine import MachineModel
from bqskit.ir.gates import CZGate, RZGate, SqrtXGate

from rotation_pass import fold_rotations


def load_qpu_spec(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def build_model(spec: dict) -> MachineModel:
    gate_map = {
        'cz': CZGate(),
        'rz': RZGate(),
        'sx': SqrtXGate(),
    }
    gate_set = {gate_map[g] for g in spec['native_gates']}
    coupling = [tuple(e) for e in spec['coupling_edges']]
    return MachineModel(
        num_qudits=spec['num_qubits'],
        coupling_graph=coupling,
        gate_set=gate_set,
    )


def check_native(circuit: Circuit) -> bool:
    for op in circuit:
        if not isinstance(op.gate, (CZGate, RZGate, SqrtXGate)):
            return False
    return True


def check_coupling(circuit: Circuit, edges: list[list[int]]) -> bool:
    allowed = set()
    for e in edges:
        allowed.add((e[0], e[1]))
        allowed.add((e[1], e[0]))
    for op in circuit:
        if op.gate.num_qudits >= 2:
            loc = tuple(op.location)
            if (loc[0], loc[1]) not in allowed:
                return False
    return True


def main() -> None:
    spec = load_qpu_spec('/app/qpu_spec.json')
    model = build_model(spec)

    # Load input
    circuit = Circuit.from_file('/app/input.qasm')
    input_gate_count = circuit.num_operations

    # Pre-compilation rotation folding
    fold_rotations(circuit)

    # Compile to target architecture
    compiled = compile(
        circuit,
        model=model,
        optimization_level=1,
        max_synthesis_size=3,
        synthesis_epsilon=1e-8,
    )

    # Post-compilation rotation folding
    fold_rotations(compiled)

    # Save compiled circuit
    compiled.save('/app/compiled.qasm')

    # Compute metrics
    two_q_count = sum(
        1 for op in compiled if op.gate.num_qudits >= 2
    )

    metrics = {
        'input_gate_count': input_gate_count,
        'output_gate_count': compiled.num_operations,
        'output_depth': compiled.depth,
        'two_qubit_gate_count': two_q_count,
        'native_gates_only': check_native(compiled),
        'coupling_respected': check_coupling(compiled, spec['coupling_edges']),
    }

    with open('/app/metrics.json', 'w') as f:
        json.dump(metrics, f, indent=2)

    print(f"Compilation complete. Metrics: {json.dumps(metrics, indent=2)}")


if __name__ == '__main__':
    main()
