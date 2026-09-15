
"""
CVRP solver pipeline:
  Phase 1: Clarke-Wright Savings + ILS for feasible solutions
  Phase 2: GLPK/GMPL LP relaxation for lower bounds
  Phase 3: Graphviz DOT/SVG route visualization
"""

import math
import os
import random
import subprocess
import sys
import time


# ========== Instance Parsing ==========

def parse_instance(filepath):
    with open(filepath) as f:
        lines = f.read().strip().split("\n")
    parts = lines[0].split()
    n, v, cap = int(parts[0]), int(parts[1]), int(parts[2])
    demands, xs, ys = [], [], []
    for i in range(1, n + 1):
        p = lines[i].split()
        demands.append(int(p[0]))
        xs.append(float(p[1]))
        ys.append(float(p[2]))
    return n, v, cap, demands, xs, ys


def build_dist(n, xs, ys):
    d = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            v = math.sqrt((xs[i] - xs[j]) ** 2 + (ys[i] - ys[j]) ** 2)
            d[i][j] = v
            d[j][i] = v
    return d


# ========== Route Cost ==========

def route_cost(route, d):
    if not route:
        return 0.0
    c = d[0][route[0]]
    for k in range(len(route) - 1):
        c += d[route[k]][route[k + 1]]
    c += d[route[-1]][0]
    return c


def total_cost(routes, d):
    return sum(route_cost(r, d) for r in routes)


# ========== Construction Heuristics ==========

def clarke_wright(n, nv, cap, demands, d):
    routes = [[i] for i in range(1, n)]
    cust_route = {i: i - 1 for i in range(1, n)}

    savings = []
    for i in range(1, n):
        for j in range(i + 1, n):
            s = d[0][i] + d[0][j] - d[i][j]
            if s > 0:
                savings.append((s, i, j))
    savings.sort(reverse=True)

    for s, i, j in savings:
        ri = cust_route.get(i)
        rj = cust_route.get(j)
        if ri is None or rj is None or ri == rj:
            continue
        if routes[ri] is None or routes[rj] is None:
            continue

        r_i = routes[ri]
        r_j = routes[rj]

        i_first = r_i[0] == i
        i_last = r_i[-1] == i
        j_first = r_j[0] == j
        j_last = r_j[-1] == j

        if not ((i_first or i_last) and (j_first or j_last)):
            continue

        di = sum(demands[c] for c in r_i)
        dj = sum(demands[c] for c in r_j)
        if di + dj > cap:
            continue

        if i_last and j_first:
            merged = r_i + r_j
        elif i_first and j_last:
            merged = r_j + r_i
        elif i_last and j_last:
            merged = r_i + r_j[::-1]
        else:
            merged = r_i[::-1] + r_j

        routes[ri] = merged
        routes[rj] = None
        for c in merged:
            cust_route[c] = ri

    result = [r for r in routes if r is not None]

    while len(result) > nv:
        result.sort(key=lambda r: sum(demands[c] for c in r))
        merged = False
        for i in range(len(result)):
            for j in range(len(result) - 1, i, -1):
                if sum(demands[c] for c in result[i]) + sum(
                    demands[c] for c in result[j]
                ) <= cap:
                    result[j].extend(result[i])
                    result.pop(i)
                    merged = True
                    break
            if merged:
                break
        if not merged:
            break

    return result


