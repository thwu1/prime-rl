#!/usr/bin/env python3
"""
Solution: Create all corrected application files and expected output.


This script writes correct versions of all application files to /app/,
including the expected_output.json computed from the correct algorithms.
It does NOT depend on any pre-existing files at /app/.

Defects fixed:
1. tile_scheduler.py: compute_tile_position must use
   actual_group_size = min(num_pid_m - first_pid_m, group_size_m)
   for partial last groups.

2. resource_model.py: B tile uses block_k x block_n, not block_m x block_n.

3. roofline.py: total_bytes must include output matrix (M*N).

4. roofline.py: num_waves must use math.ceil, not floor division.

5. predict.py: sort must be descending (reverse=True).
"""

import os
import sys
import json
import math

os.makedirs('/app', exist_ok=True)

# ============================================================
# 1. Write gpu_config.py
# ============================================================
with open('/app/gpu_config.py', 'w') as f:
    f.write('''\
# GPU Hardware Configuration (NVIDIA A100-80GB SXM)
GPU_CONFIG = {
    'name': 'A100-80GB',
    'num_sms': 108,
    'shared_mem_per_sm': 167936,            # 164 KB total per SM
    'max_shared_mem_per_block': 167936,      # 164 KB (with opt-in)
    'max_warps_per_sm': 64,
    'max_blocks_per_sm': 32,
    'fp16_peak_tflops': 312.0,              # FP16 Tensor Core peak
    'memory_bw_gbps': 2039.0,              # HBM2e bandwidth
}
''')

# ============================================================
# 2. Write workloads.py
# ============================================================
with open('/app/workloads.py', 'w') as f:
    f.write('''\
# Matrix multiplication workloads and kernel tuning configurations

WORKLOADS = [
    (4096, 4096, 4096),
    (2048, 4096, 1024),
    (1024, 1024, 8192),
    (768, 2048, 4096),
    (512, 512, 512),
    (256, 8192, 256),
]

CONFIGS = [
    {'BLOCK_M': 128, 'BLOCK_N': 128, 'BLOCK_K': 64,  'GROUP_SIZE_M': 8, 'num_stages': 3, 'num_warps': 4},
    {'BLOCK_M': 128, 'BLOCK_N': 256, 'BLOCK_K': 64,  'GROUP_SIZE_M': 8, 'num_stages': 3, 'num_warps': 8},
    {'BLOCK_M': 128, 'BLOCK_N': 128, 'BLOCK_K': 128, 'GROUP_SIZE_M': 8, 'num_stages': 4, 'num_warps': 4},
    {'BLOCK_M': 128, 'BLOCK_N': 256, 'BLOCK_K': 128, 'GROUP_SIZE_M': 8, 'num_stages': 2, 'num_warps': 8},
    {'BLOCK_M': 128, 'BLOCK_N': 128, 'BLOCK_K': 64,  'GROUP_SIZE_M': 8, 'num_stages': 2, 'num_warps': 8},
    {'BLOCK_M': 64,  'BLOCK_N': 64,  'BLOCK_K': 64,  'GROUP_SIZE_M': 8, 'num_stages': 4, 'num_warps': 4},
]
''')

