#!/usr/bin/env python3
"""QOBLIB Multi-Problem Cross-Verification, QUBO Analysis & Construction Pipeline."""

import json
import math
import os
import re
import subprocess
from collections import defaultdict, deque


# ============================================================
# Market Split
# ============================================================

def parse_ms_instance(filepath):
    with open(filepath) as f:
        lines = [
            l.strip()
            for l in f
            if l.strip() and not l.strip().startswith("#")
        ]
    parts = lines[0].replace(",", " ").split()
    m, n = int(parts[0]), int(parts[1])
    constraints = []
    for line in lines[1 : m + 1]:
        vals = list(map(int, line.replace(",", " ").split()))
        coeffs = vals[:n]
        rhs = vals[n]
        constraints.append((coeffs, rhs))
    return m, n, constraints


def detect_ms_format(data, n):
    for line in data.strip().split("\n"):
        if line.strip().startswith("x#"):
            return "x_var"
    bits = [c for c in data if c in "01"]
    has_other_digits = any(c.isdigit() and c not in "01" for c in data)
    if not has_other_digits and len(bits) == n:
        return "binary_string"
    return "index_list"


def parse_ms_solution(data, n):
    fmt = detect_ms_format(data, n)
    if fmt == "binary_string":
        sol = [int(c) for c in data if c in "01"]
        return sol, fmt
    if fmt == "x_var":
        sol = [0] * n
        for line in data.strip().split("\n"):
            match = re.match(r"x#(\d+)\s+([01])", line.strip())
            if match:
                idx = int(match.group(1))
                val = int(match.group(2))
                if 1 <= idx <= n:
                    sol[idx - 1] = val
        return sol, fmt
    sol = [0] * n
    for line in data.strip().split("\n"):
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        for token in line.split():
            try:
                idx = int(token)
                if 1 <= idx <= n:
                    sol[idx - 1] = 1
            except ValueError:
                pass
    return sol, fmt


def verify_ms(m, n, constraints, solution):
    failed = []
    for i, (coeffs, rhs) in enumerate(constraints):
        total = sum(c * s for c, s in zip(coeffs, solution))
        if total != rhs:
            failed.append(i + 1)
    return {
        "valid": len(failed) == 0,
        "ones_count": sum(solution),
    }


def run_rust_checker(instance_path, solution_path, checker_bin):
    try:
        result = subprocess.run(
            [checker_bin, instance_path, solution_path],
            capture_output=True, text=True, timeout=30
        )
        return result.returncode
    except Exception:
        return 2


def compute_qubo(m, n, constraints):
    """Derive the upper-triangular QUBO matrix from penalty formulation.

    The Market Split constraints Ax = b are reformulated as:
        minimize sum_i (A_i . x - b_i)^2

    Expanding and using x_j^2 = x_j for binary variables:
        Q_jj = (A^T A)_jj - 2*(A^T b)_j   (diagonal absorbs linear terms)
        Q_jk = 2*(A^T A)_jk  for j < k     (upper-triangular off-diagonal)
        constant_offset = b^T b
    """
    # Extract A matrix and b vector
    A = []
    b_vec = []
    for coeffs, rhs in constraints:
        A.append(coeffs)
        b_vec.append(rhs)

    # Compute A^T A
    AtA = [[0] * n for _ in range(n)]
    for j in range(n):
        for k in range(n):
            s = 0
            for i in range(m):
                s += A[i][j] * A[i][k]
            AtA[j][k] = s

    # Compute A^T b
    Atb = [0] * n
    for j in range(n):
        s = 0
        for i in range(m):
            s += A[i][j] * b_vec[i]
        Atb[j] = s

    # Compute b^T b (constant offset)
    btb = sum(bi * bi for bi in b_vec)

    # Build upper-triangular QUBO matrix
    Q = [[0] * n for _ in range(n)]
    for j in range(n):
        Q[j][j] = AtA[j][j] - 2 * Atb[j]
        for k in range(j + 1, n):
            Q[j][k] = 2 * AtA[j][k]

    # Compute properties
    nonzero_vals = [Q[j][k] for j in range(n) for k in range(j, n) if Q[j][k] != 0]
    num_nonzero = len(nonzero_vals)
    min_coeff = min(nonzero_vals) if nonzero_vals else 0
    max_coeff = max(nonzero_vals) if nonzero_vals else 0

    return Q, btb, {
        "dimension": n,
        "num_nonzero": num_nonzero,
        "min_coefficient": min_coeff,
        "max_coefficient": max_coeff,
        "constant_offset": btb,
    }


