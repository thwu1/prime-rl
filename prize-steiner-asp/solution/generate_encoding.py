#!/usr/bin/env python3
"""
Generate the ASP-Core-2 encoding for the Prize-Collecting Steiner Tree problem.
Writes the encoding to /app/encoding.lp and verifies on all benchmark instances.
"""

import sys
import json
import clingo


def build_encoding():
    """Construct the PCST encoding rule by rule."""
    rules = []

    rules.append("% Prize-Collecting Steiner Tree (PCST)")
    rules.append("% Maximize: sum of prizes of tree nodes - sum of edge weights")
    rules.append("% Equivalently minimize: sum of edge weights - sum of prizes")
    rules.append("")

    # Node selection: any node may be included in the tree
    rules.append("% Select which vertices to include in the subtree")
    rules.append("{ in_tree(V) } :- node(V).")
    rules.append("")

    # Edge selection: any edge may be used (canonical form U < V from input)
    rules.append("% Select which edges to include")
    rules.append("{ use_edge(U,V) } :- edge(U,V,_).")
    rules.append("")

    # Edge-endpoint constraints
    rules.append("% Edge endpoints must be in the tree")
    rules.append(":- use_edge(U,V), not in_tree(U).")
    rules.append(":- use_edge(U,V), not in_tree(V).")
    rules.append("")

    # Root determination: minimum-ID node in the tree (for connectivity)
    rules.append("% Root is the smallest-ID tree node")
    rules.append("has_smaller(V) :- in_tree(V), in_tree(U), U < V.")
    rules.append("root(V) :- in_tree(V), not has_smaller(V).")
    rules.append("")

    # Reachability from root (bidirectional since edges are undirected)
    rules.append("% Reachability from root via selected edges (undirected)")
    rules.append("reach(V) :- root(V).")
    rules.append("reach(V) :- reach(U), use_edge(U,V).")
    rules.append("reach(U) :- reach(V), use_edge(U,V).")
    rules.append("")

    # Connectivity enforcement
    rules.append("% All tree nodes must be reachable from root")
    rules.append(":- in_tree(V), not reach(V).")
    rules.append("")

    # Tree constraint: exactly |V|-1 edges for |V| nodes (prevents cycles)
    rules.append("% Tree must have exactly n-1 edges for n nodes")
    rules.append("tree_nodes(N) :- N = #count { V : in_tree(V) }.")
    rules.append("tree_edges(M) :- M = #count { U,V : use_edge(U,V) }.")
    rules.append(":- tree_nodes(N), tree_edges(M), N > 0, M != N - 1.")
    rules.append("")

    # Optimization via weak constraints
    # Minimize: (sum edge costs) - (sum node prizes)
    rules.append("% Minimize total edge cost minus total node prize")
    rules.append(":~ use_edge(U,V), edge(U,V,W). [W,e,U,V]")
    rules.append(":~ in_tree(V), prize(V,P). [-P,n,V]")
    rules.append("")

    # Show directives
    rules.append("#show in_tree/1.")
    rules.append("#show use_edge/2.")

    return "\n".join(rules) + "\n"


def verify_encoding(encoding_path):
    """Verify encoding on all instances using clingo Python API."""
    manifest_path = "/app/instances/test_manifest.json"
    with open(manifest_path) as f:
        manifest = json.load(f)

    all_pass = True
    for instance_name, meta in sorted(manifest.items()):
        exp_profit = meta["expected_profit"]
        instance_path = f"/app/instances/{instance_name}"
        try:
            ctl = clingo.Control(["0"])
            ctl.load(encoding_path)
            ctl.load(instance_path)
            ctl.ground([("base", [])])

            state = {"best_cost": None}

            def on_model(model, st=state):
                if model.cost:
                    st["best_cost"] = model.cost[0]

            result = ctl.solve(on_model=on_model)
            optimum_found = bool(result.satisfiable) and bool(result.exhausted)

            if not optimum_found:
                print(f"{instance_name}: OPTIMUM NOT FOUND")
                all_pass = False
                continue

            best_cost = state["best_cost"]
            if best_cost is None:
                print(f"{instance_name}: could not obtain cost")
                all_pass = False
                continue

            profit = -best_cost
            status = "PASS" if profit == exp_profit else "FAIL"
            print(f"{instance_name}: profit={profit}, expected={exp_profit} [{status}]")
            if profit != exp_profit:
                all_pass = False

        except Exception as exc:
            print(f"{instance_name}: ERROR -- {exc}")
            all_pass = False

    return all_pass


def main():
    encoding = build_encoding()
    output_path = "/app/encoding.lp"

    with open(output_path, "w") as f:
        f.write(encoding)
    print(f"Encoding written to {output_path}")

    print("\nVerifying on all instances...")
    success = verify_encoding(output_path)

    if not success:
        print("\nSome instances FAILED")
        sys.exit(1)
    else:
        print("\nAll instances PASSED")


if __name__ == "__main__":
    main()
