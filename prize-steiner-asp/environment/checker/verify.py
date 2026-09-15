#!/usr/bin/env python3
"""Validate an ASP-Core-2 encoding for the PCST optimization problem.

Usage: python3 checker/verify.py [encoding_path]
Default encoding path: /app/encoding.lp

Checks:
  - Encoding loads without syntax errors
  - Clingo proves optimality on every instance in the manifest
  - Answer sets contain valid in_tree/1 and use_edge/2 atoms
  - Selected subgraph forms a connected tree
  - Computed profit matches the expected optimum
"""
import sys
import os
import json
import re


def parse_instance(path):
    """Extract prizes and edges from an ASP instance file."""
    with open(path) as f:
        content = f.read()
    prizes = {}
    edges = {}
    for m in re.finditer(r"prize\(\s*(\d+)\s*,\s*(\d+)\s*\)", content):
        prizes[int(m.group(1))] = int(m.group(2))
    for m in re.finditer(r"edge\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", content):
        u, v, w = int(m.group(1)), int(m.group(2)), int(m.group(3))
        edges[(min(u, v), max(u, v))] = w
    return prizes, edges


def extract_solution(atoms):
    """Extract in_tree and use_edge atoms from the answer set."""
    tree_nodes = set()
    tree_edges = set()
    for atom in atoms:
        m = re.match(r"in_tree\((\d+)\)", atom)
        if m:
            tree_nodes.add(int(m.group(1)))
            continue
        m = re.match(r"use_edge\((\d+),(\d+)\)", atom)
        if m:
            tree_edges.add((int(m.group(1)), int(m.group(2))))
    return tree_nodes, tree_edges


def check_connectivity(tree_nodes, tree_edges):
    """BFS connectivity check on the selected subgraph."""
    if len(tree_nodes) <= 1:
        return True
    if not tree_edges:
        return False
    adj = {n: set() for n in tree_nodes}
    for u, v in tree_edges:
        adj[u].add(v)
        adj[v].add(u)
    start = min(tree_nodes)
    visited = {start}
    queue = [start]
    while queue:
        node = queue.pop(0)
        for nbr in adj.get(node, set()):
            if nbr not in visited:
                visited.add(nbr)
                queue.append(nbr)
    return visited == tree_nodes


def main():
    import clingo

    encoding_path = sys.argv[1] if len(sys.argv) > 1 else "/app/encoding.lp"
    manifest_path = "/app/instances/test_manifest.json"

    if not os.path.exists(encoding_path):
        print(f"ERROR: Encoding not found at {encoding_path}")
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    all_pass = True
    for instance_name, meta in sorted(manifest.items()):
        expected_profit = meta["expected_profit"]
        instance_path = os.path.join("/app/instances", instance_name)
        prizes, edges = parse_instance(instance_path)

        try:
            ctl = clingo.Control(["0"])
            ctl.load(encoding_path)
            ctl.load(instance_path)
            ctl.ground([("base", [])])
        except Exception as exc:
            print(f"FAIL {instance_name}: load/ground error — {exc}")
            all_pass = False
            continue

        state = {"best_atoms": set(), "best_cost": None}

        def on_model(model, st=state):
            st["best_atoms"] = set(str(a) for a in model.symbols(shown=True))
            if model.cost:
                st["best_cost"] = model.cost[0]

        result = ctl.solve(on_model=on_model)
        optimum_found = bool(result.satisfiable) and bool(result.exhausted)

        if not optimum_found:
            print(f"FAIL {instance_name}: optimum not proven by solver")
            all_pass = False
            continue

        tree_nodes, tree_edges = extract_solution(state["best_atoms"])

        # Validate structure
        for u, v in tree_edges:
            if u not in tree_nodes or v not in tree_nodes:
                print(f"FAIL {instance_name}: edge endpoint not in tree")
                all_pass = False
                continue
            canon = (min(u, v), max(u, v))
            if canon not in edges:
                print(f"FAIL {instance_name}: edge ({u},{v}) not in instance")
                all_pass = False
                continue

        if not check_connectivity(tree_nodes, tree_edges):
            print(f"FAIL {instance_name}: tree not connected")
            all_pass = False
            continue

        # Compute profit
        total_prize = sum(prizes.get(n, 0) for n in tree_nodes)
        total_cost = sum(
            edges[(min(u, v), max(u, v))] for u, v in tree_edges
        )
        computed_profit = total_prize - total_cost

        if computed_profit != expected_profit:
            print(
                f"FAIL {instance_name}: profit {computed_profit} "
                f"!= expected {expected_profit}"
            )
            all_pass = False
        else:
            print(f"PASS {instance_name}: profit={computed_profit}")

    if all_pass:
        print("\nAll instances passed!")
    else:
        print("\nSome instances failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
