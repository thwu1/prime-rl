#!/usr/bin/env python3


"""Produce fault-tolerance resource analysis of surface code computations."""

import json

from tqec import compile_block_graph
from tqec.computation.block_graph import BlockGraph
from tqec.gallery import cnot, memory, three_cnots
from tqec.utils.enums import Basis
from tqec.utils.noise_model import NoiseModel, NoiseRule
from tqec.utils.position import Position3D


def circuit_metrics(circ):
    """Extract the five core circuit metrics."""
    dem = circ.detector_error_model(decompose_errors=True)
    n_err = sum(1 for inst in dem.flattened() if inst.type == "error")
    errs = circ.shortest_graphlike_error(ignore_ungraphlike_errors=True)
    return {
        "num_qubits": circ.num_qubits,
        "num_detectors": circ.num_detectors,
        "num_observables": circ.num_observables,
        "num_error_mechanisms": n_err,
        "effective_code_distance": len(errs),
    }


def dem_analysis(circ):
    """Structural breakdown of the detector error model."""
    dem = circ.detector_error_model(decompose_errors=True)
    total = logical = pure = total_det = 0
    for inst in dem.flattened():
        if inst.type == "error":
            total += 1
            tgts = inst.targets_copy()
            has_log = any(t.is_logical_observable_id() for t in tgts)
            n_det = sum(1 for t in tgts if t.is_relative_detector_id())
            total_det += n_det
            if has_log:
                logical += 1
            else:
                pure += 1
    return {
        "logical_error_mechanisms": logical,
        "pure_detector_errors": pure,
        "avg_detectors_per_mechanism": (
            round(total_det / total, 6) if total else 0.0
        ),
    }


def compile_circuit(bg, k, noise):
    """Compile a block graph into a noisy stim circuit."""
    compiled = compile_block_graph(bg, observables="auto")
    return compiled.generate_stim_circuit(k=k, noise_model=noise)


def main():
    uniform_noise = NoiseModel.uniform_depolarizing(0.001)

    # Custom asymmetric noise model: different rates for different operations
    custom_noise = NoiseModel(
        idle_depolarization=0.0002,
        any_clifford_1q_rule=NoiseRule(after={"DEPOLARIZE1": 0.001}),
        any_clifford_2q_rule=NoiseRule(after={"DEPOLARIZE2": 0.005}),
        measure_rules={
            "X": NoiseRule(after={}, flip_result=0.003),
            "Y": NoiseRule(after={}, flip_result=0.003),
            "Z": NoiseRule(after={}, flip_result=0.003),
            "XX": NoiseRule(after={}, flip_result=0.003),
            "YY": NoiseRule(after={}, flip_result=0.003),
            "ZZ": NoiseRule(after={}, flip_result=0.003),
        },
        gate_rules={
            "RX": NoiseRule(after={"Z_ERROR": 0.002}),
            "RY": NoiseRule(after={"X_ERROR": 0.002}),
            "R": NoiseRule(after={"X_ERROR": 0.002}),
        },
    )

    factories = {
        "memory": lambda: memory(observable_basis=Basis.Z),
        "cnot": lambda: cnot(observable_basis=Basis.Z),
        "three_cnots": lambda: three_cnots(observable_basis=Basis.Z),
    }

    # ── Section 1: Scaling ──
    scaling = {}
    for name, factory in factories.items():
        scaling[name] = {}
        for k_val in [1, 2, 3]:
            bg = factory()
            circ = compile_circuit(bg, k_val, uniform_noise)
            d = 2 * k_val + 1
            scaling[name][f"d{d}"] = circuit_metrics(circ)

    # ── Section 2: Noise comparison (memory at d=5) ──
    noise_comparison = {}
    for noise_name, noise_model in [
        ("uniform", uniform_noise),
        ("custom", custom_noise),
    ]:
        bg = memory(observable_basis=Basis.Z)
        circ = compile_circuit(bg, 2, noise_model)
        metrics = circuit_metrics(circ)
        dem_stats = dem_analysis(circ)
        noise_comparison[noise_name] = {**metrics, **dem_stats}

    # ── Section 3: Custom memory (from scratch) ──
    # Reverse-engineer the gallery memory: it creates a single ZXZ cube at the
    # origin. The cube kind "ZXZ" means boundaries are Z along X-axis, X along
    # Y-axis, Z along Z-axis (temporal). For a Z-basis observable, the gallery
    # uses the convention f"ZX{basis.value}" = "ZXZ".
    custom_bg = BlockGraph("Custom Z Memory")
    custom_bg.add_cube(Position3D(0, 0, 0), "ZXZ")

    custom_memory = {}
    for k_val in [1, 2, 3]:
        circ = compile_circuit(custom_bg, k_val, uniform_noise)
        d = 2 * k_val + 1
        custom_memory[f"d{d}"] = circuit_metrics(circ)

    # ── Write output ──
    result = {
        "scaling": scaling,
        "noise_comparison": noise_comparison,
        "custom_memory": custom_memory,
    }

    with open("/app/analysis.json", "w") as f:
        json.dump(result, f, indent=2)

    print("Analysis written to /app/analysis.json")


if __name__ == "__main__":
    main()
