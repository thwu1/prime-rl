"""
GPU Persistent MatMul Performance Prediction System — Complete Implementation

"""

import math
import sqlite3
import json


def compute_tile_position(tile_id, num_pid_m, num_pid_n, group_size_m):
    num_pid_in_group = group_size_m * num_pid_n
    group_id = tile_id // num_pid_in_group
    first_pid_m = group_id * group_size_m
    actual_group_size = min(num_pid_m - first_pid_m, group_size_m)
    pid_m = first_pid_m + (tile_id % actual_group_size)
    pid_n = (tile_id % num_pid_in_group) // actual_group_size
    return pid_m, pid_n


def compute_shared_memory(block_m, block_n, block_k, num_stages, dtype_bytes=2):
    a_tile = block_m * block_k * dtype_bytes
    b_tile = block_k * block_n * dtype_bytes
    return (a_tile + b_tile) * num_stages


def compute_occupancy(shared_mem_per_block, num_warps, gpu_specs):
    if shared_mem_per_block > gpu_specs['max_shared_mem_per_block']:
        return 0
    if shared_mem_per_block > 0:
        blocks_by_smem = gpu_specs['shared_mem_per_sm'] // shared_mem_per_block
    else:
        blocks_by_smem = gpu_specs['max_blocks_per_sm']
    blocks_by_warps = gpu_specs['max_warps_per_sm'] // num_warps
    blocks_by_limit = gpu_specs['max_blocks_per_sm']
    return min(blocks_by_smem, blocks_by_warps, blocks_by_limit)


def build_persistent_schedule(M, N, block_m, block_n, group_size_m, num_sms):
    num_pid_m = math.ceil(M / block_m)
    num_pid_n = math.ceil(N / block_n)
    num_tiles = num_pid_m * num_pid_n
    active_sms = min(num_sms, num_tiles)
    tiles_per_sm_max = math.ceil(num_tiles / active_sms) if active_sms > 0 else 0
    return {
        'num_pid_m': num_pid_m,
        'num_pid_n': num_pid_n,
        'num_tiles': num_tiles,
        'active_sms': active_sms,
        'tiles_per_sm_max': tiles_per_sm_max,
        'group_size_m': group_size_m,
    }


def roofline_estimate(M, N, K, config, gpu_specs, dtype_bytes=2):
    total_flops = 2.0 * M * N * K
    total_bytes = (M * K + K * N + M * N) * dtype_bytes
    arithmetic_intensity = total_flops / total_bytes

    peak_flops = gpu_specs['fp16_peak_tflops'] * 1e12
    mem_bw = gpu_specs['memory_bw_gbps'] * 1e9
    ridge_point = peak_flops / mem_bw

    num_pid_m = math.ceil(M / config['BLOCK_M'])
    num_pid_n = math.ceil(N / config['BLOCK_N'])
    num_tiles = num_pid_m * num_pid_n
    active_sms = min(int(gpu_specs['num_sms']), num_tiles)

    sm_util = active_sms / gpu_specs['num_sms']
    compute_ceiling = peak_flops * sm_util
    memory_ceiling = mem_bw * arithmetic_intensity

    is_compute_bound = compute_ceiling <= memory_ceiling
    base_attainable = min(compute_ceiling, memory_ceiling)

    num_waves = math.ceil(num_tiles / active_sms) if active_sms > 0 else 0
    wave_util = num_tiles / (num_waves * active_sms) if num_waves > 0 else 1.0
    wave_util = min(wave_util, 1.0)

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


def analyze_workload(M, N, K, configs, gpu_specs):
    results = []
    for config in configs:
        entry = {'config_id': config['config_id']}

        smem = compute_shared_memory(
            config['BLOCK_M'], config['BLOCK_N'],
            config['BLOCK_K'], config['num_stages'])
        entry['shared_mem_bytes'] = smem

        occ = compute_occupancy(smem, config['num_warps'], gpu_specs)
        entry['occupancy'] = occ
        entry['is_valid'] = occ > 0

        if entry['is_valid']:
            sched = build_persistent_schedule(
                M, N, config['BLOCK_M'], config['BLOCK_N'],
                config['GROUP_SIZE_M'], int(gpu_specs['num_sms']))
            entry['schedule_info'] = sched
            perf = roofline_estimate(M, N, K, config, gpu_specs)
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


def generate_results(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Read GPU specs
    gpu_specs = {}
    for name, value, unit in c.execute('SELECT spec_name, spec_value, unit FROM gpu_specs'):
        gpu_specs[name] = value

    # Read kernel configs
    configs = []
    for row in c.execute('SELECT config_id, block_m, block_n, block_k, group_size_m, num_stages, num_warps FROM kernel_configs ORDER BY config_id'):
        configs.append({
            'config_id': row[0],
            'BLOCK_M': row[1],
            'BLOCK_N': row[2],
            'BLOCK_K': row[3],
            'GROUP_SIZE_M': row[4],
            'num_stages': row[5],
            'num_warps': row[6],
        })

    # Read workloads
    workloads = []
    for row in c.execute('SELECT dim_m, dim_n, dim_k FROM workloads ORDER BY workload_id'):
        workloads.append((row[0], row[1], row[2]))

    conn.close()

    # Generate results for all workloads
    results = {}
    for M, N, K in workloads:
        key = f"({M},{N},{K})"
        results[key] = analyze_workload(M, N, K, configs, gpu_specs)

    return results
