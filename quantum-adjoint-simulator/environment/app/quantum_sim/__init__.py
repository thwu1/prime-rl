"""
Quantum Circuit Simulator

Required modules and their public API:

gates:
    Constants: I2, X, Y, Z, H, S, T_gate, CNOT_matrix, SWAP_matrix
    Functions: Rx(theta), Ry(theta), Rz(theta) - rotation gate matrices
              dRx(theta), dRy(theta), dRz(theta) - derivatives of rotation gates

engine:
    Loads /app/quantum_sim/libqsim.so (compiled from kernel.c via `make build`)
    using ctypes. Uses the C kernel for single-qubit and single-control-single-target
    gate operations. Falls back to Python subspace iteration for multi-qubit gates.

    apply_gate(state, gate_matrix, targets, n_qubits) -> state
    apply_controlled_gate(state, gate_matrix, controls, targets, n_qubits) -> state

circuit:
    ParameterizedCircuit(n_qubits)
        .add_gate(gate_matrix, targets, controls=None)
        .add_rx(param_index, target, controls=None)
        .add_ry(param_index, target, controls=None)
        .add_rz(param_index, target, controls=None)
        .simulate(params=None, initial_state=None) -> ndarray
        .n_params -> int

differentiation:
    compute_gradients(circuit, observable, params) -> ndarray
"""
