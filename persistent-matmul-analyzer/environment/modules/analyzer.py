
import math

from .resource_model import compute_shared_memory, compute_occupancy
from .roofline import roofline_estimate


def build_persistent_schedule(M, N, block_m, block_n, group_size_m, num_sms):
    """Build scheduling metadata for a persistent matmul kernel."""
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


def analyze_workload(M, N, K, configs, gpu_specs):
    """Analyze all kernel configurations for a given workload."""
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
    """Read data from SQLite and analyze all workloads."""
    from .data_loader import load_gpu_specs, load_kernel_configs, load_workloads

    gpu_specs = load_gpu_specs(db_path)
    configs = load_kernel_configs(db_path)
    workloads = load_workloads(db_path)

    results = {}
    for M, N, K in workloads:
        key = f"({M},{N},{K})"
        results[key] = analyze_workload(M, N, K, configs, gpu_specs)

    return results
