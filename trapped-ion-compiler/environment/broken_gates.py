"""Native gate implementations for trapped-ion hardware."""
import numpy as np
from bqskit.ir.gate import Gate
from bqskit.qis.unitary.unitarymatrix import UnitaryMatrix
from bqskit.qis.unitary.unitary import RealVector


class MSGate(Gate):
    """Molmer-Sorensen entangling gate for trapped ions."""
    _num_qudits = 2
    _num_params = 1
    _radixes = (2, 2)
    _name = 'MSGate'

    def get_unitary(self, params: RealVector = []) -> UnitaryMatrix:
        self.check_parameters(params)
        theta = float(params[0])
        c = np.cos(theta)
        s = np.sin(theta)
        return UnitaryMatrix(np.array([
            [c, 0, 0, 1j * s],
            [0, c, 1j * s, 0],
            [0, 1j * s, c, 0],
            [1j * s, 0, 0, c],
        ], dtype=np.complex128))


class GPIGate(Gate):
    """Single-qubit GPI rotation gate."""
    _num_qudits = 1
    _num_params = 1
    _radixes = (2,)
    _name = 'GPIGate'

    def get_unitary(self, params: RealVector = []) -> UnitaryMatrix:
        self.check_parameters(params)
        phi = float(params[0])
        return UnitaryMatrix(np.array([
            [0, np.exp(1j * phi)],
            [np.exp(-1j * phi), 0],
        ], dtype=np.complex128))


class GPI2Gate(Gate):
    """Single-qubit GPI2 rotation gate."""
    _num_qudits = 1
    _num_params = 1
    _radixes = (2,)
    _name = 'GPI2Gate'

    def get_unitary(self, params: RealVector = []) -> UnitaryMatrix:
        self.check_parameters(params)
        phi = float(params[0])
        inv_sqrt2 = 1.0 / np.sqrt(2.0)
        return UnitaryMatrix(inv_sqrt2 * np.array([
            [1, -1j * np.exp(1j * phi)],
            [-1j * np.exp(-1j * phi), 1],
        ], dtype=np.complex128))
