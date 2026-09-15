
import math
import os
import pytest


INSTANCES = {
    "vrp_101_10_1": {
        "data": "/app/data/vrp_101_10_1.txt",
        "sol": "/app/solutions/vrp_101_10_1.sol",
        "bound": "/app/bounds/vrp_101_10_1.bound",
        "dot": "/app/visualizations/vrp_101_10_1.dot",
        "svg": "/app/visualizations/vrp_101_10_1.svg",
        "max_obj": 1050.0,
    },
    "vrp_200_16_1": {
        "data": "/app/data/vrp_200_16_1.txt",
        "sol": "/app/solutions/vrp_200_16_1.sol",
        "bound": "/app/bounds/vrp_200_16_1.bound",
        "dot": "/app/visualizations/vrp_200_16_1.dot",
        "svg": "/app/visualizations/vrp_200_16_1.svg",
        "max_obj": 2000.0,
    },
    "vrp_421_41_1": {
        "data": "/app/data/vrp_421_41_1.txt",
        "sol": "/app/solutions/vrp_421_41_1.sol",
        "bound": "/app/bounds/vrp_421_41_1.bound",
        "dot": "/app/visualizations/vrp_421_41_1.dot",
        "svg": "/app/visualizations/vrp_421_41_1.svg",
        "max_obj": 2500.0,
    },
}


def _parse_instance(filepath):
    with open(filepath) as f:
        lines = f.read().strip().split("\n")
    parts = lines[0].split()
    n = int(parts[0])
    v = int(parts[1])
    cap = int(parts[2])
    demands, xs, ys = [], [], []
    for i in range(1, n + 1):
        p = lines[i].split()
        demands.append(int(p[0]))
        xs.append(float(p[1]))
        ys.append(float(p[2]))
    return n, v, cap, demands, xs, ys


def _parse_solution(filepath, n_vehicles):
    with open(filepath) as f:
        lines = f.read().strip().split("\n")
    parts = lines[0].split()
    obj = float(parts[0])
    opt = int(parts[1])
    assert len(lines) == n_vehicles + 1, (
        f"Expected {n_vehicles + 1} lines, got {len(lines)}"
    )
    routes = []
    for i in range(1, n_vehicles + 1):
        route = list(map(int, lines[i].split()))
        routes.append(route)
    return obj, opt, routes


def _euclidean(xs, ys, i, j):
    return math.sqrt((xs[i] - xs[j]) ** 2 + (ys[i] - ys[j]) ** 2)


def _compute_total_distance(routes, xs, ys):
    total = 0.0
    for route in routes:
        for k in range(len(route) - 1):
            total += _euclidean(xs, ys, route[k], route[k + 1])
    return total


@pytest.fixture(params=sorted(INSTANCES.keys()))
def instance(request):
    name = request.param
    info = INSTANCES[name]
    n, v, cap, demands, xs, ys = _parse_instance(info["data"])
    return {
        "name": name,
        "n": n,
        "v": v,
        "cap": cap,
        "demands": demands,
        "xs": xs,
        "ys": ys,
        "sol_path": info["sol"],
        "bound_path": info["bound"],
        "dot_path": info["dot"],
        "svg_path": info["svg"],
        "max_obj": info["max_obj"],
    }


# ===== Solution file tests =====

class TestSolutionExists:
    def test_file_exists(self, instance):
        assert os.path.isfile(instance["sol_path"]), (
            f"Solution file {instance['sol_path']} not found"
        )


class TestSolutionFormat:
    def test_line_count(self, instance):
        _, _, routes = _parse_solution(instance["sol_path"], instance["v"])
        assert len(routes) == instance["v"]

    def test_first_line_values(self, instance):
        obj, opt, _ = _parse_solution(instance["sol_path"], instance["v"])
        assert isinstance(obj, float)
        assert opt in (0, 1)


class TestFeasibility:
    def test_routes_start_end_at_depot(self, instance):
        _, _, routes = _parse_solution(instance["sol_path"], instance["v"])
        for idx, route in enumerate(routes):
            assert len(route) >= 2, f"Vehicle {idx} route too short: {route}"
            assert route[0] == 0, (
                f"Vehicle {idx} does not start at depot (starts at {route[0]})"
            )
            assert route[-1] == 0, (
                f"Vehicle {idx} does not end at depot (ends at {route[-1]})"
            )

    def test_all_customers_served_exactly_once(self, instance):
        n = instance["n"]
        _, _, routes = _parse_solution(instance["sol_path"], instance["v"])
        served = []
        for route in routes:
            for c in route:
                if c != 0:
                    served.append(c)
        expected = set(range(1, n))
        served_set = set(served)
        duplicates = [c for c in served if served.count(c) > 1]
        assert len(duplicates) == 0, (
            f"Customers served multiple times: {set(duplicates)}"
        )
        missing = expected - served_set
        assert len(missing) == 0, f"Customers not served: {missing}"

    def test_capacity_constraints(self, instance):
        cap = instance["cap"]
        demands = instance["demands"]
        _, _, routes = _parse_solution(instance["sol_path"], instance["v"])
        for idx, route in enumerate(routes):
            load = sum(demands[c] for c in route if c != 0)
            assert load <= cap, (
                f"Vehicle {idx} overloaded: load={load}, capacity={cap}"
            )

    def test_customer_indices_valid(self, instance):
        n = instance["n"]
        _, _, routes = _parse_solution(instance["sol_path"], instance["v"])
        for idx, route in enumerate(routes):
            for c in route:
                assert 0 <= c < n, (
                    f"Vehicle {idx} has invalid customer index {c} (max {n - 1})"
                )


