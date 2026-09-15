"""Main navigation pipeline entry point.

"""

import json
import math
import numpy as np

from occupancy_grid import OccupancyGrid
from costmap import CostmapInflation
from frame_transforms import Transform2D
from astar_planner import AStarPlanner
from waypoint_navigator import WaypointNavigator


def compute_footprint_radii(footprint):
    """Compute inscribed and circumscribed radii from polygon footprint.

    inscribed_radius: minimum distance from origin to any edge of the polygon.
    circumscribed_radius: maximum distance from origin to any vertex.
    """
    n = len(footprint)

    circumscribed = 0.0
    for x, y in footprint:
        d = math.sqrt(x**2 + y**2)
        circumscribed = max(circumscribed, d)

    inscribed = float('inf')
    for i in range(n):
        x1, y1 = footprint[i]
        x2, y2 = footprint[(i + 1) % n]

        dx = x2 - x1
        dy = y2 - y1
        seg_len_sq = dx**2 + dy**2

        if seg_len_sq == 0:
            d = math.sqrt(x1**2 + y1**2)
        else:
            t = (-x1 * dx + -y1 * dy) / seg_len_sq
            t = max(0.0, min(1.0, t))
            closest_x = x1 + t * dx
            closest_y = y1 + t * dy
            d = math.sqrt(closest_x**2 + closest_y**2)

        inscribed = min(inscribed, d)

    return inscribed, circumscribed


def main():
    # Load occupancy grid
    og = OccupancyGrid('/app/map/warehouse_grid.npy', '/app/map/warehouse_meta.json')

    # Load robot parameters
    with open('/app/config/robot_params.json') as f:
        robot_params = json.load(f)

    footprint = robot_params['footprint']
    cost_scaling = robot_params['cost_scaling_factor']
    inflation_radius = robot_params['inflation_radius']

    # Compute radii from footprint polygon
    inscribed_r, circumscribed_r = compute_footprint_radii(footprint)
    print(f"Inscribed radius: {inscribed_r:.6f}")
    print(f"Circumscribed radius: {circumscribed_r:.6f}")

    # Create and inflate costmap
    inflation = CostmapInflation(
        og, inscribed_r, inflation_radius,
        cost_scaling, lethal_cost=254, inscribed_cost=253
    )
    costmap = inflation.inflate()
    print(f"Costmap inflated: {int(np.count_nonzero(costmap))} non-zero cells")

    # Create A* planner
    planner = AStarPlanner(costmap, og.resolution)

    # Load waypoints
    with open('/app/waypoints.json') as f:
        wp_data = json.load(f)

    start = (wp_data['start']['x'], wp_data['start']['y'])
    waypoints = [(w['id'], w['x'], w['y']) for w in wp_data['waypoints']]

    # Set up frame transforms (map -> odom -> base_link)
    map_to_odom = Transform2D(0.1, -0.05, 0.3)
    odom_to_base = Transform2D(0.5, 0.2, -0.1)
    map_to_base = map_to_odom.compose(odom_to_base)

    # Test transform chain with a known point
    test_point_base = (1.0, 0.5)
    test_point_map = map_to_base.transform_point(*test_point_base)
    print(f"Transform test: {test_point_base} -> "
          f"({test_point_map[0]:.6f}, {test_point_map[1]:.6f})")

    # Plan multi-waypoint route
    navigator = WaypointNavigator(planner, og)
    ordered, total_cost, paths = navigator.plan_route(start, waypoints)
    print(f"Waypoint order: {ordered}")
    print(f"Total path cost: {total_cost:.4f}")

    # Write results
    results = {
        'inscribed_radius': round(inscribed_r, 6),
        'circumscribed_radius': round(circumscribed_r, 6),
        'test_transform': {
            'input': list(test_point_base),
            'output': [round(test_point_map[0], 6), round(test_point_map[1], 6)]
        },
        'waypoint_order': ordered,
        'total_path_cost': round(total_cost, 4),
        'costmap_stats': {
            'max': float(np.max(costmap)),
            'nonzero_count': int(np.count_nonzero(costmap))
        }
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Navigation pipeline complete. Results written to /app/results.json")


if __name__ == '__main__':
    main()
