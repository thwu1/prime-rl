#!/usr/bin/env python3
"""GPU persistent matmul performance predictor.

Generates performance predictions for matrix multiplication workloads
across different kernel configurations on target GPU hardware.
"""
import json
import sys

sys.path.insert(0, '/app')
from gpu_config import GPU_CONFIG
from workloads import WORKLOADS, CONFIGS
from tile_scheduler import build_persistent_schedule
from resource_model import compute_shared_memory, compute_occupancy
from roofline import estimate_performance


def analyze_workload(workload, configs, gpu_config):
    """Analyze all configurations for a given workload and rank by throughput."""
    M, N, K = workload
    results = []

    for i, config in enumerate(configs):
        entry = {'config': config, 'config_id': i}

        smem = compute_shared_memory(config['BLOCK_M'], config['BLOCK_N'],
                                      config['BLOCK_K'], config['num_stages'])
        entry['shared_mem_bytes'] = smem

        occ = compute_occupancy(smem, config['num_warps'], gpu_config)
        entry['occupancy'] = occ
        entry['is_valid'] = occ > 0

        if entry['is_valid']:
            sched = build_persistent_schedule(
                M, N, config['BLOCK_M'], config['BLOCK_N'],
                config['GROUP_SIZE_M'], gpu_config['num_sms'])
            entry['schedule_info'] = {
                'num_pid_m': sched['num_pid_m'],
                'num_pid_n': sched['num_pid_n'],
                'num_tiles': sched['num_tiles'],
                'active_sms': sched['active_sms'],
                'tiles_per_sm_avg': sched['tiles_per_sm_avg'],
                'tiles_per_sm_max': sched['tiles_per_sm_max'],
            }
            perf = estimate_performance(M, N, K, config, gpu_config)
            entry['performance'] = perf
        else:
            entry['schedule_info'] = None
            entry['performance'] = {
                'total_flops': 2.0 * M * N * K,
                'total_bytes': (M * K + K * N + M * N) * 2,
                'arithmetic_intensity': 0.0,
                'ridge_point': 0.0,
                'is_compute_bound': False,
                'attainable_tflops': 0.0,
                'estimated_time_ms': 0.0,
                'wave_utilization': 0.0,
            }

        results.append(entry)

    results.sort(key=lambda x: x['performance']['attainable_tflops'])
    return results


def main():
    output = {}
    for workload in WORKLOADS:
        M, N, K = workload
        key = f"({M},{N},{K})"
        output[key] = analyze_workload(workload, CONFIGS, GPU_CONFIG)

    with open('/app/results.json', 'w') as f:
        json.dump(output, f, indent=2)
    print(f"Predictions written to /app/results.json")
    print(f"Analyzed {len(WORKLOADS)} workloads x {len(CONFIGS)} configs")


if __name__ == '__main__':
    main()
