
"""CrossResonanceGate: parameterized two-qubit gate CR(theta) = exp(-i*theta/2 * Z x X)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from bqskit.ir.gate import Gate
from bqskit.qis.unitary.unitarymatrix import UnitaryMatrix
from bqskit.qis.unitary.unitary import RealVector
from bqskit.qis.unitary.differentiable import DifferentiableUnitary


class CrossResonanceGate(Gate, DifferentiableUnitary):
    """
    Parameterized cross-resonance gate based on the ZX interaction.

    CR(theta) = exp(-i * theta/2 * (Z tensor X))
              = cos(theta/2) * I_4  -  i * sin(theta/2) * (Z tensor X)

    The ZX tensor product is:
        Z x X = [[0, 1, 0, 0],
                  [1, 0, 0, 0],
                  [0, 0, 0,-1],
                  [0, 0,-1, 0]]
    """

    _num_qudits = 2
    _num_params = 1
    _radixes = (2, 2)
    _name = 'CrossResonanceGate'
    _qasm_name = 'cr'

    def get_unitary(self, params: RealVector = []) -> UnitaryMatrix:
        self.check_parameters(params)
        theta = float(params[0])
        c = np.cos(theta / 2)
        s = np.sin(theta / 2)
        return UnitaryMatrix([
            [c,      -1j * s, 0,       0],
            [-1j * s, c,      0,       0],
            [0,       0,      c,       1j * s],
            [0,       0,      1j * s,  c],
        ])

    def get_grad(self, params: RealVector = []) -> npt.NDArray[np.complex128]:
        self.check_parameters(params)
        theta = float(params[0])
        c = np.cos(theta / 2)
        s = np.sin(theta / 2)
        # d/d(theta) CR(theta) = -sin(theta/2)/2 * I  -  i*cos(theta/2)/2 * (Z x X)
        return np.array(
            [
                [
                    [-s / 2,       -1j * c / 2, 0,            0],
                    [-1j * c / 2,  -s / 2,      0,            0],
                    [0,             0,          -s / 2,        1j * c / 2],
                    [0,             0,           1j * c / 2,  -s / 2],
                ],
            ],
            dtype=np.complex128,
        )