# ============================================================
# 3. Write tile_scheduler.py (CORRECTED)
# ============================================================
with open('/app/tile_scheduler.py', 'w') as f:
    f.write('''\
"""Tile scheduling for persistent GPU matmul kernels.

Maps linear tile IDs to 2D grid positions using grouped ordering,
and builds SM-to-tile assignment schedules for persistent execution.
"""
import math


def compute_tile_position(tile_id, num_pid_m, num_pid_n, group_size_m):
    """Map a linear tile ID to 2D tile position (pid_m, pid_n)
    using grouped ordering for L2 cache locality."""
    num_pid_in_group = group_size_m * num_pid_n
    group_id = tile_id // num_pid_in_group
    first_pid_m = group_id * group_size_m
    actual_group_size = min(num_pid_m - first_pid_m, group_size_m)
    pid_m = first_pid_m + (tile_id % actual_group_size)
    pid_n = (tile_id % num_pid_in_group) // actual_group_size
    return pid_m, pid_n


def build_persistent_schedule(M, N, block_m, block_n, group_size_m, num_sms):
    """Compute the tile schedule for a persistent matmul kernel.

    Each active SM processes tiles in a strided round-robin pattern.
    Returns schedule metadata including tile counts and SM utilization.
    """
    num_pid_m = math.ceil(M / block_m)
    num_pid_n = math.ceil(N / block_n)
    num_tiles = num_pid_m * num_pid_n
    active_sms = min(num_sms, num_tiles)

    schedule = {}
    for sm_id in range(active_sms):
        tiles = []
        for tile_id in range(sm_id, num_tiles, active_sms):
            pid_m, pid_n = compute_tile_position(tile_id, num_pid_m, num_pid_n, group_size_m)
            tiles.append((pid_m, pid_n))
        schedule[sm_id] = tiles

    tiles_per_sm_max = math.ceil(num_tiles / active_sms) if active_sms > 0 else 0
    tiles_per_sm_avg = num_tiles / active_sms if active_sms > 0 else 0.0

    return {
        'num_pid_m': num_pid_m,
        'num_pid_n': num_pid_n,
        'num_tiles': num_tiles,
        'active_sms': active_sms,
        'tiles_per_sm_avg': tiles_per_sm_avg,
        'tiles_per_sm_max': tiles_per_sm_max,
        'schedule': schedule,
    }
''')

# ============================================================
# 4. Write resource_model.py (CORRECTED)
# ============================================================
with open('/app/resource_model.py', 'w') as f:
    f.write('''\
"""Hardware resource calculations for GPU matmul kernels.

Computes shared memory requirements and SM occupancy for
different kernel tile configurations.
"""


def compute_shared_memory(block_m, block_n, block_k, num_stages, dtype_bytes=2):
    """Calculate total shared memory for a pipelined matmul tile configuration.

    Each pipeline stage holds one tile of each input matrix:
      A tile: block_m x block_k elements
      B tile: block_k x block_n elements
    Total = (A_tile + B_tile) * dtype_bytes * num_stages
    """
    a_tile = block_m * block_k * dtype_bytes
    b_tile = block_k * block_n * dtype_bytes
    return (a_tile + b_tile) * num_stages


def compute_occupancy(shared_mem_per_block, num_warps, gpu_config):
    """Calculate max concurrent blocks per SM given resource constraints.

    Returns 0 if the configuration exceeds per-block shared memory limit.
    """
    if shared_mem_per_block > gpu_config['max_shared_mem_per_block']:
        return 0

    if shared_mem_per_block > 0:
        blocks_by_smem = gpu_config['shared_mem_per_sm'] // shared_mem_per_block
    else:
        blocks_by_smem = gpu_config['max_blocks_per_sm']

    blocks_by_warps = gpu_config['max_warps_per_sm'] // num_warps
    blocks_by_limit = gpu_config['max_blocks_per_sm']

    return min(blocks_by_smem, blocks_by_warps, blocks_by_limit)
''')

