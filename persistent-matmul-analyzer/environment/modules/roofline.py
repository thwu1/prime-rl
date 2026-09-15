
import math


def roofline_estimate(M, N, K, config, gpu_specs, dtype_bytes=2):
    """Estimate kernel performance using the roofline model."""
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

    compute_ceiling = peak_flops
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
