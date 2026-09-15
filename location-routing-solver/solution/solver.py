#!/usr/bin/env python3
"""
Location-Routing Problem solver with GLPK MIP integration.

Strategy:
  1. Write completed GMPL model and data files for depot selection MIP.
  2. Solve with glpsol to determine depot openings and initial assignments.
  3. Build VRP routes per depot using Clarke-Wright savings.
  4. Improve with 2-opt, or-opt, and inter-depot local search.
  5. Perturbation: try closing depots to save setup costs.
"""

import math
import os
import subprocess
import sys


def edist(x1, y1, x2, y2):
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


# ---- Data classes --------------------------------------------------------

class Depot:
    __slots__ = ("idx", "setup", "capacity", "x", "y")
    def __init__(self, idx, setup, capacity, x, y):
        self.idx = idx
        self.setup = setup
        self.capacity = capacity
        self.x = x
        self.y = y


class Customer:
    __slots__ = ("idx", "demand", "x", "y")
    def __init__(self, idx, demand, x, y):
        self.idx = idx
        self.demand = demand
        self.x = x
        self.y = y


class Instance:
    def __init__(self, path):
        with open(path) as f:
            lines = f.read().strip().split("\n")
        parts = lines[0].split()
        self.nd = int(parts[0])
        self.nc = int(parts[1])
        self.vpd = int(parts[2])
        self.vc = int(parts[3])

        self.depots = []
        for i in range(1, self.nd + 1):
            p = lines[i].split()
            self.depots.append(Depot(i - 1, int(p[0]), int(p[1]),
                                     float(p[2]), float(p[3])))

        self.customers = []
        for i in range(self.nd + 1, self.nd + 1 + self.nc):
            p = lines[i].split()
            self.customers.append(Customer(i - self.nd - 1, int(p[0]),
                                            float(p[1]), float(p[2])))


# ---- GLPK Integration ---------------------------------------------------

GMPL_MODEL = """\
/* Depot Selection MIP for Location-Routing Problem */

set DEPOTS;
set CUSTOMERS;

param setup{d in DEPOTS};
param depot_cap{d in DEPOTS};
param demand{c in CUSTOMERS};
param dist{d in DEPOTS, c in CUSTOMERS};
param max_vehicles;
param vehicle_cap;

var open{d in DEPOTS}, binary;
var assign{d in DEPOTS, c in CUSTOMERS}, binary;

minimize total_cost:
    sum{d in DEPOTS} setup[d] * open[d]
    + sum{d in DEPOTS, c in CUSTOMERS} 2 * dist[d,c] * assign[d,c];

/* Every customer must be assigned to exactly one depot */
s.t. customer_served{c in CUSTOMERS}:
    sum{d in DEPOTS} assign[d,c] = 1;

/* A customer can only be assigned to an open depot */
s.t. depot_link{d in DEPOTS, c in CUSTOMERS}:
    assign[d,c] <= open[d];

/* Depot capacity: total assigned demand <= depot capacity when open */
s.t. depot_capacity{d in DEPOTS}:
    sum{c in CUSTOMERS} demand[c] * assign[d,c] <= depot_cap[d] * open[d];

/* Fleet limit: total assigned demand <= vehicles * vehicle capacity */
s.t. fleet_limit{d in DEPOTS}:
    sum{c in CUSTOMERS} demand[c] * assign[d,c] <= max_vehicles * vehicle_cap;

solve;

for {d in DEPOTS} {
    printf "DEPOT %d %d\\n", d, (if open[d] > 0.5 then 1 else 0);
}
for {d in DEPOTS, c in CUSTOMERS: assign[d,c] > 0.5} {
    printf "ASSIGN %d %d\\n", c, d;
}

end;
"""


