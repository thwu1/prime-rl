"""Navigation pipeline entry point.

Processes warehouse environment data to generate an optimal
multi-waypoint route plan with safety-aware costmap.
Stores intermediate results in SQLite via db_manager.

"""

import json
import math
import sys
import yaml
import numpy as np

from map_loader import MapLoader
from costmap import CostmapInflation
from transforms import Transform2D
from planner import PathPlanner
from router import RouteOptimizer
from db_manager import PipelineDB


def compute_footprint_radii(footprint):
    """Compute inscribed and circumscribed radii from polygon footprint.

    inscribed_radius: minimum distance from origin to any edge.
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
    db_path = '/app/pipeline.db'
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == '--db' and i + 1 < len(args):
            db_path = args[i + 1]

    db = PipelineDB(db_path)

    map_data = MapLoader('/app/map/warehouse.yaml')

    with open('/app/config/nav_params.yaml') as f:
        nav_params = yaml.safe_load(f)

    footprint = nav_params['robot']['footprint']
    cost_scaling = nav_params['costmap']['cost_scaling_factor']
    inflation_radius = nav_params['costmap']['inflation_radius']
    lethal_cost = nav_params['costmap']['lethal_cost']
    inscribed_cost = nav_params['costmap']['inscribed_cost']

    inscribed_r, circumscribed_r = compute_footprint_radii(footprint)

    inflation = CostmapInflation(
        map_data, inscribed_r, inflation_radius,
        cost_scaling, lethal_cost=lethal_cost, inscribed_cost=inscribed_cost
    )
    costmap = inflation.inflate()

    # Compute costmap statistics and persist to database
    lethal_count = int(np.sum(costmap == lethal_cost))
    inflated_count = int(np.count_nonzero(costmap))
    max_cost_val = float(np.max(costmap))
    coverage = round(float(np.count_nonzero(costmap)) / costmap.size, 6)
    db.store_costmap_stats(lethal_count, inflated_count, max_cost_val, coverage)

    # Coordinate frame transforms
    tf = nav_params['transforms']
    map_to_odom = Transform2D(tf['map_to_odom']['x'], tf['map_to_odom']['y'],
                              tf['map_to_odom']['theta'])
    odom_to_base = Transform2D(tf['odom_to_base']['x'], tf['odom_to_base']['y'],
                               tf['odom_to_base']['theta'])
    map_to_base = map_to_odom.compose(odom_to_base)
    test_point = tuple(tf['test_point'])
    test_output = map_to_base.transform_point(*test_point)

    # Persist transforms to database
    db.store_transform('map_to_odom', map_to_odom.x, map_to_odom.y,
                       map_to_odom.theta)
    db.store_transform('odom_to_base', odom_to_base.x, odom_to_base.y,
                       odom_to_base.theta)
    db.store_transform('composed', map_to_base.x, map_to_base.y,
                       map_to_base.theta)

    # Route planning
    with open('/app/mission/waypoints.yaml') as f:
        mission = yaml.safe_load(f)

    start = (mission['start']['x'], mission['start']['y'])
    waypoints = [(w['id'], w['x'], w['y']) for w in mission['waypoints']]

    planner = PathPlanner(costmap, map_data.resolution)
    optimizer = RouteOptimizer(planner, map_data)
    ordered, total_cost, path_cache, cost_matrix = optimizer.plan_route(
        start, waypoints)

    segment_costs = []
    current_id = 'start'
    for wp_id in ordered:
        seg_cost = cost_matrix.get((current_id, wp_id), 0)
        segment_costs.append({
            "from": current_id,
            "to": wp_id,
            "cost": round(seg_cost, 4)
        })
        current_id = wp_id

    # Persist route to database
    db.store_route(ordered, round(total_cost, 4), segment_costs)

    # Read costmap analysis back from database for final output
    costmap_from_db = db.get_costmap_stats()

    results = {
        "robot_geometry": {
            "inscribed_radius": round(inscribed_r, 6),
            "circumscribed_radius": round(circumscribed_r, 6),
            "footprint_vertices": footprint
        },
        "costmap_analysis": costmap_from_db,
        "transform_chain": {
            "map_to_odom": {
                "x": round(map_to_odom.x, 6),
                "y": round(map_to_odom.y, 6),
                "theta": round(map_to_odom.theta, 6)
            },
            "odom_to_base": {
                "x": round(odom_to_base.x, 6),
                "y": round(odom_to_base.y, 6),
                "theta": round(odom_to_base.theta, 6)
            },
            "composed": {
                "x": round(map_to_base.x, 6),
                "y": round(map_to_base.y, 6),
                "theta": round(map_to_base.theta, 6)
            },
            "test_point_input": list(test_point),
            "test_point_output": [
                round(test_output[0], 6),
                round(test_output[1], 6)
            ]
        },
        "route_plan": {
            "waypoint_order": ordered,
            "total_cost": round(total_cost, 4),
            "segment_costs": segment_costs
        }
    }

    db.close()

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Pipeline complete. Results written to /app/results.json")
    print("Database: {}".format(db_path))


if __name__ == '__main__':
    main()
