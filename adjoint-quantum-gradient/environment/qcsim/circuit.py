"""
Quantum circuit construction.

Records a sequence of gate operations that can be executed by the
simulation engine and differentiated.

"""
from qcsim.gates import (
    X_GATE,
    Y_GATE,
    Z_GATE,
    H_GATE,
    S_GATE,
    T_GATE,
    rx_gate,
    ry_gate,
    rz_gate,
    drx_gate,
    dry_gate,
    drz_gate,
)


class Circuit:
    """Records a sequence of quantum gate operations."""

    def __init__(self, n_qubits):
        self.n_qubits = n_qubits
        self.operations = []
        self.n_params = 0

    # ---- Fixed single-qubit gates ----

    def h(self, qubit):
        self.operations.append(
            {"type": "fixed", "matrix": H_GATE, "targets": (qubit,)}
        )

    def x(self, qubit):
        self.operations.append(
            {"type": "fixed", "matrix": X_GATE, "targets": (qubit,)}
        )

    def y(self, qubit):
        self.operations.append(
            {"type": "fixed", "matrix": Y_GATE, "targets": (qubit,)}
        )

    def z(self, qubit):
        self.operations.append(
            {"type": "fixed", "matrix": Z_GATE, "targets": (qubit,)}
        )

    def s(self, qubit):
        self.operations.append(
            {"type": "fixed", "matrix": S_GATE, "targets": (qubit,)}
        )

    def t(self, qubit):
        self.operations.append(
            {"type": "fixed", "matrix": T_GATE, "targets": (qubit,)}
        )

    # ---- Controlled gates ----

    def cnot(self, control, target):
        self.operations.append(
            {
                "type": "controlled",
                "matrix": X_GATE,
                "controls": (control,),
                "targets": (target,),
            }
        )

    def cz(self, control, target):
        self.operations.append(
            {
                "type": "controlled",
                "matrix": Z_GATE,
                "controls": (control,),
                "targets": (target,),
            }
        )

    # ---- Parameterized gates ----

    def rx(self, param_idx, qubit):
        self.operations.append(
            {
                "type": "parameterized",
                "gate_fn": rx_gate,
                "deriv_fn": drx_gate,
                "param_idx": param_idx,
                "targets": (qubit,),
            }
        )
        self.n_params = max(self.n_params, param_idx + 1)

    def ry(self, param_idx, qubit):
        self.operations.append(
            {
                "type": "parameterized",
                "gate_fn": ry_gate,
                "deriv_fn": dry_gate,
                "param_idx": param_idx,
                "targets": (qubit,),
            }
        )
        self.n_params = max(self.n_params, param_idx + 1)

    def rz(self, param_idx, qubit):
        self.operations.append(
            {
                "type": "parameterized",
                "gate_fn": rz_gate,
                "deriv_fn": drz_gate,
                "param_idx": param_idx,
                "targets": (qubit,),
            }
        )
        self.n_params = max(self.n_params, param_idx + 1)
