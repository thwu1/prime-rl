from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Union

import stim

DEFAULT_VOLUME_GATES = frozenset({"H", "S", "S_DAG", "X", "Z", "CX", "CZ", "SWAP"})


@dataclass(frozen=True)
class CircuitMetrics:
    cx_count: int
    volume: int
    one_qubit_gates: int
    two_qubit_gates: int
    depth: int

    def as_dict(self) -> dict:
        return {
            "cx_count": self.cx_count,
            "volume": self.volume,
            "one_qubit_gates": self.one_qubit_gates,
            "two_qubit_gates": self.two_qubit_gates,
            "depth": self.depth,
        }


StimItem = Union[stim.CircuitInstruction, stim.CircuitRepeatBlock]


def _iter_instructions(circuit: stim.Circuit) -> Iterator[stim.CircuitInstruction]:
    for item in circuit:
        if isinstance(item, stim.CircuitRepeatBlock):
            body = item.body_copy()
            for _ in range(item.repeat_count):
                yield from _iter_instructions(body)
        else:
            yield item


def _qubit_targets(inst: stim.CircuitInstruction) -> list[int]:
    return [t.value for t in inst.targets_copy() if t.is_qubit_target]


def compute_metrics(
    circuit_text: str,
    volume_gates: frozenset[str] = DEFAULT_VOLUME_GATES,
    *,
    tick_is_barrier: bool = True,
) -> CircuitMetrics:
    circuit_text = _normalize_stim_text(circuit_text)
    circuit = stim.Circuit(circuit_text)
    cx_count = 0
    volume = 0
    one_qubit = 0
    two_qubit = 0

    last_layer: dict[int, int] = {}
    depth = 0
    tick_floor = 1

    for inst in _iter_instructions(circuit):
        name = inst.name

        if name in {"QUBIT_COORDS", "SHIFT_COORDS", "DETECTOR", "OBSERVABLE_INCLUDE"}:
            continue

        if name == "TICK":
            if tick_is_barrier:
                tick_floor = max(tick_floor, depth + 1)
            continue

        qubits = _qubit_targets(inst)
        if not qubits:
            continue

        ops: list[tuple[int, ...]] = []
        if name in {"CX", "CZ", "SWAP"}:
            if len(qubits) % 2 != 0:
                raise ValueError(
                    f"Malformed {name} instruction with odd #qubit targets: {qubits}"
                )
            for i in range(0, len(qubits), 2):
                ops.append((qubits[i], qubits[i + 1]))
        else:
            for q in qubits:
                ops.append((q,))

        for op in ops:
            if len(op) == 1:
                one_qubit += 1
            elif len(op) == 2:
                two_qubit += 1

        if name in volume_gates:
            volume += len(ops)
            if name == "CX":
                cx_count += len(ops)

        for op in ops:
            uq = set(op)
            layer = tick_floor if tick_is_barrier else 1
            for q in uq:
                layer = max(layer, last_layer.get(q, 0) + 1)
            for q in uq:
                last_layer[q] = layer
            depth = max(depth, layer)

    return CircuitMetrics(
        cx_count=cx_count,
        volume=volume,
        one_qubit_gates=one_qubit,
        two_qubit_gates=two_qubit,
        depth=depth,
    )


def _normalize_stim_text(text: str) -> str:
    if text is None:
        return ""
    text = text.replace("\\n", "\n")
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            lines.append(line)
    return "\n".join(lines) + "\n"
