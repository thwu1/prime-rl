"""
Target quantum unitaries for circuit synthesis.

Each entry in TARGETS is a unitary matrix (numpy array) that must be
synthesized into a quantum circuit. MAX_CNOTS gives the maximum allowed
CNOT gate count for each compiled circuit.
"""


import numpy as np

# ---------- 2-qubit targets ----------

# 2-qubit Quantum Fourier Transform
_w = np.exp(2j * np.pi / 4)  # fourth root of unity = i
_qft2 = (1.0 / 2.0) * np.array([
    [1,    1,      1,      1     ],
    [1,    _w,     _w**2,  _w**3 ],
    [1,    _w**2,  _w**4,  _w**6 ],
    [1,    _w**3,  _w**6,  _w**9 ],
], dtype=complex)

# Square-root of SWAP gate
_sqrt_swap = np.array([
    [1.0,       0.0,       0.0,       0.0],
    [0.0,  0.5+0.5j,  0.5-0.5j,       0.0],
    [0.0,  0.5-0.5j,  0.5+0.5j,       0.0],
    [0.0,       0.0,       0.0,       1.0],
], dtype=complex)

# ---------- 3-qubit targets ----------

# Toffoli (CCX) gate: flips qubit 2 when qubits 0 and 1 are both |1>
_toffoli = np.eye(8, dtype=complex)
_toffoli[6, 6] = 0.0
_toffoli[7, 7] = 0.0
_toffoli[6, 7] = 1.0
_toffoli[7, 6] = 1.0

# Fredkin (CSWAP) gate: swaps qubits 1 and 2 when qubit 0 is |1>
_fredkin = np.eye(8, dtype=complex)
_fredkin[5, 5] = 0.0
_fredkin[6, 6] = 0.0
_fredkin[5, 6] = 1.0
_fredkin[6, 5] = 1.0

# ---------- Exported dicts ----------

TARGETS = {
    "qft2":      _qft2,
    "sqrt_swap": _sqrt_swap,
    "toffoli":   _toffoli,
    "fredkin":   _fredkin,
}

MAX_CNOTS = {
    "qft2":      5,
    "sqrt_swap": 5,
    "toffoli":   16,
    "fredkin":   16,
}
