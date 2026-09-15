"""
Configuration for the quantum circuit compilation pipeline task.
Defines target unitaries, gate sets, topology, and quality thresholds.
"""

import numpy as np

# ---- Target 2-qubit unitary matrices ----

UNITARIES = {
    # iSWAP gate: swaps |01> <-> |10> with phase factor i
    "iswap": np.array([
        [1, 0, 0, 0],
        [0, 0, 1j, 0],
        [0, 1j, 0, 0],
        [0, 0, 0, 1],
    ], dtype=complex),

    # Square-root of SWAP gate
    "sqrt_swap": np.array([
        [1, 0, 0, 0],
        [0, (1 + 1j) / 2, (1 - 1j) / 2, 0],
        [0, (1 - 1j) / 2, (1 + 1j) / 2, 0],
        [0, 0, 0, 1],
    ], dtype=complex),

    # Magic basis change (Bell basis transformation)
    "magic_basis": (1 / np.sqrt(2)) * np.array([
        [1, 0, 0, 1j],
        [0, 1j, 1, 0],
        [0, 1j, -1, 0],
        [1, 0, 0, -1j],
    ], dtype=complex),
}

# ---- Gate set specifications ----
# Each gate set is identified by a name. The pipeline must map these to
# actual quantum gate objects in the compilation framework used.
GATE_SETS = {
    "cnot_u3": ["CNOT", "U3"],       # IBM-like: CNOT + arbitrary single-qubit
    "cz_u3":   ["CZ", "U3"],         # CZ-based: CZ + arbitrary single-qubit
}

# ---- Hardware topology for 4-qubit circuit compilation ----
# Linear chain: 0 -- 1 -- 2 -- 3
TOPOLOGY = [(0, 1), (1, 2), (2, 3)]

# ---- Quality thresholds ----
HS_DISTANCE_THRESHOLD = 1e-5   # Max Hilbert-Schmidt distance for synthesis
MAX_TWO_QUBIT_GATES = 3        # Max two-qubit gates per 2-qubit unitary
