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
    pid_m = first_pid_m + (tile_id % group_size_m)
    pid_n = (tile_id % num_pid_in_group) // group_size_m
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
