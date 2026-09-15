#!/usr/bin/env python3
"""
TSPLIB Cross-Solver Optimization Pipeline

Uses tsplib95 for parsing, OR-Tools routing for TSP/CVRP,
Held-Karp DP for ATSP exact solve, and writes MIP formulation artifacts.

"""

import json
import os
import sys

import tsplib95
from ortools.constraint_solver import routing_enums_pb2, pywrapcp


INSTANCES_DIR = "/app/instances"


# ---------------------------------------------------------------------------
# Distance matrix extraction from tsplib95
# ---------------------------------------------------------------------------

def build_distance_matrix_0idx(problem):
    """Build a 0-indexed distance matrix from a tsplib95 Problem object.

    Returns (dist_matrix, nodes_list) where nodes_list maps 0-indexed
    positions back to 1-indexed TSPLIB node IDs.
    """
    nodes = sorted(problem.get_nodes())
    n = len(nodes)
    dist = [[0] * n for _ in range(n)]
    for i_idx, i_node in enumerate(nodes):
        for j_idx, j_node in enumerate(nodes):
            if i_idx != j_idx:
                dist[i_idx][j_idx] = problem.get_weight(i_node, j_node)
    return dist, nodes


# ---------------------------------------------------------------------------
# TSP solver: OR-Tools routing with guided local search
# ---------------------------------------------------------------------------

