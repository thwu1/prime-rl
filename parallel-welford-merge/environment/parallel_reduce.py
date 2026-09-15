"""
Parallel statistics computation pipeline using simulated GPU warps.

Reads datasets from /app/data/, computes statistics using parallel Welford
reduction with warp-level operations, and writes results to /app/output/.
Also performs shared memory bank conflict analysis for the accumulator struct.
"""

import json
import os
import sys

sys.path.insert(0, '/app')

from simulator.accumulator import WelfordAccumulator
from simulator.warp import block_reduce
from simulator.shared_memory import SharedMemorySimulator


def load_dataset(filepath):
    """Load a CSV dataset (one value per line)."""
    values = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                values.append(float(line))
    return values


def parallel_welford(data, config):
    """Compute statistics using parallel Welford reduction.

    Simulates GPU-style parallel processing:
    1. Each thread gets one data element, creates a single-element accumulator
    2. Block-level reduction combines thread accumulators via warp reduction
    3. Cross-block reduction combines block results
    """
    warp_size = config['warp_size']
    block_size = config['block_size']

    # Phase 1: Create per-element accumulators (one per "thread")
    accumulators = []
    for x in data:
        acc = WelfordAccumulator()
        acc.update(x)
        accumulators.append(acc)

    # Phase 2: Block-level reduction
    blocks = []
    for i in range(0, len(accumulators), block_size):
        block = accumulators[i:i + block_size]
        blocks.append(block)

    block_results = []
    for block in blocks:
        result = block_reduce(block, WelfordAccumulator.combine, warp_size)
        block_results.append(result)

    # Phase 3: Reduce across blocks
    if len(block_results) == 1:
        final = block_results[0]
    else:
        final = block_reduce(block_results, WelfordAccumulator.combine, warp_size)

    return final


def analyze_bank_conflicts(config):
    """Analyze shared memory bank conflicts for the accumulator struct layout."""
    sim = SharedMemorySimulator(
        num_banks=config['num_banks'],
        bank_width_bytes=config['bank_width_bytes']
    )

    struct_info = config['accumulator_struct']
    struct_size = struct_info['total_size_bytes']
    fields = struct_info['fields']
    warp_size = config['warp_size']

    field_analyses = {}
    total_conflicts = 0
    field_offsets = []
    current_offset = 0

    for field in fields:
        analysis = sim.analyze_struct_layout(
            struct_size, current_offset, warp_size)
        field_analyses[field['name']] = {
            'offset': current_offset,
            'conflicts': analysis['total_conflicts'],
            'unique_banks': analysis['unique_banks']
        }
        total_conflicts += analysis['total_conflicts']
        field_offsets.append(current_offset)
        current_offset += field['size_bytes']

    padding_result = sim.find_optimal_padding(
        struct_size, field_offsets, warp_size)

    return {
        'struct_size_bytes': struct_size,
        'field_analyses': field_analyses,
        'total_conflicts_per_warp': total_conflicts,
        'padding': padding_result
    }


def main():
    with open('/app/config.json', 'r') as f:
        config = json.load(f)

    data_dir = '/app/data'
    datasets = {}
    for filename in sorted(os.listdir(data_dir)):
        if filename.endswith('.csv'):
            name = filename[:-4]
            filepath = os.path.join(data_dir, filename)
            datasets[name] = load_dataset(filepath)

    # Compute statistics for each dataset using parallel reduction
    statistics = {}
    for name, data in datasets.items():
        result = parallel_welford(data, config)
        stats = result.finalize()
        statistics[name] = stats

    # Analyze bank conflicts for the accumulator struct
    bank_analysis = analyze_bank_conflicts(config)

    # Write output
    os.makedirs('/app/output', exist_ok=True)

    with open('/app/output/statistics.json', 'w') as f:
        json.dump(statistics, f, indent=2)

    with open('/app/output/bank_analysis.json', 'w') as f:
        json.dump(bank_analysis, f, indent=2)

    print("Output written to /app/output/")
    for name, stats in statistics.items():
        print(f"\n{name}:")
        for k, v in stats.items():
            print(f"  {k}: {v}")

    print(f"\nBank conflicts per warp (unpadded): {bank_analysis['total_conflicts_per_warp']}")
    pad = bank_analysis['padding']
    print(f"Optimal padding: {pad['optimal_padding_bytes']} bytes -> {pad['padded_struct_size_bytes']} bytes")


if __name__ == '__main__':
    main()
