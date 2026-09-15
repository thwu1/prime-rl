"""Cost model for the Volcano/Cascades query optimizer.

The cost model defines how the optimizer compares alternative physical plans.
Total cost is a weighted combination of three dimensions:
    total = cpu_weight * cpu  +  mem_weight * memory  +  time_weight * time
"""

from .types import Cost


class CostModel:
    """Multi-dimensional cost model with configurable weights."""

    cpu_weight = 1.0
    mem_weight = 0.5
    time_weight = 0.8

    def total_cost(self, cost):
        """Compute scalar total cost from the three dimensions."""
        return (self.cpu_weight * cost.cpu
                + self.mem_weight * cost.memory
                + self.time_weight * cost.time)

    def is_better(self, current_best, candidate):
        """Return True if *candidate* is cheaper than *current_best*.

        Compares weighted total costs so that memory-intensive and
        I/O-intensive plans are penalised appropriately.
        """
        return self.total_cost(candidate) > self.total_cost(current_best)
