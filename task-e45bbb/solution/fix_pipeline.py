"""Fix all correctness issues in the navigation pipeline.

Fixes bugs across Python modules, Makefile, and database layer.
Generates defect manifest documenting all identified issues.

"""

import json
import os


def fix_map_loader():
    """Fix coordinate conversion: world_to_grid must account for map origin."""
    content = '''\
"""Map loader for ROS2-compatible PGM + YAML map format."""

import numpy as np
import yaml
import os


class MapLoader:
    def __init__(self, yaml_path):
        with open(yaml_path) as f:
            meta = yaml.safe_load(f)

        self.resolution = meta['resolution']
        self.origin_x = meta['origin'][0]
        self.origin_y = meta['origin'][1]
        self.negate = meta.get('negate', 0)
        self.occupied_thresh = meta['occupied_thresh']
        self.free_thresh = meta['free_thresh']

        pgm_path = os.path.join(os.path.dirname(yaml_path), meta['image'])
        self.grid = self._load_pgm(pgm_path)
        self.height, self.width = self.grid.shape

    def _load_pgm(self, path):
        """Parse P5 (binary) PGM file into an integer occupancy grid."""
        with open(path, 'rb') as f:
            magic = f.readline().strip()
            if magic != b'P5':
                raise ValueError("Expected P5 PGM format, got {}".format(magic))

            line = f.readline()
            while line.startswith(b'#'):
                line = f.readline()

            width, height = map(int, line.split())
            maxval = int(f.readline().strip())
            data = f.read(width * height)

        pixels = np.frombuffer(data, dtype=np.uint8).reshape(height, width)
        pixels = np.flipud(pixels)

        if self.negate:
            occ_prob = pixels.astype(np.float64) / 255.0
        else:
            occ_prob = (255.0 - pixels.astype(np.float64)) / 255.0

        grid = np.zeros((height, width), dtype=np.int8)
        grid[occ_prob > self.occupied_thresh] = 100

        return grid

    def is_occupied(self, row, col):
        if 0 <= row < self.height and 0 <= col < self.width:
            return self.grid[row, col] >= 65
        return True

    def world_to_grid(self, world_x, world_y):
        """Convert world coordinates to grid (row, col)."""
        grid_col = int(round((world_x - self.origin_x) / self.resolution))
        grid_row = int(round((world_y - self.origin_y) / self.resolution))
        return grid_row, grid_col

    def grid_to_world(self, row, col):
        """Convert grid (row, col) to world coordinates."""
        world_x = col * self.resolution + self.origin_x
        world_y = row * self.resolution + self.origin_y
        return world_x, world_y
'''
    with open('/app/src/map_loader.py', 'w') as f:
        f.write(content)


def fix_costmap():
    """Fix inflation decay formula: use subtraction not multiplication."""
    content = '''\
"""Costmap inflation layer for safety-aware navigation."""

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
                -self.cost_scaling_factor * (distance - self.inscribed_radius)
            )
            return max(1, int((self.inscribed_cost - 1) * factor))
        return 0
'''
    with open('/app/src/costmap.py', 'w') as f:
        f.write(content)


def fix_transforms():
    """Fix compose: rotate child translation by parent rotation."""
    content = '''\
"""2D rigid body transforms for coordinate frame management."""

import math


class Transform2D:
    """Represents a 2D rigid transform (translation + rotation)."""

    def __init__(self, x, y, theta):
        self.x = x
        self.y = y
        self.theta = theta

    def transform_point(self, px, py):
        """Transform a point from child frame to parent frame."""
        cos_t = math.cos(self.theta)
        sin_t = math.sin(self.theta)
        rx = cos_t * px - sin_t * py + self.x
        ry = sin_t * px + cos_t * py + self.y
        return rx, ry

    def inverse(self):
        """Compute the inverse transform."""
        cos_t = math.cos(-self.theta)
        sin_t = math.sin(-self.theta)
        inv_x = cos_t * (-self.x) - sin_t * (-self.y)
        inv_y = sin_t * (-self.x) + cos_t * (-self.y)
        return Transform2D(inv_x, inv_y, -self.theta)

    def compose(self, other):
        """Compose this transform with another: self * other."""
        cos_t = math.cos(self.theta)
        sin_t = math.sin(self.theta)
        new_x = self.x + cos_t * other.x - sin_t * other.y
        new_y = self.y + sin_t * other.x + cos_t * other.y
        new_theta = self.theta + other.theta
        return Transform2D(new_x, new_y, new_theta)

    def __repr__(self):
        return "Transform2D(x={:.4f}, y={:.4f}, theta={:.4f})".format(
            self.x, self.y, self.theta)
'''
    with open('/app/src/transforms.py', 'w') as f:
        f.write(content)


def fix_planner():
    """Fix path planner: add heuristic and costmap-aware move cost."""
    content = '''\
"""Grid-based path planner with costmap awareness."""

import heapq
import math
import numpy as np


class PathPlanner:
    def __init__(self, costmap, resolution):
        self.costmap = costmap
        self.resolution = resolution
        self.height, self.width = costmap.shape

    def plan(self, start, goal, lethal_cost=254):
        """Plan a path from start (row, col) to goal (row, col)."""
        if self.costmap[start[0], start[1]] >= lethal_cost:
            return None, float('inf')
        if self.costmap[goal[0], goal[1]] >= lethal_cost:
            return None, float('inf')

        open_set = []
        heapq.heappush(open_set, (0, start))
        came_from = {}
        g_score = {start: 0}

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
        """Admissible heuristic: Euclidean distance in world units."""
        return math.sqrt((a[0] - b[0])**2 + (a[1] - b[1])**2) * self.resolution

    def _get_move_cost(self, current, neighbor):
        """Move cost = geometric distance + costmap traversal cost."""
        dr = abs(current[0] - neighbor[0])
        dc = abs(current[1] - neighbor[1])
        base_cost = math.sqrt(dr**2 + dc**2) * self.resolution
        costmap_cost = self.costmap[neighbor[0], neighbor[1]] / 253.0 * self.resolution
        return base_cost + costmap_cost
'''
    with open('/app/src/planner.py', 'w') as f:
        f.write(content)


