"""Tile scheduling strategies for persistent GPU kernels."""


class TileScheduler:
    """Manages tile-to-SM assignment and scheduling optimization."""

    def __init__(self, num_sms):
        self.num_sms = num_sms

    def persistent_schedule(self, num_tiles):
        """Assign tiles to SMs for persistent kernel execution.

        In a persistent kernel, each SM runs for the entire kernel lifetime
        and pulls new tiles from a work queue. Tiles should be distributed
        evenly across SMs in round-robin fashion.

        Returns a dict mapping SM id -> list of tile indices assigned to it.
        Only include SMs that receive at least one tile.
        """
        raise NotImplementedError("persistent_schedule not yet implemented")

    def find_optimal_group_size(self, grid, cache_model, candidates):
        """Search for the group_size_m that minimizes peak L2 cache pressure.

        For each candidate group size, generate the corresponding tile schedule
        and measure its maximum L2 working set over sliding windows of size
        num_sms. Return the candidate with the lowest peak pressure.

        On ties, return the smallest candidate value.
        """
        raise NotImplementedError("find_optimal_group_size not yet implemented")
