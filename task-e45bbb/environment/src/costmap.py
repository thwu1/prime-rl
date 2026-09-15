"""Costmap inflation layer for safety-aware navigation.

"""

import numpy as np
import math


class CostmapInflation:
    def __init__(self, map_loader, inscribed_radius, inflation_radius,
                 cost_scaling_factor, lethal_cost=254, inscribed_cost=253):
        self.map = map_loader
        self.inscribed_radius = inscribed_radius
        self.inflation_radius = inflation_radius
        self.cost_scaling_factor = cost_scaling_factor
        self.lethal_cost = lethal_cost
        self.inscribed_cost = inscribed_cost

    def inflate(self):
        """Generate inflated costmap from the occupancy grid."""
        height, width = self.map.grid.shape
        costmap = np.zeros((height, width), dtype=np.float64)

        occupied = np.argwhere(self.map.grid >= 65)
        inflation_cells = int(self.inflation_radius / self.map.resolution)

        for oc in occupied:
            r, c = oc
            costmap[r, c] = self.lethal_cost

            for dr in range(-inflation_cells, inflation_cells + 1):
                for dc in range(-inflation_cells, inflation_cells + 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < height and 0 <= nc < width:
                        dist = math.sqrt(dr**2 + dc**2) * self.map.resolution
                        cost = self._compute_cost(dist)
                        if cost > costmap[nr, nc]:
                            costmap[nr, nc] = cost

        return costmap

    def _compute_cost(self, distance):
        """Compute inflation cost at a given distance from the nearest obstacle."""
        if distance == 0:
            return self.lethal_cost
        elif distance <= self.inscribed_radius:
            return self.inscribed_cost
        elif distance <= self.inflation_radius:
            factor = math.exp(
                -self.cost_scaling_factor * (distance * self.inscribed_radius)
            )
            return max(1, int((self.inscribed_cost - 1) * factor))
        return 0
