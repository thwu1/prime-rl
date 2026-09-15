
"""
Correct regression graph analysis with pipeline audit, data quality triage,
filtered graph analysis, and PageRank propagation risk assessment.
"""

import csv
import json
import sys

import networkx as nx

csv.field_size_limit(sys.maxsize)


def main():
    # Parse dataset
    rows = []
    with open("/app/dataset.csv") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    total_pairs = len(rows)
    # Correct: use FIX_COMMITS_MERCURIAL for fix classification
    fixed_pairs = sum(
        1 for r in rows if r["FIX_COMMITS_MERCURIAL"].strip()
    )
    unfixed_pairs = total_pairs - fixed_pairs

    # Build correct directed graph: BUG_ID -> FIX_ID (regressor causes regression)
    G = nx.DiGraph()
    all_regressor_bugs = set()
    fix_ids = set()

    for row in rows:
        fix_id = int(row["FIX_ID"])
        fix_ids.add(fix_id)
        G.add_node(fix_id)
        bug_ids_str = row["BUG_IDS"].strip()
        if bug_ids_str:
            # Correct: space-separated, not comma-separated
            for bid_str in bug_ids_str.split():
                bid = int(bid_str)
                all_regressor_bugs.add(bid)
                G.add_edge(bid, fix_id)

    # Standard graph metrics
    out_degs = sorted(
        [(n, G.out_degree(n)) for n in G.nodes()],
        key=lambda x: (-x[1], x[0]),
    )

    wccs = list(nx.weakly_connected_components(G))
    sccs = list(nx.strongly_connected_components(G))
    num_sccs_with_cycles = sum(1 for scc in sccs if len(scc) > 1)
    has_cycles = num_sccs_with_cycles > 0

    C = nx.condensation(G)
    # Correct: use dag_longest_path_length (edge count), not len(dag_longest_path)
    longest_chain = nx.dag_longest_path_length(C)

    # Cascade vulnerability metrics
    orphan_regressor_count = len(all_regressor_bugs - fix_ids)
    pure_regression_count = len(fix_ids - all_regressor_bugs)

    multi_cause = 0
    for row in rows:
        bug_ids_str = row["BUG_IDS"].strip()
        if bug_ids_str:
            if len(set(bug_ids_str.split())) > 1:
                multi_cause += 1

    top3 = out_degs[:3]
    transitive_impact_top3 = [
        [n, len(nx.descendants(G, n))] for n, _ in top3
    ]

    nodes_with_out = [(n, d) for n, d in G.out_degree() if d > 0]
    mean_fanout = round(
        sum(d for _, d in nodes_with_out) / len(nodes_with_out), 2
    )

    # Pipeline audit results
    audit = {
        "v1": {
            "edge_direction_correct": False,
            "multivalue_parsing_correct": True,
            "fix_classification_correct": True,
            "path_length_correct": True,
        },
        "v2": {
            "edge_direction_correct": True,
            "multivalue_parsing_correct": False,
            "fix_classification_correct": True,
            "path_length_correct": True,
        },
        "v3": {
            "edge_direction_correct": True,
            "multivalue_parsing_correct": True,
            "fix_classification_correct": False,
            "path_length_correct": False,
        },
    }

    # Data quality triage
    self_referencing_pairs = 0
    no_bug_with_commits = 0
    for row in rows:
        fix_id_val = int(row["FIX_ID"])
        bug_ids_str = row["BUG_IDS"].strip()
        if bug_ids_str:
            bug_ids = [int(b) for b in bug_ids_str.split()]
            if fix_id_val in bug_ids:
                self_referencing_pairs += 1

        if (row.get("NO_BUG") == "True"
                and row["BUG_COMMITS_MERCURIAL"].strip()):
            no_bug_with_commits += 1

    extrinsic_bug_count = sum(
        1 for r in rows if r.get("NO_FILE_SHARED") == "True"
    )

    # Filtered graph: exclude extrinsic bug records (NO_FILE_SHARED=True)
    G_filtered = nx.DiGraph()
    for row in rows:
        if row.get("NO_FILE_SHARED") == "True":
            continue
        fid = int(row["FIX_ID"])
        G_filtered.add_node(fid)
        bug_ids_str = row["BUG_IDS"].strip()
        if bug_ids_str:
            for bid_str in bug_ids_str.split():
                bid = int(bid_str)
                G_filtered.add_edge(bid, fid)

    filtered_nodes = G_filtered.number_of_nodes()
    filtered_edges = G_filtered.number_of_edges()

    if filtered_nodes > 0:
        filtered_largest_wcc = max(
            len(c) for c in nx.weakly_connected_components(G_filtered)
        )
        filtered_sccs = list(nx.strongly_connected_components(G_filtered))
        filtered_has_cycles = any(len(scc) > 1 for scc in filtered_sccs)
        C_f = nx.condensation(G_filtered)
        filtered_longest_chain = nx.dag_longest_path_length(C_f)
    else:
        filtered_largest_wcc = 0
        filtered_has_cycles = False
        filtered_longest_chain = 0

    graph_edges = G.number_of_edges()
    edge_reduction_pct = round(
        (1.0 - filtered_edges / graph_edges) * 100, 2
    ) if graph_edges > 0 else 0.0

    # PageRank propagation risk
    pr = nx.pagerank(G)
    pr_sorted = sorted(pr.items(), key=lambda x: (-x[1], x[0]))
    pagerank_top10 = [[n, round(s, 6)] for n, s in pr_sorted[:10]]

    # Assemble results
    results = {
        "audit": audit,
        "total_pairs": total_pairs,
        "fixed_pairs": fixed_pairs,
        "unfixed_pairs": unfixed_pairs,
        "unique_regressor_bugs": len(all_regressor_bugs),
        "graph_nodes": G.number_of_nodes(),
        "graph_edges": graph_edges,
        "max_out_degree_bug": out_degs[0][0],
        "max_out_degree": out_degs[0][1],
        "top_10_regressors": [[n, d] for n, d in out_degs[:10]],
        "num_weakly_connected_components": len(wccs),
        "largest_wcc_size": max(len(c) for c in wccs),
        "num_sccs_with_cycles": num_sccs_with_cycles,
        "has_cycles": has_cycles,
        "longest_chain_length": longest_chain,
        "no_shared_files_count": sum(
            1 for r in rows if r.get("NO_FILE_SHARED") == "True"
        ),
        "no_bug_commit_count": sum(
            1 for r in rows if r.get("NO_BUG") == "True"
        ),
        "orphan_regressor_count": orphan_regressor_count,
        "pure_regression_count": pure_regression_count,
        "multi_cause_regression_count": multi_cause,
        "transitive_impact_top3": transitive_impact_top3,
        "mean_regressor_fanout": mean_fanout,
        "data_quality": {
            "self_referencing_pairs": self_referencing_pairs,
            "no_bug_with_commits": no_bug_with_commits,
            "extrinsic_bug_count": extrinsic_bug_count,
        },
        "filtered_graph": {
            "nodes": filtered_nodes,
            "edges": filtered_edges,
            "largest_wcc_size": filtered_largest_wcc,
            "has_cycles": filtered_has_cycles,
            "longest_chain_length": filtered_longest_chain,
            "edge_reduction_pct": edge_reduction_pct,
        },
        "pagerank_top10": pagerank_top10,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Analysis complete. Results written to /app/results.json")


if __name__ == "__main__":
    main()
