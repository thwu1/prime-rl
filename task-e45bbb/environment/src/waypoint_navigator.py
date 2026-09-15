"""Multi-waypoint route optimizer.

"""

from itertools import permutations


class WaypointNavigator:
    def __init__(self, planner, occupancy_grid):
        self.planner = planner
        self.grid = occupancy_grid

    def plan_route(self, start_world, waypoints_world):
        """Plan optimal route visiting all waypoints starting from start.

        Args:
            start_world: (x, y) tuple in world coordinates
            waypoints_world: list of (id, x, y) tuples

        Returns:
            ordered_waypoints: list of waypoint ids in optimal visit order
            total_cost: total path cost for the route
            path_cache: dict mapping (from_id, to_id) -> path
        """
        start_grid = self.grid.world_to_grid(start_world[0], start_world[1])
        waypoint_grids = {}
        for wp_id, x, y in waypoints_world:
            waypoint_grids[wp_id] = self.grid.world_to_grid(x, y)

        all_ids = ['start'] + [wp[0] for wp in waypoints_world]
        all_positions = {'start': start_grid}
        all_positions.update(waypoint_grids)

        # Build pairwise cost matrix
        cost_matrix = {}
        path_cache = {}

        for id1 in all_ids:
            for id2 in all_ids:
                if id1 != id2:
                    path, cost = self.planner.plan(
                        all_positions[id1], all_positions[id2]
                    )
                    cost_matrix[(id1, id2)] = cost
                    path_cache[(id1, id2)] = path

        wp_ids = [wp[0] for wp in waypoints_world]

        # TODO: Find the optimal ordering of waypoints that minimizes
        # total path cost from start through all waypoints.
        # This is a variant of the Traveling Salesman Problem (TSP).
        # For small N (<=6), brute-force over all permutations is feasible.
        # Currently returns waypoints in their original (input) order,
        # which is almost certainly suboptimal.
        ordered = wp_ids

        # Compute total cost for the chosen ordering
        total_cost = 0
        current = 'start'
        for wp_id in ordered:
            total_cost += cost_matrix.get((current, wp_id), float('inf'))
            current = wp_id

        return ordered, total_cost, path_cache
