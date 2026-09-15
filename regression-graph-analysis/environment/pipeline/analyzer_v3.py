"""
Regression graph analysis - version 3
Constructs a propagation graph from regressors to regressions.
"""

import csv
import json
import sys
import networkx as nx

csv.field_size_limit(sys.maxsize)


def analyze():
    rows = []
    with open("/app/dataset.csv") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    total_pairs = len(rows)
    # Count pairs where bug-related commits exist
    fixed_pairs = sum(1 for r in rows if r["BUG_COMMITS_MERCURIAL"].strip())
    unfixed_pairs = total_pairs - fixed_pairs

    G = nx.DiGraph()
    all_regressor_bugs = set()

    for row in rows:
        fix_id = int(row["FIX_ID"])
        G.add_node(fix_id)
        bug_ids_str = row["BUG_IDS"].strip()
        if bug_ids_str:
            for bid_str in bug_ids_str.split():
                bid = int(bid_str)
                all_regressor_bugs.add(bid)
                G.add_edge(bid, fix_id)

    out_degs = sorted(
        [(n, G.out_degree(n)) for n in G.nodes()],
        key=lambda x: (-x[1], x[0]),
    )

    wccs = list(nx.weakly_connected_components(G))
    sccs = list(nx.strongly_connected_components(G))
    num_sccs_with_cycles = sum(1 for scc in sccs if len(scc) > 1)

    C = nx.condensation(G)
    # Length of the longest chain through the condensation DAG
    longest_chain = len(nx.dag_longest_path(C))

    results = {
        "total_pairs": total_pairs,
        "fixed_pairs": fixed_pairs,
        "unfixed_pairs": unfixed_pairs,
        "unique_regressor_bugs": len(all_regressor_bugs),
        "graph_nodes": G.number_of_nodes(),
        "graph_edges": G.number_of_edges(),
        "max_out_degree_bug": out_degs[0][0],
        "max_out_degree": out_degs[0][1],
        "top_10_regressors": [[n, d] for n, d in out_degs[:10]],
        "num_weakly_connected_components": len(wccs),
        "largest_wcc_size": max(len(c) for c in wccs),
        "num_sccs_with_cycles": num_sccs_with_cycles,
        "has_cycles": num_sccs_with_cycles > 0,
        "longest_chain_length": longest_chain,
        "no_shared_files_count": sum(
            1 for r in rows if r.get("NO_FILE_SHARED") == "True"
        ),
        "no_bug_commit_count": sum(
            1 for r in rows if r.get("NO_BUG") == "True"
        ),
    }

    with open("/app/pipeline/output_v3.json", "w") as f:
        json.dump(results, f, indent=2)
    print("v3 analysis complete")


if __name__ == "__main__":
    analyze()
