"""Machine model for a trapped-ion quantum computer."""
from __future__ import annotations

import sys
sys.path.insert(0, '/app')

from bqskit.compiler.machine import MachineModel
from bqskit.ir.gates.parameterized.rz import RZGate

from gates import MSGate, GPIGate, GPI2Gate


def get_trapped_ion_model() -> MachineModel:
    """Return a MachineModel for a 3-qubit all-to-all trapped-ion system."""
    return MachineModel(
        num_qudits=3,
        coupling_graph=None,  # None = all-to-all
        gate_set=[MSGate(), GPIGate(), GPI2Gate(), RZGate()],
    )
