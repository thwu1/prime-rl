#!/usr/bin/env python3
"""
Fix all bugs in rechunker.py and zarr_inspector.py, design and implement
cost_model.py from scratch, and run the evaluation pipeline.

"""

import subprocess
import sys


def fix_rechunker():
    """Fix 4 algorithmic bugs in rechunker.py."""
    with open('/app/rechunker.py', 'r') as f:
        code = f.read()

    # Bug 1: _calculate_shared_chunks uses max() but should use min()
    # Shared chunks must fit within BOTH read and write layouts, so each
    # dimension must be <= both the read and write chunk size. That means
    # element-wise minimum, not maximum.
    code = code.replace(
        'max(c_read, c_write) for c_read, c_write in zip(read_chunks, write_chunks)',
        'min(c_read, c_write) for c_read, c_write in zip(read_chunks, write_chunks)',
    )

    # Bug 2: _count_intermediate_chunks missing the -1 correction
    # At each LCM boundary, source and target share an aligned boundary.
    # That shared boundary should only be counted once, giving
    # splits_per_lcm = src_splits + tgt_splits - 1.
    code = code.replace(
        'splits_per_lcm = multiple // source_chunk + multiple // target_chunk\n',
        'splits_per_lcm = multiple // source_chunk + multiple // target_chunk - 1\n',
    )

    # Bug 3: calculate_stage_chunks uses np.linspace instead of np.geomspace
    # Geometric spacing preserves element count per chunk across stages
    # (each stage has roughly the same total chunk volume), while linear
    # spacing doesn't have this property.
    code = code.replace(
        'np.linspace(read_chunks, write_chunks, num=stage_count + 1)',
        'np.geomspace(read_chunks, write_chunks, num=stage_count + 1)',
    )

    # Bug 4: consolidate_chunks multiplies before truncating headroom
    # Must truncate headroom to integer BEFORE multiplying by chunk size
    # to guarantee the result fits within the memory budget. Otherwise
    # rounding can cause the consolidated chunk to exceed max_mem.
    code = code.replace(
        'larger_chunk = int(chunks[n_axis] * headroom)',
        'larger_chunk = chunks[n_axis] * int(headroom)',
    )

    with open('/app/rechunker.py', 'w') as f:
        f.write(code)

    print("Fixed 4 bugs in /app/rechunker.py")


def implement_cost_model():
    """Design and implement the complete cost_model.py from scratch."""
    implementation = '''\
"""
Cost model for evaluating and comparing rechunking plans.

Implements I/O operation counting, memory utilization assessment,
weighted cost scoring, and multi-stage strategy optimization.

"""

import sys
from math import prod
from typing import List, Optional, Sequence, Tuple

sys.path.insert(0, '/app')

from rechunker import (
    calculate_single_stage_io_ops, consolidate_chunks,
    _calculate_shared_chunks, calculate_stage_chunks,
)


def calculate_plan_io_ops(plan, shape):
    """Total I/O ops = sum of per-stage ops. Each stage's ops come from
    counting intermediate chunks between that stage's pre and post chunks."""
    return sum(
        calculate_single_stage_io_ops(shape, pre, post)
        for pre, _int, post in plan
    )


def calculate_memory_utilization(plan, itemsize, max_mem):
    """Memory utilization = average ratio of intermediate chunk memory to
    the memory budget across all stages. Measures how efficiently the
    budget is used: int_chunk_bytes / max_mem, averaged."""
    total = 0.0
    for _pre, int_chunks, _post in plan:
        int_mem = itemsize * prod(int_chunks)
        total += int_mem / max_mem
    return total / len(plan)


def calculate_plan_cost(io_ops, mem_utilization, shape_volume, alpha=0.7, beta=0.3):
    """Weighted cost: alpha * (io_ops / shape_volume) + beta * (1 - mem_utilization).
    I/O intensity is normalized by array size. Memory waste is the complement
    of utilization. Lower cost = better plan."""
    return alpha * (io_ops / shape_volume) + beta * (1 - mem_utilization)


def find_optimal_stage_count(shape, source_chunks, target_chunks, itemsize, max_mem, max_stages=10):
    """Search over 1..max_stages to find the configuration minimizing cost.
    For each candidate stage count, consolidate read/write chunks within
    memory budget, compute geometric intermediate layouts, and evaluate cost."""
    write_chunks = consolidate_chunks(shape, target_chunks, itemsize, max_mem)

    read_chunk_limits = []
    for sc, wc in zip(source_chunks, write_chunks):
        if wc > sc:
            read_chunk_limits.append(wc)
        else:
            read_chunk_limits.append(None)
    read_chunks = consolidate_chunks(
        shape, source_chunks, itemsize, max_mem, read_chunk_limits
    )

    shape_volume = prod(shape)
    best_cost = float("inf")
    best_plan = None
    best_count = 1

    for n in range(1, max_stages + 1):
        stages = calculate_stage_chunks(read_chunks, write_chunks, n)
        if any(any(c <= 0 for c in s) for s in stages):
            continue
        pre_list = [read_chunks] + stages
        post_list = stages + [write_chunks]
        int_list = [
            _calculate_shared_chunks(p, q)
            for p, q in zip(pre_list, post_list)
        ]
        plan = list(zip(pre_list, int_list, post_list))

        io = calculate_plan_io_ops(plan, shape)
        util = calculate_memory_utilization(plan, itemsize, max_mem)
        cost = calculate_plan_cost(io, util, shape_volume)

        if cost < best_cost:
            best_cost = cost
            best_plan = plan
            best_count = n

    return best_count, best_plan, best_cost
'''
    with open('/app/cost_model.py', 'w') as f:
        f.write(implementation)

    print("Implemented complete cost_model.py from scratch")


