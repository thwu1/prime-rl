"""Parameterized quantum circuit."""
import numpy as np
from .gates import Rx, Ry, Rz, dRx, dRy, dRz
from .engine import apply_gate, apply_controlled_gate


class ParameterizedCircuit:
    """A quantum circuit composed of fixed and parameterized gates."""

    def __init__(self, n_qubits):
        self.n_qubits = n_qubits
        self.operations = []
        self.n_params = 0

    def add_gate(self, gate_matrix, targets, controls=None):
        """Append a fixed (non-parameterized) gate."""
        if isinstance(targets, int):
            targets = (targets,)
        self.operations.append({
            'type': 'fixed',
            'gate_matrix': np.array(gate_matrix, dtype=complex),
            'targets': tuple(targets),
            'controls': tuple(controls) if controls is not None else None,
        })

    def _add_rotation(self, gate_func, deriv_func, param_index, target, controls):
        self.n_params = max(self.n_params, param_index + 1)
        self.operations.append({
            'type': 'parameterized',
            'gate_func': gate_func,
            'gate_deriv': deriv_func,
            'param_index': param_index,
            'targets': (target,),
            'controls': tuple(controls) if controls is not None else None,
        })

    def add_rx(self, param_index, target, controls=None):
        self._add_rotation(Rx, dRx, param_index, target, controls)

    def add_ry(self, param_index, target, controls=None):
        self._add_rotation(Ry, dRy, param_index, target, controls)

    def add_rz(self, param_index, target, controls=None):
        self._add_rotation(Rz, dRz, param_index, target, controls)

    def simulate(self, params=None, initial_state=None):
        """Run the circuit and return the final state vector."""
        n = self.n_qubits
        if initial_state is not None:
            state = np.array(initial_state, dtype=complex).copy()
        else:
            state = np.zeros(1 << n, dtype=complex)
            state[0] = 1.0

        for op in self.operations:
            if op['type'] == 'fixed':
                matrix = op['gate_matrix']
            else:
                matrix = op['gate_func'](params[op['param_index']])

            if op['controls'] is not None:
                apply_controlled_gate(state, matrix, op['controls'], op['targets'], n)
            else:
                apply_gate(state, matrix, op['targets'], n)

        return state