def write_gmpl_model(output_path):
    """Write the completed GMPL model for depot selection."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(GMPL_MODEL)


def write_gmpl_data(inst, output_path):
    """Generate a GMPL data file from instance data."""
    lines = ["data;", ""]

    depot_indices = " ".join(str(i) for i in range(inst.nd))
    cust_indices = " ".join(str(i) for i in range(inst.nc))
    lines.append(f"set DEPOTS := {depot_indices};")
    lines.append(f"set CUSTOMERS := {cust_indices};")
    lines.append("")

    lines.append(f"param max_vehicles := {inst.vpd};")
    lines.append(f"param vehicle_cap := {inst.vc};")
    lines.append("")

    lines.append("param setup :=")
    for i in range(inst.nd):
        lines.append(f"  {i} {inst.depots[i].setup}")
    lines.append(";")
    lines.append("")

    lines.append("param depot_cap :=")
    for i in range(inst.nd):
        lines.append(f"  {i} {inst.depots[i].capacity}")
    lines.append(";")
    lines.append("")

    lines.append("param demand :=")
    for i in range(inst.nc):
        lines.append(f"  {i} {inst.customers[i].demand}")
    lines.append(";")
    lines.append("")

    # Distance matrix in GMPL table format
    cust_hdr = " ".join(str(j) for j in range(inst.nc))
    lines.append(f"param dist : {cust_hdr} :=")
    for i in range(inst.nd):
        d = inst.depots[i]
        vals = []
        for j in range(inst.nc):
            c = inst.customers[j]
            vals.append(f"{edist(d.x, d.y, c.x, c.y):.4f}")
        lines.append(f"  {i} " + " ".join(vals))
    lines.append(";")
    lines.append("")
    lines.append("end;")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def run_glpsol(model_path, data_path, log_path):
    """Run glpsol and return (opened_set, assignments_dict) or (None, None)."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    result = subprocess.run(
        ["glpsol", "--model", model_path, "--data", data_path,
         "--tmlim", "90"],
        capture_output=True, text=True, timeout=120
    )

    # Write log
    with open(log_path, "w") as f:
        f.write(result.stdout)
        if result.stderr:
            f.write("\n--- STDERR ---\n")
            f.write(result.stderr)

    if result.returncode != 0:
        print(f"glpsol failed (rc={result.returncode}): "
              f"{result.stderr[:300]}", file=sys.stderr)
        return None, None

    # Parse output
    opened = set()
    assignments = {}
    for line in result.stdout.split("\n"):
        line = line.strip()
        if line.startswith("DEPOT "):
            parts = line.split()
            dep_idx = int(parts[1])
            is_open = int(parts[2])
            if is_open:
                opened.add(dep_idx)
        elif line.startswith("ASSIGN "):
            parts = line.split()
            cust_idx = int(parts[1])
            dep_idx = int(parts[2])
            assignments[cust_idx] = dep_idx

    return opened, assignments


# ---- Solution structure --------------------------------------------------

class Solution:
    def __init__(self, inst):
        self.inst = inst
        self.opened = [False] * inst.nd
        self.assignment = [-1] * inst.nc
        self.depot_routes = {}

    def cost(self):
        total = 0.0
        inst = self.inst
        for i in range(inst.nd):
            if self.opened[i]:
                total += inst.depots[i].setup
        for dep_idx, routes in self.depot_routes.items():
            dep = inst.depots[dep_idx]
            for route in routes:
                if not route:
                    continue
                c0 = inst.customers[route[0]]
                total += edist(dep.x, dep.y, c0.x, c0.y)
                for k in range(len(route) - 1):
                    c1 = inst.customers[route[k]]
                    c2 = inst.customers[route[k + 1]]
                    total += edist(c1.x, c1.y, c2.x, c2.y)
                cl = inst.customers[route[-1]]
                total += edist(cl.x, cl.y, dep.x, dep.y)
        return total


# ---- Greedy depot selection (fallback) -----------------------------------

def select_depots(inst):
    total_demand = sum(c.demand for c in inst.customers)
    ranked = sorted(range(inst.nd),
                    key=lambda i: inst.depots[i].setup / max(1, inst.depots[i].capacity))
    opened = [False] * inst.nd
    covered = 0
    for i in ranked:
        opened[i] = True
        covered += inst.depots[i].capacity
        if covered >= total_demand:
            break
    if covered < total_demand:
        for i in range(inst.nd):
            if not opened[i]:
                opened[i] = True
                covered += inst.depots[i].capacity
                if covered >= total_demand:
                    break
    return opened


# ---- Customer assignment (fallback) -------------------------------------

