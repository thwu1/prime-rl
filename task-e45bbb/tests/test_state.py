"""Tests for the warehouse navigation pipeline.

"""

import pytest
import json
import math
import os
import sys
import subprocess
import sqlite3
import numpy as np

sys.path.insert(0, '/app/src')


class TestMapLoading:
    """Verify PGM map loading and grid properties."""

    def test_grid_dimensions(self):
        from map_loader import MapLoader
        ml = MapLoader('/app/map/warehouse.yaml')
        assert ml.height == 50 and ml.width == 50

    def test_perimeter_walls(self):
        from map_loader import MapLoader
        ml = MapLoader('/app/map/warehouse.yaml')
        assert ml.is_occupied(0, 25), "Bottom wall should be occupied"
        assert ml.is_occupied(49, 25), "Top wall should be occupied"
        assert ml.is_occupied(25, 0), "Left wall should be occupied"
        assert ml.is_occupied(25, 49), "Right wall should be occupied"

    def test_free_center(self):
        from map_loader import MapLoader
        ml = MapLoader('/app/map/warehouse.yaml')
        assert not ml.is_occupied(10, 10), "Interior area should be free"

    def test_barrier_present(self):
        from map_loader import MapLoader
        ml = MapLoader('/app/map/warehouse.yaml')
        assert ml.is_occupied(15, 20), "Horizontal barrier should be occupied"


class TestMapCoordinates:
    """Verify world-to-grid and grid-to-world coordinate conversions."""

    def test_origin_maps_to_grid_zero(self):
        from map_loader import MapLoader
        ml = MapLoader('/app/map/warehouse.yaml')
        r, c = ml.world_to_grid(-2.5, -2.5)
        assert r == 0 and c == 0, (
            "Origin (-2.5,-2.5) should map to (0,0), got ({},{})".format(r, c))

    def test_center_maps_to_grid_center(self):
        from map_loader import MapLoader
        ml = MapLoader('/app/map/warehouse.yaml')
        r, c = ml.world_to_grid(0.0, 0.0)
        assert r == 25 and c == 25, (
            "World (0,0) should map to (25,25), got ({},{})".format(r, c))

    def test_roundtrip_consistency(self):
        from map_loader import MapLoader
        ml = MapLoader('/app/map/warehouse.yaml')
        test_points = [(0.0, 0.0), (-2.0, -1.5), (1.5, 2.0), (-1.0, 0.5)]
        for wx, wy in test_points:
            r, c = ml.world_to_grid(wx, wy)
            rx, ry = ml.grid_to_world(r, c)
            assert abs(rx - wx) <= ml.resolution, (
                "Roundtrip x failed for ({},{}): got ({},{})".format(
                    wx, wy, rx, ry))
            assert abs(ry - wy) <= ml.resolution, (
                "Roundtrip y failed for ({},{}): got ({},{})".format(
                    wx, wy, rx, ry))

    def test_positive_world_coords(self):
        from map_loader import MapLoader
        ml = MapLoader('/app/map/warehouse.yaml')
        r, c = ml.world_to_grid(2.0, 1.0)
        assert r == 35 and c == 45, (
            "World (2.0,1.0) should map to (35,45), got ({},{})".format(r, c))


class TestFootprintRadii:
    """Verify inscribed and circumscribed radius computation."""

    def test_rectangle_inscribed(self):
        from pipeline import compute_footprint_radii
        footprint = [[-0.2, -0.15], [-0.2, 0.15], [0.2, 0.15], [0.2, -0.15]]
        inscribed, _ = compute_footprint_radii(footprint)
        assert abs(inscribed - 0.15) < 0.001, (
            "Expected inscribed 0.15, got {}".format(inscribed))

    def test_rectangle_circumscribed(self):
        from pipeline import compute_footprint_radii
        footprint = [[-0.2, -0.15], [-0.2, 0.15], [0.2, 0.15], [0.2, -0.15]]
        _, circumscribed = compute_footprint_radii(footprint)
        assert abs(circumscribed - 0.25) < 0.001, (
            "Expected circumscribed 0.25, got {}".format(circumscribed))

    def test_equilateral_triangle(self):
        from pipeline import compute_footprint_radii
        footprint = [[0.3, 0.0], [-0.15, 0.25981], [-0.15, -0.25981]]
        inscribed, circumscribed = compute_footprint_radii(footprint)
        assert abs(circumscribed - 0.3) < 0.001
        assert abs(inscribed - 0.15) < 0.002


