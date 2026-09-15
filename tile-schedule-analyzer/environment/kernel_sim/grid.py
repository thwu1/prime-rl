"""Tile grid management for blocked matrix multiplication kernels."""


class TileGrid:
    """Models the 2D tile grid for a blocked matmul C = A @ B.

    Matrix C (M x N) is divided into tiles of size BLOCK_M x BLOCK_N.
    Each tile (i, j) computes C[i*bm:(i+1)*bm, j*bn:(j+1)*bn] by iterating
    over K in chunks of BLOCK_K.
    """

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
        """Row-major tile ordering -- baseline with poor L2 locality on large grids."""
        return [(i, j) for i in range(self.num_pid_m) for j in range(self.num_pid_n)]

    def grouped_schedule(self, group_size_m):
        """Generate tile execution order using grouped/swizzled ordering.

        Tiles should be ordered to improve L2 cache data reuse by processing
        clusters of nearby tiles before moving on. The group_size_m parameter
        controls how many row-tiles are grouped together.

        Must return a list of (pid_m, pid_n) tuples covering all tiles exactly once.
        """
        raise NotImplementedError("grouped_schedule not yet implemented")

    def grouped_tile_id(self, pid, group_size_m):
        """Map a linear program ID to 2D tile coordinates under grouped ordering.

        This is the inverse of the linearization: given a flat program index,
        return the (pid_m, pid_n) coordinates in the grouped execution order.
        Must be consistent with grouped_schedule.
        """
        raise NotImplementedError("grouped_tile_id not yet implemented")