def fix_router():
    """Fix route optimizer: find minimum-cost waypoint ordering."""
    content = '''\
"""Multi-waypoint route optimizer."""

from itertools import permutations


class RouteOptimizer:
    def __init__(self, planner, map_loader):
        self.planner = planner
        self.map = map_loader

    def plan_route(self, start_world, waypoints_world):
        """Plan optimal route visiting all waypoints from the start position."""
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

        best_order = None
        best_cost = float('inf')
        for perm in permutations(wp_ids):
            cost = 0
            current = 'start'
            for wp_id in perm:
                cost += cost_matrix.get((current, wp_id), float('inf'))
                current = wp_id
            if cost < best_cost:
                best_cost = cost
                best_order = list(perm)

        ordered = best_order if best_order else wp_ids

        total_cost = 0
        current = 'start'
        for wp_id in ordered:
            total_cost += cost_matrix.get((current, wp_id), float('inf'))
            current = wp_id

        return ordered, total_cost, path_cache, cost_matrix
'''
    with open('/app/src/router.py', 'w') as f:
        f.write(content)


def fix_makefile():
    """Fix Makefile: correct variable expansion and jq field name."""
    with open('/app/Makefile', 'r') as f:
        content = f.read()

    # Fix variable expansion: $DB_PATH -> $(DB_PATH) in pipeline recipe
    content = content.replace('--db $DB_PATH', '--db $(DB_PATH)')

    # Fix jq field name: .route_plan.segments -> .route_plan.segment_costs
    content = content.replace('.route_plan.segments', '.route_plan.segment_costs')

    with open('/app/Makefile', 'w') as f:
        f.write(content)


def fix_db_manager():
    """Fix db_manager.py: correct argument order in store_costmap_stats."""
    with open('/app/src/db_manager.py', 'r') as f:
        content = f.read()

    # Fix: swapped arguments (inflated_count, lethal_count) -> (lethal_count, inflated_count)
    content = content.replace(
        '(inflated_count, lethal_count, max_cost, coverage)',
        '(lethal_count, inflated_count, max_cost, coverage)')

    with open('/app/src/db_manager.py', 'w') as f:
        f.write(content)


def generate_defect_manifest():
    """Generate the defect manifest documenting all identified and corrected issues."""
    manifest = [
        {
            "file": "Makefile",
            "category": "build",
            "description": "Make variable DB_PATH referenced as $DB_PATH instead of $(DB_PATH), causing Make to interpret $D as undefined variable and pass literal 'B_PATH' to the pipeline script."
        },
        {
            "file": "Makefile",
            "category": "validation",
            "description": "jq validation filter references .route_plan.segments which does not exist in the output; the correct field name is .route_plan.segment_costs per the schema."
        },
        {
            "file": "src/map_loader.py",
            "category": "numeric",
            "description": "world_to_grid omits the map origin offset when converting world coordinates to grid indices, producing incorrect grid positions for any map with non-zero origin."
        },
        {
            "file": "src/costmap.py",
            "category": "numeric",
            "description": "Exponential decay formula uses multiplication (distance * inscribed_radius) instead of subtraction (distance - inscribed_radius), producing incorrect inflation costs."
        },
        {
            "file": "src/transforms.py",
            "category": "numeric",
            "description": "Transform composition adds child translation directly instead of rotating it by the parent frame's rotation angle, violating SE(2) rigid-body transform semantics."
        },
        {
            "file": "src/planner.py",
            "category": "algorithmic",
            "description": "A* heuristic always returns zero, degenerating the search to Dijkstra's algorithm and dramatically increasing search time."
        },
        {
            "file": "src/planner.py",
            "category": "algorithmic",
            "description": "Move cost calculation only accounts for geometric distance without incorporating the costmap cell cost, causing the planner to ignore obstacle proximity."
        },
        {
            "file": "src/router.py",
            "category": "algorithmic",
            "description": "Route optimizer returns waypoints in input order instead of evaluating permutations to find the minimum-cost visit sequence."
        },
        {
            "file": "src/db_manager.py",
            "category": "data-integrity",
            "description": "store_costmap_stats swaps inflated_count and lethal_count arguments in the INSERT VALUES clause, storing each value in the wrong column."
        }
    ]

    with open('/app/defect_manifest.json', 'w') as f:
        json.dump(manifest, f, indent=2)


if __name__ == '__main__':
    print("Fixing map_loader.py...")
    fix_map_loader()

    print("Fixing costmap.py...")
    fix_costmap()

    print("Fixing transforms.py...")
    fix_transforms()

    print("Fixing planner.py...")
    fix_planner()

    print("Fixing router.py...")
    fix_router()

    print("Fixing Makefile...")
    fix_makefile()

    print("Fixing db_manager.py...")
    fix_db_manager()

    print("Generating defect manifest...")
    generate_defect_manifest()

    print("All fixes applied.")
