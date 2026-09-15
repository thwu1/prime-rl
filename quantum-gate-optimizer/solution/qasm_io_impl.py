"""OpenQASM 2.0 parser and writer implementation.

"""

import re
import sys
sys.path.insert(0, '/app')
from circuit import Circuit


# Mapping from QASM gate names to internal gate names
QASM_TO_INTERNAL = {
    'h': 'H', 'x': 'X', 'y': 'Y', 'z': 'Z',
    's': 'S', 'sdg': 'Sdg', 't': 'T', 'tdg': 'Tdg',
    'rx': 'Rx', 'ry': 'Ry', 'rz': 'Rz',
    'cx': 'CNOT', 'cz': 'CZ', 'swap': 'SWAP',
    'id': 'I',
}

INTERNAL_TO_QASM = {v: k for k, v in QASM_TO_INTERNAL.items()}


def parse_qasm(qasm_str: str) -> Circuit:
    """Parse an OpenQASM 2.0 string into a Circuit."""
    lines = qasm_str.strip().split('\n')
    num_qubits = None
    ops = []

    for line in lines:
        line = line.strip()
        if not line or line.startswith('//'):
            continue
        if line.startswith('OPENQASM') or line.startswith('include'):
            continue

        # qreg declaration
        qreg_match = re.match(r'qreg\s+(\w+)\[(\d+)\];', line)
        if qreg_match:
            num_qubits = int(qreg_match.group(2))
            continue

        # Skip creg declarations
        if line.startswith('creg'):
            continue

        # Gate instruction: gate_name(params) qubit_list;
        gate_match = re.match(r'(\w+)(?:\(([^)]*)\))?\s+(.+);', line)
        if gate_match:
            qasm_name = gate_match.group(1).lower()
            params_str = gate_match.group(2)
            qubits_str = gate_match.group(3)

            if qasm_name not in QASM_TO_INTERNAL:
                continue

            internal_name = QASM_TO_INTERNAL[qasm_name]

            # Parse parameters
            params = []
            if params_str:
                params = [float(p.strip()) for p in params_str.split(',')]

            # Parse qubits: q[0],q[1] -> [0, 1]
            qubit_matches = re.findall(r'\w+\[(\d+)\]', qubits_str)
            qubits = [int(q) for q in qubit_matches]

            ops.append((internal_name, params, qubits))

    if num_qubits is None:
        raise ValueError("No qreg declaration found in QASM")

    circuit = Circuit(num_qubits)
    for name, params, qubits in ops:
        circuit.add(name, params, qubits)

    return circuit


def write_qasm(circuit: Circuit) -> str:
    """Write a Circuit to OpenQASM 2.0 format."""
    lines = [
        'OPENQASM 2.0;',
        'include "qelib1.inc";',
        f'qreg q[{circuit.num_qubits}];',
    ]

    for op in circuit.operations:
        qasm_name = INTERNAL_TO_QASM.get(op.name, op.name.lower())
        qubit_str = ','.join(f'q[{q}]' for q in op.qubits)

        if op.params:
            params_str = ','.join(str(p) for p in op.params)
            lines.append(f'{qasm_name}({params_str}) {qubit_str};')
        else:
            lines.append(f'{qasm_name} {qubit_str};')

    return '\n'.join(lines) + '\n'
