#!/usr/bin/env python3
"""Run trace-driven evaluation comparing baseline vs optimized configurations.

"""

import json
import os
import sys

sys.path.insert(0, '/app')
from numa_coherence import NUMACoherenceSimulator


def parse_trace(filename):
    """Parse a trace file into a list of (op, core_id, addr, data) tuples."""
    ops = []
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            core = int(parts[0])
            op = parts[1].upper()
            addr = int(parts[2], 0)
            if op == 'READ':
                ops.append(('READ', core, addr, None))
            elif op == 'WRITE':
                wdata = int(parts[3], 0)
                ops.append(('WRITE', core, addr, wdata))
    return ops


def run_simulation(ops, enable_owner_opt, enable_chiplet_cache):
    """Run a simulation with given configuration and return stats."""
    sim = NUMACoherenceSimulator(
        num_cores=8, l1_capacity=8, cores_per_chiplet=4,
        enable_owner_opt=enable_owner_opt,
        enable_chiplet_cache=enable_chiplet_cache,
    )
    for op, core, addr, data in ops:
        if op == 'READ':
            sim.read(core, addr)
        else:
            sim.write(core, addr, data)
    return sim.stats


def main():
    traces_dir = '/app/traces'
    trace_files = sorted([
        f for f in os.listdir(traces_dir)
        if f.endswith('.trace')
    ])

    results = {'traces': {}}

    for trace_file in trace_files:
        trace_path = os.path.join(traces_dir, trace_file)
        ops = parse_trace(trace_path)

        baseline_stats = run_simulation(ops, False, False)
        optimized_stats = run_simulation(ops, True, True)

        results['traces'][trace_file] = {
            'baseline': {
                'total_cycles': baseline_stats['total_cycles'],
                'inter_chiplet_messages': baseline_stats['inter_chiplet_messages'],
                'memory_writebacks': baseline_stats['memory_writebacks'],
            },
            'optimized': {
                'total_cycles': optimized_stats['total_cycles'],
                'inter_chiplet_messages': optimized_stats['inter_chiplet_messages'],
                'memory_writebacks': optimized_stats['memory_writebacks'],
            },
        }

    # Compute summary statistics
    cycle_reductions = []
    wb_reductions = []
    inter_reductions = []

    for trace_data in results['traces'].values():
        b = trace_data['baseline']
        o = trace_data['optimized']

        if b['total_cycles'] > 0:
            cycle_reductions.append(
                100.0 * (b['total_cycles'] - o['total_cycles']) / b['total_cycles'])
        if b['memory_writebacks'] > 0:
            wb_reductions.append(
                100.0 * (b['memory_writebacks'] - o['memory_writebacks']) / b['memory_writebacks'])
        else:
            wb_reductions.append(0.0)
        if b['inter_chiplet_messages'] > 0:
            inter_reductions.append(
                100.0 * (b['inter_chiplet_messages'] - o['inter_chiplet_messages']) / b['inter_chiplet_messages'])
        else:
            inter_reductions.append(0.0)

    results['summary'] = {
        'avg_cycle_reduction_pct': round(
            sum(cycle_reductions) / len(cycle_reductions), 2) if cycle_reductions else 0.0,
        'avg_writeback_reduction_pct': round(
            sum(wb_reductions) / len(wb_reductions), 2) if wb_reductions else 0.0,
        'avg_inter_chiplet_reduction_pct': round(
            sum(inter_reductions) / len(inter_reductions), 2) if inter_reductions else 0.0,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Evaluation complete. Results written to /app/results.json")
    print(f"Summary: {json.dumps(results['summary'], indent=2)}")


if __name__ == '__main__':
    main()
