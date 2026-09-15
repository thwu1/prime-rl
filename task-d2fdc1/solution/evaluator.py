#!/usr/bin/env python3
"""
Evaluator for the graph scheduling cost model with asymmetric bandwidth.
Computes total latency for a problem+solution pair per the roofline model.

"""

import json
import sys
import math


def evaluate(problem, solution):
    widths = problem['widths']
    heights = problem['heights']
    op_types = problem['op_types']
    op_inputs = problem['inputs']
    op_outputs = problem['outputs']
    base_costs = problem['base_costs']
    capacity = problem['fast_memory_capacity']
    read_bw = problem['slow_memory_read_bandwidth']
    write_bw = problem['slow_memory_write_bandwidth']
    transition_cost = problem.get('transition_cost', 0)
    native_w, native_h = problem['native_granularity']
    native_k = native_w  # per spec: native k equals native w

    subgraphs = solution['subgraphs']
    granularities = solution['granularities']
    retains_list = solution['tensors_to_retain']
    traversals = solution.get('traversal_orders', [None] * len(subgraphs))

    total_latency = 0.0
    retained_set = set()

    for sg_idx in range(len(subgraphs)):
        sg_ops = subgraphs[sg_idx]
        w, h, k = granularities[sg_idx]
        retain_after = set(retains_list[sg_idx])
        traversal = traversals[sg_idx] if sg_idx < len(traversals) else None

        # Add transition cost between consecutive subgraphs
        if sg_idx > 0:
            total_latency += transition_cost

        # --- Identify produced/consumed/ephemeral tensors ---
        produced = set()
        consumed = set()
        for oi in sg_ops:
            for t in op_outputs[oi]:
                produced.add(t)
            for t in op_inputs[oi]:
                consumed.add(t)

        potentially_ephemeral = produced & consumed
        ephemeral = set()
        for t in potentially_ephemeral:
            # Find producing op
            for oi in sg_ops:
                if t in op_outputs[oi]:
                    if op_types[oi] == 'Pointwise':
                        ephemeral.add(t)
                    elif op_types[oi] == 'MatMul':
                        K_op = widths[op_inputs[oi][0]]
                        if k < K_op:
                            ephemeral.add(t)
                    break

        external_inputs = consumed - produced
        external_outputs = produced - consumed

        # --- Spatial grid ---
        grid_rows = 1
        grid_cols = 1
        for oi in sg_ops:
            for t in op_outputs[oi]:
                grid_cols = max(grid_cols, math.ceil(widths[t] / w))
                grid_rows = max(grid_rows, math.ceil(heights[t] / h))
        n_tiles = grid_rows * grid_cols

        # --- Split-K steps ---
        num_k_steps = 1
        for oi in sg_ops:
            if op_types[oi] == 'MatMul':
                K_op = widths[op_inputs[oi][0]]
                num_k_steps = max(num_k_steps, math.ceil(K_op / k))

        # --- Working set check ---
        pipeline_mode = any(
            op_types[oi] == 'MatMul' and k < widths[op_inputs[oi][0]]
            for oi in sg_ops
        )

        def input_strip_size(tensor_id, op_idx, input_pos):
            ot = op_types[op_idx]
            if ot == 'MatMul':
                if input_pos == 0:  # LHS: h * K
                    return h * widths[tensor_id]
                else:  # RHS: min(k, K) * w
                    return min(k, heights[tensor_id]) * w
            else:  # Pointwise
                return h * w

        ws = 0
        for t in retained_set:
            ws += widths[t] * heights[t]

        if pipeline_mode:
            seen = set()
            for oi in sg_ops:
                for idx, t in enumerate(op_inputs[oi]):
                    if t in ephemeral or t in seen or t in retained_set:
                        continue
                    ws += input_strip_size(t, oi, idx)
                    seen.add(t)
                for t in op_outputs[oi]:
                    if t in ephemeral or t in seen:
                        continue
                    ws += h * w
                    seen.add(t)
        else:
            max_op_ws = 0
            for oi in sg_ops:
                op_ws = 0
                for idx, t in enumerate(op_inputs[oi]):
                    if t in ephemeral or t in retained_set:
                        continue
                    op_ws += input_strip_size(t, oi, idx)
                for t in op_outputs[oi]:
                    if t in ephemeral:
                        continue
                    op_ws += h * w
                max_op_ws = max(max_op_ws, op_ws)
            ws += max_op_ws

        if ws > capacity:
            return None  # OOM

        # --- Compute time per step ---
        compute_per_step = 0.0
        for oi in sg_ops:
            sf = max(1, math.ceil(w / native_w)) * max(1, math.ceil(h / native_h))
            if op_types[oi] == 'Pointwise':
                compute_per_step += base_costs[oi] * sf
            elif op_types[oi] == 'MatMul':
                K_op = widths[op_inputs[oi][0]]
                compute_per_step += base_costs[oi] * sf * min(k, K_op) / native_k

        # --- Tile traversal with data reuse ---
        if traversal is None:
            tile_order = list(range(n_tiles))
        else:
            tile_order = [int(x) for x in traversal]

        prev_loaded = {}
        for t in retained_set:
            if t in consumed:
                prev_loaded[t] = ('retained', t)

        sg_latency = 0.0
        for tile_idx in tile_order:
            row = tile_idx // grid_cols
            col = tile_idx % grid_cols

            for k_step in range(num_k_steps):
                new_loaded = {}
                mem_in = 0.0  # raw data size for reads

                for oi in sg_ops:
                    for idx, t in enumerate(op_inputs[oi]):
                        if t in ephemeral or t in new_loaded:
                            continue
                        if t in retained_set:
                            new_loaded[t] = ('retained', t)
                            continue

                        if op_types[oi] == 'MatMul':
                            if idx == 0:  # LHS
                                sid = ('lhs', t, row)
                                ssz = h * widths[t]
                            else:  # RHS
                                sid = ('rhs', t, col, k_step)
                                ssz = min(k, heights[t]) * w
                        else:
                            sid = ('pw', t, row, col)
                            ssz = h * w

                        new_loaded[t] = sid
                        if prev_loaded.get(t) != sid:
                            mem_in += ssz

                mem_out = 0.0  # raw data size for writes
                if k_step == num_k_steps - 1:
                    for t in external_outputs:
                        if t not in retain_after:
                            mem_out += h * w

                # Asymmetric bandwidth: separate read and write times
                read_time = mem_in / read_bw
                write_time = mem_out / write_bw
                mem_time = read_time + write_time
                step_lat = max(compute_per_step, mem_time)
                sg_latency += step_lat
                prev_loaded = new_loaded

        total_latency += sg_latency
        retained_set = retain_after

    return total_latency


def main():
    if len(sys.argv) != 3:
        print("Usage: evaluate.py <problem.json> <solution.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        problem = json.load(f)
    with open(sys.argv[2]) as f:
        solution = json.load(f)

    result = evaluate(problem, solution)
    if result is None:
        print("OOM")
        sys.exit(1)
    else:
        print(f"{result}")


if __name__ == '__main__':
    main()
