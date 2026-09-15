#!/usr/bin/env python3
"""
Regression dependency forensics: audit, clean, analyze, optimize.
Reads data from /data/, writes /app/results.json.
"""
import csv
import json
import sys
from collections import deque, defaultdict

import networkx as nx


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


def main():
    csv.field_size_limit(sys.maxsize)

    # ================================================================
    # 1. Read and deduplicate CSV
    # ================================================================
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

    # ================================================================
    # 2. Build directed graph, count self-loops
    # ================================================================
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

    # ================================================================
    # 3. Graph topology
    # ================================================================
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

    C = nx.condensation(G)
    cond_longest = nx.dag_longest_path_length(C)

    num_sources = sum(1 for n in G.nodes() if G.in_degree(n) == 0)
    num_sinks = sum(1 for n in G.nodes() if G.out_degree(n) == 0)

    out_sorted = sorted(G.nodes(), key=lambda n: (-G.out_degree(n), n))
    max_out_degree = G.out_degree(out_sorted[0])
    max_out_degree_node = out_sorted[0]

    in_sorted = sorted(G.nodes(), key=lambda n: (-G.in_degree(n), n))
    max_in_degree = G.in_degree(in_sorted[0])
    max_in_degree_node = in_sorted[0]

    # ================================================================
    # 4. Cascade analysis (forward reachability)
    # ================================================================
    reach = compute_forward_reach(G)
    total_cascade_impact = sum(reach.values())
    max_forward_reach = max(reach.values()) if reach else 0

    reach_ranked = sorted(reach.items(), key=lambda x: (-x[1], x[0]))
    top_10 = [{"bug_id": n, "forward_reach": r} for n, r in reach_ranked[:10]]

    # ================================================================
    # 5. Greedy prevention
    # ================================================================
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

    # ================================================================
    # 6. Component risk (cross-reference with JSONL metadata)
    # ================================================================
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

    # ================================================================
    # 7. Write results
    # ================================================================
    results = {
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

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