def assign_customers(inst, opened):
    open_indices = [i for i in range(inst.nd) if opened[i]]
    remaining_cap = {
        i: min(inst.depots[i].capacity, inst.vpd * inst.vc)
        for i in open_indices
    }

    pairs = []
    for j in range(inst.nc):
        c = inst.customers[j]
        for i in open_indices:
            d = inst.depots[i]
            pairs.append((edist(c.x, c.y, d.x, d.y), j, i))
    pairs.sort()

    assignment = [-1] * inst.nc
    assigned = set()

    for _, j, i in pairs:
        if j in assigned:
            continue
        if remaining_cap[i] >= inst.customers[j].demand:
            assignment[j] = i
            remaining_cap[i] -= inst.customers[j].demand
            assigned.add(j)

    unassigned = set(range(inst.nc)) - assigned
    if unassigned:
        for i in range(inst.nd):
            if not opened[i]:
                opened[i] = True
                remaining_cap[i] = inst.depots[i].capacity
                for j in sorted(unassigned):
                    if remaining_cap[i] >= inst.customers[j].demand:
                        assignment[j] = i
                        remaining_cap[i] -= inst.customers[j].demand
                        unassigned.discard(j)
            if not unassigned:
                break

    return assignment


# ---- Clarke-Wright savings -----------------------------------------------

def clarke_wright(inst, dep_idx, cust_indices):
    if not cust_indices:
        return []

    dep = inst.depots[dep_idx]

    routes = {i: [c] for i, c in enumerate(cust_indices)}
    route_demand = {i: inst.customers[c].demand for i, c in enumerate(cust_indices)}
    cust_to_route = {c: i for i, c in enumerate(cust_indices)}

    savings = []
    for ii, ci in enumerate(cust_indices):
        c1 = inst.customers[ci]
        for jj in range(ii + 1, len(cust_indices)):
            cj = cust_indices[jj]
            c2 = inst.customers[cj]
            s = (edist(dep.x, dep.y, c1.x, c1.y) +
                 edist(dep.x, dep.y, c2.x, c2.y) -
                 edist(c1.x, c1.y, c2.x, c2.y))
            savings.append((s, ci, cj))
    savings.sort(reverse=True)

    for s, ci, cj in savings:
        if s <= 0:
            break
        ri = cust_to_route.get(ci)
        rj = cust_to_route.get(cj)
        if ri is None or rj is None or ri == rj:
            continue
        if ri not in routes or rj not in routes:
            continue

        route_i = routes[ri]
        route_j = routes[rj]

        ci_end = (ci == route_i[0] or ci == route_i[-1])
        cj_end = (cj == route_j[0] or cj == route_j[-1])
        if not ci_end or not cj_end:
            continue

        if route_demand[ri] + route_demand[rj] > inst.vc:
            continue

        if ci == route_i[-1] and cj == route_j[0]:
            new_route = route_i + route_j
        elif ci == route_i[-1] and cj == route_j[-1]:
            new_route = route_i + route_j[::-1]
        elif ci == route_i[0] and cj == route_j[0]:
            new_route = route_i[::-1] + route_j
        elif ci == route_i[0] and cj == route_j[-1]:
            new_route = route_j + route_i
        else:
            continue

        new_demand = route_demand[ri] + route_demand[rj]
        routes[ri] = new_route
        route_demand[ri] = new_demand
        del routes[rj]
        del route_demand[rj]
        for c in new_route:
            cust_to_route[c] = ri

    result = list(routes.values())

    split_result = []
    for route in result:
        rd = sum(inst.customers[c].demand for c in route)
        if rd <= inst.vc:
            split_result.append(route)
        else:
            current = []
            current_demand = 0
            for c in route:
                cd = inst.customers[c].demand
                if current_demand + cd > inst.vc and current:
                    split_result.append(current)
                    current = [c]
                    current_demand = cd
                else:
                    current.append(c)
                    current_demand += cd
            if current:
                split_result.append(current)
    result = split_result

    while len(result) > inst.vpd:
        result.sort(key=lambda r: sum(inst.customers[c].demand for c in r))
        merged = False
        for i in range(len(result)):
            for j in range(i + 1, len(result)):
                d1 = sum(inst.customers[c].demand for c in result[i])
                d2 = sum(inst.customers[c].demand for c in result[j])
                if d1 + d2 <= inst.vc:
                    result[j] = result[i] + result[j]
                    result.pop(i)
                    merged = True
                    break
            if merged:
                break
        if not merged:
            break

    return result


# ---- 2-opt ---------------------------------------------------------------

