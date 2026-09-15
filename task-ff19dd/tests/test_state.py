"""
TSPLIB Benchmark Optimization — Verification Tests

Tests independently parse instance files and verify /app/results.json
for correctness of distance computations, tour validity, solution quality,
and CVRP constraint satisfaction.

"""

import json
import math
import os
import pytest


# ---------------------------------------------------------------------------
# Independent TSPLIB parser and distance functions
# ---------------------------------------------------------------------------

def nint(x):
    """TSPLIB nint: round half up (matches C: (int)(x + 0.5) for x >= 0)."""
    return int(x + 0.5)


def euc_2d_dist(c1, c2):
    """EUC_2D distance per TSPLIB spec."""
    xd = c1[0] - c2[0]
    yd = c1[1] - c2[1]
    return nint(math.sqrt(xd * xd + yd * yd))


def att_dist(c1, c2):
    """ATT pseudo-Euclidean distance per TSPLIB spec (equivalent to ceiling)."""
    xd = c1[0] - c2[0]
    yd = c1[1] - c2[1]
    rij = math.sqrt((xd * xd + yd * yd) / 10.0)
    tij = nint(rij)
    if tij < rij:
        return tij + 1
    return tij


def parse_tsplib(filepath):
    """Parse a TSPLIB95 file into header dict + section data."""
    with open(filepath) as f:
        lines = [l.rstrip("\n") for l in f.readlines()]

    spec = {}
    current_section = None
    current_data = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == "EOF":
            continue

        if stripped.endswith("_SECTION"):
            if current_section:
                spec[current_section] = current_data
            current_section = stripped
            current_data = []
            continue

        if current_section is not None:
            current_data.append(stripped)
        else:
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                spec[key.strip()] = val.strip()

    if current_section:
        spec[current_section] = current_data

    return spec


def parse_coords(lines):
    """Parse NODE_COORD_SECTION lines into {1-indexed id: (x, y)}."""
    coords = {}
    for line in lines:
        parts = line.split()
        if len(parts) >= 3:
            idx = int(parts[0])
            coords[idx] = (float(parts[1]), float(parts[2]))
    return coords


def parse_flat_ints(lines):
    """Parse all integers from multi-line section data."""
    values = []
    for line in lines:
        values.extend(int(x) for x in line.split())
    return values


