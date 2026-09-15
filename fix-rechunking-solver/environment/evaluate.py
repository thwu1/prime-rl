"""Evaluation pipeline for rechunking strategies.

Reads array target specifications from /app/arrays.json, inspects Zarr
stores at /app/zarr_stores/ for source metadata, computes rechunking
plans, evaluates plan quality, analyzes access patterns, finds optimal
multi-stage configurations, and writes the evaluation report.

"""

import json
import sys
from math import prod

sys.path.insert(0, '/app')

from rechunker import rechunking_plan
from cost_model import (
    calculate_plan_io_ops,
    calculate_memory_utilization,
    calculate_plan_cost,
    find_optimal_stage_count,
)
from zarr_inspector import (
    extract_all_metadata,
    compute_access_cost,
    compute_chunk_alignment_score,
)


def main():
    # Step 1: Extract source metadata from Zarr stores
    print("Inspecting Zarr stores...")
    store_metadata = extract_all_metadata('/app/zarr_stores')

    # Step 2: Load target configurations and access patterns
    with open('/app/arrays.json') as f:
        config = json.load(f)

    report = {'arrays': []}

    for arr_spec in config['arrays']:
        name = arr_spec['name']
        if name not in store_metadata:
            print(f"Warning: no Zarr store found for {name}, skipping")
            continue

        meta = store_metadata[name]
        shape = tuple(meta['shape'])
        source_chunks = tuple(meta['source_chunks'])
        target_chunks = tuple(arr_spec['target_chunks'])
        itemsize = meta['itemsize']
        max_mem = arr_spec['max_mem']

        print(f"\nProcessing {name}: shape={shape}, "
              f"{source_chunks} -> {target_chunks}")

        # Step 3: Compute single-stage rechunking plan
        read_chunks, int_chunks, write_chunks = rechunking_plan(
            shape=shape,
            source_chunks=source_chunks,
            target_chunks=target_chunks,
            itemsize=itemsize,
            max_mem=max_mem,
        )

        # Step 4: Evaluate plan quality
        plan = [(read_chunks, int_chunks, write_chunks)]
        io_ops = calculate_plan_io_ops(plan, shape)
        mem_util = calculate_memory_utilization(plan, itemsize, max_mem)
        shape_volume = prod(shape)
        cost = calculate_plan_cost(io_ops, mem_util, shape_volume)

        # Step 5: Find optimal multi-stage configuration
        opt_stages, opt_plan, opt_cost = find_optimal_stage_count(
            shape=shape,
            source_chunks=source_chunks,
            target_chunks=target_chunks,
            itemsize=itemsize,
            max_mem=max_mem,
        )

        # Step 6: Analyze access patterns
        access_analysis = {}
        for pattern_name, selectivity in arr_spec['access_patterns'].items():
            src_cost = compute_access_cost(
                list(source_chunks), list(shape), selectivity
            )
            tgt_cost = compute_access_cost(
                list(write_chunks), list(shape), selectivity
            )
            alignment = compute_chunk_alignment_score(
                list(write_chunks), list(shape), selectivity
            )
            access_analysis[pattern_name] = {
                'source_cost': src_cost,
                'target_cost': tgt_cost,
                'alignment_score': round(alignment, 6),
                'improvement_ratio': round(src_cost / max(tgt_cost, 1), 4),
            }

        report['arrays'].append({
            'name': name,
            'shape': list(shape),
            'source_chunks': list(source_chunks),
            'read_chunks': list(read_chunks),
            'int_chunks': list(int_chunks),
            'write_chunks': list(write_chunks),
            'io_ops': io_ops,
            'mem_utilization': round(mem_util, 6),
            'cost': round(cost, 6),
            'optimal_stages': opt_stages,
            'optimal_cost': round(opt_cost, 6),
            'access_pattern_analysis': access_analysis,
        })

        print(f"  Plan: read={read_chunks}, int={int_chunks}, "
              f"write={write_chunks}")
        print(f"  IO ops: {io_ops}, Utilization: {mem_util:.4f}, "
              f"Cost: {cost:.6f}")
        print(f"  Optimal: {opt_stages} stages, cost={opt_cost:.6f}")

    with open('/app/evaluation_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\nEvaluation report written for {len(report['arrays'])} arrays")


if __name__ == '__main__':
    main()
