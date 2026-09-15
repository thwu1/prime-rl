#!/usr/bin/env python3
"""
Solution for the quantum circuit compilation pipeline task.
Uses BQSKit to synthesise 2-qubit unitaries across two gate sets and
compile a 4-qubit circuit to a linear-chain topology.
"""

import json
import os
import sys
from itertools import permutations

import numpy as np

# Make config importable
sys.path.insert(0, "/app")
from config import (
    UNITARIES,
    GATE_SETS,
    TOPOLOGY,
    HS_DISTANCE_THRESHOLD,
    MAX_TWO_QUBIT_GATES,
)

from bqskit import Circuit, MachineModel, compile as bqs_compile
from bqskit.ir.gates import CNOTGate, CZGate, U3Gate
from bqskit.qis import UnitaryMatrix

# ---------------------------------------------------------------------------
# Gate-set mapping
# ---------------------------------------------------------------------------

GATE_OBJ_MAP = {
    "cnot_u3": {CNOTGate(), U3Gate()},
    "cz_u3": {CZGate(), U3Gate()},
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def hs_distance(U, V):
    n = U.shape[0]
    return 1.0 - abs(np.trace(U.conj().T @ V)) / n


def min_hs_over_perms(compiled_U, target_U, n_qubits):
    n = 2 ** n_qubits

    def perm_matrix(perm):
        P = np.zeros((n, n), dtype=complex)
        for s in range(n):
            bits = [(s >> (n_qubits - 1 - i)) & 1 for i in range(n_qubits)]
            nb = [bits[perm[i]] for i in range(n_qubits)]
            ns = sum(b << (n_qubits - 1 - i) for i, b in enumerate(nb))
            P[ns, s] = 1.0
        return P

    pmats = [perm_matrix(p) for p in permutations(range(n_qubits))]
    best = float("inf")
    for P in pmats:
        for Q in pmats:
            d = hs_distance(compiled_U, P @ target_U @ Q)
            best = min(best, d)
            if best < 1e-12:
                return best
    return best


# ---------------------------------------------------------------------------
# Part 1: Unitary synthesis
# ---------------------------------------------------------------------------

os.makedirs("/app/output", exist_ok=True)
results = {"unitary_synthesis": [], "circuit_compilation": {}}

print("=== Part 1: Unitary Synthesis ===")
for name, target_arr in UNITARIES.items():
    for gs_name in GATE_SETS:
        gs = GATE_OBJ_MAP[gs_name]
        model = MachineModel(2, gate_set=gs)
        target = UnitaryMatrix(target_arr)

        circuit = bqs_compile(target, model=model, optimization_level=2)

        # Distance
        computed_u = circuit.get_unitary()
        dist = float(computed_u.get_distance_from(target))

        # Two-qubit gate count
        two_q = sum(1 for op in circuit if op.num_qudits == 2)

        # Save
        qasm_file = f"output/{name}_{gs_name}.qasm"
        circuit.save(f"/app/{qasm_file}")

        results["unitary_synthesis"].append({
            "target_name": name,
            "gate_set": gs_name,
            "two_qubit_gate_count": two_q,
            "total_gate_count": circuit.num_operations,
            "hs_distance": dist,
            "qasm_file": qasm_file,
        })

        print(f"  {name}/{gs_name}: {two_q} 2-q gates, HS={dist:.2e}")

# ---------------------------------------------------------------------------
# Part 2: 4-qubit circuit compilation
# ---------------------------------------------------------------------------

print("\n=== Part 2: Circuit Compilation ===")
original = Circuit.from_file("/app/input_circuit.qasm")
original_cnots = sum(1 for op in original if op.num_qudits == 2)

model = MachineModel(
    4,
    coupling_graph=TOPOLOGY,
    gate_set={CNOTGate(), U3Gate()},
)

compiled = bqs_compile(original, model=model, optimization_level=2)

# Topology check
valid_edges = set()
for e in TOPOLOGY:
    valid_edges.add(tuple(e))
    valid_edges.add((e[1], e[0]))

topo_valid = True
for op in compiled:
    if op.num_qudits == 2:
        if tuple(op.location) not in valid_edges:
            topo_valid = False
            break

compiled_cnots = sum(1 for op in compiled if op.num_qudits == 2)

# Unitary distance (accounting for permutation from routing)
compiled_u = compiled.get_unitary().numpy
original_u = original.get_unitary().numpy

dist = hs_distance(compiled_u, original_u)
if dist > 1e-4:
    dist = min_hs_over_perms(compiled_u, original_u, 4)

compiled.save("/app/output/compiled_circuit.qasm")

results["circuit_compilation"] = {
    "cnot_count_original": original_cnots,
    "cnot_count_compiled": compiled_cnots,
    "hs_distance": float(dist),
    "topology_valid": topo_valid,
    "qasm_file": "output/compiled_circuit.qasm",
}

print(f"  Original 2-q gates: {original_cnots}")
print(f"  Compiled 2-q gates: {compiled_cnots}")
print(f"  HS distance: {dist:.2e}")
print(f"  Topology valid: {topo_valid}")

# ---------------------------------------------------------------------------
# Write results
# ---------------------------------------------------------------------------

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print("\nPipeline completed. Results written to /app/results.json")