class TestCostmapInflation:
    """Verify costmap inflation produces correct graduated costs."""

    def test_lethal_at_obstacle(self):
        from map_loader import MapLoader
        from costmap import CostmapInflation
        ml = MapLoader('/app/map/warehouse.yaml')
        inflation = CostmapInflation(ml, 0.15, 0.5, 3.0)
        costmap = inflation.inflate()
        assert costmap[0, 25] == 254, (
            "Wall cell should be lethal (254), got {}".format(costmap[0, 25]))

    def test_inscribed_cost_near_wall(self):
        from map_loader import MapLoader
        from costmap import CostmapInflation
        ml = MapLoader('/app/map/warehouse.yaml')
        inflation = CostmapInflation(ml, 0.15, 0.5, 3.0)
        costmap = inflation.inflate()
        assert costmap[1, 25] == 253, (
            "Cell within inscribed radius should be 253, got {}".format(
                costmap[1, 25]))

    def test_exponential_decay(self):
        from map_loader import MapLoader
        from costmap import CostmapInflation
        ml = MapLoader('/app/map/warehouse.yaml')
        inflation = CostmapInflation(ml, 0.15, 0.5, 3.0)
        costmap = inflation.inflate()
        val = costmap[2, 25]
        expected = int((253 - 1) * math.exp(-3.0 * (0.2 - 0.15)))
        assert abs(val - expected) <= 2, (
            "Decay cost at 0.2m: expected ~{}, got {}".format(expected, val))

    def test_free_space_zero(self):
        from map_loader import MapLoader
        from costmap import CostmapInflation
        ml = MapLoader('/app/map/warehouse.yaml')
        inflation = CostmapInflation(ml, 0.15, 0.5, 3.0)
        costmap = inflation.inflate()
        assert costmap[25, 43] == 0, (
            "Far free-space cell should be 0, got {}".format(costmap[25, 43]))


class TestTransformComposition:
    """Verify 2D rigid transform composition."""

    def test_compose_with_rotation(self):
        from transforms import Transform2D
        t1 = Transform2D(0.1, -0.05, 0.3)
        t2 = Transform2D(0.5, 0.2, -0.1)
        composed = t1.compose(t2)

        expected_x = 0.1 + math.cos(0.3) * 0.5 - math.sin(0.3) * 0.2
        expected_y = -0.05 + math.sin(0.3) * 0.5 + math.cos(0.3) * 0.2
        expected_theta = 0.2

        assert abs(composed.x - expected_x) < 0.001, (
            "Compose x: expected {:.6f}, got {:.6f}".format(
                expected_x, composed.x))
        assert abs(composed.y - expected_y) < 0.001, (
            "Compose y: expected {:.6f}, got {:.6f}".format(
                expected_y, composed.y))
        assert abs(composed.theta - expected_theta) < 0.001

    def test_transform_point_rotation(self):
        from transforms import Transform2D
        t = Transform2D(1.0, 2.0, math.pi / 2)
        px, py = t.transform_point(1.0, 0.0)
        assert abs(px - 1.0) < 0.001, "Expected x~1.0, got {}".format(px)
        assert abs(py - 3.0) < 0.001, "Expected y~3.0, got {}".format(py)

    def test_compose_identity(self):
        from transforms import Transform2D
        t = Transform2D(1.0, 2.0, 0.5)
        identity = Transform2D(0.0, 0.0, 0.0)
        composed = t.compose(identity)
        assert abs(composed.x - 1.0) < 0.001
        assert abs(composed.y - 2.0) < 0.001
        assert abs(composed.theta - 0.5) < 0.001


