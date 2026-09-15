"""Tests for the quantum circuit optimization pipeline.

Verifies:
1. Optimizer reduces gate count while preserving unitary (up to global phase)
2. QASM parser/writer correctly handles OpenQASM 2.0 format
3. Benchmark pipeline produces valid JSON report with correct results

"""

import sys
sys.path.insert(0, '/app')

import json
import os
import subprocess
import numpy as np
import pytest
from circuit import Circuit, Operation
from optimizer import CircuitOptimizer


def unitaries_equal(U1, U2, tol=1e-8):
    """Check if two unitaries are equal up to global phase."""
    product = U1.conj().T @ U2
    phase = product[0, 0]
    if abs(abs(phase) - 1) > tol:
        return False
    return np.allclose(product, phase * np.eye(product.shape[0]), atol=tol)


def assert_optimized(num_qubits, ops_data, max_gates, label=""):
    """Build circuit, optimize, verify unitary equivalence and gate count."""
    c = Circuit(num_qubits)
    for name, params, qubits in ops_data:
        c.add(name, params, qubits)

    original_U = c.unitary()
    original_count = c.gate_count()

    optimizer = CircuitOptimizer()
    optimized = optimizer.optimize(c)

    assert optimized.num_qubits == num_qubits, (
        f"{label}: num_qubits changed from {num_qubits} to {optimized.num_qubits}"
    )

    optimized_U = optimized.unitary()

    assert unitaries_equal(original_U, optimized_U), (
        f"{label}: Unitary not preserved after optimization. "
        f"Original {original_count} gates -> {optimized.gate_count()} gates."
    )

    assert optimized.gate_count() <= max_gates, (
        f"{label}: Gate count {optimized.gate_count()} exceeds target {max_gates}. "
        f"Original had {original_count} gates."
    )


# ============================================================
# Optimizer correctness tests
# ============================================================

def test_adjacent_inverse_cancel():
    """H-H, X-X, S-Sdg, CNOT-CNOT should all cancel."""
    assert_optimized(3, [
        ('H', [], [0]), ('H', [], [0]),
        ('X', [], [1]), ('X', [], [1]),
        ('S', [], [2]), ('Sdg', [], [2]),
        ('CNOT', [], [0, 1]), ('CNOT', [], [0, 1]),
    ], max_gates=0, label="adjacent_inverse")


def test_disjoint_qubit_commute():
    """Gates on disjoint qubits commute, enabling non-adjacent cancellation."""
    assert_optimized(4, [
        ('CNOT', [], [0, 1]),
        ('X', [], [2]),
        ('H', [], [3]),
        ('CNOT', [], [0, 1]),
        ('X', [], [2]),
        ('H', [], [3]),
    ], max_gates=0, label="disjoint_commute")


def test_cnot_z_control_commute():
    """Z on the control qubit commutes through CNOT, enabling cancellation."""
    assert_optimized(2, [
        ('CNOT', [], [0, 1]),
        ('Z', [], [0]),
        ('CNOT', [], [0, 1]),
    ], max_gates=1, label="cnot_z_control")


def test_cnot_x_target_commute():
    """X on the target qubit commutes through CNOT, enabling cancellation."""
    assert_optimized(2, [
        ('CNOT', [], [0, 1]),
        ('X', [], [1]),
        ('CNOT', [], [0, 1]),
    ], max_gates=1, label="cnot_x_target")


def test_multi_pass_optimize():
    """Requires multiple optimization passes to fully reduce."""
    assert_optimized(3, [
        ('H', [], [0]),
        ('CNOT', [], [0, 1]),
        ('T', [], [2]),
        ('CNOT', [], [0, 1]),
        ('H', [], [0]),
        ('Tdg', [], [2]),
        ('X', [], [1]),
        ('X', [], [1]),
    ], max_gates=0, label="multi_pass")


def test_rz_rotation_cancel():
    """Three Rz gates whose angles sum to zero should cancel to identity."""
    assert_optimized(1, [
        ('Rz', [0.3], [0]),
        ('Rz', [0.5], [0]),
        ('Rz', [-0.8], [0]),
    ], max_gates=0, label="rz_cancel")