# ============================================================
# 5. Write roofline.py (CORRECTED)
# ============================================================
with open('/app/roofline.py', 'w') as f:
    f.write('''\
"""Roofline performance model for GPU matmul kernels.

Estimates attainable throughput based on compute ceiling,
memory bandwidth, SM utilization, and wave quantization.
"""
import math


def estimate_performance(M, N, K, config, gpu_config, dtype_bytes=2):
    """Estimate kernel throughput using the roofline model.

    Accounts for SM utilization (when fewer tiles than SMs) and
    wave quantization (idle SMs in the last wave).
    """
    total_flops = 2.0 * M * N * K
    total_bytes = (M * K + K * N + M * N) * dtype_bytes
    arithmetic_intensity = total_flops / total_bytes

    peak_flops = gpu_config['fp16_peak_tflops'] * 1e12
    mem_bw = gpu_config['memory_bw_gbps'] * 1e9
    ridge_point = peak_flops / mem_bw

    num_pid_m = math.ceil(M / config['BLOCK_M'])
    num_pid_n = math.ceil(N / config['BLOCK_N'])
    num_tiles = num_pid_m * num_pid_n
    active_sms = min(gpu_config['num_sms'], num_tiles)

    sm_util = active_sms / gpu_config['num_sms']
    compute_ceiling = peak_flops * sm_util
    memory_ceiling = mem_bw * arithmetic_intensity

    is_compute_bound = compute_ceiling <= memory_ceiling
    base_attainable = min(compute_ceiling, memory_ceiling)

    num_waves = math.ceil(num_tiles / active_sms)
    wave_util = num_tiles / (num_waves * active_sms) if num_waves > 0 else 1.0

    attainable_flops = base_attainable * wave_util
    attainable_tflops = attainable_flops / 1e12
    estimated_time_ms = (total_flops / attainable_flops * 1e3) if attainable_flops > 0 else 0.0

    return {
        'total_flops': total_flops,
        'total_bytes': total_bytes,
        'arithmetic_intensity': arithmetic_intensity,
        'ridge_point': ridge_point,
        'is_compute_bound': is_compute_bound,
        'attainable_tflops': attainable_tflops,
        'estimated_time_ms': estimated_time_ms,
        'wave_utilization': wave_util,
    }
''')

# ============================================================
# 6. Write predict.py (CORRECTED)
# ============================================================
with open('/app/predict.py', 'w') as f:
    f.write('''\
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

    results.sort(key=lambda x: x['performance']['attainable_tflops'], reverse=True)
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
''')

# ============================================================
# 7. Write validate.py
# ============================================================
with open('/app/validate.py', 'w') as f:
    f.write('''\
#!/usr/bin/env python3
"""Validate predictor output against expected results."""
import json
import sys
import os


def load_json(path):
    with open(path) as f:
        return json.load(f)


def compare_results(expected, actual):
    """Compare actual results against expected, return list of failure messages."""
    failures = []

    exp_keys = set(expected.keys())
    act_keys = set(actual.keys())

    if exp_keys != act_keys:
        missing = exp_keys - act_keys
        extra = act_keys - exp_keys
        if missing:
            failures.append(f"Missing workloads: {missing}")
        if extra:
            failures.append(f"Unexpected workloads: {extra}")
        return failures

    for wk_key in sorted(expected.keys()):
        exp_configs = expected[wk_key]
        act_configs = actual[wk_key]

        if len(exp_configs) != len(act_configs):
            failures.append(f"{wk_key}: expected {len(exp_configs)} configs, got {len(act_configs)}")
            continue

        for idx, (ec, ac) in enumerate(zip(exp_configs, act_configs)):
            prefix = f"{wk_key} rank {idx}"

            if ec['config_id'] != ac['config_id']:
                failures.append(
                    f"{prefix}: wrong config at this rank -- expected config_id {ec['config_id']}, "
                    f"got {ac['config_id']}")

            if ec['is_valid'] != ac['is_valid']:
                failures.append(
                    f"{prefix} (config {ac['config_id']}): validity mismatch -- "
                    f"expected {ec['is_valid']}, got {ac['is_valid']}")

            if ec['shared_mem_bytes'] != ac['shared_mem_bytes']:
                failures.append(
                    f"{prefix} (config {ac['config_id']}): shared_mem_bytes -- "
                    f"expected {ec['shared_mem_bytes']}, got {ac['shared_mem_bytes']}")

            if ec['occupancy'] != ac['occupancy']:
                failures.append(
                    f"{prefix} (config {ac['config_id']}): occupancy -- "
                    f"expected {ec['occupancy']}, got {ac['occupancy']}")

            ep = ec['performance']
            ap = ac['performance']

            for field in ['total_flops', 'total_bytes', 'is_compute_bound']:
                if ep[field] != ap[field]:
                    failures.append(
                        f"{prefix} (config {ac['config_id']}): {field} -- "
                        f"expected {ep[field]}, got {ap[field]}")

            for field in ['arithmetic_intensity', 'attainable_tflops',
                          'estimated_time_ms', 'wave_utilization', 'ridge_point']:
                ev = ep[field]
                av = ap[field]
                if ev == 0 and av == 0:
                    continue
                if ev == 0 or abs(ev - av) / max(abs(ev), 1e-15) > 0.001:
                    failures.append(
                        f"{prefix} (config {ac['config_id']}): {field} -- "
                        f"expected {ev:.6g}, got {av:.6g}")

            if ec['is_valid'] and ac['is_valid']:
                es = ec['schedule_info']
                as_ = ac['schedule_info']
                if as_ is None:
                    failures.append(f"{prefix}: schedule_info missing for valid config")
                else:
                    for field in ['num_pid_m', 'num_pid_n', 'num_tiles',
                                  'active_sms', 'tiles_per_sm_max']:
                        if es[field] != as_[field]:
                            failures.append(
                                f"{prefix} (config {ac['config_id']}): schedule {field} -- "
                                f"expected {es[field]}, got {as_[field]}")

    return failures


def main():
    expected_path = '/app/expected_output.json'
    results_path = '/app/results.json'

    if not os.path.exists(results_path):
        print("ERROR: /app/results.json not found. Run: python3 /app/predict.py")
        sys.exit(1)

    expected = load_json(expected_path)
    actual = load_json(results_path)

    failures = compare_results(expected, actual)

    if not failures:
        print("PASS: All predictions match expected output.")
        sys.exit(0)
    else:
        print(f"FAIL: {len(failures)} discrepancies found:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)


if __name__ == '__main__':
    main()
''')

