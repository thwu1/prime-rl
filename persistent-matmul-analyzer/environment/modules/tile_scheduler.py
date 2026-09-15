
import math


def compute_tile_position(tile_id, num_pid_m, num_pid_n, group_size_m):
    """Map linear tile ID to 2D grid position using grouped ordering."""
    num_pid_in_group = group_size_m * num_pid_n
    group_id = tile_id // num_pid_in_group
    first_pid_m = group_id * group_size_m
    actual_group_size = min(num_pid_m - first_pid_m, group_size_m)
    pid_m = first_pid_m + (tile_id % actual_group_size)
    pid_n = (tile_id % num_pid_in_group) // group_size_m
    return pid_m, pid_n
