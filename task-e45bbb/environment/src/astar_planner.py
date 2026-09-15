"""A* path planner on a 2D costmap grid.

"""

import heapq
import math
import numpy as np


class AStarPlanner:
    def __init__(self, costmap, resolution):
        self.costmap = costmap
        self.resolution = resolution
        self.height, self.width = costmap.shape

    def plan(self, start, goal, lethal_cost=254):
        """Plan path from start (row, col) to goal (row, col).

        Returns (path, total_cost) where path is a list of (row, col) tuples,
        or (None, float('inf')) if no path exists.
        """
        if self.costmap[start[0], start[1]] >= lethal_cost:
            return None, float('inf')
        if self.costmap[goal[0], goal[1]] >= lethal_cost:
            return None, float('inf')

        open_set = []
        heapq.heappush(open_set, (0, start))
        came_from = {}
        g_score = {start: 0}

        # 8-connected grid movements
        neighbors = [(-1, -1), (-1, 0), (-1, 1),
                     (0, -1),           (0, 1),
                     (1, -1),  (1, 0),  (1, 1)]

        while open_set:
            _, current = heapq.heappop(open_set)

            if current == goal:
                path = [current]
                while current in came_from:
                    current = came_from[current]
                    path.append(current)
                path.reverse()
                return path, g_score[goal]

            for dr, dc in neighbors:
                nr, nc = current[0] + dr, current[1] + dc
                neighbor = (nr, nc)

                if not (0 <= nr < self.height and 0 <= nc < self.width):
                    continue
                if self.costmap[nr, nc] >= lethal_cost:
                    continue

                move_cost = self._get_move_cost(current, neighbor)
                tentative_g = g_score[current] + move_cost

                if tentative_g < g_score.get(neighbor, float('inf')):
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f_score = tentative_g + self._heuristic(neighbor, goal)
                    heapq.heappush(open_set, (f_score, neighbor))

        return None, float('inf')

    def _heuristic(self, a, b):
        """Admissible heuristic for A*.

        TODO: Implement a proper admissible heuristic that estimates
        the minimum cost to reach goal b from cell a.
        Currently returns 0, which makes A* degrade to Dijkstra's
        algorithm (correct but inefficient).
        """
        return 0

    def _get_move_cost(self, current, neighbor):
        """Compute cost of moving from current cell to neighbor.

        TODO: The move cost should account for both the geometric
        (Euclidean) step distance AND the costmap traversal cost at
        the destination cell. Currently only uses geometric distance,
        ignoring costmap costs entirely. This causes the planner to
        find geometrically short paths that may cut through high-cost
        inflated zones near obstacles.

        The costmap value at each cell ranges from 0 (free) to 253
        (inscribed). Scale the costmap contribution by
        (costmap_value / 253.0) * resolution to keep it proportional.
        """
        dr = abs(current[0] - neighbor[0])
        dc = abs(current[1] - neighbor[1])
        base_cost = math.sqrt(dr**2 + dc**2) * self.resolution
        return base_cost
