
"""RotationFoldingPass: merges consecutive RZ gates on the same qubit."""

from __future__ import annotations

import numpy as np

from bqskit.compiler.basepass import BasePass
from bqskit.ir.circuit import Circuit
from bqskit.ir.gates.parameterized.rz import RZGate
from bqskit.ir.point import CircuitPoint


def fold_rotations(circuit: Circuit) -> None:
    """
    Merge consecutive RZ gates on the same qubit in-place.

    If the merged angle is congruent to 0 mod 2*pi (within tolerance 1e-10),
    the gate is removed entirely.
    """
    changed = True
    while changed:
        changed = False

        for qudit in range(circuit.num_qudits):
            prev_rz_point = None
            prev_rz_angle = None

            for cycle in range(circuit.num_cycles):
                point = CircuitPoint(cycle, qudit)

                if circuit.is_point_idle(point):
                    continue

                op = circuit[point]

                if isinstance(op.gate, RZGate) and len(op.location) == 1:
                    if prev_rz_point is not None:
                        # Found two consecutive RZ gates on this qudit — merge
                        total = prev_rz_angle + op.params[0]
                        angle_mod = total % (2 * np.pi)
                        is_identity = (
                            abs(angle_mod) < 1e-10
                            or abs(angle_mod - 2 * np.pi) < 1e-10
                        )

                        if is_identity:
                            # Both cancel to identity — remove both
                            # Pop later point first so earlier point stays valid
                            circuit.pop(point)
                            circuit.pop(prev_rz_point)
                        else:
                            # Replace earlier gate with merged angle, remove later
                            circuit.replace_gate(
                                prev_rz_point,
                                RZGate(),
                                list(op.location),
                                [total],
                            )
                            circuit.pop(point)

                        changed = True
                        break  # restart scan — cycle indices may have shifted
                    else:
                        prev_rz_point = point
                        prev_rz_angle = op.params[0]
                else:
                    # Non-RZ gate on this qudit — reset accumulator
                    prev_rz_point = None
                    prev_rz_angle = None

            if changed:
                break  # restart outer loop


class RotationFoldingPass(BasePass):
    """BQSKit compiler pass that merges consecutive RZ gates."""

    async def run(self, circuit: Circuit, data) -> None:  # noqa: ANN001
        fold_rotations(circuit)
