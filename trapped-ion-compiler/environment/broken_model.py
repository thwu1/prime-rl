"""Machine model for trapped-ion QPU."""
import sys
sys.path.insert(0, '/app')

from bqskit.compiler.machine import MachineModel
from bqskit.ir.gates.parameterized.rz import RZGate

from gates import MSGate, GPIGate


def get_trapped_ion_model() -> MachineModel:
    """Create a hardware model for the trapped-ion system."""
    return MachineModel(
        num_qudits=2,
        coupling_graph=[(0, 1)],
        gate_set=[MSGate(), GPIGate(), RZGate()],
    )