# ============================================================
# 8. Generate and write expected_output.json
# ============================================================

GPU_CONFIG = {
    'name': 'A100-80GB',
    'num_sms': 108,
    'shared_mem_per_sm': 167936,
    'max_shared_mem_per_block': 167936,
    'max_warps_per_sm': 64,
    'max_blocks_per_sm': 32,
    'fp16_peak_tflops': 312.0,
    'memory_bw_gbps': 2039.0,
}

WORKLOADS = [
    (4096, 4096, 4096),
    (2048, 4096, 1024),
    (1024, 1024, 8192),
    (768, 2048, 4096),
    (512, 512, 512),
    (256, 8192, 256),
]

CONFIGS = [
    {'BLOCK_M': 128, 'BLOCK_N': 128, 'BLOCK_K': 64,  'GROUP_SIZE_M': 8, 'num_stages': 3, 'num_warps': 4},
    {'BLOCK_M': 128, 'BLOCK_N': 256, 'BLOCK_K': 64,  'GROUP_SIZE_M': 8, 'num_stages': 3, 'num_warps': 8},
    {'BLOCK_M': 128, 'BLOCK_N': 128, 'BLOCK_K': 128, 'GROUP_SIZE_M': 8, 'num_stages': 4, 'num_warps': 4},
    {'BLOCK_M': 128, 'BLOCK_N': 256, 'BLOCK_K': 128, 'GROUP_SIZE_M': 8, 'num_stages': 2, 'num_warps': 8},
    {'BLOCK_M': 128, 'BLOCK_N': 128, 'BLOCK_K': 64,  'GROUP_SIZE_M': 8, 'num_stages': 2, 'num_warps': 8},
    {'BLOCK_M': 64,  'BLOCK_N': 64,  'BLOCK_K': 64,  'GROUP_SIZE_M': 8, 'num_stages': 4, 'num_warps': 4},
]


def _compute_shared_memory(block_m, block_n, block_k, num_stages, dtype_bytes=2):
    a_tile = block_m * block_k * dtype_bytes
    b_tile = block_k * block_n * dtype_bytes
    return (a_tile + b_tile) * num_stages


def _compute_occupancy(shared_mem_per_block, num_warps, gpu_config):
    if shared_mem_per_block > gpu_config['max_shared_mem_per_block']:
        return 0
    if shared_mem_per_block > 0:
        blocks_by_smem = gpu_config['shared_mem_per_sm'] // shared_mem_per_block
    else:
        blocks_by_smem = gpu_config['max_blocks_per_sm']
    blocks_by_warps = gpu_config['max_warps_per_sm'] // num_warps
    blocks_by_limit = gpu_config['max_blocks_per_sm']
    return min(blocks_by_smem, blocks_by_warps, blocks_by_limit)


