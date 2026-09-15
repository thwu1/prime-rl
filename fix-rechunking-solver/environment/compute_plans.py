#!/usr/bin/env python3
"""Compute rechunking plans with cost analysis for arrays defined in arrays.json.

Reads array specifications from /app/arrays.json, computes a rechunking
plan for each using the solver in rechunker.py, evaluates plan quality
using cost_model.py, finds optimal staging, and writes the results
to /app/plans.json.

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


def main():
    with open('/app/arrays.json') as f:
        config = json.load(f)

    results = {'plans': []}
    for arr in config['arrays']:
        shape = tuple(arr['shape'])
        plan = rechunking_plan(
            shape=shape,
            source_chunks=tuple(arr['source_chunks']),
            target_chunks=tuple(arr['target_chunks']),
            itemsize=arr['itemsize'],
            max_mem=arr['max_mem'],
        )
        read_chunks, int_chunks, write_chunks = plan

        io_ops = calculate_plan_io_ops([plan], shape)
        mem_util = calculate_memory_utilization(
            [plan], arr['itemsize'], arr['max_mem']
        )
        shape_volume = prod(shape)
        cost = calculate_plan_cost(io_ops, mem_util, shape_volume)

        opt_stages, opt_plan, opt_cost = find_optimal_stage_count(
            shape=shape,
            source_chunks=tuple(arr['source_chunks']),
            target_chunks=tuple(arr['target_chunks']),
            itemsize=arr['itemsize'],
            max_mem=arr['max_mem'],
        )

        results['plans'].append({
            'name': arr['name'],
            'read_chunks': list(read_chunks),
            'int_chunks': list(int_chunks),
            'write_chunks': list(write_chunks),
            'io_ops': io_ops,
            'mem_utilization': round(mem_util, 6),
            'cost': round(cost, 6),
            'optimal_stages': opt_stages,
            'optimal_cost': round(opt_cost, 6),
        })

    with open('/app/plans.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Generated plans for {len(results['plans'])} arrays")


if __name__ == '__main__':
    main()
