"""
Verification tests for quantum circuit synthesis pipeline.
Checks unitary equivalence, gate set compliance, topology, and CNOT counts.
"""


import json
import sys
from itertools import permutations as iter_perms
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, "/app")
from unitaries import MAX_CNOTS, TARGETS

from bqskit import Circuit
from bqskit.ir.gates import CNOTGate, U3Gate
from bqskit.qis import UnitaryMatrix

OUTPUT_DIR = Path("/app/output")
HARDWARE_PATH = Path("/app/hardware.json")

TWO_QUBIT_NAMES = [n for n, u in TARGETS.items() if u.shape[0] == 4]
THREE_QUBIT_NAMES = [n for n, u in TARGETS.items() if u.shape[0] == 8]
ALL_NAMES = list(TARGETS.keys())


def _load_hardware():
    with open(HARDWARE_PATH) as f:
        return json.load(f)


def _build_perm_matrix(perm, n_qubits):
    """Build the 2^n x 2^n matrix for a qubit permutation."""
    dim = 2 ** n_qubits
    P = np.zeros((dim, dim), dtype=complex)
    for idx in range(dim):
        bits = [(idx >> (n_qubits - 1 - q)) & 1 for q in range(n_qubits)]
        new_bits = [bits[perm[q]] for q in range(n_qubits)]
        new_idx = sum(b << (n_qubits - 1 - q) for q, b in enumerate(new_bits))
        P[new_idx, idx] = 1.0
    return P


def _min_distance_over_permutations(compiled_u, target_np, n_qubits):
    """
    Compute the minimum Hilbert-Schmidt distance between a compiled
    circuit's unitary and the target, trying all qubit permutations.
    Topology mapping may relabel qubits, so we check every permutation.
    """
    best = float("inf")
    for perm in iter_perms(range(n_qubits)):
        P = _build_perm_matrix(perm, n_qubits)
        permuted_target = P @ target_np @ P.T
        try:
            d = float(compiled_u.get_distance_from(UnitaryMatrix(permuted_target)))
        except Exception:
            # Fallback: manual HS distance
            compiled_np = np.asarray(compiled_u)
            dim = compiled_np.shape[0]
            inner = np.abs(np.trace(permuted_target.conj().T @ compiled_np))
            d = 1.0 - inner / dim
        best = min(best, d)
    return best


# ─── File existence ──────────────────────────────────────────────

class TestOutputExists:
    def test_output_directory_exists(self):
        assert OUTPUT_DIR.exists(), "Output directory /app/output/ does not exist"

    def test_results_json_exists(self):
        assert (OUTPUT_DIR / "results.json").exists(), "results.json not found"

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_qasm_file_exists(self, name):
        qasm = OUTPUT_DIR / f"{name}.qasm"
        assert qasm.exists(), f"QASM file for '{name}' not found at {qasm}"


# ─── Unitary correctness ────────────────────────────────────────

class TestUnitaryCorrectness:
    """Verify each compiled circuit implements the target unitary."""

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_unitary_distance(self, name):
        circuit = Circuit.from_file(str(OUTPUT_DIR / f"{name}.qasm"))
        compiled_u = circuit.get_unitary()
        target_np = TARGETS[name]
        n_qubits = int(np.log2(target_np.shape[0]))

        dist = _min_distance_over_permutations(compiled_u, target_np, n_qubits)
        assert dist < 1e-3, (
            f"Circuit '{name}': min HS distance over permutations = {dist:.6e} "
            f"(threshold 1e-3)"
        )

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_circuit_qubit_count(self, name):
        circuit = Circuit.from_file(str(OUTPUT_DIR / f"{name}.qasm"))
        target_np = TARGETS[name]
        expected = int(np.log2(target_np.shape[0]))
        assert circuit.num_qudits == expected, (
            f"Circuit '{name}' has {circuit.num_qudits} qubits, expected {expected}"
        )


# ─── Gate set compliance ────────────────────────────────────────

class TestGateSet:
    ALLOWED_GATE_TYPES = {CNOTGate, U3Gate}

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_gate_set_compliance(self, name):
        circuit = Circuit.from_file(str(OUTPUT_DIR / f"{name}.qasm"))
        for op in circuit:
            gtype = type(op.gate)
            assert gtype in self.ALLOWED_GATE_TYPES, (
                f"Circuit '{name}' contains disallowed gate: {gtype.__name__}. "
                f"Only CNOTGate and U3Gate are permitted."
            )


# ─── Topology compliance (3-qubit circuits only) ────────────────

class TestTopology:

    @pytest.mark.parametrize("name", THREE_QUBIT_NAMES)
    def test_topology_compliance(self, name):
        hw = _load_hardware()
        coupling = hw["topology"]["coupling_graph"]
        allowed_edges = set()
        for e in coupling:
            allowed_edges.add((e[0], e[1]))
            allowed_edges.add((e[1], e[0]))

        circuit = Circuit.from_file(str(OUTPUT_DIR / f"{name}.qasm"))
        for op in circuit:
            if op.num_qudits == 2:
                loc = tuple(op.location)
                assert loc in allowed_edges, (
                    f"Circuit '{name}': two-qubit gate on qubits {loc} "
                    f"violates topology (allowed edges: {sorted(allowed_edges)})"
                )


# ─── CNOT count thresholds ──────────────────────────────────────

class TestCNOTCount:

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_cnot_within_threshold(self, name):
        circuit = Circuit.from_file(str(OUTPUT_DIR / f"{name}.qasm"))
        count = circuit.count(CNOTGate())
        limit = MAX_CNOTS[name]
        assert count <= limit, (
            f"Circuit '{name}' has {count} CNOTs, exceeding threshold of {limit}"
        )


# ─── Results JSON structure ─────────────────────────────────────

class TestResultsJSON:

    @pytest.fixture
    def results(self):
        with open(OUTPUT_DIR / "results.json") as f:
            return json.load(f)

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_entry_exists(self, name, results):
        assert name in results, f"results.json missing entry for '{name}'"

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_required_fields(self, name, results):
        entry = results[name]
        assert "cnot_count" in entry and isinstance(entry["cnot_count"], int), \
            f"'{name}': cnot_count must be an int"
        assert "distance" in entry and isinstance(entry["distance"], (int, float)), \
            f"'{name}': distance must be a number"
        assert "num_qubits" in entry and isinstance(entry["num_qubits"], int), \
            f"'{name}': num_qubits must be an int"

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_reported_distance_reasonable(self, name, results):
        d = results[name]["distance"]
        assert d < 1e-3, (
            f"'{name}': reported distance {d} exceeds 1e-3"
        )
