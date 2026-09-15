"""L2 cache behavior model for tiled matrix multiplication — corrected."""


class L2CacheModel:
    """Models L2 cache working set and DRAM traffic for tile sequences."""

    def __init__(self, k_tiles):
        self.k_tiles = k_tiles

    def working_set(self, tiles):
        """Count of distinct A-row and B-column stripes referenced by tiles."""
        rows = len(set(t[0] for t in tiles))
        cols = len(set(t[1] for t in tiles))
        return rows + cols

    def dram_loads(self, tiles):
        """Total DRAM-to-L2 block transfers for a set of tiles."""
        return self.working_set(tiles) * self.k_tiles

    def max_window_pressure(self, schedule, window_size):
        """Peak L2 working set over all sliding windows of consecutive tiles."""
        if window_size >= len(schedule):
            return self.working_set(schedule)
        max_ws = 0
        for start in range(len(schedule) - window_size + 1):
            ws = self.working_set(schedule[start:start + window_size])
            if ws > max_ws:
                max_ws = ws
        return max_ws