def sweep_construction(n, nv, cap, demands, xs, ys, d):
    depot_x, depot_y = xs[0], ys[0]
    angles = []
    for i in range(1, n):
        angle = math.atan2(ys[i] - depot_y, xs[i] - depot_x)
        angles.append((angle, i))
    angles.sort()

    best_routes = None
    best_cost = float("inf")
    step = max(1, len(angles) // 30)

    for start in range(0, len(angles), step):
        ordered = angles[start:] + angles[:start]
        routes = []
        route = []
        rem = cap
        for _, cust in ordered:
            if demands[cust] <= rem:
                route.append(cust)
                rem -= demands[cust]
            else:
                if route:
                    routes.append(route)
                route = [cust]
                rem = cap - demands[cust]
        if route:
            routes.append(route)

        while len(routes) > nv:
            best_pair = 0
            best_dem = float("inf")
            for i in range(len(routes) - 1):
                cd = sum(demands[c] for c in routes[i]) + sum(
                    demands[c] for c in routes[i + 1]
                )
                if cd < best_dem:
                    best_dem = cd
                    best_pair = i
            if best_dem <= cap:
                routes[best_pair] = routes[best_pair] + routes[best_pair + 1]
                routes.pop(best_pair + 1)
            else:
                break

        if len(routes) > nv:
            continue

        feasible = True
        for r in routes:
            if sum(demands[c] for c in r) > cap:
                feasible = False
                break
        if not feasible:
            continue

        cost = total_cost(routes, d)
        if cost < best_cost:
            best_cost = cost
            best_routes = [list(r) for r in routes]

    return best_routes


def nn_construction(n, nv, cap, demands, d):
    unvisited = set(range(1, n))
    routes = [[] for _ in range(nv)]
    route_demand = [0] * nv

    for v in range(nv):
        current = 0
        while unvisited:
            best_cust = -1
            best_dist = float("inf")
            for cust in unvisited:
                if (
                    demands[cust] <= cap - route_demand[v]
                    and d[current][cust] < best_dist
                ):
                    best_dist = d[current][cust]
                    best_cust = cust
            if best_cust < 0:
                break
            routes[v].append(best_cust)
            unvisited.remove(best_cust)
            route_demand[v] += demands[best_cust]
            current = best_cust

    for cust in sorted(unvisited):
        candidates = sorted(range(nv), key=lambda v: route_demand[v])
        for v in candidates:
            if route_demand[v] + demands[cust] <= cap:
                routes[v].append(cust)
                route_demand[v] += demands[cust]
                break
        else:
            v = candidates[0]
            routes[v].append(cust)
            route_demand[v] += demands[cust]

    return routes


def construct(n, nv, cap, demands, d, xs, ys):
    routes = clarke_wright(n, nv, cap, demands, d)
    if len(routes) <= nv:
        return routes
    print(
        f"  CW produced too many routes ({len(routes)}), trying alternatives",
        file=sys.stderr,
    )

    routes_sweep = sweep_construction(n, nv, cap, demands, xs, ys, d)
    routes_nn = nn_construction(n, nv, cap, demands, d)

    if routes_sweep is not None:
        cost_sweep = total_cost(routes_sweep, d)
        cost_nn = total_cost(routes_nn, d)
        if cost_sweep < cost_nn:
            return routes_sweep

    return routes_nn


# ========== Local Search Operators ==========

def two_opt(route, d):
    n = len(route)
    if n < 2:
        return False
    for i in range(n - 1):
        for j in range(i + 1, n):
            pi = route[i - 1] if i > 0 else 0
            nj = route[j + 1] if j < n - 1 else 0
            old = d[pi][route[i]] + d[route[j]][nj]
            new = d[pi][route[j]] + d[route[i]][nj]
            if new < old - 1e-10:
                route[i : j + 1] = route[i : j + 1][::-1]
                return True
    return False


def two_opt_full(route, d):
    while two_opt(route, d):
        pass


def or_opt(route, d):
    n = len(route)
    if n < 3:
        return False
    for seg_len in [1, 2, 3]:
        if seg_len >= n:
            continue
        for i in range(n - seg_len + 1):
            seg = route[i : i + seg_len]
            pi = route[i - 1] if i > 0 else 0
            ns = route[i + seg_len] if i + seg_len < n else 0
            remove_gain = d[pi][seg[0]] + d[seg[-1]][ns] - d[pi][ns]

            remaining = route[:i] + route[i + seg_len :]
            m = len(remaining)
            for j in range(m + 1):
                if j == i:
                    continue
                pj = remaining[j - 1] if j > 0 else 0
                nj = remaining[j] if j < m else 0
                insert_cost = d[pj][seg[0]] + d[seg[-1]][nj] - d[pj][nj]
                if remove_gain - insert_cost > 1e-10:
                    route[:] = remaining[:j] + seg + remaining[j:]
                    return True
    return False


def or_opt_full(route, d):
    while or_opt(route, d):
        pass


def relocate(routes, demands, cap, d, rd):
    nr = len(routes)
    for ri in range(nr):
        for ci in range(len(routes[ri])):
            cust = routes[ri][ci]
            pc = routes[ri][ci - 1] if ci > 0 else 0
            nc = routes[ri][ci + 1] if ci < len(routes[ri]) - 1 else 0
            save = d[pc][cust] + d[cust][nc] - d[pc][nc]

            for rj in range(nr):
                if ri == rj:
                    continue
                if rd[rj] + demands[cust] > cap:
                    continue
                for pos in range(len(routes[rj]) + 1):
                    pp = routes[rj][pos - 1] if pos > 0 else 0
                    np_ = routes[rj][pos] if pos < len(routes[rj]) else 0
                    cost = d[pp][cust] + d[cust][np_] - d[pp][np_]
                    if save - cost > 1e-10:
                        routes[ri].pop(ci)
                        rd[ri] -= demands[cust]
                        routes[rj].insert(pos, cust)
                        rd[rj] += demands[cust]
                        return True
    return False


def swap_customers(routes, demands, cap, d, rd):
    nr = len(routes)
    for ri in range(nr):
        for ci in range(len(routes[ri])):
            c1 = routes[ri][ci]
            pc1 = routes[ri][ci - 1] if ci > 0 else 0
            nc1 = routes[ri][ci + 1] if ci < len(routes[ri]) - 1 else 0

            for rj in range(ri + 1, nr):
                for cj in range(len(routes[rj])):
                    c2 = routes[rj][cj]
                    new_ri = rd[ri] - demands[c1] + demands[c2]
                    new_rj = rd[rj] - demands[c2] + demands[c1]
                    if new_ri > cap or new_rj > cap:
                        continue

                    pc2 = routes[rj][cj - 1] if cj > 0 else 0
                    nc2 = (
                        routes[rj][cj + 1] if cj < len(routes[rj]) - 1 else 0
                    )

                    old = (
                        d[pc1][c1] + d[c1][nc1] + d[pc2][c2] + d[c2][nc2]
                    )
                    new = (
                        d[pc1][c2] + d[c2][nc1] + d[pc2][c1] + d[c1][nc2]
                    )
                    if new < old - 1e-10:
                        routes[ri][ci] = c2
                        routes[rj][cj] = c1
                        rd[ri] = new_ri
                        rd[rj] = new_rj
                        return True
    return False


def cross_exchange(routes, demands, cap, d, rd):
    nr = len(routes)
    for ri in range(nr):
        if not routes[ri]:
            continue
        for ki in range(len(routes[ri])):
            a = routes[ri][ki]
            b = routes[ri][ki + 1] if ki + 1 < len(routes[ri]) else 0
            tail_i_dem = sum(
                demands[routes[ri][k]] for k in range(ki + 1, len(routes[ri]))
            )
            head_i_dem = rd[ri] - tail_i_dem

            for rj in range(ri + 1, nr):
                if not routes[rj]:
                    continue
                for kj in range(len(routes[rj])):
                    c = routes[rj][kj]
                    dd = (
                        routes[rj][kj + 1]
                        if kj + 1 < len(routes[rj])
                        else 0
                    )
                    tail_j_dem = sum(
                        demands[routes[rj][k]]
                        for k in range(kj + 1, len(routes[rj]))
                    )
                    head_j_dem = rd[rj] - tail_j_dem

                    if (
                        head_i_dem + tail_j_dem > cap
                        or head_j_dem + tail_i_dem > cap
                    ):
                        continue

                    old = d[a][b] + d[c][dd]
                    new = d[a][dd] + d[c][b]
                    if new < old - 1e-10:
                        tail_i = routes[ri][ki + 1 :]
                        tail_j = routes[rj][kj + 1 :]
                        routes[ri] = routes[ri][: ki + 1] + tail_j
                        routes[rj] = routes[rj][: kj + 1] + tail_i
                        rd[ri] = head_i_dem + tail_j_dem
                        rd[rj] = head_j_dem + tail_i_dem
                        return True
    return False


def local_search(routes, demands, cap, d, rd, time_limit_abs):
    iteration = 0
    while time.time() < time_limit_abs:
        improved = False
        if relocate(routes, demands, cap, d, rd):
            improved = True
        elif swap_customers(routes, demands, cap, d, rd):
            improved = True
        elif cross_exchange(routes, demands, cap, d, rd):
            improved = True

        if improved:
            for r in routes:
                two_opt_full(r, d)
            iteration += 1
        else:
            break
    for r in routes:
        or_opt_full(r, d)
        two_opt_full(r, d)
    return iteration


def perturb(routes, demands, cap, rd, strength=4):
    nr = len(routes)
    non_empty = [i for i in range(nr) if len(routes[i]) > 1]
    for _ in range(strength):
        if len(non_empty) < 2:
            break
        ri, rj = random.sample(non_empty, 2)
        ci = random.randint(0, len(routes[ri]) - 1)
        cj = random.randint(0, len(routes[rj]) - 1)
        c1 = routes[ri][ci]
        c2 = routes[rj][cj]
        new_ri = rd[ri] - demands[c1] + demands[c2]
        new_rj = rd[rj] - demands[c2] + demands[c1]
        if new_ri <= cap and new_rj <= cap:
            routes[ri][ci] = c2
            routes[rj][cj] = c1
            rd[ri] = new_ri
            rd[rj] = new_rj


# ========== VRP Solver ==========

def solve(filepath, output_path, time_limit):
    random.seed(42)

    n, nv, cap, demands, xs, ys = parse_instance(filepath)
    d = build_dist(n, xs, ys)

    t0 = time.time()
    deadline = t0 + time_limit

    routes = construct(n, nv, cap, demands, d, xs, ys)
    print(
        f"  Construction: {total_cost(routes, d):.2f} ({len(routes)} routes)",
        file=sys.stderr,
    )

    for r in routes:
        two_opt_full(r, d)
        or_opt_full(r, d)
    print(f"  2-opt+or-opt: {total_cost(routes, d):.2f}", file=sys.stderr)

    rd = [sum(demands[c] for c in r) for r in routes]

    iters = local_search(routes, demands, cap, d, rd, deadline)

    best_cost = total_cost(routes, d)
    best_routes = [list(r) for r in routes]
    best_rd = list(rd)
    print(f"  After LS: {best_cost:.2f} ({iters} iters)", file=sys.stderr)

    ils_count = 0
    while time.time() < deadline - 1:
        saved_routes = [list(r) for r in routes]
        saved_rd = list(rd)

        perturb(routes, demands, cap, rd)
        for r in routes:
            two_opt_full(r, d)
        local_search(routes, demands, cap, d, rd, deadline - 0.5)

        current_cost = total_cost(routes, d)
        if current_cost < best_cost:
            best_cost = current_cost
            best_routes = [list(r) for r in routes]
            best_rd = list(rd)
        else:
            routes[:] = [list(r) for r in best_routes]
            rd[:] = list(best_rd)

        ils_count += 1

    routes[:] = best_routes
    rd[:] = best_rd

    final = total_cost(routes, d)
    elapsed = time.time() - t0
    print(
        f"  Final: {final:.2f} ({ils_count} ILS restarts, {elapsed:.1f}s)",
        file=sys.stderr,
    )

    while len(routes) < nv:
        routes.append([])

    with open(output_path, "w") as f:
        f.write(f"{final:.4f} 0\n")
        for r in routes:
            if not r:
                f.write("0 0\n")
            else:
                f.write("0 " + " ".join(str(c) for c in r) + " 0\n")

    return final


# ========== Phase 2: LP Relaxation via GLPK ==========

def generate_gmpl_data(filepath, output_dat):
    """Generate GMPL .dat file from VRP instance for use with glpsol."""
    n, v, cap, demands, xs, ys = parse_instance(filepath)
    with open(output_dat, "w") as f:
        f.write("data;\n\n")
        f.write(f"param n := {n};\n")
        f.write(f"param nv := {v};\n\n")
        f.write("param cx :=\n")
        for i in range(n):
            f.write(f"  {i} {xs[i]}\n")
        f.write(";\n\n")
        f.write("param cy :=\n")
        for i in range(n):
            f.write(f"  {i} {ys[i]}\n")
        f.write(";\n\n")
        f.write("end;\n")


def compute_lp_bound(model_file, data_file, bound_file):
    """Run glpsol to compute LP relaxation lower bound."""
    try:
        result = subprocess.run(
            ["glpsol", "--math", model_file, "--data", data_file],
            capture_output=True,
            text=True,
            timeout=600,
        )
        for line in result.stdout.split("\n"):
            if "LP_BOUND:" in line:
                bound = float(line.split("LP_BOUND:")[1].strip())
                with open(bound_file, "w") as f:
                    f.write(f"{bound:.6f}\n")
                print(f"  LP bound: {bound:.6f}", file=sys.stderr)
                return bound
        print("  WARNING: Could not parse LP bound from glpsol output",
              file=sys.stderr)
        if result.returncode != 0:
            print(f"  glpsol exit code: {result.returncode}", file=sys.stderr)
            stderr_tail = result.stderr[-500:] if result.stderr else ""
            print(f"  stderr: {stderr_tail}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print("  WARNING: glpsol timed out after 600s", file=sys.stderr)
    except Exception as e:
        print(f"  ERROR computing LP bound: {e}", file=sys.stderr)
    return None


# ========== Phase 3: Visualization via Graphviz ==========

ROUTE_COLORS = [
    "#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00",
    "#a65628", "#f781bf", "#999999", "#66c2a5", "#fc8d62",
    "#8da0cb", "#e78ac3", "#a6d854", "#ffd92f", "#e5c494",
    "#b3b3b3", "#1b9e77", "#d95f02", "#7570b3", "#e7298a",
    "#66a61e", "#e6ab02", "#a6761d", "#666666", "#8dd3c7",
    "#ffffb3", "#bebada", "#fb8072", "#80b1d3", "#fdb462",
    "#b3de69", "#fccde5", "#d9d9d9", "#bc80bd", "#ccebc5",
    "#ffed6f", "#1f78b4", "#33a02c", "#e31a1c", "#ff7f00",
    "#6a3d9a",
]


def generate_dot(routes, xs, ys, n, dot_file):
    """Generate Graphviz DOT file with positioned nodes and colored routes."""
    with open(dot_file, "w") as f:
        f.write("graph vrp {\n")
        f.write("  overlap=false;\n")
        f.write("  splines=true;\n")
        f.write('  node [shape=point, width=0.05];\n')
        # Depot node
        f.write(
            f'  0 [shape=square, color=red, width=0.15, '
            f'pos="{xs[0]},{ys[0]}!"];\n'
        )
        # Customer nodes
        for i in range(1, n):
            f.write(f'  {i} [pos="{xs[i]},{ys[i]}!"];\n')
        # Route edges
        for ridx, route in enumerate(routes):
            color = ROUTE_COLORS[ridx % len(ROUTE_COLORS)]
            full = [0] + list(route) + [0]
            for k in range(len(full) - 1):
                a, b = full[k], full[k + 1]
                if a != b:
                    f.write(f'  {a} -- {b} [color="{color}"];\n')
        f.write("}\n")


def render_svg(dot_file, svg_file):
    """Run neato with fixed positions to render DOT as SVG."""
    try:
        subprocess.run(
            ["neato", "-n2", "-Tsvg", "-o", svg_file, dot_file],
            check=True,
            capture_output=True,
            timeout=120,
        )
        print(f"  SVG rendered: {svg_file}", file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"  ERROR rendering SVG: {e.stderr}", file=sys.stderr)
    except Exception as e:
        print(f"  ERROR rendering SVG: {e}", file=sys.stderr)


# ========== Main Pipeline ==========

def main():
    os.makedirs("/app/solutions", exist_ok=True)
    os.makedirs("/app/models", exist_ok=True)
    os.makedirs("/app/bounds", exist_ok=True)
    os.makedirs("/app/visualizations", exist_ok=True)

    model_file = "/app/models/vrp_lp.mod"

    instances = [
        (
            "vrp_101_10_1",
            "/app/data/vrp_101_10_1.txt",
            "/app/solutions/vrp_101_10_1.sol",
            40,
        ),
        (
            "vrp_200_16_1",
            "/app/data/vrp_200_16_1.txt",
            "/app/solutions/vrp_200_16_1.sol",
            60,
        ),
        (
            "vrp_421_41_1",
            "/app/data/vrp_421_41_1.txt",
            "/app/solutions/vrp_421_41_1.sol",
            100,
        ),
    ]

    for name, fp, op, tl in instances:
        print(f"\n=== {name} ===", file=sys.stderr)

        # Phase 1: Solve VRP
        print("Phase 1: Solving VRP...", file=sys.stderr)
        try:
            result = solve(fp, op, tl)
            print(f"  Solution distance: {result:.2f}", file=sys.stderr)
        except Exception as e:
            print(f"  ERROR solving VRP: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            continue

        # Phase 2: Compute LP relaxation bound via GLPK
        print("Phase 2: Computing LP bound via glpsol...", file=sys.stderr)
        data_file = f"/app/models/{name}.dat"
        bound_file = f"/app/bounds/{name}.bound"
        generate_gmpl_data(fp, data_file)
        compute_lp_bound(model_file, data_file, bound_file)

        # Phase 3: Generate route visualization via Graphviz
        print("Phase 3: Generating visualization via neato...", file=sys.stderr)
        n, v, cap, demands, xs, ys = parse_instance(fp)
        with open(op) as f:
            lines = f.read().strip().split("\n")
        routes_for_viz = []
        for i in range(1, len(lines)):
            route = list(map(int, lines[i].split()))
            inner = [c for c in route if c != 0]
            routes_for_viz.append(inner)

        dot_file = f"/app/visualizations/{name}.dot"
        svg_file = f"/app/visualizations/{name}.svg"
        generate_dot(routes_for_viz, xs, ys, n, dot_file)
        render_svg(dot_file, svg_file)

    print("\nPipeline complete.", file=sys.stderr)


if __name__ == "__main__":
    main()
