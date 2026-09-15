
import json
import os
import pytest


@pytest.fixture(scope="module")
def architecture():
    with open("/app/architecture.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def deployment_plan():
    with open("/app/deployment_plan.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def assignments(deployment_plan):
    return deployment_plan["assignments"]


@pytest.fixture(scope="module")
def components(architecture):
    return {c["id"]: c for c in architecture["components"]}


@pytest.fixture(scope="module")
def nodes(architecture):
    return {n["id"]: n for n in architecture["deployment_nodes"]}


@pytest.fixture(scope="module")
def zone_level(architecture):
    ordering = architecture["security_zone_hierarchy"]["ordering"]
    return {z: i for i, z in enumerate(ordering)}


def test_output_exists():
    assert os.path.exists("/app/deployment_plan.json"), (
        "deployment_plan.json not found at /app/deployment_plan.json"
    )


def test_valid_json():
    with open("/app/deployment_plan.json") as f:
        data = json.load(f)
    assert "assignments" in data, "Missing 'assignments' key"
    assert isinstance(data["assignments"], dict), "'assignments' must be a dict"
    assert "total_cost_per_hour" in data, "Missing 'total_cost_per_hour' key"
    assert "nodes_used" in data, "Missing 'nodes_used' key"


def test_all_components_assigned(architecture, assignments):
    comp_ids = {c["id"] for c in architecture["components"]}
    assigned = set(assignments.keys())
    missing = comp_ids - assigned
    assert not missing, f"Missing component assignments: {missing}"
    extra = assigned - comp_ids
    assert not extra, f"Unknown component IDs in assignments: {extra}"


def test_valid_node_assignments(architecture, assignments):
    node_ids = {n["id"] for n in architecture["deployment_nodes"]}
    for comp_id, node_id in assignments.items():
        assert node_id in node_ids, (
            f"Component '{comp_id}' assigned to unknown node '{node_id}'"
        )


def test_cpu_capacity(architecture, assignments, components, nodes):
    node_cpu = {}
    for comp_id, node_id in assignments.items():
        node_cpu[node_id] = node_cpu.get(node_id, 0) + components[comp_id]["cpu_units"]

    for node_id, used in node_cpu.items():
        cap = nodes[node_id]["cpu_capacity"]
        assert used <= cap, (
            f"Node '{node_id}': CPU usage {used} exceeds capacity {cap}"
        )


def test_memory_capacity(architecture, assignments, components, nodes):
    node_mem = {}
    for comp_id, node_id in assignments.items():
        node_mem[node_id] = node_mem.get(node_id, 0) + components[comp_id]["memory_mb"]

    for node_id, used in node_mem.items():
        cap = nodes[node_id]["memory_capacity_mb"]
        assert used <= cap, (
            f"Node '{node_id}': memory usage {used}MB exceeds capacity {cap}MB"
        )


def test_security_zone_constraints(assignments, components, nodes, zone_level):
    for comp_id, node_id in assignments.items():
        comp_lvl = zone_level[components[comp_id]["security_classification"]]
        node_lvl = zone_level[nodes[node_id]["security_zone"]]
        assert node_lvl >= comp_lvl, (
            f"Component '{comp_id}' (classification="
            f"'{components[comp_id]['security_classification']}') placed on node "
            f"'{node_id}' (zone='{nodes[node_id]['security_zone']}'): "
            f"zone level {node_lvl} < required {comp_lvl}"
        )


def test_affinity_rules(architecture, assignments):
    for rule in architecture["quality_attributes"]["affinity_rules"]:
        comps = rule["components"]
        assigned_nodes = [assignments[c] for c in comps]
        assert len(set(assigned_nodes)) == 1, (
            f"Affinity violation: {comps} must be on same node but assigned to "
            f"{dict(zip(comps, assigned_nodes))}"
        )


def test_anti_affinity_rules(architecture, assignments):
    for rule in architecture["quality_attributes"]["anti_affinity_rules"]:
        comps = rule["components"]
        assigned_nodes = [assignments[c] for c in comps]
        assert len(set(assigned_nodes)) == len(comps), (
            f"Anti-affinity violation: {comps} must be on different nodes but "
            f"assigned to {dict(zip(comps, assigned_nodes))}"
        )


def test_latency_scenario_auth(architecture, assignments, components, nodes):
    _check_latency_scenario(architecture, assignments, components, nodes, 0)


def test_latency_scenario_expense(architecture, assignments, components, nodes):
    _check_latency_scenario(architecture, assignments, components, nodes, 1)


def test_latency_scenario_payment(architecture, assignments, components, nodes):
    _check_latency_scenario(architecture, assignments, components, nodes, 2)


def test_latency_scenario_report(architecture, assignments, components, nodes):
    _check_latency_scenario(architecture, assignments, components, nodes, 3)


def test_latency_scenario_fraud(architecture, assignments, components, nodes):
    _check_latency_scenario(architecture, assignments, components, nodes, 4)


def _check_latency_scenario(architecture, assignments, components, nodes, idx):
    lat_model = architecture["latency_model"]
    sn_ms = lat_model["same_node_ms"]
    sa_ms = lat_model["same_az_different_node_ms"]
    ca_ms = lat_model["cross_az_ms"]

    scenario = architecture["quality_attributes"]["latency_scenarios"][idx]
    path = scenario["path"]
    budget = scenario["max_end_to_end_ms"]

    total_proc = sum(components[c]["processing_time_ms"] for c in path)
    total_net = 0.0

    for i in range(len(path) - 1):
        na = assignments[path[i]]
        nb = assignments[path[i + 1]]
        if na == nb:
            total_net += sn_ms
        elif nodes[na]["availability_zone"] == nodes[nb]["availability_zone"]:
            total_net += sa_ms
        else:
            total_net += ca_ms

    total = total_proc + total_net
    assert total <= budget, (
        f"Latency scenario '{scenario['name']}': {total:.1f}ms exceeds budget "
        f"{budget:.1f}ms (processing={total_proc:.1f}ms, network={total_net:.1f}ms, "
        f"path={path})"
    )


def test_az_distribution(architecture, assignments, nodes):
    for req in architecture["quality_attributes"]["az_distribution_requirements"]:
        group = req["component_group"]
        min_zones = req["min_zones"]
        azs = {nodes[assignments[c]]["availability_zone"] for c in group}
        assert len(azs) >= min_zones, (
            f"AZ distribution violation: group {group} spans {len(azs)} zone(s) "
            f"({azs}), needs at least {min_zones}"
        )


def test_cost_threshold(architecture, assignments):
    nodes_dict = {n["id"]: n for n in architecture["deployment_nodes"]}
    used = set(assignments.values())
    cost = sum(nodes_dict[n]["cost_per_hour"] for n in used)
    assert cost <= 21.0, (
        f"Total cost ${cost:.2f}/hr exceeds budget of $21.00/hr "
        f"(nodes used: {sorted(used)})"
    )


def test_output_consistency(deployment_plan, architecture):
    nodes_dict = {n["id"]: n for n in architecture["deployment_nodes"]}
    assignments = deployment_plan["assignments"]
    used = set(assignments.values())
    actual_cost = sum(nodes_dict[n]["cost_per_hour"] for n in used)

    reported_cost = deployment_plan["total_cost_per_hour"]
    assert abs(reported_cost - actual_cost) < 0.01, (
        f"Reported cost ${reported_cost:.2f} != actual ${actual_cost:.2f}"
    )

    reported_nodes = set(deployment_plan["nodes_used"])
    assert reported_nodes == used, (
        f"Reported nodes {sorted(reported_nodes)} != actual {sorted(used)}"
    )
