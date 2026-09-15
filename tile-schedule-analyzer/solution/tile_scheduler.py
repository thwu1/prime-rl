#!/usr/bin/env python3
"""
GPU Kernel Tile Schedule Cache Analyzer

Implements tile scheduling analysis for blocked matrix multiplication kernels,
modeling the grouped/swizzled tile ordering used in Triton's matmul tutorial.
"""

import json


def grouped_tile_id(pid, num_pid_m, num_pid_n, group_size_m):
    """Map a linear program ID to (pid_m, pid_n) using grouped ordering.

    Programs are ordered column-major within groups of group_size_m row-tiles.
    The last group may have fewer rows if num_pid_m % group_size_m != 0.
    """
    num_pid_in_group = group_size_m * num_pid_n
    group_id = pid // num_pid_in_group
    first_pid_m = group_id * group_size_m
    group_size_m_actual = min(num_pid_m - first_pid_m, group_size_m)
    pid_m = first_pid_m + ((pid % num_pid_in_group) % group_size_m_actual)
    pid_n = (pid % num_pid_in_group) // group_size_m_actual
    return (pid_m, pid_n)


def tile_schedule(num_pid_m, num_pid_n, group_size_m):
    """Generate the complete tile execution order for all tiles."""
    total = num_pid_m * num_pid_n
    return [
        grouped_tile_id(pid, num_pid_m, num_pid_n, group_size_m)
        for pid in range(total)
    ]


def l2_working_set(tiles):
    """Count L2 working set: unique A-row-stripes + unique B-col-stripes."""
    rows = set()
    cols = set()
    for r, c in tiles:
        rows.add(r)
        cols.add(c)
    return len(rows) + len(cols)


def dram_block_loads(tiles, k_tiles):
    """Total DRAM-to-L2 block loads = working_set * k_tiles."""
    return l2_working_set(tiles) * k_tiles


def persistent_schedule(num_tiles, num_sms):
    """Distribute tile IDs across SMs for persistent kernel execution.

    SM i processes tiles i, i+num_sms, i+2*num_sms, ...
    Only includes SMs that receive at least one tile.
    """
    assignment = {}
    for sm in range(min(num_sms, num_tiles)):
        tile_list = list(range(sm, num_tiles, num_sms))
        if tile_list:
            assignment[sm] = tile_list
    return assignment


def bytes_in_flight(bandwidth_bytes_per_sec, latency_sec):
    """Little's Law: bytes_in_flight = bandwidth * latency."""
    return bandwidth_bytes_per_sec * latency_sec


def _max_l2_pressure(schedule, window_size):
    """Compute maximum L2 working set across all sliding windows."""
    n = len(schedule)
    if window_size >= n:
        return l2_working_set(schedule)
    max_pressure = 0
    for i in range(n - window_size + 1):
        window = schedule[i : i + window_size]
        pressure = l2_working_set(window)
        if pressure > max_pressure:
            max_pressure = pressure
    return max_pressure


def optimal_group_size(num_pid_m, num_pid_n, window_size, candidate_groups):
    """Find GROUP_SIZE_M minimizing max L2 working set over sliding windows.

    On ties, returns the smallest candidate.
    """
    best_group = None
    best_pressure = float("inf")
    for g in sorted(candidate_groups):
        schedule = tile_schedule(num_pid_m, num_pid_n, g)
        pressure = _max_l2_pressure(schedule, window_size)
        if pressure < best_pressure:
            best_pressure = pressure
            best_group = g
    return best_group


def analyze_configuration():
    """Run analysis on specified hardware configuration and write results."""
    M, N, K = 4096, 4096, 2048
    BLOCK_M, BLOCK_N, BLOCK_K = 128, 128, 64
    num_pid_m = M // BLOCK_M
    num_pid_n = N // BLOCK_N
    k_tiles = K // BLOCK_K
    total_tiles = num_pid_m * num_pid_n
    NUM_SMS = 132
    bandwidth_bytes_s = 3.35e12
    latency_s = 400e-9

    bif = bytes_in_flight(bandwidth_bytes_s, latency_s)

    candidates = [1, 2, 4, 8, 16, 32]
    opt_g = optimal_group_size(num_pid_m, num_pid_n, NUM_SMS, candidates)

    rm_schedule = tile_schedule(num_pid_m, num_pid_n, 1)
    rm_pressure = _max_l2_pressure(rm_schedule, NUM_SMS)

    opt_schedule = tile_schedule(num_pid_m, num_pid_n, opt_g)
    opt_pressure = _max_l2_pressure(opt_schedule, NUM_SMS)

    result = {
        "num_pid_m": num_pid_m,
        "num_pid_n": num_pid_n,
        "k_tiles": k_tiles,
        "total_tiles": total_tiles,
        "bytes_in_flight": bif,
        "optimal_group_size": opt_g,
        "row_major_max_pressure": rm_pressure,
        "optimal_max_pressure": opt_pressure,
    }

    with open("/app/analysis.json", "w") as f:
        json.dump(result, f, indent=2)

    return result


if __name__ == "__main__":
    result = analyze_configuration()
    print(json.dumps(result, indent=2))
