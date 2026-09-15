#!/usr/bin/env python3
"""
GPU Kernel Performance Analyzer with Roofline Model and Fusion Planning.
Reads hardware specs and operator graphs, produces a roofline-model-based
performance analysis with operator fusion recommendations.
"""

import json
from functools import reduce
import operator as op_module


def numel(shape):
    """Compute the total number of elements in a tensor of given shape."""
    return reduce(op_module.mul, shape, 1)


def compute_flops(operator):
    """Compute the FLOP count for a given operator."""
    t = operator["type"]
    p = operator["params"]
    if t == "matmul":
        return 2 * p["M"] * p["K"] * p["N"]
    elif t == "linear":
        return 2 * p["B"] * p["I"] * p["O"]
    elif t == "conv2d":
        Ho = (p["H"] + 2 * p["padding"] - p["K"]) // p["stride"] + 1
        Wo = (p["W"] + 2 * p["padding"] - p["K"]) // p["stride"] + 1
        return 2 * p["N"] * p["C_out"] * Ho * Wo * p["C_in"] * p["K"] * p["K"]
    elif t in ("relu", "scale", "add", "mul"):
        return numel(p["shape"])
    elif t == "gelu":
        return 8 * numel(p["shape"])
    elif t == "sigmoid":
        return 4 * numel(p["shape"])
    elif t == "tanh":
        return 5 * numel(p["shape"])
    elif t == "swish":
        return 5 * numel(p["shape"])
    elif t == "softmax":
        return 5 * numel(p["shape"])
    elif t == "batchnorm":
        return 4 * numel(p["shape"])
    elif t == "layernorm":
        return 5 * numel(p["shape"])
    else:
        raise ValueError(f"Unknown operator type: {t}")


def compute_memory(operator, dtype_bytes):
    """Compute the memory traffic in bytes for a given operator."""
    t = operator["type"]
    p = operator["params"]
    if t == "matmul":
        return (p["M"] * p["K"] + p["K"] * p["N"] + p["M"] * p["N"]) * dtype_bytes
    elif t == "linear":
        return (p["B"] * p["I"] + p["I"] * p["O"] + p["B"] * p["O"]) * dtype_bytes
    elif t == "conv2d":
        Ho = (p["H"] + 2 * p["padding"] - p["K"]) // p["stride"] + 1
        Wo = (p["W"] + 2 * p["padding"] - p["K"]) // p["stride"] + 1
        return (p["N"] * p["C_in"] * p["H"] * p["W"]
                + p["C_out"] * p["C_in"] * p["K"] * p["K"]
                + p["N"] * p["C_out"] * Ho * Wo) * dtype_bytes
    elif t in ("add", "mul"):
        return 3 * numel(p["shape"]) * dtype_bytes
    else:
        # All unary elementwise, norm, and reduction ops
        return 2 * numel(p["shape"]) * dtype_bytes


def output_numel_of(operator):
    """Compute the number of elements in the output tensor of an operator."""
    t = operator["type"]
    p = operator["params"]
    if t == "matmul":
        return p["M"] * p["N"]
    elif t == "linear":
        return p["B"] * p["O"]
    elif t == "conv2d":
        Ho = (p["H"] + 2 * p["padding"] - p["K"]) // p["stride"] + 1
        Wo = (p["W"] + 2 * p["padding"] - p["K"]) // p["stride"] + 1
        return p["N"] * p["C_out"] * Ho * Wo
    else:
        return numel(p["shape"])


def is_anchor(operator):
    """Check if an operator is an anchor op (matmul, linear, conv2d)."""
    return operator["type"] in ("matmul", "linear", "conv2d")


def find_fusion_groups(operators):
    """Identify fusion groups by scanning operators in sequence.
    Start a new group when an anchor op is encountered and the
    current group already contains an anchor."""
    groups = []
    current = []
    for op in operators:
        if is_anchor(op) and any(is_anchor(o) for o in current):
            groups.append(current)
            current = [op]
        else:
            current.append(op)
    if current:
        groups.append(current)
    return groups


