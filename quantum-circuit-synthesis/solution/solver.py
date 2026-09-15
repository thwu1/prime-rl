#!/usr/bin/env python3
"""
Synthesize quantum circuits for each target unitary using BQSKit,
mapping 3-qubit circuits to the hardware topology.
"""


import json
import os
import sys
from itertools import permutations as iter_perms

import numpy as np

sys.path.insert(0, "/app")
from unitaries import MAX_CNOTS, TARGETS

from bqskit import MachineModel, compile
from bqskit.compiler import Compiler
from bqskit.ir.gates import CNOTGate, U3Gate
from bqskit.qis import UnitaryMatrix


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


def _min_distance(compiled_u, target_np, n_qubits):
    """Minimum HS distance over all qubit permutations (handles topology relabelling)."""
    best = float("inf")
    for perm in iter_perms(range(n_qubits)):
        P = _build_perm_matrix(perm, n_qubits)
        permuted = P @ target_np @ P.T
        d = float(compiled_u.get_distance_from(UnitaryMatrix(permuted)))
        best = min(best, d)
    return best

# Load hardware specification
with open("/app/hardware.json") as f:
    hardware = json.load(f)

gate_set = {CNOTGate(), U3Gate()}

# Build a topology-aware model for 3-qubit circuits
coupling_graph_3q = [tuple(e) for e in hardware["topology"]["coupling_graph"]]
model_3q = MachineModel(
    hardware["topology"]["num_qubits"],
    coupling_graph=coupling_graph_3q,
    gate_set=gate_set,
)

# Simple model (no topology) for 2-qubit circuits
model_2q = MachineModel(2, gate_set=gate_set)

os.makedirs("/app/output", exist_ok=True)
results = {}

# Use a cached Compiler to avoid per-call startup overhead
with Compiler() as compiler:
    for name, target_np in TARGETS.items():
        n_qubits = int(np.log2(target_np.shape[0]))
        target_u = UnitaryMatrix(target_np)

        if n_qubits <= 2:
            model = model_2q
        else:
            model = model_3q

        # Synthesize the unitary into a circuit for the target model.
        # optimization_level=2 gives good CNOT reduction without
        # excessive compile time.  max_synthesis_size must be >= n_qubits
        # so the synthesis pass can handle the full unitary in one block.
        compiled = compile(
            target_u,
            model=model,
            optimization_level=2,
            max_synthesis_size=n_qubits,
            compiler=compiler,
        )

        # Save QASM
        compiled.save(f"/app/output/{name}.qasm")

        # Compute metrics (permutation-aware for topology-mapped circuits)
        compiled_u = compiled.get_unitary()
        distance = _min_distance(compiled_u, target_np, n_qubits)
        cnot_count = compiled.count(CNOTGate())

        results[name] = {
            "cnot_count": cnot_count,
            "distance": distance,
            "num_qubits": n_qubits,
        }
        print(f"  {name}: {cnot_count} CNOTs, distance={distance:.2e}")

# Write summary
with open("/app/output/results.json", "w") as f:
    json.dump(results, f, indent=2)

print("All circuits compiled. Results at /app/output/results.json")