class TestQuality:
    def test_objective_consistency(self, instance):
        xs, ys = instance["xs"], instance["ys"]
        obj, _, routes = _parse_solution(instance["sol_path"], instance["v"])
        computed = _compute_total_distance(routes, xs, ys)
        assert abs(computed - obj) <= 1.0, (
            f"Reported objective {obj:.2f} differs from computed {computed:.2f}"
        )

    def test_objective_meets_threshold(self, instance):
        xs, ys = instance["xs"], instance["ys"]
        max_obj = instance["max_obj"]
        _, _, routes = _parse_solution(instance["sol_path"], instance["v"])
        computed = _compute_total_distance(routes, xs, ys)
        assert computed <= max_obj, (
            f"Instance {instance['name']}: distance {computed:.2f} "
            f"exceeds threshold {max_obj:.1f}"
        )


# ===== GMPL model tests =====

class TestGMPLModel:
    def test_model_file_exists(self):
        assert os.path.isfile("/app/models/vrp_lp.mod"), (
            "GMPL model file not found at /app/models/vrp_lp.mod"
        )

    def test_model_has_param_declarations(self):
        with open("/app/models/vrp_lp.mod") as f:
            content = f.read()
        assert "param" in content, "Model missing param declarations"

    def test_model_has_variable_declarations(self):
        with open("/app/models/vrp_lp.mod") as f:
            content = f.read()
        assert "var" in content, "Model missing var declarations"

    def test_model_has_objective(self):
        with open("/app/models/vrp_lp.mod") as f:
            content = f.read().lower()
        assert "minimize" in content or "maximize" in content, (
            "Model missing objective function"
        )

    def test_model_has_constraints(self):
        with open("/app/models/vrp_lp.mod") as f:
            content = f.read()
        assert "s.t." in content or "subject to" in content.lower(), (
            "Model missing constraint definitions"
        )

    def test_model_has_solve_statement(self):
        with open("/app/models/vrp_lp.mod") as f:
            content = f.read()
        assert "solve" in content, "Model missing solve statement"

    def test_model_defines_lp_relaxation(self):
        with open("/app/models/vrp_lp.mod") as f:
            content = f.read()
        has_lb = ">= 0" in content or ">=0" in content
        has_ub = "<= 1" in content or "<=1" in content
        assert has_lb and has_ub, (
            "Model should define LP relaxation with variables in [0,1]"
        )


# ===== LP bound tests =====

class TestLPBounds:
    def test_bound_file_exists(self, instance):
        assert os.path.isfile(instance["bound_path"]), (
            f"LP bound file not found at {instance['bound_path']}"
        )

    def test_bound_is_numeric(self, instance):
        with open(instance["bound_path"]) as f:
            content = f.read().strip()
        try:
            float(content)
        except ValueError:
            pytest.fail(f"LP bound file does not contain a valid number: '{content}'")

    def test_bound_is_positive(self, instance):
        with open(instance["bound_path"]) as f:
            bound = float(f.read().strip())
        assert bound > 0, f"LP bound must be positive, got {bound}"

    def test_bound_is_valid_lower_bound(self, instance):
        with open(instance["bound_path"]) as f:
            bound = float(f.read().strip())
        xs, ys = instance["xs"], instance["ys"]
        _, _, routes = _parse_solution(instance["sol_path"], instance["v"])
        computed = _compute_total_distance(routes, xs, ys)
        assert bound <= computed + 1.0, (
            f"LP bound {bound:.2f} exceeds solution distance {computed:.2f} "
            f"(not a valid lower bound)"
        )


# ===== Visualization tests =====

class TestVisualizationDOT:
    def test_dot_file_exists(self, instance):
        assert os.path.isfile(instance["dot_path"]), (
            f"DOT file not found at {instance['dot_path']}"
        )

    def test_dot_has_graph_keyword(self, instance):
        with open(instance["dot_path"]) as f:
            content = f.read()
        assert "graph" in content, "DOT file missing 'graph' keyword"

    def test_dot_has_edge_definitions(self, instance):
        with open(instance["dot_path"]) as f:
            content = f.read()
        assert "--" in content, "DOT file missing edge definitions (--)"

    def test_dot_has_position_attributes(self, instance):
        with open(instance["dot_path"]) as f:
            content = f.read()
        assert "pos=" in content, "DOT file missing pos= attributes for nodes"

    def test_dot_has_all_nodes(self, instance):
        with open(instance["dot_path"]) as f:
            content = f.read()
        n = instance["n"]
        pos_count = content.count("pos=")
        assert pos_count >= n, (
            f"DOT file has {pos_count} positioned nodes, expected at least {n}"
        )

    def test_dot_has_color_attributes(self, instance):
        with open(instance["dot_path"]) as f:
            content = f.read()
        assert "color=" in content, (
            "DOT file missing color= attributes for route differentiation"
        )


class TestVisualizationSVG:
    def test_svg_file_exists(self, instance):
        assert os.path.isfile(instance["svg_path"]), (
            f"SVG file not found at {instance['svg_path']}"
        )

    def test_svg_has_svg_tag(self, instance):
        with open(instance["svg_path"]) as f:
            content = f.read()
        assert "<svg" in content, "SVG file missing <svg tag"

    def test_svg_has_content(self, instance):
        size = os.path.getsize(instance["svg_path"])
        assert size > 500, (
            f"SVG file too small ({size} bytes), likely empty or invalid"
        )
