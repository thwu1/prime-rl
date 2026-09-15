"""
TSPLIB95 benchmark verification solver.

Handles corrupted EDGE_WEIGHT_FORMAT headers by detecting value-count
mismatches and inferring the correct format from the data.

"""
import json
import math


# ── TSPLIB parsing utilities ──────────────────────────────────────────


def parse_tsplib_header(lines):
    header = {}
    for line in lines:
        s = line.strip()
        if s in ("NODE_COORD_SECTION", "EDGE_WEIGHT_SECTION",
                 "DEMAND_SECTION", "DEPOT_SECTION", "TOUR_SECTION",
                 "DISPLAY_DATA_SECTION", "EOF"):
            break
        if ":" in s:
            key, _, val = s.partition(":")
            header[key.strip().upper()] = val.strip()
    return header


def find_section(lines, section_name):
    for i, line in enumerate(lines):
        if line.strip() == section_name:
            return i + 1
    return None


def parse_coords(lines, start, n):
    coords = {}
    for i in range(start, len(lines)):
        s = lines[i].strip()
        if s == "EOF" or s.startswith("-1"):
            break
        parts = s.split()
        if len(parts) >= 3:
            coords[int(parts[0])] = (float(parts[1]), float(parts[2]))
        if len(coords) == n:
            break
    return coords


def parse_edge_weights(lines, start):
    values = []
    for i in range(start, len(lines)):
        s = lines[i].strip()
        if s in ("EOF", "DEMAND_SECTION", "DISPLAY_DATA_SECTION",
                 "DEPOT_SECTION", "NODE_COORD_SECTION"):
            break
        values.extend(int(x) for x in s.split())
    return values


def parse_demands(lines, start, n):
    demands = {}
    for i in range(start, len(lines)):
        s = lines[i].strip()
        if s in ("EOF", "DEPOT_SECTION"):
            break
        parts = s.split()
        if len(parts) >= 2:
            demands[int(parts[0])] = int(parts[1])
        if len(demands) == n:
            break
    return demands


def parse_tour(lines, start):
    tour = []
    for i in range(start, len(lines)):
        s = lines[i].strip()
        if s == "EOF":
            break
        val = int(s)
        if val == -1:
            break
        tour.append(val)
    return tour


# ── Distance functions ────────────────────────────────────────────────


def nint(x):
    """TSPLIB nint: round to nearest integer (round half away from zero)."""
    return int(x + 0.5) if x >= 0 else int(x - 0.5)


def euc_2d(c1, c2):
    dx = c1[0] - c2[0]
    dy = c1[1] - c2[1]
    return nint(math.sqrt(dx * dx + dy * dy))


def att_distance(c1, c2):
    dx = c1[0] - c2[0]
    dy = c1[1] - c2[1]
    rij = math.sqrt((dx * dx + dy * dy) / 10.0)
    tij = nint(rij)
    if tij < rij:
        return tij + 1
    return tij


# ── Matrix building ──────────────────────────────────────────────────


def build_full_matrix(values, n):
    matrix = [[0] * n for _ in range(n)]
    idx = 0
    for i in range(n):
        for j in range(n):
            matrix[i][j] = values[idx]
            idx += 1
    return matrix


def build_lower_col(values, n):
    """Strict lower triangle, column-major order."""
    matrix = [[0] * n for _ in range(n)]
    idx = 0
    for j in range(n - 1):
        for i in range(j + 1, n):
            matrix[i][j] = values[idx]
            matrix[j][i] = values[idx]
            idx += 1
    return matrix


def resolve_explicit_matrix(values, n, declared_format):
    """Build distance matrix, detecting and correcting corrupted format headers.

    When the declared format's expected value count doesn't match the actual
    data, infer the correct format from the value count and TSPLIB conventions.
    """
    format_counts = {
        'FULL_MATRIX': n * n,
        'LOWER_COL': n * (n - 1) // 2,
        'LOWER_ROW': n * (n - 1) // 2,
        'UPPER_COL': n * (n - 1) // 2,
        'UPPER_ROW': n * (n - 1) // 2,
        'LOWER_DIAG_COL': n * (n + 1) // 2,
        'LOWER_DIAG_ROW': n * (n + 1) // 2,
        'UPPER_DIAG_COL': n * (n + 1) // 2,
        'UPPER_DIAG_ROW': n * (n + 1) // 2,
    }

    actual_count = len(values)
    expected = format_counts.get(declared_format, -1)

    if actual_count == expected:
        if declared_format == 'FULL_MATRIX':
            return build_full_matrix(values, n)
        elif declared_format == 'LOWER_COL':
            return build_lower_col(values, n)
        # Add other formats as needed
        return build_lower_col(values, n)

    # Mismatch detected — infer format from value count
    if actual_count == n * n:
        return build_full_matrix(values, n)
    elif actual_count == n * (n - 1) // 2:
        # Non-diagonal triangular format; LOWER_COL is the TSPLIB default
        return build_lower_col(values, n)

    raise ValueError(
        f"Format mismatch: header says {declared_format} "
        f"(expects {expected} values) but found {actual_count} values "
        f"for dimension {n}"
    )


# ── Held-Karp exact TSP/ATSP solver ─────────────────────────────────


