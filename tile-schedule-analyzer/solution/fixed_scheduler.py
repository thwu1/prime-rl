"""Tile scheduling strategies for persistent GPU kernels — corrected."""


class TileScheduler:
    """Manages tile-to-SM assignment and scheduling optimization."""

    def __init__(self, num_sms):
        self.num_sms = num_sms

    def persistent_schedule(self, num_tiles):
        """Assign tiles to SMs via round-robin distribution.

        SM i gets tiles i, i+num_sms, i+2*num_sms, ...
        Only SMs that receive at least one tile are included.
        """
        result = {}
        for tile_id in range(num_tiles):
            sm_id = tile_id % self.num_sms
            if sm_id not in result:
                result[sm_id] = []
            result[sm_id].append(tile_id)
        return result

    def find_optimal_group_size(self, grid, cache_model, candidates):
        """Find the group_size_m minimizing peak L2 cache pressure.

        Evaluates max_window_pressure (window = num_sms) for each candidate.
        Returns smallest candidate on tie.
        """
        best_g = None
        best_pressure = float("inf")
        for g in sorted(candidates):
            schedule = grid.grouped_schedule(g)
            pressure = cache_model.max_window_pressure(schedule, self.num_sms)
            if pressure < best_pressure:
                best_pressure = pressure
                best_g = g
        return best_g
