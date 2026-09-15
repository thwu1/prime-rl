#!/usr/bin/env python3
"""LOCC Constraint Validator for OpenQASM 3.0 Distillation Circuits.

Validates that a quantum circuit respects LOCC (Local Operations and Classical
Communication) constraints for entanglement distillation between Alice and Bob.

Usage:
    python3 /app/validate_locc.py <qasm_file> <num_bell_pairs>

LOCC Rules:
    - Two-qubit gates may only operate within Alice's qubits (indices 0..N-1)
      or within Bob's qubits (indices N..2N-1)
    - Single-qubit gates, measurements, and classical operations: unrestricted
    - Classical feedforward (conditioning gates on measurement outcomes): allowed

Exit codes:
    0 - PASS (circuit is LOCC-compliant)
    1 - FAIL (LOCC violation or parse error)
    2 - Usage error

"""

import sys
import re
import os


def extract_multi_qubit_ops(qasm_content):
    """Extract all multi-qubit gate operations from QASM3 content.

    Returns list of (gate_name, [qubit_indices]) tuples for gates
    acting on 2 or more qubits.
    """
    ops = []
    for line in qasm_content.split('\n'):
        line = line.strip()
        if not line or line.startswith('//'):
            continue
        skip_prefixes = (
            'OPENQASM', 'include', 'qubit', 'bit', 'int', 'uint',
            'bool', 'float', 'const', 'let', 'input', 'output',
            '{', '}', 'barrier', 'reset', 'delay', 'pragma',
        )
        if any(line.startswith(p) for p in skip_prefixes):
            continue
        if 'measure' in line:
            continue
        # Strip conditional prefix (classical feedforward is LOCC-allowed)
        line = re.sub(r'^if\s*\([^)]*\)\s*', '', line)
        if not line:
            continue
        # Parse gate instruction: name(params)? qubit_operands;
        m = re.match(r'(\w+)(?:\([^)]*\))?\s+(.*?)\s*;', line)
        if m:
            gate_name = m.group(1).lower()
            operands_str = m.group(2)
            qubit_indices = [int(x) for x in re.findall(r'q\[(\d+)\]', operands_str)]
            if len(qubit_indices) >= 2:
                ops.append((gate_name, qubit_indices))
    return ops


def validate_locc(qasm_file, num_bell_pairs):
    """Validate LOCC constraints on an OpenQASM 3.0 circuit.

    Args:
        qasm_file: Path to the QASM3 file.
        num_bell_pairs: Number of Bell pairs N. Circuit must have 2N qubits.

    Returns:
        True if the circuit passes LOCC validation, False otherwise.
    """
    n = num_bell_pairs
    total_qubits = 2 * n
    alice = set(range(n))
    bob = set(range(n, total_qubits))

    with open(qasm_file) as f:
        content = f.read()

    # Verify qubit declaration
    qm = re.search(r'qubit\[(\d+)\]', content)
    if not qm:
        print(f"FAIL: No qubit declaration found in {qasm_file}")
        return False
    declared = int(qm.group(1))
    if declared != total_qubits:
        print(f"FAIL: Expected {total_qubits} qubits (2*N for N={n}), "
              f"found qubit[{declared}] in {qasm_file}")
        return False

    # Check all multi-qubit gates
    multi_ops = extract_multi_qubit_ops(content)
    violations = []
    for gate_name, qubit_indices in multi_ops:
        qs = set(qubit_indices)
        in_alice = qs.issubset(alice)
        in_bob = qs.issubset(bob)
        if not (in_alice or in_bob):
            side_info = []
            for qi in qubit_indices:
                side = "Alice" if qi in alice else "Bob"
                side_info.append(f"q[{qi}]({side})")
            violations.append(
                f"  {gate_name} on {', '.join(side_info)} -- "
                f"crosses Alice/Bob boundary"
            )

    if violations:
        print(f"FAIL: {len(violations)} LOCC violation(s) in "
              f"{os.path.basename(qasm_file)}:")
        for v in violations:
            print(v)
        print(f"\n  Alice qubits: {sorted(alice)}")
        print(f"  Bob qubits:   {sorted(bob)}")
        return False

    n_ops = len(multi_ops)
    print(f"PASS: {os.path.basename(qasm_file)} -- "
          f"{n_ops} multi-qubit gate(s), all LOCC-compliant "
          f"(N={n}, Alice=q[0..{n-1}], Bob=q[{n}..{total_qubits-1}])")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)

    qasm_path = sys.argv[1]
    try:
        n_pairs = int(sys.argv[2])
    except ValueError:
        print(f"ERROR: num_bell_pairs must be a positive integer, "
              f"got '{sys.argv[2]}'")
        sys.exit(2)

    if n_pairs < 1:
        print(f"ERROR: num_bell_pairs must be >= 1, got {n_pairs}")
        sys.exit(2)

    if not os.path.isfile(qasm_path):
        print(f"ERROR: File not found: {qasm_path}")
        sys.exit(1)

    ok = validate_locc(qasm_path, n_pairs)
    sys.exit(0 if ok else 1)