def eval_qubo(Q, btb, x):
    """Evaluate QUBO objective: sum_j Q_jj*x_j + sum_{j<k} Q_jk*x_j*x_k + btb."""
    n = len(x)
    val = 0
    for j in range(n):
        val += Q[j][j] * x[j]
        for k in range(j + 1, n):
            val += Q[j][k] * x[j] * x[k]
    return val + btb


# ============================================================
# Independent Set
# ============================================================

def parse_dimacs_graph(filepath):
    num_nodes = 0
    num_edges_expected = 0
    edges = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            parts = line.split()
            if parts[0] == "p":
                num_nodes = int(parts[2])
                num_edges_expected = int(parts[3])
            elif parts[0] == "e":
                u, v = int(parts[1]), int(parts[2])
                edges.append((u, v))
    return num_nodes, num_edges_expected, edges


def build_adjacency(num_nodes, edges):
    adj = defaultdict(set)
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)
    return adj


def detect_is_format(data, n):
    cleaned = "".join(c for c in data if c in "01")
    if len(cleaned) == n:
        return "binary_string"
    return "index_list"


def parse_is_solution(data, n):
    fmt = detect_is_format(data, n)
    if fmt == "binary_string":
        cleaned = "".join(c for c in data if c in "01")
        node_set = [i + 1 for i, c in enumerate(cleaned) if c == "1"]
        return node_set, fmt
    indices = []
    for line in data.strip().split("\n"):
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        for token in line.split():
            try:
                idx = int(token)
                if 1 <= idx <= n:
                    indices.append(idx)
            except ValueError:
                pass
    return indices, fmt


def verify_is(adj, node_set):
    conflicts = []
    node_set_s = set(node_set)
    for u in sorted(node_set):
        for v in adj[u]:
            if v in node_set_s and v > u:
                conflicts.append([u, v])
    return {
        "valid": len(conflicts) == 0,
        "set_size": len(node_set),
    }


# ============================================================
# CVRP
# ============================================================

def parse_cvrp_instance(filepath):
    name = ""
    dimension = 0
    capacity = 0
    coords = []
    demands = []
    depot = 1
    section = ""

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "NODE_COORD_SECTION" in line:
                section = "coords"
                continue
            elif "DEMAND_SECTION" in line:
                section = "demands"
                continue
            elif "DEPOT_SECTION" in line:
                section = "depot"
                continue
            elif line == "EOF" or line == "-1":
                if section == "depot":
                    section = ""
                continue

            if line.startswith("NAME"):
                name = line.split(":")[1].strip().strip('"')
                continue
            elif line.startswith("DIMENSION"):
                dimension = int(line.split(":")[1].strip())
                continue
            elif line.startswith("CAPACITY"):
                capacity = int(line.split(":")[1].strip())
                continue
            elif line.startswith("TYPE") or line.startswith("EDGE_WEIGHT_TYPE") or line.startswith("COMMENT"):
                continue

            if section == "coords":
                parts = line.split()
                if len(parts) >= 3:
                    coords.append((float(parts[1]), float(parts[2])))
            elif section == "demands":
                parts = line.split()
                if len(parts) >= 2:
                    demands.append(int(parts[1]))
            elif section == "depot":
                try:
                    d = int(line)
                    if d > 0:
                        depot = d
                except ValueError:
                    pass

    return {
        "name": name,
        "dimension": dimension,
        "capacity": capacity,
        "coords": coords,
        "demands": demands,
        "depot": depot,
    }