def build_euc2d_matrix(coords, n):
    """Build n*n distance matrix (1-indexed) using EUC_2D."""
    dist = [[0] * (n + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, n + 1):
            if i != j:
                dist[i][j] = euc_2d_dist(coords[i], coords[j])
    return dist


def build_att_matrix(coords, n):
    """Build n*n distance matrix (1-indexed) using ATT."""
    dist = [[0] * (n + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, n + 1):
            if i != j:
                dist[i][j] = att_dist(coords[i], coords[j])
    return dist


def build_full_matrix(values, n):
    """Build distance matrix from FULL_MATRIX flat values (1-indexed)."""
    dist = [[0] * (n + 1) for _ in range(n + 1)]
    for i in range(n):
        for j in range(n):
            dist[i + 1][j + 1] = values[i * n + j]
    return dist


def build_lower_col_matrix(values, n):
    """Build symmetric distance matrix from LOWER_COL flat values (1-indexed).

    LOWER_COL stores the strictly lower triangular part column by column:
    Column j (1-indexed): d(j+1,j), d(j+2,j), ..., d(n,j)
    """
    dist = [[0] * (n + 1) for _ in range(n + 1)]
    idx = 0
    for j in range(1, n):  # columns 1 to n-1
        for i in range(j + 1, n + 1):  # rows j+1 to n
            dist[i][j] = values[idx]
            dist[j][i] = values[idx]
            idx += 1
    return dist


def parse_demands(lines):
    """Parse DEMAND_SECTION into {1-indexed id: demand}."""
    demands = {}
    for line in lines:
        parts = line.split()
        if len(parts) >= 2:
            demands[int(parts[0])] = int(parts[1])
    return demands


def parse_depot(lines):
    """Parse DEPOT_SECTION, return 1-indexed depot node."""
    for line in lines:
        v = int(line.strip())
        if v == -1:
            break
        return v
    return 1


def compute_tour_length(tour, dist):
    """Compute total tour length (1-indexed tour, returns to start)."""
    total = 0
    n = len(tour)
    for i in range(n):
        total += dist[tour[i]][tour[(i + 1) % n]]
    return total


def compute_route_distance(route, dist):
    """Compute distance of a single route [depot, c1, ..., ck, depot]."""
    total = 0
    for i in range(len(route) - 1):
        total += dist[route[i]][route[i + 1]]
    return total


# ---------------------------------------------------------------------------
# Load instance data (parsed once)
# ---------------------------------------------------------------------------

INSTANCES_DIR = "/app/instances"


@pytest.fixture(scope="session")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def berlin52_data():
    spec = parse_tsplib(os.path.join(INSTANCES_DIR, "berlin52.tsp"))
    n = int(spec["DIMENSION"])
    coords = parse_coords(spec["NODE_COORD_SECTION"])
    dist = build_euc2d_matrix(coords, n)
    return {"n": n, "dist": dist, "optimal": 7542}


@pytest.fixture(scope="session")
def att48_data():
    spec = parse_tsplib(os.path.join(INSTANCES_DIR, "att48.tsp"))
    n = int(spec["DIMENSION"])
    coords = parse_coords(spec["NODE_COORD_SECTION"])
    dist = build_att_matrix(coords, n)
    return {"n": n, "dist": dist, "optimal": 10628}


@pytest.fixture(scope="session")
def br17_data():
    spec = parse_tsplib(os.path.join(INSTANCES_DIR, "br17.atsp"))
    n = int(spec["DIMENSION"])
    values = parse_flat_ints(spec["EDGE_WEIGHT_SECTION"])
    dist = build_full_matrix(values, n)
    return {"n": n, "dist": dist, "optimal": 39}


@pytest.fixture(scope="session")
def eil22_data():
    spec = parse_tsplib(os.path.join(INSTANCES_DIR, "eil22.vrp"))
    n = int(spec["DIMENSION"])
    coords = parse_coords(spec["NODE_COORD_SECTION"])
    dist = build_euc2d_matrix(coords, n)
    demands = parse_demands(spec["DEMAND_SECTION"])
    depot = parse_depot(spec["DEPOT_SECTION"])
    capacity = int(spec["CAPACITY"])
    return {"n": n, "dist": dist, "demands": demands, "depot": depot, "capacity": capacity}


@pytest.fixture(scope="session")
def eil13_data():
    spec = parse_tsplib(os.path.join(INSTANCES_DIR, "eil13.vrp"))
    n = int(spec["DIMENSION"])
    values = parse_flat_ints(spec["EDGE_WEIGHT_SECTION"])
    dist = build_lower_col_matrix(values, n)
    demands = parse_demands(spec["DEMAND_SECTION"])
    depot = parse_depot(spec["DEPOT_SECTION"])
    capacity = int(spec["CAPACITY"])
    return {"n": n, "dist": dist, "demands": demands, "depot": depot, "capacity": capacity}


# ---------------------------------------------------------------------------
# Test: results.json exists and has correct structure
# ---------------------------------------------------------------------------

class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json not found"

    def test_results_is_valid_json(self, results):
        assert isinstance(results, dict)

    def test_all_instances_present(self, results):
        for name in ["berlin52", "att48", "br17", "eil22", "eil13"]:
            assert name in results, f"Missing instance '{name}' in results"

    def test_tsp_fields(self, results):
        for name in ["berlin52", "att48", "br17"]:
            entry = results[name]
            assert "tour" in entry, f"{name}: missing 'tour'"
            assert "tour_length" in entry, f"{name}: missing 'tour_length'"

    def test_cvrp_fields(self, results):
        for name in ["eil22", "eil13"]:
            entry = results[name]
            assert "routes" in entry, f"{name}: missing 'routes'"
            assert "total_distance" in entry, f"{name}: missing 'total_distance'"


# ---------------------------------------------------------------------------
# Test: Spot-check distance computations
# ---------------------------------------------------------------------------

class TestDistanceSpotChecks:
    """Verify specific known distance values to catch parser/formula errors."""

    def test_berlin52_euc2d_distances(self, berlin52_data):
        d = berlin52_data["dist"]
        assert d[1][2] == 666
        assert d[1][52] == 1220
        assert d[10][33] == 501

    def test_att48_att_distances(self, att48_data):
        d = att48_data["dist"]
        assert d[1][2] == 1495
        assert d[1][48] == 1184
        assert d[6][17] == 230

    def test_br17_explicit_distances(self, br17_data):
        d = br17_data["dist"]
        assert d[1][2] == 3
        assert d[2][1] == 3
        assert d[1][12] == 0
        assert d[4][5] == 0
        assert d[5][10] == 48

    def test_eil22_euc2d_distances(self, eil22_data):
        d = eil22_data["dist"]
        assert d[1][2] == 49
        assert d[1][22] == 34

    def test_eil13_lower_col_distances(self, eil13_data):
        d = eil13_data["dist"]
        assert d[1][2] == 9
        assert d[2][1] == 9
        assert d[1][13] == 52
        assert d[13][1] == 52
        assert d[2][3] == 5
        assert d[3][2] == 5
        assert d[7][8] == 7
        assert d[8][7] == 7
        assert d[12][13] == 10
        assert d[13][12] == 10
        assert d[11][12] == 8
        assert d[12][11] == 8


# ---------------------------------------------------------------------------
# Test: TSP/ATSP tour validity
# ---------------------------------------------------------------------------

class TestTourValidity:
    def _check_tour(self, tour, n, name):
        assert len(tour) == n, f"{name}: tour has {len(tour)} cities, expected {n}"
        assert sorted(tour) == list(range(1, n + 1)), \
            f"{name}: tour does not visit each city 1..{n} exactly once"

    def test_berlin52_tour_valid(self, results, berlin52_data):
        self._check_tour(results["berlin52"]["tour"], berlin52_data["n"], "berlin52")

    def test_att48_tour_valid(self, results, att48_data):
        self._check_tour(results["att48"]["tour"], att48_data["n"], "att48")

    def test_br17_tour_valid(self, results, br17_data):
        self._check_tour(results["br17"]["tour"], br17_data["n"], "br17")


# ---------------------------------------------------------------------------
# Test: TSP tour length correctness and quality
# ---------------------------------------------------------------------------

class TestTSPQuality:
    def _check_tsp_quality(self, results, data, name, quality_bound):
        entry = results[name]
        tour = entry["tour"]
        reported = entry["tour_length"]
        recomputed = compute_tour_length(tour, data["dist"])

        assert reported == recomputed, \
            f"{name}: reported tour_length={reported} but recomputed={recomputed}"

        threshold = int(data["optimal"] * quality_bound)
        assert recomputed <= threshold, \
            f"{name}: tour_length={recomputed} exceeds {quality_bound}x optimal " \
            f"({data['optimal']}) = {threshold}"

    def test_berlin52_quality(self, results, berlin52_data):
        self._check_tsp_quality(results, berlin52_data, "berlin52", 1.05)

    def test_att48_quality(self, results, att48_data):
        self._check_tsp_quality(results, att48_data, "att48", 1.05)


# ---------------------------------------------------------------------------
# Test: ATSP exact optimality
# ---------------------------------------------------------------------------

class TestATSPOptimality:
    def test_br17_exact_optimal(self, results, br17_data):
        """ATSP instance must be solved to proven optimality."""
        entry = results["br17"]
        tour = entry["tour"]
        reported = entry["tour_length"]
        recomputed = compute_tour_length(tour, br17_data["dist"])

        assert reported == recomputed, \
            f"br17: reported tour_length={reported} but recomputed={recomputed}"
        assert recomputed == br17_data["optimal"], \
            f"br17: expected exact optimal {br17_data['optimal']}, got {recomputed}"


# ---------------------------------------------------------------------------
# Test: CVRP feasibility
# ---------------------------------------------------------------------------

class TestCVRPFeasibility:
    def _check_cvrp(self, results, data, name):
        entry = results[name]
        routes = entry["routes"]
        reported_dist = entry["total_distance"]
        n = data["n"]
        demands = data["demands"]
        depot = data["depot"]
        capacity = data["capacity"]
        dist = data["dist"]

        all_customers = set()
        expected_customers = set(range(1, n + 1)) - {depot}

        total_dist = 0
        for ridx, route in enumerate(routes):
            assert len(route) >= 3, \
                f"{name} route {ridx}: too short (need at least depot-customer-depot)"
            assert route[0] == depot, \
                f"{name} route {ridx}: does not start at depot {depot}"
            assert route[-1] == depot, \
                f"{name} route {ridx}: does not end at depot {depot}"

            route_demand = 0
            for node in route[1:-1]:
                assert node not in all_customers, \
                    f"{name}: customer {node} appears in multiple routes"
                all_customers.add(node)
                route_demand += demands[node]

            assert route_demand <= capacity, \
                f"{name} route {ridx}: demand={route_demand} exceeds capacity={capacity}"

            total_dist += compute_route_distance(route, dist)

        assert all_customers == expected_customers, \
            f"{name}: not all customers served. Missing: {expected_customers - all_customers}"

        assert reported_dist == total_dist, \
            f"{name}: reported total_distance={reported_dist} but recomputed={total_dist}"

    def test_eil22_feasibility(self, results, eil22_data):
        self._check_cvrp(results, eil22_data, "eil22")

    def test_eil13_feasibility(self, results, eil13_data):
        self._check_cvrp(results, eil13_data, "eil13")
