"""Custom differentiable gates for IonQ trapped-ion quantum hardware."""
from __future__ import annotations

import numpy as np
import numpy.typing as npt
from bqskit.ir.gate import Gate
from bqskit.qis.unitary.differentiable import DifferentiableUnitary
from bqskit.qis.unitary.unitarymatrix import UnitaryMatrix
from bqskit.qis.unitary.unitary import RealVector


class MSGate(Gate, DifferentiableUnitary):
    """Molmer-Sorensen XX-interaction gate: exp(-i * theta * X x X)."""
    _num_qudits = 2
    _num_params = 1
    _radixes = (2, 2)
    _name = 'MSGate'

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other)

    def __hash__(self) -> int:
        return hash(type(self).__name__)

    def get_unitary(self, params: RealVector = []) -> UnitaryMatrix:
        self.check_parameters(params)
        theta = float(params[0])
        c = np.cos(theta)
        s = np.sin(theta)
        return UnitaryMatrix(np.array([
            [c, 0, 0, -1j * s],
            [0, c, -1j * s, 0],
            [0, -1j * s, c, 0],
            [-1j * s, 0, 0, c],
        ], dtype=np.complex128))

    def get_grad(self, params: RealVector = []) -> npt.NDArray[np.complex128]:
        self.check_parameters(params)
        theta = float(params[0])
        c = np.cos(theta)
        s = np.sin(theta)
        return np.array([
            [
                [-s, 0, 0, -1j * c],
                [0, -s, -1j * c, 0],
                [0, -1j * c, -s, 0],
                [-1j * c, 0, 0, -s],
            ],
        ], dtype=np.complex128)

    def get_unitary_and_grad(
        self, params: RealVector = [],
    ) -> tuple[UnitaryMatrix, npt.NDArray[np.complex128]]:
        self.check_parameters(params)
        theta = float(params[0])
        c = np.cos(theta)
        s = np.sin(theta)
        unitary = UnitaryMatrix(np.array([
            [c, 0, 0, -1j * s],
            [0, c, -1j * s, 0],
            [0, -1j * s, c, 0],
            [-1j * s, 0, 0, c],
        ], dtype=np.complex128))
        grad = np.array([
            [
                [-s, 0, 0, -1j * c],
                [0, -s, -1j * c, 0],
                [0, -1j * c, -s, 0],
                [-1j * c, 0, 0, -s],
            ],
        ], dtype=np.complex128)
        return unitary, grad


class GPIGate(Gate, DifferentiableUnitary):
    """IonQ GPI gate: [[0, exp(-i*phi)], [exp(i*phi), 0]]."""
    _num_qudits = 1
    _num_params = 1
    _radixes = (2,)
    _name = 'GPIGate'

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other)

    def __hash__(self) -> int:
        return hash(type(self).__name__)

    def get_unitary(self, params: RealVector = []) -> UnitaryMatrix:
        self.check_parameters(params)
        phi = float(params[0])
        return UnitaryMatrix(np.array([
            [0, np.exp(-1j * phi)],
            [np.exp(1j * phi), 0],
        ], dtype=np.complex128))

    def get_grad(self, params: RealVector = []) -> npt.NDArray[np.complex128]:
        self.check_parameters(params)
        phi = float(params[0])
        return np.array([
            [
                [0, -1j * np.exp(-1j * phi)],
                [1j * np.exp(1j * phi), 0],
            ],
        ], dtype=np.complex128)

    def get_unitary_and_grad(
        self, params: RealVector = [],
    ) -> tuple[UnitaryMatrix, npt.NDArray[np.complex128]]:
        self.check_parameters(params)
        phi = float(params[0])
        ep = np.exp(-1j * phi)
        em = np.exp(1j * phi)
        unitary = UnitaryMatrix(np.array([
            [0, ep],
            [em, 0],
        ], dtype=np.complex128))
        grad = np.array([
            [
                [0, -1j * ep],
                [1j * em, 0],
            ],
        ], dtype=np.complex128)
        return unitary, grad


class GPI2Gate(Gate, DifferentiableUnitary):
    """IonQ GPI2 gate: (1/sqrt(2)) * [[1, -i*exp(-i*phi)], [-i*exp(i*phi), 1]]."""
    _num_qudits = 1
    _num_params = 1
    _radixes = (2,)
    _name = 'GPI2Gate'

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other)

    def __hash__(self) -> int:
        return hash(type(self).__name__)

    def get_unitary(self, params: RealVector = []) -> UnitaryMatrix:
        self.check_parameters(params)
        phi = float(params[0])
        inv_sqrt2 = 1.0 / np.sqrt(2.0)
        return UnitaryMatrix(inv_sqrt2 * np.array([
            [1, -1j * np.exp(-1j * phi)],
            [-1j * np.exp(1j * phi), 1],
        ], dtype=np.complex128))

    def get_grad(self, params: RealVector = []) -> npt.NDArray[np.complex128]:
        self.check_parameters(params)
        phi = float(params[0])
        inv_sqrt2 = 1.0 / np.sqrt(2.0)
        return np.array([
            inv_sqrt2 * np.array([
                [0, -np.exp(-1j * phi)],
                [np.exp(1j * phi), 0],
            ], dtype=np.complex128),
        ])

    def get_unitary_and_grad(
        self, params: RealVector = [],
    ) -> tuple[UnitaryMatrix, npt.NDArray[np.complex128]]:
        self.check_parameters(params)
        phi = float(params[0])
        inv_sqrt2 = 1.0 / np.sqrt(2.0)
        ep = np.exp(-1j * phi)
        em = np.exp(1j * phi)
        unitary = UnitaryMatrix(inv_sqrt2 * np.array([
            [1, -1j * ep],
            [-1j * em, 1],
        ], dtype=np.complex128))
        grad = np.array([
            inv_sqrt2 * np.array([
                [0, -ep],
                [em, 0],
            ], dtype=np.complex128),
        ])
        return unitary, grad
