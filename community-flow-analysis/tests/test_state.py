
import json
import os
import pytest

EXPECTED_GROUPS = [
    {1, 2, 3, 4, 5, 6},
    {7, 8, 9, 10, 11, 12},
    {13, 14, 15, 16, 17, 18},
    {19, 20, 21, 22, 23, 24},
    {25, 26, 27, 28, 29, 30, 31},
]


def load_results():
    with open("/app/results.json") as f:
        return json.load(f)


def test_results_file_structure():
    assert os.path.isfile("/app/results.json"), "results.json not found"
    results = load_results()
    assert isinstance(results, dict), "results.json must be a JSON object"
    required = [
        "active_nodes", "valid_links", "community_count", "modularity",
        "community_map", "max_flow", "critical_link", "bridges",
    ]
    for key in required:
        assert key in results, f"Missing required key: {key}"


def test_active_nodes():
    results = load_results()
    assert results["active_nodes"] == 31, (
        f"Expected 31 active nodes, got {results['active_nodes']}"
    )


def test_valid_links():
    results = load_results()
    assert results["valid_links"] == 86, (
        f"Expected 86 valid links, got {results['valid_links']}"
    )


def test_data_issues_detected():
    results = load_results()
    issues = results.get("data_issues_found", 0)
    assert issues >= 4, (
        f"Expected at least 4 data issues detected, got {issues}"
    )


def test_community_count():
    results = load_results()
    assert results["community_count"] == 5, (
        f"Expected 5 communities, got {results['community_count']}"
    )


def test_all_active_nodes_assigned():
    results = load_results()
    cmap = results["community_map"]
    for n in range(1, 32):
        assert str(n) in cmap, f"Node {n} missing from community_map"


def test_community_partition_structure():
    results = load_results()
    cmap = results["community_map"]
    group_labels = []
    for group in EXPECTED_GROUPS:
        labels = set()
        for n in group:
            labels.add(cmap[str(n)])
        assert len(labels) == 1, (
            f"Nodes {sorted(group)} should share one community label, got {labels}"
        )
        group_labels.append(labels.pop())
    assert len(set(group_labels)) == 5, (
        f"Expected 5 distinct community labels, got {len(set(group_labels))}"
    )


def test_modularity():
    results = load_results()
    mod = results["modularity"]
    assert abs(float(mod) - 0.7592) < 0.01, (
        f"Modularity {mod} not within 0.01 of expected 0.7592"
    )


def test_max_flow_endpoints():
    results = load_results()
    mf = results["max_flow"]
    assert int(mf["source"]) == 1, f"Max flow source should be 1, got {mf['source']}"
    assert int(mf["target"]) == 29, f"Max flow target should be 29, got {mf['target']}"


def test_max_flow_value():
    results = load_results()
    mf = results["max_flow"]
    assert abs(float(mf["value"]) - 8) < 0.01, (
        f"Max flow value {mf['value']} != expected 8"
    )


def test_critical_link_identity():
    results = load_results()
    cl = results["critical_link"]
    edge = {int(cl["node_a"]), int(cl["node_b"])}
    assert edge == {24, 25}, (
        f"Critical link {edge} != expected {{24, 25}}"
    )


def test_critical_link_impact():
    results = load_results()
    cl = results["critical_link"]
    assert abs(float(cl["flow_impact"]) - 4) < 0.01, (
        f"Critical link flow impact {cl['flow_impact']} != expected 4"
    )


def test_bridges():
    results = load_results()
    bridges = results["bridges"]
    assert isinstance(bridges, list), "bridges must be a list"
    bridge_sets = [frozenset(int(x) for x in b) for b in bridges]
    assert frozenset({30, 31}) in bridge_sets, (
        f"Bridge (30,31) not found in {bridges}"
    )
    assert len(bridges) == 1, f"Expected exactly 1 bridge, got {len(bridges)}"