class TestPathPlanner:
    """Verify path planner correctness."""

    def test_empty_grid_path(self):
        from planner import PathPlanner
        costmap = np.zeros((10, 10), dtype=np.float64)
        planner = PathPlanner(costmap, 0.1)
        path, cost = planner.plan((0, 0), (9, 9))
        assert path is not None, "Path should exist in empty grid"
        assert path[0] == (0, 0)
        assert path[-1] == (9, 9)

    def test_path_avoids_obstacle(self):
        from planner import PathPlanner
        costmap = np.zeros((10, 10), dtype=np.float64)
        costmap[5, 2:8] = 254
        planner = PathPlanner(costmap, 0.1)
        path, cost = planner.plan((3, 5), (7, 5))
        assert path is not None, "Path should exist around obstacle"
        for r, c in path:
            assert costmap[r, c] < 254, (
                "Path traverses lethal cell ({},{})".format(r, c))

    def test_no_path_blocked(self):
        from planner import PathPlanner
        costmap = np.zeros((10, 10), dtype=np.float64)
        costmap[5, :] = 254
        planner = PathPlanner(costmap, 0.1)
        path, cost = planner.plan((3, 5), (7, 5))
        assert path is None, "No path should exist through complete wall"

    def test_costmap_aware_routing(self):
        from planner import PathPlanner
        costmap = np.zeros((20, 20), dtype=np.float64)
        costmap[8:12, 5:15] = 200
        planner = PathPlanner(costmap, 0.1)
        path, cost = planner.plan((10, 0), (10, 19))
        assert path is not None
        high_cost_cells = sum(1 for r, c in path if costmap[r, c] >= 200)
        assert high_cost_cells < len(path), (
            "Planner should minimize traversal of high-cost cells")


