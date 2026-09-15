#!/usr/bin/env python3
"""
Solver for architecture deployment optimization using OR-tools CP-SAT.
Assigns 28 components to 8 nodes subject to capacity, security zone,
affinity/anti-affinity, latency path, and AZ distribution constraints,
while minimizing total hourly infrastructure cost.
"""

import json
import sys
from ortools.sat.python import cp_model


def solve():
    with open("/app/architecture.json") as f:
        arch = json.load(f)

    components = arch["components"]
    dep_nodes = arch["deployment_nodes"]
    qa = arch["quality_attributes"]
    lat_model = arch["latency_model"]
    zone_ordering = arch["security_zone_hierarchy"]["ordering"]

    n_comp = len(components)
    n_node = len(dep_nodes)

    comp_idx = {c["id"]: i for i, c in enumerate(components)}
    node_idx = {n["id"]: i for i, n in enumerate(dep_nodes)}
    zone_level = {z: i for i, z in enumerate(zone_ordering)}

    # Valid node indices per component (security zone constraint)
    valid_nodes = []
    for c in components:
        c_level = zone_level[c["security_classification"]]
        valid = [j for j in range(n_node)
                 if zone_level[dep_nodes[j]["security_zone"]] >= c_level]
        valid_nodes.append(valid)

    # AZ integer mapping
    az_names = sorted(set(n["availability_zone"] for n in dep_nodes))
    az_map = {name: idx for idx, name in enumerate(az_names)}
    az_list = [az_map[n["availability_zone"]] for n in dep_nodes]
    n_az = len(az_names)

    model = cp_model.CpModel()

    # Decision variables: which node each component is assigned to
    node_of = []
    for i, c in enumerate(components):
        var = model.new_int_var_from_domain(
            cp_model.Domain.FromValues(valid_nodes[i]),
            f"node_{c['id']}"
        )
        node_of.append(var)

    # Binary indicators: is_on[i][j] = 1 iff component i is on node j
    is_on = []
    for i in range(n_comp):
        row = []
        for j in range(n_node):
            b = model.new_bool_var(f"on_{i}_{j}")
            model.add(node_of[i] == j).only_enforce_if(b)
            model.add(node_of[i] != j).only_enforce_if(~b)
            row.append(b)
        is_on.append(row)

    # AZ variables via element constraint
    az_of = []
    for i in range(n_comp):
        az_var = model.new_int_var(0, n_az - 1, f"az_{i}")
        model.add_element(node_of[i], az_list, az_var)
        az_of.append(az_var)

    # Capacity constraints
    for j in range(n_node):
        model.add(
            sum(components[i]["cpu_units"] * is_on[i][j]
                for i in range(n_comp))
            <= dep_nodes[j]["cpu_capacity"]
        )
        model.add(
            sum(components[i]["memory_mb"] * is_on[i][j]
                for i in range(n_comp))
            <= dep_nodes[j]["memory_capacity_mb"]
        )

    # Affinity: paired components must share a node
    for rule in qa["affinity_rules"]:
        ids = [comp_idx[cid] for cid in rule["components"]]
        for k in range(1, len(ids)):
            model.add(node_of[ids[0]] == node_of[ids[k]])

    # Anti-affinity: paired components must be on different nodes
    for rule in qa["anti_affinity_rules"]:
        ids = [comp_idx[cid] for cid in rule["components"]]
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                model.add(node_of[ids[a]] != node_of[ids[b]])

    # AZ distribution: component groups must span min_zones distinct AZs
    for req in qa["az_distribution_requirements"]:
        group = [comp_idx[cid] for cid in req["component_group"]]
        min_zones = req["min_zones"]

        az_present = []
        for az_val in range(n_az):
            has_this_az = model.new_bool_var(
                f"hasaz_{req['component_group'][0]}_{az_val}"
            )
            indicators = []
            for ci in group:
                b = model.new_bool_var(f"inaz_{ci}_{az_val}")
                model.add(az_of[ci] == az_val).only_enforce_if(b)
                model.add(az_of[ci] != az_val).only_enforce_if(~b)
                indicators.append(b)
            model.add_max_equality(has_this_az, indicators)
            az_present.append(has_this_az)
        model.add(sum(az_present) >= min_zones)

    # Latency scenarios (scale by 10 for integer arithmetic)
    SCALE = 10
    sn_lat = int(lat_model["same_node_ms"] * SCALE)       # 5
    sa_lat = int(lat_model["same_az_different_node_ms"] * SCALE)  # 20
    ca_lat = int(lat_model["cross_az_ms"] * SCALE)         # 80

    for scenario in qa["latency_scenarios"]:
        path = scenario["path"]
        budget_scaled = int(scenario["max_end_to_end_ms"] * SCALE)

        proc_sum = sum(
            int(components[comp_idx[cid]]["processing_time_ms"] * SCALE)
            for cid in path
        )

        hop_vars = []
        for k in range(len(path) - 1):
            ci = comp_idx[path[k]]
            cj = comp_idx[path[k + 1]]

            same_node = model.new_bool_var(f"sn_{scenario['name']}_{k}")
            model.add(node_of[ci] == node_of[cj]).only_enforce_if(same_node)
            model.add(node_of[ci] != node_of[cj]).only_enforce_if(~same_node)

            same_az = model.new_bool_var(f"sa_{scenario['name']}_{k}")
            model.add(az_of[ci] == az_of[cj]).only_enforce_if(same_az)
            model.add(az_of[ci] != az_of[cj]).only_enforce_if(~same_az)

            # same_node implies same_az
            model.add_implication(same_node, same_az)

            hop_lat = model.new_int_var(sn_lat, ca_lat, f"hl_{scenario['name']}_{k}")
            model.add(hop_lat == sn_lat).only_enforce_if(same_node)
            model.add(hop_lat == sa_lat).only_enforce_if(~same_node, same_az)
            model.add(hop_lat == ca_lat).only_enforce_if(~same_node, ~same_az)

            hop_vars.append(hop_lat)

        total_lat = model.new_int_var(0, 100000, f"total_{scenario['name']}")
        model.add(total_lat == proc_sum + sum(hop_vars))
        model.add(total_lat <= budget_scaled)

    # Cost objective: minimize sum of cost_per_hour for used nodes
    COST_SCALE = 100  # work in cents
    node_used = []
    for j in range(n_node):
        used = model.new_bool_var(f"used_{j}")
        model.add_max_equality(used, [is_on[i][j] for i in range(n_comp)])
        node_used.append(used)

    total_cost = model.new_int_var(0, 1000000, "total_cost")
    model.add(
        total_cost == sum(
            node_used[j] * int(dep_nodes[j]["cost_per_hour"] * COST_SCALE)
            for j in range(n_node)
        )
    )
    model.minimize(total_cost)

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 180
    solver.parameters.num_workers = 1
    status = solver.solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        assignments = {}
        for i, c in enumerate(components):
            nj = solver.value(node_of[i])
            assignments[c["id"]] = dep_nodes[nj]["id"]

        used_ids = sorted(set(assignments.values()))
        cost = sum(dep_nodes[node_idx[nid]]["cost_per_hour"] for nid in used_ids)

        result = {
            "assignments": assignments,
            "total_cost_per_hour": cost,
            "nodes_used": used_ids,
        }

        with open("/app/deployment_plan.json", "w") as f:
            json.dump(result, f, indent=2)

        status_name = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
        print(f"Solution found ({status_name}). Cost: ${cost:.2f}/hr")
        print(f"Nodes used: {used_ids}")
    else:
        print(f"No feasible solution found (status: {solver.status_name(status)})")
        sys.exit(1)


if __name__ == "__main__":
    solve()
