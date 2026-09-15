
import csv
import json
import sys
from collections import deque, defaultdict

import networkx as nx
import pytest


def compute_forward_reach(graph):
    """BFS from each node to count distinct reachable nodes (excluding self)."""
    reach = {}
    for n in graph.nodes():
        visited = {n}
        q = deque([n])
        while q:
            cur = q.popleft()
            for s in graph.successors(cur):
                if s not in visited:
                    visited.add(s)
                    q.append(s)
        reach[n] = len(visited) - 1
    return reach


def build_reference():
    """Independently compute all reference metrics from raw data files."""
    csv.field_size_limit(sys.maxsize)

    # --- Read and deduplicate CSV ---
    with open("/data/regression_export.csv") as f:
        raw_rows = list(csv.DictReader(f))

    total_raw_rows = len(raw_rows)

    seen = set()
    unique_rows = []
    for row in raw_rows:
        key = tuple(sorted(row.items()))
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)

    unique_row_count = len(unique_rows)

    # --- Build graph, count self-loops ---
    G = nx.DiGraph()
    all_ids = set()
    self_loop_count = 0

    for row in unique_rows:
        fix_id = int(row["FIX_ID"])
        all_ids.add(fix_id)
        bids = row["BUG_IDS"].strip()
        if bids:
            for b in bids.split():
                bid = int(b)
                all_ids.add(bid)
                if bid == fix_id:
                    self_loop_count += 1
                else:
                    if not G.has_edge(bid, fix_id):
                        G.add_edge(bid, fix_id)

    for nid in all_ids:
        if nid not in G:
            G.add_node(nid)

    clean_edge_count = G.number_of_edges()

    # --- Graph topology ---
    num_nodes = G.number_of_nodes()
    num_edges = G.number_of_edges()

    wccs = list(nx.weakly_connected_components(G))
    num_wcc = len(wccs)
    largest_wcc_size = max(len(c) for c in wccs)

    sccs = [c for c in nx.strongly_connected_components(G) if len(c) > 1]
    num_nontrivial_sccs = len(sccs)
    if sccs:
        sccs.sort(key=lambda c: (-len(c), min(c)))
        largest_scc_size = len(sccs[0])
    else:
        largest_scc_size = 0

    C_dag = nx.condensation(G)
    cond_longest = nx.dag_longest_path_length(C_dag)

    num_sources = sum(1 for n in G.nodes() if G.in_degree(n) == 0)
    num_sinks = sum(1 for n in G.nodes() if G.out_degree(n) == 0)

    out_sorted = sorted(G.nodes(), key=lambda n: (-G.out_degree(n), n))
    max_out_degree = G.out_degree(out_sorted[0])
    max_out_degree_node = out_sorted[0]

    in_sorted = sorted(G.nodes(), key=lambda n: (-G.in_degree(n), n))
    max_in_degree = G.in_degree(in_sorted[0])
    max_in_degree_node = in_sorted[0]

    # --- Cascade analysis ---
    reach = compute_forward_reach(G)
    total_cascade_impact = sum(reach.values())
    max_forward_reach = max(reach.values()) if reach else 0

    reach_ranked = sorted(reach.items(), key=lambda x: (-x[1], x[0]))
    top_10 = [{"bug_id": n, "forward_reach": r} for n, r in reach_ranked[:10]]

    # --- Greedy prevention ---
    G_greedy = G.copy()
    prevention_sequence = []
    cumulative_reach_removed = 0
    threshold = total_cascade_impact * 0.5

    while cumulative_reach_removed < threshold and G_greedy.number_of_nodes() > 0:
        greedy_reach = compute_forward_reach(G_greedy)
        if not greedy_reach:
            break
        best_node, best_reach = sorted(
            greedy_reach.items(), key=lambda x: (-x[1], x[0])
        )[0]
        if best_reach == 0:
            break
        prevention_sequence.append(best_node)
        cumulative_reach_removed += best_reach
        G_greedy.remove_node(best_node)

    remaining_reach = compute_forward_reach(G_greedy)
    remaining_total_impact = sum(remaining_reach.values())

    # --- Component risk ---
    metadata = {}
    with open("/data/patch_metadata.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                entry = json.loads(line)
                metadata[entry["bug_id"]] = entry["component"]

    comp_data = defaultdict(lambda: {"total_forward_reach": 0, "bug_count": 0})
    for n in G.nodes():
        comp = metadata.get(n, "unknown")
        comp_data[comp]["total_forward_reach"] += reach[n]
        comp_data[comp]["bug_count"] += 1

    comp_ranked = sorted(
        comp_data.items(), key=lambda x: (-x[1]["total_forward_reach"], x[0])
    )
    top_5_components = [
        {
            "component": comp,
            "total_forward_reach": data["total_forward_reach"],
            "bug_count": data["bug_count"],
        }
        for comp, data in comp_ranked[:5]
    ]

    return {
        "data_quality": {
            "total_raw_rows": total_raw_rows,
            "unique_rows": unique_row_count,
            "self_loop_edges": self_loop_count,
            "clean_edge_count": clean_edge_count,
        },
        "graph_topology": {
            "num_nodes": num_nodes,
            "num_edges": num_edges,
            "num_weakly_connected_components": num_wcc,
            "largest_wcc_size": largest_wcc_size,
            "num_nontrivial_sccs": num_nontrivial_sccs,
            "largest_scc_size": largest_scc_size,
            "condensation_longest_path": cond_longest,
            "num_sources": num_sources,
            "num_sinks": num_sinks,
            "max_out_degree": max_out_degree,
            "max_out_degree_node": max_out_degree_node,
            "max_in_degree": max_in_degree,
            "max_in_degree_node": max_in_degree_node,
        },
        "cascade_analysis": {
            "total_cascade_impact": total_cascade_impact,
            "max_forward_reach": max_forward_reach,
            "top_10_cascade_sources": top_10,
        },
        "greedy_prevention": {
            "prevention_sequence": prevention_sequence,
            "steps_required": len(prevention_sequence),
            "cumulative_reach_removed": cumulative_reach_removed,
            "remaining_total_impact": remaining_total_impact,
        },
        "component_risk": {
            "top_5_components": top_5_components,
        },
    }


def load_results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reference():
    return build_reference()


@pytest.fixture(scope="module")
def results():
    return load_results()


# ================================================================
# Data Quality Tests
# ================================================================
class TestDataQuality:
    def test_total_raw_rows(self, results, reference):
        assert results["data_quality"]["total_raw_rows"] == reference["data_quality"]["total_raw_rows"]

    def test_unique_rows(self, results, reference):
        assert results["data_quality"]["unique_rows"] == reference["data_quality"]["unique_rows"]

    def test_self_loop_edges(self, results, reference):
        assert results["data_quality"]["self_loop_edges"] == reference["data_quality"]["self_loop_edges"]

    def test_clean_edge_count(self, results, reference):
        assert results["data_quality"]["clean_edge_count"] == reference["data_quality"]["clean_edge_count"]


# ================================================================
# Graph Topology Tests
# ================================================================
class TestGraphTopology:
    def test_num_nodes(self, results, reference):
        assert results["graph_topology"]["num_nodes"] == reference["graph_topology"]["num_nodes"]

    def test_num_edges(self, results, reference):
        assert results["graph_topology"]["num_edges"] == reference["graph_topology"]["num_edges"]

    def test_num_wcc(self, results, reference):
        assert results["graph_topology"]["num_weakly_connected_components"] == reference["graph_topology"]["num_weakly_connected_components"]

    def test_largest_wcc(self, results, reference):
        assert results["graph_topology"]["largest_wcc_size"] == reference["graph_topology"]["largest_wcc_size"]

    def test_num_nontrivial_sccs(self, results, reference):
        assert results["graph_topology"]["num_nontrivial_sccs"] == reference["graph_topology"]["num_nontrivial_sccs"]

    def test_largest_scc_size(self, results, reference):
        assert results["graph_topology"]["largest_scc_size"] == reference["graph_topology"]["largest_scc_size"]

    def test_condensation_longest_path(self, results, reference):
        assert results["graph_topology"]["condensation_longest_path"] == reference["graph_topology"]["condensation_longest_path"]

    def test_num_sources(self, results, reference):
        assert results["graph_topology"]["num_sources"] == reference["graph_topology"]["num_sources"]

    def test_num_sinks(self, results, reference):
        assert results["graph_topology"]["num_sinks"] == reference["graph_topology"]["num_sinks"]

    def test_max_out_degree(self, results, reference):
        assert results["graph_topology"]["max_out_degree"] == reference["graph_topology"]["max_out_degree"]

    def test_max_out_degree_node(self, results, reference):
        assert results["graph_topology"]["max_out_degree_node"] == reference["graph_topology"]["max_out_degree_node"]

    def test_max_in_degree(self, results, reference):
        assert results["graph_topology"]["max_in_degree"] == reference["graph_topology"]["max_in_degree"]

    def test_max_in_degree_node(self, results, reference):
        assert results["graph_topology"]["max_in_degree_node"] == reference["graph_topology"]["max_in_degree_node"]


# ================================================================
# Cascade Analysis Tests
# ================================================================
class TestCascadeAnalysis:
    def test_total_cascade_impact(self, results, reference):
        assert results["cascade_analysis"]["total_cascade_impact"] == reference["cascade_analysis"]["total_cascade_impact"]

    def test_max_forward_reach(self, results, reference):
        assert results["cascade_analysis"]["max_forward_reach"] == reference["cascade_analysis"]["max_forward_reach"]

    def test_top_10_cascade_sources(self, results, reference):
        assert results["cascade_analysis"]["top_10_cascade_sources"] == reference["cascade_analysis"]["top_10_cascade_sources"]


# ================================================================
# Greedy Prevention Tests
# ================================================================
class TestGreedyPrevention:
    def test_prevention_sequence(self, results, reference):
        assert results["greedy_prevention"]["prevention_sequence"] == reference["greedy_prevention"]["prevention_sequence"]

    def test_steps_required(self, results, reference):
        assert results["greedy_prevention"]["steps_required"] == reference["greedy_prevention"]["steps_required"]

    def test_cumulative_reach_removed(self, results, reference):
        assert results["greedy_prevention"]["cumulative_reach_removed"] == reference["greedy_prevention"]["cumulative_reach_removed"]

    def test_remaining_total_impact(self, results, reference):
        assert results["greedy_prevention"]["remaining_total_impact"] == reference["greedy_prevention"]["remaining_total_impact"]


# ================================================================
# Component Risk Tests
# ================================================================
class TestComponentRisk:
    def test_top_5_components(self, results, reference):
        assert results["component_risk"]["top_5_components"] == reference["component_risk"]["top_5_components"]