def test_rz_rotation_merge():
    """Four Rz(pi/4) gates should merge to single Rz(pi)."""
    pi = np.pi
    assert_optimized(1, [
        ('Rz', [pi / 4], [0]),
        ('Rz', [pi / 4], [0]),
        ('Rz', [pi / 4], [0]),
        ('Rz', [pi / 4], [0]),
    ], max_gates=1, label="rz_merge")


def test_rz_commute_cancel():
    """Rz (diagonal) gates commute through CNOT on control, then merge to zero."""
    assert_optimized(2, [
        ('Rz', [0.5], [0]),
        ('CNOT', [], [0, 1]),
        ('Rz', [0.3], [0]),
        ('Rz', [-0.8], [0]),
        ('CNOT', [], [0, 1]),
    ], max_gates=0, label="rz_commute")


def test_cz_diagonal_commute():
    """Diagonal gates commute through CZ on either qubit."""
    assert_optimized(3, [
        ('CZ', [], [0, 1]),
        ('T', [], [0]),
        ('T', [], [1]),
        ('CZ', [], [0, 1]),
        ('Tdg', [], [0]),
        ('Tdg', [], [1]),
        ('H', [], [2]),
        ('H', [], [2]),
    ], max_gates=0, label="cz_diagonal")


def test_general_merge_t8_identity():
    """T^8 = I requires merging gates via matrix multiplication."""
    assert_optimized(1, [
        ('T', [], [0]), ('T', [], [0]), ('T', [], [0]), ('T', [], [0]),
        ('T', [], [0]), ('T', [], [0]), ('T', [], [0]), ('T', [], [0]),
    ], max_gates=0, label="t8_identity")


def test_unitary_preserved_nontrivial():
    """A circuit with no optimization opportunities must preserve unitary."""
    assert_optimized(3, [
        ('H', [], [0]),
        ('CNOT', [], [0, 1]),
        ('T', [], [1]),
        ('CNOT', [], [1, 2]),
        ('S', [], [2]),
    ], max_gates=5, label="no_opt_preserve")


def test_edge_empty_circuit():
    """Empty circuit should return empty circuit."""
    assert_optimized(2, [], max_gates=0, label="empty")


def test_edge_single_gate():
    """Single-gate circuit should be returned as-is."""
    assert_optimized(1, [
        ('H', [], [0]),
    ], max_gates=1, label="single_gate")


def test_swap_cancel():
    """SWAP applied twice is identity."""
    assert_optimized(2, [
        ('SWAP', [], [0, 1]),
        ('SWAP', [], [0, 1]),
    ], max_gates=0, label="swap_cancel")


def test_s_commute_cnot_control():
    """S (diagonal) commutes through CNOT on control qubit."""
    assert_optimized(2, [
        ('CNOT', [], [0, 1]),
        ('S', [], [0]),
        ('CNOT', [], [0, 1]),
        ('Sdg', [], [0]),
    ], max_gates=0, label="s_commute_cnot")


# ============================================================
# QASM parser/writer tests
# ============================================================

def test_qasm_parse_basic():
    """Parse a simple QASM circuit and verify correctness."""
    from qasm_io import parse_qasm

    qasm = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
h q[0];
cx q[0],q[1];
t q[1];
"""
    circuit = parse_qasm(qasm)
    assert circuit.num_qubits == 2
    assert circuit.gate_count() == 3
    assert circuit.operations[0].name == 'H'
    assert circuit.operations[0].qubits == [0]
    assert circuit.operations[1].name == 'CNOT'
    assert circuit.operations[1].qubits == [0, 1]
    assert circuit.operations[2].name == 'T'
    assert circuit.operations[2].qubits == [1]


def test_qasm_parse_parametric():
    """Parse parametric rotation gates from QASM."""
    from qasm_io import parse_qasm

    qasm = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[1];
rz(0.5) q[0];
rx(1.2) q[0];
ry(3.14159265358979) q[0];
"""
    circuit = parse_qasm(qasm)
    assert circuit.num_qubits == 1
    assert circuit.gate_count() == 3
    assert circuit.operations[0].name == 'Rz'
    assert abs(circuit.operations[0].params[0] - 0.5) < 1e-10
    assert circuit.operations[1].name == 'Rx'
    assert abs(circuit.operations[1].params[0] - 1.2) < 1e-10
    assert circuit.operations[2].name == 'Ry'
    assert abs(circuit.operations[2].params[0] - 3.14159265358979) < 1e-10


