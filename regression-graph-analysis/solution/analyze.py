
"""
Analyze Mozilla's regressors-regressions dataset to build a regression
propagation graph and compute structural metrics.
"""

import csv
import json
import sys

import networkx as nx

csv.field_size_limit(sys.maxsize)


def main():
    # ------------------------------------------------------------------
    # 1. Parse the dataset
    # ------------------------------------------------------------------
    rows = []
    with open("/app/dataset.csv", "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    total_pairs = len(rows)
    fixed_pairs = 0
    unfixed_pairs = 0

    # ------------------------------------------------------------------
    # 2. Build directed regression propagation graph
    #    Edge: BUG_ID -> FIX_ID  ("fixing BUG_ID introduced regression FIX_ID")
    # ------------------------------------------------------------------
    G = nx.DiGraph()
    all_regressor_bugs = set()

    for row in rows:
        fix_id = int(row["FIX_ID"])
        G.add_node(fix_id)

        if row["FIX_COMMITS_MERCURIAL"].strip():
            fixed_pairs += 1
        else:
            unfixed_pairs += 1

        bug_ids_str = row["BUG_IDS"].strip()
        if bug_ids_str:
            for bid_str in bug_ids_str.split():
                bid = int(bid_str)
                all_regressor_bugs.add(bid)
                G.add_edge(bid, fix_id)

    # ------------------------------------------------------------------
    # 3. Compute graph metrics
    # ------------------------------------------------------------------
    graph_nodes = G.number_of_nodes()
    graph_edges = G.number_of_edges()

    # Out-degree analysis (regressor impact)
    out_deg_list = [(node, G.out_degree(node)) for node in G.nodes()]
    out_deg_list.sort(key=lambda x: (-x[1], x[0]))

    max_out_degree_bug = out_deg_list[0][0]
    max_out_degree = out_deg_list[0][1]
    top_10_regressors = [[n, d] for n, d in out_deg_list[:10]]

    # Weakly connected components
    wccs = list(nx.weakly_connected_components(G))
    num_wcc = len(wccs)
    largest_wcc_size = max(len(c) for c in wccs)

    # Strongly connected components and cycle detection
    sccs = list(nx.strongly_connected_components(G))
    num_sccs_with_cycles = sum(1 for scc in sccs if len(scc) > 1)
    has_cycles = num_sccs_with_cycles > 0

    # Condensation DAG and longest directed path
    condensation = nx.condensation(G)
    longest_chain = nx.dag_longest_path_length(condensation)

    # Boolean flag counts from original CSV
    no_shared_files_count = sum(
        1 for r in rows if r.get("NO_FILE_SHARED", "") == "True"
    )
    no_bug_commit_count = sum(
        1 for r in rows if r.get("NO_BUG", "") == "True"
    )

    # ------------------------------------------------------------------
    # 4. Write results
    # ------------------------------------------------------------------
    results = {
        "total_pairs": total_pairs,
        "fixed_pairs": fixed_pairs,
        "unfixed_pairs": unfixed_pairs,
        "unique_regressor_bugs": len(all_regressor_bugs),
        "graph_nodes": graph_nodes,
        "graph_edges": graph_edges,
        "max_out_degree_bug": max_out_degree_bug,
        "max_out_degree": max_out_degree,
        "top_10_regressors": top_10_regressors,
        "num_weakly_connected_components": num_wcc,
        "largest_wcc_size": largest_wcc_size,
        "num_sccs_with_cycles": num_sccs_with_cycles,
        "has_cycles": has_cycles,
        "longest_chain_length": longest_chain,
        "no_shared_files_count": no_shared_files_count,
        "no_bug_commit_count": no_bug_commit_count,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Analysis complete. Results written to /app/results.json")
    for k, v in results.items():
        if k == "top_10_regressors":
            print(f"  {k}:")
            for entry in v:
                print(f"    bug {entry[0]}: {entry[1]} regressions")
        else:
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