def roofline_time(flops, memory_bytes, peak_flops, bandwidth):
    """Compute the roofline execution time as the bottleneck of
    compute time and memory transfer time."""
    compute_time = flops / peak_flops
    memory_time = memory_bytes / bandwidth
    return max(compute_time, memory_time)


def analyze_graph(graph, hardware):
    """Perform full roofline and fusion analysis on a single operator graph."""
    peak_flops = hardware["peak_flops_fp32"]
    bandwidth = hardware["memory_bandwidth_bytes_per_sec"]
    dtype_bytes = hardware["dtype_bytes"]
    ridge_point = peak_flops / bandwidth

    operators = graph["operators"]

    # Per-operator metrics
    op_results = []
    for op in operators:
        flops = compute_flops(op)
        mem = compute_memory(op, dtype_bytes)
        ai = flops / mem if mem > 0 else float("inf")
        bound = "compute" if ai >= ridge_point else "memory"
        op_results.append({
            "id": op["id"],
            "type": op["type"],
            "flops": flops,
            "memory_bytes": mem,
            "arithmetic_intensity": ai,
            "bound": bound,
        })

    # Fusion analysis
    groups = find_fusion_groups(operators)
    fusion_results = []
    for group in groups:
        group_ids = [op["id"] for op in group]

        # Unfused metrics
        unfused_mem = sum(compute_memory(op, dtype_bytes) for op in group)

        # Compute fusion savings: for each internal edge, eliminate intermediate
        total_savings = 0
        for i in range(len(group) - 1):
            intermediate_numel = output_numel_of(group[i])
            savings = 2 * intermediate_numel * dtype_bytes
            total_savings += savings

        fused_mem = unfused_mem - total_savings
        fused_flops = sum(compute_flops(op) for op in group)

        # Compute execution times
        unfused_time = sum(
            roofline_time(
                compute_flops(op),
                compute_memory(op, dtype_bytes),
                peak_flops,
                bandwidth,
            )
            for op in group
        )
        fused_time = roofline_time(fused_flops, fused_mem, peak_flops, bandwidth)
        speedup = unfused_time / fused_time if fused_time > 0 else 1.0

        fusion_results.append({
            "operator_ids": group_ids,
            "unfused_memory_bytes": unfused_mem,
            "fused_memory_bytes": fused_mem,
            "memory_savings_bytes": total_savings,
            "estimated_speedup": speedup,
        })

    # Graph-level totals
    total_unfused = sum(fg["unfused_memory_bytes"] for fg in fusion_results)
    total_fused = sum(fg["fused_memory_bytes"] for fg in fusion_results)
    savings_pct = ((total_unfused - total_fused) / total_unfused * 100
                   if total_unfused > 0 else 0.0)

    return {
        "name": graph["name"],
        "operators": op_results,
        "fusion_groups": fusion_results,
        "total_unfused_memory_bytes": total_unfused,
        "total_fused_memory_bytes": total_fused,
        "memory_savings_pct": savings_pct,
    }


def main():
    with open("/app/hardware.json") as f:
        hardware = json.load(f)
    with open("/app/graphs.json") as f:
        graphs_data = json.load(f)

    ridge_point = hardware["peak_flops_fp32"] / hardware["memory_bandwidth_bytes_per_sec"]

    results = {
        "hardware": {
            "name": hardware["name"],
            "peak_flops": hardware["peak_flops_fp32"],
            "bandwidth": hardware["memory_bandwidth_bytes_per_sec"],
            "dtype_bytes": hardware["dtype_bytes"],
            "ridge_point": ridge_point,
        },
        "graphs": [analyze_graph(g, hardware) for g in graphs_data["graphs"]],
    }

    with open("/app/analysis.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Analysis written to /app/analysis.json")


if __name__ == "__main__":
    main()