def test_qasm_roundtrip():
    """Parse QASM -> Circuit -> QASM -> Circuit preserves unitary."""
    from qasm_io import parse_qasm, write_qasm

    qasm_in = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[3];
h q[0];
cx q[0],q[1];
rz(0.7) q[2];
s q[1];
cz q[1],q[2];
"""
    c1 = parse_qasm(qasm_in)
    qasm_out = write_qasm(c1)
    c2 = parse_qasm(qasm_out)

    assert c1.num_qubits == c2.num_qubits
    assert c1.gate_count() == c2.gate_count()
    assert unitaries_equal(c1.unitary(), c2.unitary())


def test_qasm_parse_all_gates():
    """Parse all supported gate types from QASM."""
    from qasm_io import parse_qasm

    qasm = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
x q[0];
y q[0];
z q[0];
s q[0];
sdg q[0];
t q[0];
tdg q[0];
h q[0];
rx(0.1) q[0];
ry(0.2) q[0];
rz(0.3) q[0];
cx q[0],q[1];
cz q[0],q[1];
swap q[0],q[1];
"""
    circuit = parse_qasm(qasm)
    assert circuit.num_qubits == 2
    assert circuit.gate_count() == 14

    expected_names = ['X', 'Y', 'Z', 'S', 'Sdg', 'T', 'Tdg', 'H',
                      'Rx', 'Ry', 'Rz', 'CNOT', 'CZ', 'SWAP']
    for op, expected in zip(circuit.operations, expected_names):
        assert op.name == expected, f"Expected {expected}, got {op.name}"


# ============================================================
# Pipeline integration tests
# ============================================================

def test_pipeline_report_exists():
    """Running 'make benchmark' must produce a valid JSON report."""
    result = subprocess.run(
        ['make', 'benchmark'],
        cwd='/app',
        capture_output=True,
        text=True,
        timeout=120
    )
    assert result.returncode == 0, (
        f"make benchmark failed.\nstdout: {result.stdout[-500:]}\nstderr: {result.stderr[-500:]}"
    )

    report_path = '/app/results/report.json'
    assert os.path.exists(report_path), "report.json not produced"

    with open(report_path) as f:
        report = json.load(f)

    assert isinstance(report, list), "Report must be a JSON array"
    assert len(report) >= 5, f"Report has {len(report)} entries, expected >= 5"

    required_keys = {'file', 'original_gates', 'optimized_gates', 'equivalent'}
    for entry in report:
        assert required_keys.issubset(entry.keys()), (
            f"Entry missing keys: {required_keys - set(entry.keys())}"
        )
        assert entry['equivalent'] is True, (
            f"Optimizer broke unitary equivalence for {entry['file']}"
        )
        assert isinstance(entry['original_gates'], int)
        assert isinstance(entry['optimized_gates'], int)
        assert entry['optimized_gates'] <= entry['original_gates']


def test_pipeline_benchmark_targets():
    """Specific benchmark circuits must meet gate reduction targets."""
    report_path = '/app/results/report.json'
    if not os.path.exists(report_path):
        result = subprocess.run(
            ['make', 'benchmark'],
            cwd='/app',
            capture_output=True,
            text=True,
            timeout=120
        )
        assert result.returncode == 0, f"make benchmark failed: {result.stderr[-500:]}"

    with open(report_path) as f:
        report = json.load(f)

    targets = {
        'adjacent_cancel.qasm': 0,
        'commute_reduce.qasm': 1,
        'rotation_merge.qasm': 0,
        'multi_pass.qasm': 0,
        'diagonal_fusion.qasm': 0,
    }

    by_file = {e['file']: e for e in report}

    for fname, max_gates in targets.items():
        assert fname in by_file, f"Missing benchmark result for {fname}"
        entry = by_file[fname]
        assert entry['optimized_gates'] <= max_gates, (
            f"{fname}: optimized to {entry['optimized_gates']} gates, target <= {max_gates}"
        )
        assert entry['equivalent'] is True, (
            f"{fname}: unitary equivalence broken"
        )
