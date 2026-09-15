#!/usr/bin/env python3
"""
Proof Structure Soundness Analyzer

Analyzes a JasperGold-style proof decomposition for:
1. Circular dependencies in assume-guarantee decompositions
2. Incomplete case-splits and partitions
3. Per-node decomposition soundness
"""

import json
import sys
from collections import defaultdict


def load_spec(path="/app/proof_structure.json"):
    with open(path) as f:
        return json.load(f)


def collect_all_nodes(node, parent=None, results=None):
    """Recursively collect all nodes with their parent info."""
    if results is None:
        results = {}
    results[node["id"]] = {"node": node, "parent": parent}
    for child in node.get("children", []):
        collect_all_nodes(child, parent=node["id"], results=results)
    return results


def build_assumption_graph_for_ag_node(node, all_nodes):
    """
    For an AG node, build a directed graph among its children based on
    assumption references. Edge A->B means A assumes B's guarantee.
    """
    graph = defaultdict(set)
    child_ids = {c["id"] for c in node.get("children", [])}

    for child in node.get("children", []):
        child_id = child["id"]
        for assumption in child.get("assumptions", []):
            # Parse "NodeID:guarantee" format
            if ":" in assumption:
                target_id = assumption.split(":")[0]
                if target_id in child_ids:
                    graph[child_id].add(target_id)
    return graph, child_ids


def find_sccs(graph, nodes):
    """Tarjan's algorithm for finding strongly connected components."""
    index_counter = [0]
    stack = []
    lowlink = {}
    index = {}
    on_stack = {}
    sccs = []

    def strongconnect(v):
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in graph.get(v, set()):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif on_stack.get(w, False):
                lowlink[v] = min(lowlink[v], index[w])

        if lowlink[v] == index[v]:
            scc = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == v:
                    break
            if len(scc) >= 2:
                sccs.append(sorted(scc))

    for v in nodes:
        if v not in index:
            strongconnect(v)

    return sccs


def find_all_circular_dependencies(root_node, all_nodes):
    """Find circular dependencies in all AG nodes throughout the tree."""
    all_cycles = []

    def traverse(node):
        if node.get("strategy") == "assume-guarantee":
            graph, child_ids = build_assumption_graph_for_ag_node(node, all_nodes)
            sccs = find_sccs(graph, child_ids)
            all_cycles.extend(sccs)
        for child in node.get("children", []):
            traverse(child)

    traverse(root_node)
    return all_cycles


def check_case_split_completeness(node, design_modes):
    """Check if a case-split node covers all values of its split signal."""
    signal = node.get("split_signal", "")
    if signal not in design_modes:
        return None  # Can't check without mode definition

    all_values = design_modes[signal]
    covered = []
    for child in node.get("children", []):
        condition = child.get("condition", "")
        if "==" in condition:
            value = condition.split("==")[1].strip()
            # Try to match as the original type
            covered.append(value)

    # Convert all_values to strings for comparison
    all_str = [str(v) for v in all_values]
    covered_str = [str(v) for v in covered]

    missing = sorted(set(all_str) - set(covered_str))
    if missing:
        return {
            "node_id": node["id"],
            "signal": signal,
            "covered": sorted(covered_str),
            "missing": missing
        }
    return None


def check_partition_completeness(node, design_modes):
    """Check if a partition node covers all values of its partition signal."""
    signal = node.get("partition_signal", "")
    if signal not in design_modes:
        return None

    all_values = design_modes[signal]
    covered = []
    for child in node.get("children", []):
        pv = child.get("partition_value")
        if pv is not None:
            covered.append(pv)

    # Compare as sets (handling int/str differences)
    all_set = set(str(v) for v in all_values)
    covered_set = set(str(v) for v in covered)
    missing = sorted(all_set - covered_set)

    if missing:
        return {
            "node_id": node["id"],
            "signal": signal,
            "covered": sorted(str(v) for v in covered),
            "missing": missing
        }
    return None


def find_all_incomplete_splits(root_node, design_modes):
    """Find all incomplete case-splits and partitions."""
    issues = []

    def traverse(node):
        strategy = node.get("strategy", "")
        if strategy == "case-split":
            issue = check_case_split_completeness(node, design_modes)
            if issue:
                issues.append(issue)
        elif strategy == "partition":
            issue = check_partition_completeness(node, design_modes)
            if issue:
                issues.append(issue)
        for child in node.get("children", []):
            traverse(child)

    traverse(root_node)
    return issues


def compute_decomposition_soundness(root_node, all_nodes, design_modes):
    """
    Compute decomposition soundness for every non-leaf node.

    A non-leaf node is sound iff:
    (a) If AG: no circular deps among its children
    (b) If case-split: covers all values
    (c) If partition: covers all values
    (d) All children's decompositions are recursively sound (children that are
        non-leaf nodes must themselves be sound)
    """
    soundness = {}

    def compute(node):
        strategy = node.get("strategy", "")

        if strategy == "leaf":
            return True  # Leaves are not tracked in soundness

        # Check children recursively first
        children_sound = True
        for child in node.get("children", []):
            child_strategy = child.get("strategy", "")
            if child_strategy != "leaf":
                child_sound = compute(child)
                if not child_sound:
                    children_sound = False

        # Check this node's own decomposition
        own_sound = True

        if strategy == "assume-guarantee":
            graph, child_ids = build_assumption_graph_for_ag_node(node, all_nodes)
            sccs = find_sccs(graph, child_ids)
            if sccs:
                own_sound = False

        elif strategy == "case-split":
            issue = check_case_split_completeness(node, design_modes)
            if issue:
                own_sound = False

        elif strategy == "partition":
            issue = check_partition_completeness(node, design_modes)
            if issue:
                own_sound = False

        # stopat strategy is considered sound if children are sound

        is_sound = own_sound and children_sound
        soundness[node["id"]] = is_sound
        return is_sound

    compute(root_node)
    return soundness


def main():
    spec = load_spec()
    design_modes = spec["design_modes"]
    root = spec["proof_structure"]

    all_nodes = collect_all_nodes(root)

    # 1. Find circular dependencies
    cycles = find_all_circular_dependencies(root, all_nodes)
    circular_deps = [{"cycle": c} for c in cycles]

    # 2. Find incomplete case-splits
    incomplete_splits = find_all_incomplete_splits(root, design_modes)

    # 3. Compute decomposition soundness
    soundness = compute_decomposition_soundness(root, all_nodes, design_modes)

    # 4. Overall soundness
    overall_sound = all(soundness.values())

    report = {
        "overall_sound": overall_sound,
        "circular_dependencies": circular_deps,
        "incomplete_case_splits": incomplete_splits,
        "decomposition_soundness": soundness
    }

    with open("/app/analysis_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Analysis complete. Report written to /app/analysis_report.json")
    print(f"  Overall sound: {overall_sound}")
    print(f"  Circular dependencies found: {len(cycles)}")
    print(f"  Incomplete case-splits found: {len(incomplete_splits)}")


if __name__ == "__main__":
    main()
