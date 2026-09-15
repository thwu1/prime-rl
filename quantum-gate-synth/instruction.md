Synthesize a quantum circuit that implements a given 3-qubit unitary matrix, targeting a QPU with restricted linear connectivity and a non-standard native gate set. Python 3 with numpy is available in the environment; scipy and BQSKit (Berkeley Quantum Synthesis Toolkit) can be installed via pip3.

`/app/target_unitary.py` defines the target 8×8 unitary matrix (import and call `get_target_unitary()`). `/app/hardware_spec.json` specifies the QPU: 3 qubits with linear coupling `{(0,1), (1,2)}` and native gate set `{xxplusyy, rz, sx}`.

The 2-qubit entangling gate XXPlusYY(θ, β) has the 4×4 unitary:

    [[1,           0,                            0,                            0],
     [0,           cos(θ/2),                     i·sin(θ/2)·exp(iβ),          0],
     [0,           i·sin(θ/2)·exp(-iβ),          cos(θ/2),                    0],
     [0,           0,                            0,                            1]]

This gate is not in BQSKit's standard gate library. RZ(θ) = diag(e^{-iθ/2}, e^{iθ/2}) and SX = ½[[1+i, 1-i],[1-i, 1+i]] follow standard definitions.

Write `/app/pipeline.py` and execute it to produce:

- `/app/result/circuit.json`: `{"num_qubits": 3, "gates": [{"name": "xxplusyy"|"rz"|"sx", "params": [float, ...], "qubits": [int, ...]}, ...]}`
- `/app/result/metrics.json`: `{"xxplusyy_count": int, "total_gates": int, "process_fidelity": float}`

Process fidelity is defined as |Tr(U_target† · U_circuit)|² / d² where d = 8.

Constraints:
- Process fidelity > 1 − 1e-6
- XXPlusYY gate count ≤ 25
- Only gates from {xxplusyy, rz, sx} in the output circuit
- Two-qubit gates only on adjacent qubit pairs per coupling graph