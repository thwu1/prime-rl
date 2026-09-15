"""Multi-waypoint route optimizer.

"""

from itertools import permutations


class RouteOptimizer:
    def __init__(self, planner, map_loader):
        self.planner = planner
        self.map = map_loader

    def plan_route(self, start_world, waypoints_world):
        """Plan route visiting all waypoints from the start position.

        Args:
            start_world: (x, y) tuple in world coordinates
            waypoints_world: list of (id, x, y) tuples

        Returns:
            ordered_ids: list of waypoint ids in visit order
            total_cost: total path cost
            path_cache: dict of computed paths
            cost_matrix: dict of pairwise costs
        """
        start_grid = self.map.world_to_grid(start_world[0], start_world[1])
        waypoint_grids = {}
        for wp_id, x, y in waypoints_world:
            waypoint_grids[wp_id] = self.map.world_to_grid(x, y)

        all_ids = ['start'] + [wp[0] for wp in waypoints_world]
        all_positions = {'start': start_grid}
        all_positions.update(waypoint_grids)

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

        ordered = wp_ids

        total_cost = 0
        current = 'start'
        for wp_id in ordered:
            total_cost += cost_matrix.get((current, wp_id), float('inf'))
            current = wp_id

        return ordered, total_cost, path_cache, cost_matrix