def fix_zarr_inspector():
    """Fix 1 bug and implement 1 function in zarr_inspector.py."""
    with open('/app/zarr_inspector.py', 'r') as f:
        code = f.read()

    # Bug: compute_access_cost uses int() (truncation) instead of ceil()
    # Even partial chunk access requires reading the full chunk from storage,
    # so the per-dimension count must be rounded UP.
    code = code.replace(
        '        n_chunks = int(extent / c)',
        '        n_chunks = ceil(extent / c)',
    )

    # Implement compute_chunk_alignment_score: selectivity-weighted average
    # of per-dimension coverage ratios (chunk_size / shape_extent).
    # High-selectivity dimensions are weighted more heavily because those
    # are the dimensions the access pattern reads most of.
    code = code.replace(
        '    # TODO: implement this function\n'
        '    raise NotImplementedError("compute_chunk_alignment_score not implemented")',
        '    weighted_sum = sum(\n'
        '        sel * (tc / s)\n'
        '        for tc, s, sel in zip(target_chunks, shape, selectivity)\n'
        '    )\n'
        '    return weighted_sum / sum(selectivity)',
    )

    with open('/app/zarr_inspector.py', 'w') as f:
        f.write(code)

    print("Fixed 1 bug and implemented 1 function in /app/zarr_inspector.py")


def run_pipeline():
    """Run the evaluation pipeline to generate evaluation_report.json."""
    result = subprocess.run(
        [sys.executable, '/app/evaluate.py'],
        capture_output=True, text=True,
    )
    print(result.stdout, end='')
    if result.returncode != 0:
        print(f"Pipeline error: {result.stderr}", file=sys.stderr)
        sys.exit(1)


def verify_report():
    """Basic sanity check on generated report."""
    import json
    from math import prod as mprod

    with open('/app/evaluation_report.json') as f:
        report = json.load(f)
    with open('/app/arrays.json') as f:
        config = json.load(f)

    cfg_by_name = {a['name']: a for a in config['arrays']}
    for arr in report['arrays']:
        max_mem = cfg_by_name[arr['name']]['max_mem']
        from zarr_inspector import extract_store_metadata
        meta = extract_store_metadata(f"/app/zarr_stores/{arr['name']}")
        itemsize = meta['itemsize']

        read_mem = itemsize * mprod(arr['read_chunks'])
        write_mem = itemsize * mprod(arr['write_chunks'])
        assert read_mem <= max_mem, f"Read memory violation for {arr['name']}"
        assert write_mem <= max_mem, f"Write memory violation for {arr['name']}"
        assert 0 < arr['mem_utilization'] <= 1.0, \
            f"Bad utilization for {arr['name']}"
        assert arr['cost'] > 0, f"Bad cost for {arr['name']}"
        assert arr['optimal_cost'] <= arr['cost'] + 1e-6, \
            f"Optimal worse than single for {arr['name']}"
        assert 'access_pattern_analysis' in arr, \
            f"Missing access patterns for {arr['name']}"

    print(f"Verified {len(report['arrays'])} arrays: all constraints satisfied")


if __name__ == '__main__':
    fix_rechunker()
    implement_cost_model()
    fix_zarr_inspector()
    run_pipeline()
    verify_report()
