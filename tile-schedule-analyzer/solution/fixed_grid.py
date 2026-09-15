"""Tile grid management for blocked matrix multiplication — corrected."""


class TileGrid:
    """Models the 2D tile grid for a blocked matmul C = A @ B."""

    def __init__(self, M, N, K, block_m, block_n, block_k):
        self.M = M
        self.N = N
        self.K = K
        self.block_m = block_m
        self.block_n = block_n
        self.block_k = block_k
        self.num_pid_m = M // block_m
        self.num_pid_n = N // block_n
        self.k_tiles = K // block_k
        self.total_tiles = self.num_pid_m * self.num_pid_n

    def naive_schedule(self):
        """Row-major tile ordering."""
        return [(i, j) for i in range(self.num_pid_m) for j in range(self.num_pid_n)]

    def grouped_schedule(self, group_size_m):
        """Grouped/swizzled tile ordering for improved L2 cache locality.

        Tiles are processed column-major within groups of group_size_m rows,
        so that nearby tiles share A-row and B-column stripes in L2.
        """
        return [self.grouped_tile_id(pid, group_size_m)
                for pid in range(self.total_tiles)]

    def grouped_tile_id(self, pid, group_size_m):
        """Map linear program ID to 2D tile coordinates under grouped ordering.

        Uses the standard swizzled mapping: divide the M-dimension into groups
        of group_size_m rows. Within each group, iterate column-major. The last
        group may have fewer rows if num_pid_m is not divisible by group_size_m.
        """
        num_pid_in_group = group_size_m * self.num_pid_n
        group_id = pid // num_pid_in_group
        first_pid_m = group_id * group_size_m
        actual_group_size = min(self.num_pid_m - first_pid_m, group_size_m)
        pid_in_group = pid % num_pid_in_group
        pid_m = first_pid_m + (pid_in_group % actual_group_size)
        pid_n = pid_in_group // actual_group_size
        return (pid_m, pid_n)
