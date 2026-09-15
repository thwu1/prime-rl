#!/usr/bin/env python3
"""Benchmark pipeline implementation.

"""

import json
import glob
import os
import sys
import numpy as np

sys.path.insert(0, '/app')

from circuit import Circuit
from optimizer import CircuitOptimizer
from qasm_io import parse_qasm, write_qasm


def unitaries_equal(U1, U2, tol=1e-8):
    """Check if two unitaries are equal up to global phase."""
    product = U1.conj().T @ U2
    phase = product[0, 0]
    if abs(abs(phase) - 1) > tol:
        return False
    return np.allclose(product, phase * np.eye(product.shape[0]), atol=tol)


def main():
    benchmark_dir = '/app/benchmarks'
    results_dir = '/app/results'
    os.makedirs(results_dir, exist_ok=True)

    optimizer = CircuitOptimizer()
    report = []

    for qasm_path in sorted(glob.glob(os.path.join(benchmark_dir, '*.qasm'))):
        fname = os.path.basename(qasm_path)

        with open(qasm_path) as f:
            qasm_str = f.read()

        circuit = parse_qasm(qasm_str)
        original_U = circuit.unitary()
        original_gates = circuit.gate_count()

        optimized = optimizer.optimize(circuit)
        optimized_U = optimized.unitary()
        optimized_gates = optimized.gate_count()

        equiv = bool(unitaries_equal(original_U, optimized_U))

        # Write optimized QASM
        opt_qasm = write_qasm(optimized)
        opt_path = os.path.join(results_dir, f'optimized_{fname}')
        with open(opt_path, 'w') as f:
            f.write(opt_qasm)

        report.append({
            'file': fname,
            'original_gates': original_gates,
            'optimized_gates': optimized_gates,
            'equivalent': equiv,
        })

        print(f"{fname}: {original_gates} -> {optimized_gates} gates, equivalent={equiv}")

    report_path = os.path.join(results_dir, 'report.json')
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\nReport written to {report_path}")


if __name__ == '__main__':
    main()