def held_karp(dist, n):
    """Solve TSP/ATSP exactly using bitmask DP. Returns (cost, tour_0indexed)."""
    INF = float("inf")
    dp = [[INF] * n for _ in range(1 << n)]
    parent = [[(-1, -1)] * n for _ in range(1 << n)]
    dp[1][0] = 0

    for mask in range(1 << n):
        for u in range(n):
            if dp[mask][u] >= INF:
                continue
            if not (mask & (1 << u)):
                continue
            for v in range(n):
                if mask & (1 << v):
                    continue
                new_mask = mask | (1 << v)
                new_cost = dp[mask][u] + dist[u][v]
                if new_cost < dp[new_mask][v]:
                    dp[new_mask][v] = new_cost
                    parent[new_mask][v] = (mask, u)

    full_mask = (1 << n) - 1
    best_cost = INF
    best_last = -1
    for u in range(1, n):
        cost = dp[full_mask][u] + dist[u][0]
        if cost < best_cost:
            best_cost = cost
            best_last = u

    tour = []
    mask = full_mask
    u = best_last
    while u != -1:
        tour.append(u)
        prev_mask, prev_u = parent[mask][u]
        mask = prev_mask
        u = prev_u
    tour.reverse()

    return best_cost, tour


# ── Nearest-neighbor heuristic ───────────────────────────────────────


def nearest_neighbor(dist_func, coords, n, start=0):
    visited = [False] * n
    tour = [start]
    visited[start] = True
    total = 0
    for _ in range(n - 1):
        current = tour[-1]
        best_d = float("inf")
        best_next = -1
        for j in range(n):
            if visited[j]:
                continue
            d = dist_func(coords[current], coords[j])
            if d < best_d or (d == best_d and j < best_next):
                best_d = d
                best_next = j
        tour.append(best_next)
        visited[best_next] = True
        total += best_d
    total += dist_func(coords[tour[-1]], coords[tour[0]])
    return total, tour


# ── Instance solvers ─────────────────────────────────────────────────


def solve_br17():
    with open("/app/instances/br17.atsp") as f:
        lines = f.readlines()
    header = parse_tsplib_header(lines)
    n = int(header["DIMENSION"])
    start = find_section(lines, "EDGE_WEIGHT_SECTION")
    values = parse_edge_weights(lines, start)
    matrix = build_full_matrix(values, n)
    cost, tour_0 = held_karp(matrix, n)
    tour_1 = [x + 1 for x in tour_0]
    return cost, tour_1


def solve_berlin52():
    with open("/app/instances/berlin52.tsp") as f:
        lines = f.readlines()
    header = parse_tsplib_header(lines)
    n = int(header["DIMENSION"])
    start = find_section(lines, "NODE_COORD_SECTION")
    coords = parse_coords(lines, start, n)

    with open("/app/instances/berlin52.opt.tour") as f:
        tour_lines = f.readlines()
    tour_start = find_section(tour_lines, "TOUR_SECTION")
    tour = parse_tour(tour_lines, tour_start)

    cost = 0
    for i in range(len(tour)):
        u = tour[i]
        v = tour[(i + 1) % len(tour)]
        cost += euc_2d(coords[u], coords[v])
    return cost


def solve_att48():
    with open("/app/instances/att48.tsp") as f:
        lines = f.readlines()
    header = parse_tsplib_header(lines)
    n = int(header["DIMENSION"])
    start = find_section(lines, "NODE_COORD_SECTION")
    coords_dict = parse_coords(lines, start, n)
    coords_list = [coords_dict[i + 1] for i in range(n)]

    d_1_2 = att_distance(coords_list[0], coords_list[1])
    d_2_3 = att_distance(coords_list[1], coords_list[2])
    d_6_7 = att_distance(coords_list[5], coords_list[6])

    nn_cost, _ = nearest_neighbor(att_distance, coords_list, n, start=0)

    return d_1_2, d_2_3, d_6_7, nn_cost


def solve_eil13():
    with open("/app/instances/eil13.vrp") as f:
        lines = f.readlines()
    header = parse_tsplib_header(lines)
    n = int(header["DIMENSION"])
    capacity = int(header["CAPACITY"])
    declared_format = header.get("EDGE_WEIGHT_FORMAT", "LOWER_COL").strip()

    ew_start = find_section(lines, "EDGE_WEIGHT_SECTION")
    values = parse_edge_weights(lines, ew_start)

    # Handle potentially corrupted format header
    matrix = resolve_explicit_matrix(values, n, declared_format)

    dem_start = find_section(lines, "DEMAND_SECTION")
    demands = parse_demands(lines, dem_start, n)

    d_1_2 = matrix[0][1]
    d_1_13 = matrix[0][12]
    d_6_7 = matrix[5][6]
    d_7_8 = matrix[6][7]

    total_demand = sum(v for k, v in demands.items() if k != 1)
    min_vehicles = math.ceil(total_demand / capacity)

    tsp_cost, _ = held_karp(matrix, n)

    return d_1_2, d_1_13, d_6_7, d_7_8, min_vehicles, tsp_cost


# ── Main ─────────────────────────────────────────────────────────────


def main():
    results = {}

    br17_cost, br17_tour = solve_br17()
    results["br17_optimal_cost"] = br17_cost
    results["br17_optimal_tour"] = br17_tour

    results["berlin52_tour_cost"] = solve_berlin52()

    d12, d23, d67, nn_cost = solve_att48()
    results["att48_distance_1_2"] = d12
    results["att48_distance_2_3"] = d23
    results["att48_distance_6_7"] = d67
    results["att48_nn_cost"] = nn_cost

    e12, e113, e67, e78, min_v, tsp_opt = solve_eil13()
    results["eil13_distance_1_2"] = e12
    results["eil13_distance_1_13"] = e113
    results["eil13_distance_6_7"] = e67
    results["eil13_distance_7_8"] = e78
    results["eil13_min_vehicles"] = min_v
    results["eil13_tsp_optimal"] = tsp_opt

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
