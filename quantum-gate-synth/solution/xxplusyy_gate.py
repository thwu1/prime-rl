
"""Custom XXPlusYY gate implementation for BQSKit synthesis."""
import numpy as np
import numpy.typing as npt

from bqskit.ir.gate import Gate
from bqskit.ir.gates.qubitgate import QubitGate
from bqskit.qis.unitary.differentiable import DifferentiableUnitary
from bqskit.qis.unitary.unitarymatrix import UnitaryMatrix
from bqskit.qis.unitary.unitary import RealVector


class XXPlusYYGate(Gate, DifferentiableUnitary):
    """
    The XX+YY interaction gate, parameterized by theta and beta.

    Unitary:
        [[1,           0,                            0,                            0],
         [0,           cos(theta/2),                 i*sin(theta/2)*exp(i*beta),   0],
         [0,           i*sin(theta/2)*exp(-i*beta),  cos(theta/2),                 0],
         [0,           0,                            0,                            1]]
    """

    _num_qudits = 2
    _num_params = 2
    _radixes = (2, 2)
    _name = "XXPlusYY"

    def get_unitary(self, params: RealVector = [0.0, 0.0]) -> UnitaryMatrix:
        self.check_parameters(params)
        theta = float(params[0])
        beta = float(params[1])
        c = np.cos(theta / 2.0)
        s = np.sin(theta / 2.0)
        eb = np.exp(1j * beta)
        return UnitaryMatrix(
            [
                [1, 0, 0, 0],
                [0, c, 1j * s * eb, 0],
                [0, 1j * s / eb, c, 0],
                [0, 0, 0, 1],
            ]
        )

    def get_grad(self, params: RealVector = [0.0, 0.0]) -> npt.NDArray[np.complex128]:
        self.check_parameters(params)
        theta = float(params[0])
        beta = float(params[1])
        c = np.cos(theta / 2.0)
        s = np.sin(theta / 2.0)
        eb = np.exp(1j * beta)

        # Partial derivative with respect to theta
        dU_dtheta = np.array(
            [
                [0, 0, 0, 0],
                [0, -s / 2.0, 1j * (c / 2.0) * eb, 0],
                [0, 1j * (c / 2.0) / eb, -s / 2.0, 0],
                [0, 0, 0, 0],
            ],
            dtype=np.complex128,
        )

        # Partial derivative with respect to beta
        dU_dbeta = np.array(
            [
                [0, 0, 0, 0],
                [0, 0, -s * eb, 0],
                [0, s / eb, 0, 0],
                [0, 0, 0, 0],
            ],
            dtype=np.complex128,
        )

        return np.array([dU_dtheta, dU_dbeta])

    def get_unitary_and_grad(
        self, params: RealVector = [0.0, 0.0]
    ) -> tuple[UnitaryMatrix, npt.NDArray[np.complex128]]:
        self.check_parameters(params)
        theta = float(params[0])
        beta = float(params[1])
        c = np.cos(theta / 2.0)
        s = np.sin(theta / 2.0)
        eb = np.exp(1j * beta)

        utry = UnitaryMatrix(
            [
                [1, 0, 0, 0],
                [0, c, 1j * s * eb, 0],
                [0, 1j * s / eb, c, 0],
                [0, 0, 0, 1],
            ]
        )

        dU_dtheta = np.array(
            [
                [0, 0, 0, 0],
                [0, -s / 2.0, 1j * (c / 2.0) * eb, 0],
                [0, 1j * (c / 2.0) / eb, -s / 2.0, 0],
                [0, 0, 0, 0],
            ],
            dtype=np.complex128,
        )

        dU_dbeta = np.array(
            [
                [0, 0, 0, 0],
                [0, 0, -s * eb, 0],
                [0, s / eb, 0, 0],
                [0, 0, 0, 0],
            ],
            dtype=np.complex128,
        )

        return utry, np.array([dU_dtheta, dU_dbeta])
