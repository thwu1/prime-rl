#!/usr/bin/env python3

"""
IOPDDL Graph Scheduling Cost Model Evaluator.

Evaluates a solution (execution schedule) for a computational DAG on an AI
accelerator with a three-tier memory hierarchy. Computes total latency using
a roofline performance model with spatial tiling, split-K reduction, traversal-
order data reuse, and inter-subgraph tensor retention.
"""

import json
import math
import sys


def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def evaluate(problem: dict, solution: dict) -> dict:
    widths = problem["widths"]
    heights = problem["heights"]
    op_inputs = problem["inputs"]
    op_outputs = problem["outputs"]
    base_costs = problem["base_costs"]
    op_types = problem["op_types"]
    capacity = problem["fast_memory_capacity"]
    bandwidth = problem["slow_memory_bandwidth"]
    native_w, native_h = problem["native_granularity"]
    native_k = native_w

    n_ops = len(op_types)
    n_tensors = len(widths)

    subgraphs = solution["subgraphs"]
    granularities = solution["granularities"]
    retains = solution["tensors_to_retain"]
    traversals = solution["traversal_orders"]

    # --- Validation: op coverage ---
    covered = set()
    for sg in subgraphs:
        for op_idx in sg:
            covered.add(op_idx)
    if covered != set(range(n_ops)):
        missing = set(range(n_ops)) - covered
        return {
            "valid": False,
            "total_latency": 0.0,
            "subgraph_latencies": [],
            "error": f"Ops not covered: {sorted(missing)}",
        }

    # --- Identify tensor producers ---
    producer_of = {}
    for op_idx in range(n_ops):
        for t in op_outputs[op_idx]:
            producer_of[t] = op_idx

    # Track retained tensors from previous subgraph
    retained_set = set()

    total_latency = 0.0
    subgraph_latencies = []

    for sg_idx, sg_ops in enumerate(subgraphs):
        w, h, k = granularities[sg_idx]
        retain_list = retains[sg_idx]
        traversal = traversals[sg_idx]

        sg_ops_set = set(sg_ops)

        # --- Classify tensors ---
        produced_in_sg = set()
        consumed_in_sg = set()
        for op_idx in sg_ops:
            for t in op_outputs[op_idx]:
                produced_in_sg.add(t)
            for t in op_inputs[op_idx]:
                consumed_in_sg.add(t)

        ephemeral = produced_in_sg & consumed_in_sg
        boundary_inputs = consumed_in_sg - produced_in_sg
        boundary_outputs = produced_in_sg - consumed_in_sg

        # --- OOM check (per-op) ---
        for op_idx in sg_ops:
            ws = 0
            op_type = op_types[op_idx]
            for i, t in enumerate(op_inputs[op_idx]):
                if op_type == "MatMul":
                    ws += (h * k) if i == 0 else (k * w)
                else:
                    ws += w * h
            for t in op_outputs[op_idx]:
                ws += w * h
            if ws > capacity:
                return {
                    "valid": False,
                    "total_latency": 0.0,
                    "subgraph_latencies": [],
                    "error": f"OOM: Op {op_idx} working set {ws} > capacity {capacity}",
                }

        # --- Tile structure ---
        out_W, out_H = 0, 0
        for op_idx in sg_ops:
            for t in op_outputs[op_idx]:
                out_W = max(out_W, widths[t])
                out_H = max(out_H, heights[t])

        n_w = max(1, math.ceil(out_W / w))
        n_h = max(1, math.ceil(out_H / h))
        n_spatial = n_w * n_h

        # n_k from MatMul ops
        n_k = 1
        for op_idx in sg_ops:
            if op_types[op_idx] == "MatMul":
                lhs_t = op_inputs[op_idx][0]
                K_dim = widths[lhs_t]
                n_k = max(n_k, math.ceil(K_dim / k) if k > 0 else 1)

        # Traversal order
        tile_order = list(range(n_spatial)) if traversal is None else traversal

        # Compute per step
        compute_per_step = 0.0
        for op_idx in sg_ops:
            if op_types[op_idx] == "Pointwise":
                compute_per_step += base_costs[op_idx]
            else:
                compute_per_step += base_costs[op_idx] * min(k, native_k) / native_k

        # --- Build boundary input descriptors ---
        # Each describes a boundary input tensor and its access pattern
        input_descs = []  # list of (tensor_id, kind, K_dim)
        seen_tensors = set()

        for op_idx in sg_ops:
            op_type = op_types[op_idx]
            for i, t in enumerate(op_inputs[op_idx]):
                if t not in boundary_inputs or t in seen_tensors:
                    continue
                seen_tensors.add(t)
                if op_type == "MatMul":
                    if i == 0:
                        K_dim = widths[t]
                        input_descs.append((t, "matmul_lhs", K_dim))
                    else:
                        input_descs.append((t, "matmul_rhs", 0))
                else:
                    input_descs.append((t, "pointwise", 0))

        # --- Simulate step by step ---
        sg_latency = 0.0

        # Residency tracking
        # LHS: track resident row index per tensor
        lhs_resident_row = {}  # tensor_id -> row_index
        # RHS: track resident (col_index, k_step) per tensor
        # Reused only if BOTH col and k_step match previous step
        rhs_resident = {}  # tensor_id -> (col_index, k_step)

        for tile_seq_idx, tile_idx in enumerate(tile_order):
            tile_row = tile_idx // n_w
            tile_col = tile_idx % n_w

            for k_step in range(n_k):
                is_first_k = (k_step == 0)
                is_last_k = (k_step == n_k - 1)

                mem_in = 0.0
                mem_out = 0.0

                for t_id, kind, K_dim in input_descs:
                    is_retained = t_id in retained_set

                    if kind == "matmul_lhs":
                        # Load full row-band (h × K) on first k-step of tile
                        # Reuse if same row as previous tile
                        if is_first_k:
                            if is_retained:
                                pass
                            elif lhs_resident_row.get(t_id) == tile_row:
                                pass  # same row, reuse
                            else:
                                mem_in += h * K_dim
                            lhs_resident_row[t_id] = tile_row

                    elif kind == "matmul_rhs":
                        # RHS strip: k × w. Reused if (col, k_step) matches previous.
                        if is_retained:
                            pass
                        else:
                            prev = rhs_resident.get(t_id)
                            if prev is not None and prev[0] == tile_col and prev[1] == k_step:
                                pass  # reuse
                            else:
                                mem_in += k * w
                        rhs_resident[t_id] = (tile_col, k_step)

                    else:  # pointwise
                        # Load w × h on first k-step of tile
                        if is_first_k:
                            if is_retained:
                                pass
                            else:
                                mem_in += w * h

                # Output eviction on last k-step
                if is_last_k:
                    for t in boundary_outputs:
                        if t not in retain_list:
                            mem_out += w * h

                # Roofline
                mem_time = (mem_in + mem_out) / bandwidth
                step_lat = max(compute_per_step, mem_time)
                sg_latency += step_lat

        subgraph_latencies.append(sg_latency)
        total_latency += sg_latency

        # Update retained set
        retained_set = set(retain_list)

    return {
        "valid": True,
        "total_latency": total_latency,
        "subgraph_latencies": subgraph_latencies,
    }


def main():
    if len(sys.argv) != 3:
        print(json.dumps({"valid": False, "error": "Usage: evaluate.py <problem.json> <solution.json>"}))
        sys.exit(1)

    problem = load_json(sys.argv[1])
    solution = load_json(sys.argv[2])
    result = evaluate(problem, solution)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