def two_opt(inst, route, dep_idx):
    dep = inst.depots[dep_idx]
    n = len(route)
    if n < 3:
        return route

    improved = True
    while improved:
        improved = False
        for i in range(n - 1):
            for j in range(i + 2, n):
                if i == 0:
                    ax, ay = dep.x, dep.y
                else:
                    c = inst.customers[route[i - 1]]
                    ax, ay = c.x, c.y

                ci = inst.customers[route[i]]
                cj = inst.customers[route[j]]

                if j == n - 1:
                    bx, by = dep.x, dep.y
                else:
                    c = inst.customers[route[j + 1]]
                    bx, by = c.x, c.y

                old = edist(ax, ay, ci.x, ci.y) + edist(cj.x, cj.y, bx, by)
                new = edist(ax, ay, cj.x, cj.y) + edist(ci.x, ci.y, bx, by)

                if new < old - 1e-10:
                    route[i:j + 1] = route[i:j + 1][::-1]
                    improved = True
    return route


# ---- Or-opt --------------------------------------------------------------

def or_opt(inst, route, dep_idx):
    dep = inst.depots[dep_idx]
    n = len(route)
    if n < 3:
        return route

    def route_cost(r):
        if not r:
            return 0.0
        c0 = inst.customers[r[0]]
        t = edist(dep.x, dep.y, c0.x, c0.y)
        for k in range(len(r) - 1):
            c1 = inst.customers[r[k]]
            c2 = inst.customers[r[k + 1]]
            t += edist(c1.x, c1.y, c2.x, c2.y)
        cl = inst.customers[r[-1]]
        t += edist(cl.x, cl.y, dep.x, dep.y)
        return t

    improved = True
    while improved:
        improved = False
        best_cost = route_cost(route)
        for seg_len in (1, 2, 3):
            for i in range(len(route) - seg_len + 1):
                seg = route[i:i + seg_len]
                rest = route[:i] + route[i + seg_len:]
                for j in range(len(rest) + 1):
                    candidate = rest[:j] + seg + rest[j:]
                    cc = route_cost(candidate)
                    if cc < best_cost - 1e-10:
                        route = candidate
                        best_cost = cc
                        improved = True
                        break
                if improved:
                    break
            if improved:
                break
    return route


# ---- Inter-depot relocation ----------------------------------------------

def inter_depot_search(inst, sol):
    improved = True
    while improved:
        improved = False
        for j in range(inst.nc):
            cur_dep = sol.assignment[j]
            c = inst.customers[j]

            cur_d = inst.depots[cur_dep]
            cur_marginal = 2.0 * edist(c.x, c.y, cur_d.x, cur_d.y)

            for dep_idx in range(inst.nd):
                if dep_idx == cur_dep or not sol.opened[dep_idx]:
                    continue
                d = inst.depots[dep_idx]

                dep_load = sum(
                    inst.customers[ci].demand
                    for ci in range(inst.nc)
                    if sol.assignment[ci] == dep_idx
                )
                eff_cap = min(d.capacity, inst.vpd * inst.vc)
                if dep_load + c.demand > eff_cap:
                    continue

                new_marginal = 2.0 * edist(c.x, c.y, d.x, d.y)
                if new_marginal < cur_marginal - 1e-6:
                    sol.assignment[j] = dep_idx
                    cur_dep = dep_idx
                    cur_marginal = new_marginal
                    improved = True


def _add_to_routes(inst, sol, cust_idx, dep_idx):
    if dep_idx not in sol.depot_routes:
        sol.depot_routes[dep_idx] = []
    for route in sol.depot_routes[dep_idx]:
        rd = sum(inst.customers[c].demand for c in route)
        if rd + inst.customers[cust_idx].demand <= inst.vc:
            route.append(cust_idx)
            return True
    if len(sol.depot_routes[dep_idx]) < inst.vpd:
        sol.depot_routes[dep_idx].append([cust_idx])
        return True
    return False


# ---- Try closing depots --------------------------------------------------