def _estimate_performance(M, N, K, config, gpu_config, dtype_bytes=2):
    total_flops = 2.0 * M * N * K
    total_bytes = (M * K + K * N + M * N) * dtype_bytes
    arithmetic_intensity = total_flops / total_bytes
    peak_flops = gpu_config['fp16_peak_tflops'] * 1e12
    mem_bw = gpu_config['memory_bw_gbps'] * 1e9
    ridge_point = peak_flops / mem_bw
    num_pid_m = math.ceil(M / config['BLOCK_M'])
    num_pid_n = math.ceil(N / config['BLOCK_N'])
    num_tiles = num_pid_m * num_pid_n
    active_sms = min(gpu_config['num_sms'], num_tiles)
    sm_util = active_sms / gpu_config['num_sms']
    compute_ceiling = peak_flops * sm_util
    memory_ceiling = mem_bw * arithmetic_intensity
    is_compute_bound = compute_ceiling <= memory_ceiling
    base_attainable = min(compute_ceiling, memory_ceiling)
    num_waves = math.ceil(num_tiles / active_sms)
    wave_util = num_tiles / (num_waves * active_sms) if num_waves > 0 else 1.0
    attainable_flops = base_attainable * wave_util
    attainable_tflops = attainable_flops / 1e12
    estimated_time_ms = (total_flops / attainable_flops * 1e3) if attainable_flops > 0 else 0.0
    return {
        'total_flops': total_flops,
        'total_bytes': total_bytes,
        'arithmetic_intensity': arithmetic_intensity,
        'ridge_point': ridge_point,
        'is_compute_bound': is_compute_bound,
        'attainable_tflops': attainable_tflops,
        'estimated_time_ms': estimated_time_ms,
        'wave_utilization': wave_util,
    }


def _build_schedule(M, N, block_m, block_n, group_size_m, num_sms):
    num_pid_m = math.ceil(M / block_m)
    num_pid_n = math.ceil(N / block_n)
    num_tiles = num_pid_m * num_pid_n
    active_sms = min(num_sms, num_tiles)
    tiles_per_sm_max = math.ceil(num_tiles / active_sms) if active_sms > 0 else 0
    tiles_per_sm_avg = num_tiles / active_sms if active_sms > 0 else 0.0
    return {
        'num_pid_m': num_pid_m,
        'num_pid_n': num_pid_n,
        'num_tiles': num_tiles,
        'active_sms': active_sms,
        'tiles_per_sm_avg': tiles_per_sm_avg,
        'tiles_per_sm_max': tiles_per_sm_max,
    }


def _analyze_workload(workload, configs, gpu_config):
    M, N, K = workload
    results = []
    for i, config in enumerate(configs):
        entry = {'config': config, 'config_id': i}
        smem = _compute_shared_memory(config['BLOCK_M'], config['BLOCK_N'],
                                       config['BLOCK_K'], config['num_stages'])
        entry['shared_mem_bytes'] = smem
        occ = _compute_occupancy(smem, config['num_warps'], gpu_config)
        entry['occupancy'] = occ
        entry['is_valid'] = occ > 0
        if entry['is_valid']:
            sched = _build_schedule(M, N, config['BLOCK_M'], config['BLOCK_N'],
                                    config['GROUP_SIZE_M'], gpu_config['num_sms'])
            entry['schedule_info'] = sched
            perf = _estimate_performance(M, N, K, config, gpu_config)
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
    results.sort(key=lambda x: x['performance']['attainable_tflops'], reverse=True)
    return results


output = {}
for workload in WORKLOADS:
    M, N, K = workload
    key = f"({M},{N},{K})"
    output[key] = _analyze_workload(workload, CONFIGS, GPU_CONFIG)

with open('/app/expected_output.json', 'w') as f:
    json.dump(output, f, indent=2)

print("All corrected files written to /app/")
print("expected_output.json generated from correct algorithms")