def solve_tsp_ortools(dist, n):
    """Solve symmetric TSP using OR-Tools routing solver.

    Args:
        dist: 0-indexed n*n distance matrix
        n: number of nodes

    Returns:
        (tour_0idx, tour_length) where tour_0idx is a list of 0-indexed nodes
    """
    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return dist[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
    search_parameters.time_limit.seconds = 30

    solution = routing.SolveWithParameters(search_parameters)
    if not solution:
        raise RuntimeError("OR-Tools TSP solver found no solution")

    tour = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        tour.append(manager.IndexToNode(index))
        index = solution.Value(routing.NextVar(index))

    return tour, solution.ObjectiveValue()


# ---------------------------------------------------------------------------
# ATSP: MIP formulation artifacts + Held-Karp exact solver
# ---------------------------------------------------------------------------

ATSP_MODEL = r"""/* ATSP with Miller-Tucker-Zemlin subtour elimination constraints */

set NODES;
param n := card(NODES);
param c{i in NODES, j in NODES};

var x{i in NODES, j in NODES: i <> j}, binary;
var u{i in NODES}, >= 0, <= n - 1;

minimize total_cost: sum{i in NODES, j in NODES: i <> j} c[i,j] * x[i,j];

/* Each node has exactly one outgoing arc */
s.t. depart{i in NODES}: sum{j in NODES: j <> i} x[i,j] = 1;

/* Each node has exactly one incoming arc */
s.t. arrive{j in NODES}: sum{i in NODES: i <> j} x[i,j] = 1;

/* MTZ subtour elimination: for all non-start node pairs */
s.t. mtz{i in NODES, j in NODES: i <> j and i >= 2 and j >= 2}:
    u[i] - u[j] + n * x[i,j] <= n - 1;

/* Fix position of starting node */
s.t. fix_start: u[1] = 0;

/* Position bounds for non-start nodes */
s.t. pos_lower{i in NODES: i >= 2}: u[i] >= 1;

solve;

end;
"""


def write_atsp_model():
    """Write the GMPL/MathProg model for ATSP to /app/atsp.mod."""
    with open("/app/atsp.mod", "w") as f:
        f.write(ATSP_MODEL)


def write_atsp_data(problem):
    """Generate GLPK data file for an ATSP instance from tsplib95 Problem.

    tsplib95 may return 0-indexed nodes for ATSP EXPLICIT instances.
    The MIP model assumes 1-indexed nodes (MTZ constraints use i>=2 to
    exclude the start node, and u[1]=0 fixes the start position), so we
    always remap to 1..n here.
    """
    nodes = sorted(problem.get_nodes())
    n = len(nodes)

    with open("/app/br17.dat", "w") as f:
        f.write("data;\n\n")
        f.write("set NODES := " + " ".join(str(i) for i in range(1, n + 1)) + ";\n\n")

        header = " ".join(f"{j:6d}" for j in range(1, n + 1))
        f.write(f"param c :\n    {header} :=\n")
        for idx_i, i_node in enumerate(nodes):
            vals = []
            for j_node in nodes:
                vals.append(problem.get_weight(i_node, j_node))
            row_str = " ".join(f"{v:6d}" for v in vals)
            f.write(f"{idx_i + 1:3d} {row_str}\n")
        f.write(";\n\n")
        f.write("end;\n")


def solve_atsp_heldkarp(problem):
    """Solve ATSP exactly using Held-Karp dynamic programming.

    O(n^2 * 2^n) time and O(n * 2^n) space.  Feasible for n <= ~22.
    Returns (tour_1indexed, cost).
    """
    nodes = sorted(problem.get_nodes())
    n = len(nodes)

    # Build 0-indexed distance matrix
    d = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            d[i][j] = problem.get_weight(nodes[i], nodes[j])

    BIG = 10 ** 9
    full = (1 << n) - 1

    # dp[S][u] = min cost to start at node 0, visit exactly the nodes
    # in bitmask S, and end at node u.
    dp = [[BIG] * n for _ in range(1 << n)]
    parent = [[-1] * n for _ in range(1 << n)]

    dp[1 << 0][0] = 0  # start at internal node 0

    for S in range(1, 1 << n):
        if not (S & 1):
            continue  # node 0 must always be in the visited set
        for u in range(n):
            if dp[S][u] >= BIG:
                continue
            if not (S & (1 << u)):
                continue
            for v in range(1, n):  # extend to unvisited node v (v != 0)
                if S & (1 << v):
                    continue
                new_S = S | (1 << v)
                new_cost = dp[S][u] + d[u][v]
                if new_cost < dp[new_S][v]:
                    dp[new_S][v] = new_cost
                    parent[new_S][v] = u

    # Close the tour: find best last node before returning to node 0
    best_cost = BIG
    best_last = -1
    for u in range(1, n):
        total = dp[full][u] + d[u][0]
        if total < best_cost:
            best_cost = total
            best_last = u

    # Reconstruct the path by following parent pointers
    path = [best_last]
    S = full
    u = best_last
    while True:
        prev = parent[S][u]
        S ^= (1 << u)
        u = prev
        path.append(u)
        if u == 0:
            break
    path.reverse()  # now [0, ..., best_last]

    # Convert from internal 0-indexed to 1-indexed TSPLIB node IDs.
    # tsplib95 may use 0-based or 1-based node IDs depending on the instance.
    tour = [nodes[i] for i in path]
    if nodes[0] == 0:
        tour = [x + 1 for x in tour]

    return tour, best_cost


# ---------------------------------------------------------------------------
# CVRP solver: OR-Tools routing with capacity dimension
# ---------------------------------------------------------------------------

def solve_cvrp_ortools(dist, demands_0idx, capacity, n, depot_0idx):
    """Solve CVRP using OR-Tools routing solver with capacity constraints.

    Args:
        dist: 0-indexed n*n distance matrix
        demands_0idx: list of demands indexed by 0-indexed node
        capacity: vehicle capacity
        n: total number of nodes (including depot)
        depot_0idx: 0-indexed depot node

    Returns:
        (routes_0idx, total_distance) where routes are lists of 0-indexed nodes
    """
    total_demand = sum(demands_0idx[i] for i in range(n) if i != depot_0idx)
    min_vehicles = -(-total_demand // capacity)  # ceiling division
    num_vehicles = min_vehicles + 3

    manager = pywrapcp.RoutingIndexManager(n, num_vehicles, depot_0idx)
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return dist[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    def demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        return demands_0idx[from_node]

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index,
        0,                              # null capacity slack
        [capacity] * num_vehicles,      # vehicle maximum capacities
        True,                           # start cumul to zero
        "Capacity"
    )

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
    search_parameters.time_limit.seconds = 30

    solution = routing.SolveWithParameters(search_parameters)
    if not solution:
        raise RuntimeError("OR-Tools CVRP solver found no solution")

    routes = []
    total_distance = 0
    for vehicle_id in range(num_vehicles):
        route = []
        index = routing.Start(vehicle_id)
        while not routing.IsEnd(index):
            route.append(manager.IndexToNode(index))
            index = solution.Value(routing.NextVar(index))
        route.append(manager.IndexToNode(index))  # append end depot

        # Only include non-empty routes (more than depot -> depot)
        if len(route) > 2:
            routes.append(route)
            for k in range(len(route) - 1):
                total_distance += dist[route[k]][route[k + 1]]

    return routes, total_distance


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    results = {}

    # --- berlin52 (TSP, EUC_2D) ---
    print("Solving berlin52 (TSP, EUC_2D) via OR-Tools...")
    problem = tsplib95.load(os.path.join(INSTANCES_DIR, "berlin52.tsp"))
    dist, nodes = build_distance_matrix_0idx(problem)
    n = len(nodes)
    tour_0idx, cost = solve_tsp_ortools(dist, n)
    tour_1idx = [nodes[i] for i in tour_0idx]
    results["berlin52"] = {"tour": tour_1idx, "tour_length": cost}
    print(f"  tour_length={cost} (optimal=7542, ratio={cost / 7542:.3f})")

    # --- att48 (TSP, ATT) ---
    print("Solving att48 (TSP, ATT) via OR-Tools...")
    problem = tsplib95.load(os.path.join(INSTANCES_DIR, "att48.tsp"))
    dist, nodes = build_distance_matrix_0idx(problem)
    n = len(nodes)
    tour_0idx, cost = solve_tsp_ortools(dist, n)
    tour_1idx = [nodes[i] for i in tour_0idx]
    results["att48"] = {"tour": tour_1idx, "tour_length": cost}
    print(f"  tour_length={cost} (optimal=10628, ratio={cost / 10628:.3f})")

    # --- br17 (ATSP, EXPLICIT FULL_MATRIX) ---
    print("Solving br17 (ATSP, EXPLICIT) via Held-Karp DP...")
    problem = tsplib95.load(os.path.join(INSTANCES_DIR, "br17.atsp"))
    write_atsp_model()
    write_atsp_data(problem)
    tour, cost = solve_atsp_heldkarp(problem)
    results["br17"] = {"tour": tour, "tour_length": cost}
    print(f"  tour_length={cost} (optimal=39)")

    # --- eil22 (CVRP, EUC_2D) ---
    print("Solving eil22 (CVRP, EUC_2D) via OR-Tools...")
    problem = tsplib95.load(os.path.join(INSTANCES_DIR, "eil22.vrp"))
    dist, nodes = build_distance_matrix_0idx(problem)
    n = len(nodes)
    node_to_idx = {node: idx for idx, node in enumerate(nodes)}

    demands_0idx = [0] * n
    for node, demand in problem.demands.items():
        demands_0idx[node_to_idx[node]] = demand

    depot_node = problem.depots[0]
    depot_0idx = node_to_idx[depot_node]
    capacity = problem.capacity

    routes_0idx, total_dist = solve_cvrp_ortools(
        dist, demands_0idx, capacity, n, depot_0idx)
    routes_1idx = [[nodes[i] for i in route] for route in routes_0idx]
    results["eil22"] = {"routes": routes_1idx, "total_distance": total_dist}
    print(f"  total_distance={total_dist}, routes={len(routes_1idx)}")

    # --- eil13 (CVRP, EXPLICIT LOWER_COL) ---
    print("Solving eil13 (CVRP, EXPLICIT LOWER_COL) via OR-Tools...")
    problem = tsplib95.load(os.path.join(INSTANCES_DIR, "eil13.vrp"))
    dist, nodes = build_distance_matrix_0idx(problem)
    n = len(nodes)
    node_to_idx = {node: idx for idx, node in enumerate(nodes)}

    demands_0idx = [0] * n
    for node, demand in problem.demands.items():
        demands_0idx[node_to_idx[node]] = demand

    depot_node = problem.depots[0]
    depot_0idx = node_to_idx[depot_node]
    capacity = problem.capacity

    routes_0idx, total_dist = solve_cvrp_ortools(
        dist, demands_0idx, capacity, n, depot_0idx)
    routes_1idx = [[nodes[i] for i in route] for route in routes_0idx]
    results["eil13"] = {"routes": routes_1idx, "total_distance": total_dist}
    print(f"  total_distance={total_dist}, routes={len(routes_1idx)}")

    # --- Write output ---
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
