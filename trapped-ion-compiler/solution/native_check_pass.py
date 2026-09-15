"""Custom BQSKit compiler pass for native gate verification."""
from __future__ import annotations

from bqskit.compiler.basepass import BasePass
from bqskit.ir.circuit import Circuit


class NativeGateCheckPass(BasePass):
    """Verify all gates in a circuit belong to a native gate type set."""

    def __init__(self, native_gate_types: set) -> None:
        self._native_gate_types = set(native_gate_types)

    async def run(self, circuit: Circuit, data: dict) -> None:
        gate_counts: dict[str, int] = {}
        all_native = True

        for op in circuit:
            gate_name = op.gate.name
            gate_counts[gate_name] = gate_counts.get(gate_name, 0) + 1
            if type(op.gate) not in self._native_gate_types:
                all_native = False

        data['gate_counts'] = gate_counts
        data['all_native'] = all_native
