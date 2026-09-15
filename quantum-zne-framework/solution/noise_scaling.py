"""Noise amplification via circuit folding for zero-noise extrapolation.

"""
import copy
import math
import sys

sys.path.insert(0, "/app")
from simulator import GATE_ADJOINTS


def fold_circuit_global(circuit, scale_factor):
    """Fold the entire circuit to amplify noise by an odd integer factor.

    For scale_factor k, the folded circuit is C (C-dagger C)^((k-1)/2),
    where C-dagger is the circuit with gates reversed and each gate
    replaced by its adjoint.

    Args:
        circuit: dict with n_qubits, gates, observable.
        scale_factor: odd integer >= 1.

    Returns:
        New circuit dict with folded gate sequence.
    """
    k = int(round(scale_factor))
    if abs(k - scale_factor) > 1e-10:
        raise ValueError(
            f"scale_factor must be an odd integer, got {scale_factor}"
        )
    if k < 1:
        raise ValueError(f"scale_factor must be >= 1, got {k}")
    if k % 2 == 0:
        raise ValueError(
            f"scale_factor must be odd for global folding, got {k}"
        )

    result = copy.deepcopy(circuit)
    if k == 1:
        return result

    original_gates = circuit["gates"]

    # Build C-dagger: reverse order, adjoint each gate
    adjoint_gates = []
    for gate in reversed(original_gates):
        adjoint_gates.append(
            {
                "name": GATE_ADJOINTS[gate["name"]],
                "targets": list(gate["targets"]),
            }
        )

    # Build C (C-dagger C)^((k-1)/2)
    folded_gates = [copy.deepcopy(g) for g in original_gates]
    for _ in range((k - 1) // 2):
        folded_gates.extend(copy.deepcopy(adjoint_gates))
        folded_gates.extend([copy.deepcopy(g) for g in original_gates])

    result["gates"] = folded_gates
    return result


def fold_gates_from_end(circuit, scale_factor):
    """Fold individual gates from the end of the circuit.

    Each folded gate G becomes G G-dagger G (tripling its noise
    contribution). The number of gates folded is ceil(n*(s-1)/2)
    where n is the total gate count and s is the scale factor.

    Args:
        circuit: dict with n_qubits, gates, observable.
        scale_factor: float >= 1.0.

    Returns:
        New circuit dict with partially folded gate sequence.
    """
    if scale_factor < 1.0 - 1e-10:
        raise ValueError(f"scale_factor must be >= 1.0, got {scale_factor}")

    result = copy.deepcopy(circuit)
    if abs(scale_factor - 1.0) < 1e-10:
        return result

    original_gates = circuit["gates"]
    n = len(original_gates)
    num_to_fold = math.ceil(n * (scale_factor - 1) / 2)
    num_to_fold = min(num_to_fold, n)

    new_gates = []
    for i, gate in enumerate(original_gates):
        new_gates.append(copy.deepcopy(gate))
        # Fold gates from the end of the circuit
        if i >= n - num_to_fold:
            adj_gate = {
                "name": GATE_ADJOINTS[gate["name"]],
                "targets": list(gate["targets"]),
            }
            new_gates.append(adj_gate)
            new_gates.append(copy.deepcopy(gate))

    result["gates"] = new_gates
    return result
