"""L2 cache behavior model for tiled matrix multiplication."""


class L2CacheModel:
    """Models L2 cache working set and DRAM traffic for tile sequences.

    During blocked matmul, each output tile (i, j) reads:
      - A-row stripe i: all k_tiles blocks from row i of matrix A
      - B-column stripe j: all k_tiles blocks from column j of matrix B

    Tiles that share a row index reuse the same A-stripe; tiles sharing a
    column index reuse the same B-stripe. The L2 cache working set is the
    number of distinct stripes that must be resident simultaneously.
    """

    def __init__(self, k_tiles):
        self.k_tiles = k_tiles

    def working_set(self, tiles):
        """Count of distinct A-row and B-column stripes referenced by tiles.

        For a tile list [(i1,j1), (i2,j2), ...], this is the number of
        unique row indices plus the number of unique column indices.
        """
        row_count = len([t[0] for t in tiles])
        col_count = len([t[1] for t in tiles])
        return row_count + col_count

    def dram_loads(self, tiles):
        """Total DRAM-to-L2 block transfers for a set of tiles.

        Each distinct stripe consists of k_tiles sub-blocks that must be
        loaded from DRAM if not already in L2.
        """
        return self.working_set(tiles) * self.k_tiles

    def max_window_pressure(self, schedule, window_size):
        """Peak L2 working set over all sliding windows of consecutive tiles.

        Simulates a scenario where window_size tiles execute concurrently
        (e.g., across all SMs) and their combined working set must fit in L2.
        Returns the maximum working set across all possible windows.
        """
        if window_size >= len(schedule):
            return self.working_set(schedule)
        max_ws = 0
        for start in range(len(schedule) - window_size + 1):
            window = schedule[start:start + window_size]
            ws = self.working_set(window)
            if ws > max_ws:
                max_ws = ws
        return max_ws