class TestResults:
    """Verify the final pipeline output."""

    def test_results_file_exists(self):
        assert os.path.exists('/app/results.json'), (
            "results.json not found - run the pipeline first")

    def test_results_schema_compliance(self):
        """Verify results.json matches the documented output schema structure."""
        with open('/app/results.json') as f:
            results = json.load(f)

        for key in ['robot_geometry', 'costmap_analysis',
                     'transform_chain', 'route_plan']:
            assert key in results, "Missing top-level key: {}".format(key)

        rg = results['robot_geometry']
        for key in ['inscribed_radius', 'circumscribed_radius',
                     'footprint_vertices']:
            assert key in rg, "Missing robot_geometry.{}".format(key)
        assert isinstance(rg['footprint_vertices'], list)
        assert len(rg['footprint_vertices']) >= 3
        for v in rg['footprint_vertices']:
            assert isinstance(v, list) and len(v) == 2

        ca = results['costmap_analysis']
        for key in ['lethal_cell_count', 'inflated_cell_count',
                     'max_cost', 'inflation_coverage_ratio']:
            assert key in ca, "Missing costmap_analysis.{}".format(key)
        assert 0 <= ca['inflation_coverage_ratio'] <= 1

        tc = results['transform_chain']
        for key in ['map_to_odom', 'odom_to_base', 'composed',
                     'test_point_input', 'test_point_output']:
            assert key in tc, "Missing transform_chain.{}".format(key)
        for tf_key in ['map_to_odom', 'odom_to_base', 'composed']:
            for coord in ['x', 'y', 'theta']:
                assert coord in tc[tf_key], (
                    "Missing {}.{}".format(tf_key, coord))
        assert len(tc['test_point_input']) == 2
        assert len(tc['test_point_output']) == 2

        rp = results['route_plan']
        for key in ['waypoint_order', 'total_cost', 'segment_costs']:
            assert key in rp, "Missing route_plan.{}".format(key)
        assert isinstance(rp['segment_costs'], list)
        for seg in rp['segment_costs']:
            for key in ['from', 'to', 'cost']:
                assert key in seg, "Missing segment_costs.{}".format(key)

    def test_inscribed_radius(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert abs(results['robot_geometry']['inscribed_radius'] - 0.15) < 0.001

    def test_circumscribed_radius(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert abs(
            results['robot_geometry']['circumscribed_radius'] - 0.25) < 0.001

    def test_transform_composition(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        composed = results['transform_chain']['composed']

        cx = 0.1 + math.cos(0.3) * 0.5 - math.sin(0.3) * 0.2
        cy = -0.05 + math.sin(0.3) * 0.5 + math.cos(0.3) * 0.2

        assert abs(composed['x'] - cx) < 0.001, (
            "Composed x: expected {:.6f}, got {}".format(cx, composed['x']))
        assert abs(composed['y'] - cy) < 0.001, (
            "Composed y: expected {:.6f}, got {}".format(cy, composed['y']))
        assert abs(composed['theta'] - 0.2) < 0.001

    def test_transform_output(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        tp_out = results['transform_chain']['test_point_output']

        cx = 0.1 + math.cos(0.3) * 0.5 - math.sin(0.3) * 0.2
        cy = -0.05 + math.sin(0.3) * 0.5 + math.cos(0.3) * 0.2
        theta = 0.2
        ex = math.cos(theta) * 1.0 - math.sin(theta) * 0.5 + cx
        ey = math.sin(theta) * 1.0 + math.cos(theta) * 0.5 + cy

        assert abs(tp_out[0] - ex) < 0.01, (
            "Transform x: expected {:.4f}, got {}".format(ex, tp_out[0]))
        assert abs(tp_out[1] - ey) < 0.01, (
            "Transform y: expected {:.4f}, got {}".format(ey, tp_out[1]))

    def test_path_cost_finite(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert results['route_plan']['total_cost'] < float('inf'), (
            "Path cost is infinite")
        assert results['route_plan']['total_cost'] > 0, (
            "Path cost must be positive")

    def test_waypoint_order_is_permutation(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        expected_ids = {'W1', 'W2', 'W3', 'W4', 'W5'}
        actual_ids = set(results['route_plan']['waypoint_order'])
        assert actual_ids == expected_ids, (
            "Invalid waypoint set: {}".format(actual_ids))

    def test_waypoint_order_is_optimal(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert results['route_plan']['total_cost'] < 100.0, (
            "Total cost {} seems too high".format(
                results['route_plan']['total_cost']))

    def test_costmap_has_inflation(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        ca = results['costmap_analysis']
        assert ca['inflated_cell_count'] > 500, (
            "Costmap should have significant inflation coverage, got {}".format(
                ca['inflated_cell_count']))
        assert ca['max_cost'] == 254, (
            "Costmap max should be lethal cost (254)")

    def test_segment_costs_match_route(self):
        """Verify segment_costs covers the full route consistently."""
        with open('/app/results.json') as f:
            results = json.load(f)
        rp = results['route_plan']
        segments = rp['segment_costs']
        order = rp['waypoint_order']

        assert len(segments) == len(order), (
            "Expected {} segments, got {}".format(len(order), len(segments)))
        assert segments[0]['from'] == 'start'
        for i, seg in enumerate(segments):
            assert seg['to'] == order[i]
            assert seg['cost'] > 0, (
                "Segment {}->{} has non-positive cost".format(
                    seg['from'], seg['to']))
        for i in range(1, len(segments)):
            assert segments[i]['from'] == order[i - 1]

    def test_segment_costs_sum(self):
        """Total cost must equal sum of segment costs."""
        with open('/app/results.json') as f:
            results = json.load(f)
        rp = results['route_plan']
        seg_sum = sum(s['cost'] for s in rp['segment_costs'])
        assert abs(seg_sum - rp['total_cost']) < 0.02, (
            "Segment sum {:.4f} != total_cost {:.4f}".format(
                seg_sum, rp['total_cost']))


class TestPipelineDB:
    """Verify SQLite database intermediate state."""

    def test_db_exists(self):
        assert os.path.exists('/app/pipeline.db'), (
            "pipeline.db not found - pipeline must write intermediate state to SQLite")

    def test_costmap_stats_column_ordering(self):
        """Lethal cell count must be less than inflated cell count."""
        conn = sqlite3.connect('/app/pipeline.db')
        c = conn.cursor()
        c.execute(
            'SELECT lethal_cell_count, inflated_cell_count '
            'FROM costmap_stats ORDER BY id DESC LIMIT 1')
        row = c.fetchone()
        conn.close()
        assert row is not None, "No costmap stats in database"
        lethal, inflated = row
        assert lethal < inflated, (
            "lethal_cell_count ({}) should be less than inflated_cell_count ({})"
            " - check column ordering in INSERT".format(lethal, inflated))

    def test_route_data_in_db(self):
        conn = sqlite3.connect('/app/pipeline.db')
        c = conn.cursor()
        c.execute(
            'SELECT waypoint_order, total_cost '
            'FROM route_data ORDER BY id DESC LIMIT 1')
        row = c.fetchone()
        conn.close()
        assert row is not None, "No route data in database"
        wp_order = json.loads(row[0])
        assert set(wp_order) == {'W1', 'W2', 'W3', 'W4', 'W5'}, (
            "Route data waypoints: {}".format(wp_order))
        assert row[1] > 0 and row[1] < 100, (
            "Route total_cost in DB should be positive and reasonable: {}".format(
                row[1]))

    def test_transforms_in_db(self):
        conn = sqlite3.connect('/app/pipeline.db')
        c = conn.cursor()
        c.execute(
            "SELECT x, y, theta FROM transform_results "
            "WHERE transform_key = 'composed'")
        row = c.fetchone()
        conn.close()
        assert row is not None, "Composed transform not in database"
        expected_x = 0.1 + math.cos(0.3) * 0.5 - math.sin(0.3) * 0.2
        expected_y = -0.05 + math.sin(0.3) * 0.5 + math.cos(0.3) * 0.2
        assert abs(row[0] - expected_x) < 0.001, (
            "DB composed x: expected {:.6f}, got {}".format(expected_x, row[0]))
        assert abs(row[1] - expected_y) < 0.001, (
            "DB composed y: expected {:.6f}, got {}".format(expected_y, row[1]))

    def test_costmap_db_json_consistency(self):
        """Verify DB costmap stats match results.json."""
        with open('/app/results.json') as f:
            results = json.load(f)
        conn = sqlite3.connect('/app/pipeline.db')
        c = conn.cursor()
        c.execute(
            'SELECT lethal_cell_count, inflated_cell_count, max_cost, '
            'inflation_coverage_ratio FROM costmap_stats ORDER BY id DESC LIMIT 1')
        row = c.fetchone()
        conn.close()
        ca = results['costmap_analysis']
        assert row[0] == ca['lethal_cell_count'], (
            "DB lethal_cell_count ({}) != JSON ({})".format(
                row[0], ca['lethal_cell_count']))
        assert row[1] == ca['inflated_cell_count'], (
            "DB inflated_cell_count ({}) != JSON ({})".format(
                row[1], ca['inflated_cell_count']))


class TestMakeWorkflow:
    """Verify Makefile correctness via dry-run inspection."""

    def test_makefile_expands_db_path(self):
        """Pipeline recipe must correctly expand DB_PATH variable."""
        result = subprocess.run(
            ['make', '-n', '-C', '/app', 'pipeline'],
            capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, (
            "make -n pipeline failed: {}".format(result.stderr))
        for line in result.stdout.strip().split('\n'):
            if 'pipeline.py' in line:
                assert '/app/pipeline.db' in line, (
                    "DB_PATH not correctly expanded in pipeline recipe. "
                    "Check Make variable syntax ($VAR vs $(VAR)). "
                    "Command: {}".format(line))
                break
        else:
            assert False, "No pipeline.py command found in make -n output"

    def test_makefile_validate_field_name(self):
        """Validate target must reference segment_costs, not segments."""
        result = subprocess.run(
            ['make', '-n', '-C', '/app', 'validate'],
            capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, (
            "make -n validate failed: {}".format(result.stderr))
        for line in result.stdout.strip().split('\n'):
            if 'jq' in line:
                assert 'segment_costs' in line, (
                    "validate target uses wrong field name in jq expression. "
                    "Expected 'segment_costs'. Command: {}".format(line))
                break
        else:
            assert False, "No jq command found in make -n validate output"

    def test_jq_validates_results(self):
        """Verify results.json passes jq structural validation."""
        result = subprocess.run(
            ['jq', '-e',
             '(.route_plan.segment_costs | length > 0) and '
             '(.robot_geometry.inscribed_radius > 0)',
             '/app/results.json'],
            capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, (
            "jq structural validation failed: {}".format(result.stderr))


class TestDefectManifest:
    """Verify the defect manifest documents the investigation findings."""

    def test_manifest_exists(self):
        assert os.path.exists('/app/defect_manifest.json'), (
            "defect_manifest.json not found at /app/defect_manifest.json")

    def test_manifest_valid_json_array(self):
        with open('/app/defect_manifest.json') as f:
            manifest = json.load(f)
        assert isinstance(manifest, list), "Manifest must be a JSON array"

    def test_manifest_entry_count(self):
        """Pipeline has multiple defects across its toolchain; manifest must document them."""
        with open('/app/defect_manifest.json') as f:
            manifest = json.load(f)
        assert len(manifest) >= 7, (
            "Manifest should document at least 7 defects, found {}".format(
                len(manifest)))

    def test_manifest_entry_structure(self):
        """Each entry must have file, category, and description fields."""
        with open('/app/defect_manifest.json') as f:
            manifest = json.load(f)
        valid_categories = {
            'build', 'numeric', 'data-integrity', 'algorithmic', 'validation'
        }
        for i, entry in enumerate(manifest):
            assert 'file' in entry, (
                "Entry {} missing 'file' field".format(i))
            assert 'category' in entry, (
                "Entry {} missing 'category' field".format(i))
            assert 'description' in entry, (
                "Entry {} missing 'description' field".format(i))
            assert entry['category'] in valid_categories, (
                "Entry {} has invalid category '{}', must be one of {}".format(
                    i, entry['category'], valid_categories))
            assert isinstance(entry['description'], str) and len(
                entry['description']) > 10, (
                "Entry {} description must be a meaningful string".format(i))

    def test_manifest_category_diversity(self):
        """Defects span multiple categories; manifest must reflect this."""
        with open('/app/defect_manifest.json') as f:
            manifest = json.load(f)
        categories = {e['category'] for e in manifest}
        assert len(categories) >= 4, (
            "Manifest should span at least 4 defect categories, found: {}".format(
                categories))

    def test_manifest_file_coverage(self):
        """Manifest must reference defects in build system and source modules."""
        with open('/app/defect_manifest.json') as f:
            manifest = json.load(f)
        files_mentioned = {e['file'] for e in manifest}

        assert any('Makefile' in f for f in files_mentioned), (
            "Manifest must document build system defects (Makefile)")

        src_files = {
            f for f in files_mentioned
            if f.startswith('src/') or '/src/' in f
        }
        assert len(src_files) >= 5, (
            "Manifest should document defects in at least 5 source modules, "
            "found: {}".format(src_files))