def try_close_depots(inst, sol):
    for dep_idx in list(sol.depot_routes.keys()):
        if not sol.opened[dep_idx]:
            continue

        dep_custs = []
        for routes in sol.depot_routes.get(dep_idx, []):
            dep_custs.extend(routes)
        if not dep_custs:
            sol.opened[dep_idx] = False
            sol.depot_routes.pop(dep_idx, None)
            continue

        setup_saved = inst.depots[dep_idx].setup

        remaining_caps = {}
        for i in range(inst.nd):
            if i != dep_idx and sol.opened[i]:
                load = sum(inst.customers[c].demand
                           for c in range(inst.nc) if sol.assignment[c] == i)
                remaining_caps[i] = min(
                    inst.depots[i].capacity,
                    inst.vpd * inst.vc
                ) - load

        feasible = True
        reassignment = {}
        extra_routing = 0.0
        for cid in dep_custs:
            c = inst.customers[cid]
            best_dep = None
            best_extra = float("inf")
            old_dep = inst.depots[dep_idx]
            old_dist = edist(c.x, c.y, old_dep.x, old_dep.y)

            for i, cap in remaining_caps.items():
                if cap >= c.demand:
                    d = inst.depots[i]
                    new_dist = edist(c.x, c.y, d.x, d.y)
                    extra = 2.0 * new_dist - 2.0 * old_dist
                    if extra < best_extra:
                        best_extra = extra
                        best_dep = i
            if best_dep is None:
                feasible = False
                break
            reassignment[cid] = best_dep
            remaining_caps[best_dep] -= c.demand
            extra_routing += best_extra

        if feasible and extra_routing < setup_saved:
            sol.opened[dep_idx] = False
            sol.depot_routes.pop(dep_idx, None)
            for cid, new_dep in reassignment.items():
                sol.assignment[cid] = new_dep


# ---- Rebuild routes ------------------------------------------------------

def _bin_pack(demands, cap, max_bins):
    n = len(demands)
    if n == 0:
        return []
    bins = [[] for _ in range(max_bins)]
    loads = [0] * max_bins

    order = sorted(range(n), key=lambda i: -demands[i])

    def solve(pos):
        if pos == n:
            return True
        idx = order[pos]
        d = demands[idx]
        tried = set()
        for b in range(max_bins):
            if loads[b] + d > cap:
                continue
            if loads[b] in tried:
                continue
            tried.add(loads[b])
            bins[b].append(idx)
            loads[b] += d
            if solve(pos + 1):
                return True
            bins[b].pop()
            loads[b] -= d
        return False

    if solve(0):
        return [b for b in bins if b]
    return None


def _rebuild_routes(inst, sol):
    depot_custs = {}
    for j in range(inst.nc):
        dep = sol.assignment[j]
        depot_custs.setdefault(dep, []).append(j)

    sol.depot_routes = {}
    overflow = []

    for dep_idx, custs in depot_custs.items():
        demands = [inst.customers[c].demand for c in custs]
        packed = _bin_pack(demands, inst.vc, inst.vpd)

        if packed is not None:
            sol.depot_routes[dep_idx] = [
                [custs[i] for i in grp] for grp in packed
            ]
        else:
            dep = inst.depots[dep_idx]

            def angle(c_idx):
                c = inst.customers[c_idx]
                return math.atan2(c.y - dep.y, c.x - dep.x)
            ordered = sorted(custs, key=angle)

            routes = []
            current_route = []
            current_demand = 0
            for c_idx in ordered:
                cd = inst.customers[c_idx].demand
                if current_demand + cd > inst.vc and current_route:
                    routes.append(current_route)
                    current_route = [c_idx]
                    current_demand = cd
                else:
                    current_route.append(c_idx)
                    current_demand += cd
            if current_route:
                routes.append(current_route)

            sol.depot_routes[dep_idx] = routes[:inst.vpd]
            for r in routes[inst.vpd:]:
                overflow.extend(r)

    for cid in overflow:
        c = inst.customers[cid]
        best_dep = None
        best_dist = float("inf")
        for dep_idx in range(inst.nd):
            if not sol.opened[dep_idx]:
                continue
            d = inst.depots[dep_idx]
            dep_load = sum(
                inst.customers[ci].demand
                for ci in range(inst.nc) if sol.assignment[ci] == dep_idx
            )
            if dep_load + c.demand > d.capacity:
                continue
            dd = edist(c.x, c.y, d.x, d.y)
            if dd < best_dist:
                best_dist = dd
                best_dep = dep_idx
        if best_dep is None:
            for dep_idx in range(inst.nd):
                if not sol.opened[dep_idx]:
                    sol.opened[dep_idx] = True
                    sol.depot_routes[dep_idx] = []
                    best_dep = dep_idx
                    break
        if best_dep is not None:
            sol.assignment[cid] = best_dep
            _add_to_routes(inst, sol, cid, best_dep)


# ---- Main solver ----------------------------------------------------------