def euc2d_distance(p1, p2):
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    return int(math.sqrt(dx * dx + dy * dy) + 0.5)


def parse_cvrp_solution(filepath):
    routes = []
    route_re = re.compile(r"Route\s*#\d+\s*:\s*(.+)")

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            m = route_re.match(line)
            if m:
                route = [int(x) for x in m.group(1).split()]
                routes.append(route)
    return routes


def verify_cvrp(instance, routes):
    depot_idx = instance["depot"] - 1
    num_customers = instance["dimension"] - 1
    coords = instance["coords"]
    demands = instance["demands"]
    capacity = instance["capacity"]

    visited = set()
    valid = True
    total_cost = 0
    max_route_load = 0

    for route in routes:
        route_load = 0
        route_cost = 0
        prev = depot_idx

        for cust_num in route:
            if cust_num < 1 or cust_num > num_customers:
                valid = False
                continue
            if cust_num in visited:
                valid = False
            visited.add(cust_num)

            node_idx = cust_num
            route_load += demands[node_idx]
            route_cost += euc2d_distance(coords[prev], coords[node_idx])
            prev = node_idx

        route_cost += euc2d_distance(coords[prev], coords[depot_idx])
        total_cost += route_cost

        if route_load > capacity:
            valid = False

        max_route_load = max(max_route_load, route_load)

    if len(visited) != num_customers:
        valid = False

    return {
        "valid": valid,
        "num_routes": len(routes),
        "total_cost": total_cost,
        "max_route_load": max_route_load,
    }


# ============================================================
# Topology
# ============================================================

def bfs_max_depth(adj, start, n):
    dist = {start: 0}
    q = deque([start])
    while q:
        node = q.popleft()
        for neighbor in adj[node]:
            if neighbor not in dist:
                dist[neighbor] = dist[node] + 1
                q.append(neighbor)
    return max(dist.values()) if dist else 0


def compute_diameter(adj, n):
    diameter = 0
    for start in range(1, n + 1):
        d = bfs_max_depth(adj, start, n)
        diameter = max(diameter, d)
    return diameter


def count_components(adj, n):
    visited = set()
    components = 0
    for start in range(1, n + 1):
        if start not in visited:
            components += 1
            q = deque([start])
            visited.add(start)
            while q:
                node = q.popleft()
                for neighbor in adj[node]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        q.append(neighbor)
    return components


def verify_topology(filepath, required_n, required_d):
    n, m, edges = parse_dimacs_graph(filepath)
    adj = build_adjacency(n, edges)

    max_deg = max((len(adj[i]) for i in range(1, n + 1)), default=0)
    connected = count_components(adj, n) == 1
    diam = compute_diameter(adj, n) if connected else -1

    valid = n == required_n and max_deg <= required_d and connected

    return {
        "valid": valid,
        "num_nodes": n,
        "num_edges": m,
        "max_degree": max_deg,
        "diameter": diam,
        "connected": connected,
    }


# ============================================================
# Topology Construction
# ============================================================

def construct_topology(n, d):
    edges = []
    for i in range(1, n + 1):
        left = 2 * i
        right = 2 * i + 1
        if left <= n:
            edges.append((i, left))
        if right <= n:
            edges.append((i, right))
    return edges


def write_dimacs_graph(filepath, n, edges):
    with open(filepath, "w") as f:
        f.write(f"c Constructed graph: {n} nodes, max degree 3\n")
        f.write(f"p edge {n} {len(edges)}\n")
        for u, v in edges:
            f.write(f"e {u} {v}\n")


# ============================================================
# Main
# ============================================================

def main():
    results = {}

    # --- Market Split ---
    ms_dir = "/app/data/market_split"
    m, n, constraints = parse_ms_instance(os.path.join(ms_dir, "instance.dat"))

    checker_bin = os.path.join(ms_dir, "checker", "target", "release", "check_marketsplit")
    rust_built = os.path.exists(checker_bin)

    # Compute QUBO matrix
    Q, btb, qubo_props = compute_qubo(m, n, constraints)

    ms_candidates = {}
    for fname in sorted(os.listdir(ms_dir)):
        if fname.startswith("candidate_") and fname.endswith(".sol"):
            sol_path = os.path.join(ms_dir, fname)
            with open(sol_path) as f:
                data = f.read()
            sol, fmt = parse_ms_solution(data, n)
            result = verify_ms(m, n, constraints, sol)

            if rust_built:
                exit_code = run_rust_checker(
                    os.path.join(ms_dir, "instance.dat"),
                    sol_path,
                    checker_bin
                )
            else:
                exit_code = -1

            result["rust_exit_code"] = exit_code
            result["qubo_objective"] = eval_qubo(Q, btb, sol)
            ms_candidates[fname] = result

    results["market_split"] = {
        "num_constraints": m,
        "num_variables": n,
        "rust_checker_built": rust_built,
        "candidates": ms_candidates,
        "qubo": qubo_props,
    }

    # --- Independent Set ---
    is_dir = "/app/data/independent_set"
    num_nodes, num_edges, edges = parse_dimacs_graph(
        os.path.join(is_dir, "instance.col")
    )
    adj = build_adjacency(num_nodes, edges)

    is_candidates = {}
    for fname in sorted(os.listdir(is_dir)):
        if fname.startswith("candidate_") and fname.endswith(".sol"):
            with open(os.path.join(is_dir, fname)) as f:
                data = f.read()
            node_set, fmt = parse_is_solution(data, num_nodes)
            result = verify_is(adj, node_set)
            is_candidates[fname] = result

    results["independent_set"] = {
        "num_nodes": num_nodes,
        "num_edges": num_edges,
        "candidates": is_candidates,
    }

    # --- CVRP ---
    cvrp_dir = "/app/data/cvrp"
    instance = parse_cvrp_instance(os.path.join(cvrp_dir, "instance.vrp"))

    cvrp_candidates = {}
    for fname in sorted(os.listdir(cvrp_dir)):
        if fname.startswith("candidate_") and fname.endswith(".sol"):
            routes = parse_cvrp_solution(os.path.join(cvrp_dir, fname))
            result = verify_cvrp(instance, routes)
            cvrp_candidates[fname] = result

    results["cvrp"] = {
        "instance_name": instance["name"],
        "num_customers": instance["dimension"] - 1,
        "vehicle_capacity": instance["capacity"],
        "candidates": cvrp_candidates,
    }

    # --- Topology Verification ---
    topo_verify_dir = "/app/data/topology/verify"
    with open(os.path.join(topo_verify_dir, "instance.dat")) as f:
        parts = f.read().strip().split()
        req_n, req_d = int(parts[0]), int(parts[1])

    topo_candidates = {}
    for fname in sorted(os.listdir(topo_verify_dir)):
        if fname.endswith(".gph"):
            result = verify_topology(
                os.path.join(topo_verify_dir, fname), req_n, req_d
            )
            topo_candidates[fname] = result

    results["topology_verify"] = {
        "required_nodes": req_n,
        "required_max_degree": req_d,
        "candidates": topo_candidates,
    }

    # --- Topology Construction ---
    topo_construct_dir = "/app/data/topology/construct"
    with open(os.path.join(topo_construct_dir, "instance.dat")) as f:
        parts = f.read().strip().split()
        con_n, con_d = int(parts[0]), int(parts[1])

    tree_edges = construct_topology(con_n, con_d)
    output_path = "/app/solutions/topo_25_3.gph"
    write_dimacs_graph(output_path, con_n, tree_edges)

    # --- Write results ---
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Pipeline complete.")
    print(f"Results written to /app/results.json")
    print(f"Constructed topology written to {output_path}")


if __name__ == "__main__":
    main()