def solve(inst, glpk_opened=None, glpk_assignments=None):
    sol = Solution(inst)

    if glpk_opened is not None and glpk_assignments is not None:
        # Use GLPK MIP decisions
        for i in range(inst.nd):
            sol.opened[i] = (i in glpk_opened)
        assigned = set()
        for cust_idx, dep_idx in glpk_assignments.items():
            if cust_idx < inst.nc and dep_idx < inst.nd and sol.opened[dep_idx]:
                sol.assignment[cust_idx] = dep_idx
                assigned.add(cust_idx)
        # Assign any missing customers to nearest open depot
        for j in range(inst.nc):
            if j not in assigned:
                c = inst.customers[j]
                best_dep = None
                best_dist = float("inf")
                for i in range(inst.nd):
                    if sol.opened[i]:
                        d = inst.depots[i]
                        dd = edist(c.x, c.y, d.x, d.y)
                        if dd < best_dist:
                            best_dist = dd
                            best_dep = i
                if best_dep is not None:
                    sol.assignment[j] = best_dep
                    assigned.add(j)
    else:
        # Fallback: greedy
        sol.opened = select_depots(inst)
        sol.assignment = assign_customers(inst, sol.opened)

    # Improvement phases
    try_close_depots(inst, sol)
    inter_depot_search(inst, sol)
    _rebuild_routes(inst, sol)

    # Route improvement
    for dep_idx, routes in list(sol.depot_routes.items()):
        for r in range(len(routes)):
            routes[r] = two_opt(inst, routes[r], dep_idx)
            routes[r] = or_opt(inst, routes[r], dep_idx)

    # Safety: ensure all customers served
    served = set()
    for routes in sol.depot_routes.values():
        for route in routes:
            served.update(route)
    missing = set(range(inst.nc)) - served
    if missing:
        for cid in missing:
            placed = False
            for dep_idx in range(inst.nd):
                if sol.opened[dep_idx]:
                    if _add_to_routes(inst, sol, cid, dep_idx):
                        sol.assignment[cid] = dep_idx
                        placed = True
                        break
            if not placed:
                for dep_idx in range(inst.nd):
                    if not sol.opened[dep_idx]:
                        sol.opened[dep_idx] = True
                        sol.depot_routes[dep_idx] = [[cid]]
                        sol.assignment[cid] = dep_idx
                        break

    # Clean up empty depots
    for i in range(inst.nd):
        if sol.opened[i]:
            custs_at = [c for c in range(inst.nc) if sol.assignment[c] == i]
            if not custs_at:
                sol.opened[i] = False
                sol.depot_routes.pop(i, None)

    return sol


# ---- Output ---------------------------------------------------------------

def write_solution(sol, path):
    inst = sol.inst
    total_cost = sol.cost()

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(f"{total_cost:.1f} 0\n")
        flags = " ".join("1" if sol.opened[i] else "0"
                         for i in range(inst.nd))
        f.write(flags + "\n")

        for dep_idx in range(inst.nd):
            if sol.opened[dep_idx]:
                routes = sol.depot_routes.get(dep_idx, [])
                routes = [r for r in routes if r]
                f.write(f"{len(routes)}\n")
                for route in routes:
                    f.write(" ".join(str(c) for c in route) + "\n")


def main():
    # Phase 1: Write GMPL model
    model_path = "/app/models/depot_selection.mod"
    write_gmpl_model(model_path)
    print("Wrote GMPL model", file=sys.stderr)

    instances = ["instance_1", "instance_2", "instance_3"]
    for name in instances:
        inst_path = f"/app/data/{name}.txt"
        sol_path = f"/app/solutions/{name}.sol"
        data_path = f"/app/models/{name}.dat"
        log_path = f"/app/logs/glpsol_{name}.log"

        if not os.path.isfile(inst_path):
            print(f"Skipping {name}: {inst_path} not found", file=sys.stderr)
            continue

        inst = Instance(inst_path)

        # Phase 2: Generate GMPL data and solve with glpsol
        write_gmpl_data(inst, data_path)
        print(f"Wrote GMPL data for {name}", file=sys.stderr)

        glpk_opened, glpk_assignments = run_glpsol(
            model_path, data_path, log_path
        )
        if glpk_opened is not None:
            print(f"GLPK solved {name}: {len(glpk_opened)} depots opened",
                  file=sys.stderr)
        else:
            print(f"GLPK failed for {name}, using greedy fallback",
                  file=sys.stderr)

        # Phase 3: Build VRP solution using MIP decisions
        sol = solve(inst, glpk_opened, glpk_assignments)
        write_solution(sol, sol_path)
        print(f"{name}: cost = {sol.cost():.2f}", file=sys.stderr)


if __name__ == "__main__":
    main()
