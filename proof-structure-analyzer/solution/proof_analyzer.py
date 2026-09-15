#!/usr/bin/env python3
"""
Formal verification proof structure analyzer.

Reads a proof decomposition tree from /app/proof_structure.json, propagates
proof statuses through the tree according to correct formal semantics, and
writes a signoff report to /app/signoff_report.json.

Strategies and their semantics:
- leaf: base proof with concrete status from engine
- assume_guarantee: compositional; unsound if circular assumptions; propagated
  status is weakest child status if sound
- case_split: proven iff all cases proven AND exhaustive; falsified if any case
  falsified; otherwise inconclusive
- partition: over-approximation; proven child -> proven parent; falsified child
  -> inconclusive parent (spurious CEX possible)
- stopat: bounded proof; proven child -> bounded_proven; falsified child ->
  falsified (real CEX)
"""

import json
import sys
from collections import defaultdict

STATUS_ORDER = {
    "proven": 0,
    "bounded_proven": 1,
    "inconclusive": 2,
    "falsified": 3,
    "error": 4,
}


def weaker_status(a, b):
    """Return the weaker (worse) of two statuses."""
    if STATUS_ORDER.get(a, 99) >= STATUS_ORDER.get(b, 99):
        return a
    return b


def has_cycle(assumptions):
    """Detect cycles in the assumption dependency graph.

    assumptions: dict mapping node_id -> list of node_ids it assumes.
    Returns (has_cycle: bool, cycle_participants: set).
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in assumptions}
    cycle_nodes = set()

    def dfs(node):
        color[node] = GRAY
        for dep in assumptions.get(node, []):
            if dep not in color:
                continue
            if color[dep] == GRAY:
                cycle_nodes.add(node)
                cycle_nodes.add(dep)
                return True
            if color[dep] == WHITE:
                if dfs(dep):
                    if color.get(node) == GRAY:
                        cycle_nodes.add(node)
                    return True
        color[node] = BLACK
        return False

    found = False
    for node in assumptions:
        if color[node] == WHITE:
            if dfs(node):
                found = True

    return found, cycle_nodes


def propagate_status(node_id, nodes_by_id, memo):
    """Bottom-up status propagation through the proof tree.

    Returns (status, issues) tuple.
    """
    if node_id in memo:
        return memo[node_id]

    node = nodes_by_id[node_id]
    strategy = node["strategy"]
    issues = []

    if strategy == "leaf":
        status = node.get("status", "inconclusive")
        memo[node_id] = (status, issues)
        return status, issues

    elif strategy == "assume_guarantee":
        children = node.get("children", [])
        assumptions = node.get("assumptions", {})

        # Check for circular dependencies
        cycle_found, cycle_nodes = has_cycle(assumptions)
        if cycle_found:
            cycle_pairs = []
            for n in sorted(cycle_nodes):
                for dep in assumptions.get(n, []):
                    if dep in cycle_nodes:
                        cycle_pairs.append(f"{n} <-> {dep}")
            if cycle_pairs:
                issues.append(
                    f"Circular assume-guarantee dependency detected: "
                    f"{', '.join(sorted(set(cycle_pairs)))}"
                )
            else:
                issues.append("Circular assume-guarantee dependency detected")
            memo[node_id] = ("error", issues)
            return "error", issues

        # Propagate children
        overall_status = "proven"
        for child_id in children:
            child_status, child_issues = propagate_status(
                child_id, nodes_by_id, memo
            )
            issues.extend(child_issues)
            overall_status = weaker_status(overall_status, child_status)

        memo[node_id] = (overall_status, issues)
        return overall_status, issues

    elif strategy == "case_split":
        cases = node.get("cases", [])
        exhaustive = node.get("exhaustive", False)

        child_statuses = []
        for case in cases:
            case_node_id = case["node"]
            child_status, child_issues = propagate_status(
                case_node_id, nodes_by_id, memo
            )
            issues.extend(child_issues)
            child_statuses.append((case_node_id, case.get("value", "?"), child_status))

        # If any case is falsified, the property is falsified
        falsified_cases = [
            (nid, val) for nid, val, s in child_statuses if s == "falsified"
        ]
        if falsified_cases:
            for nid, val in falsified_cases:
                cex_node = nodes_by_id.get(nid, {})
                depth = cex_node.get("counterexample_depth", "unknown")
                issues.append(
                    f"Case {nid} is falsified (counterexample at depth {depth})"
                )
            if not exhaustive:
                issues.append("Case split is not exhaustive")
            memo[node_id] = ("falsified", issues)
            return "falsified", issues

        # Check for inconclusive cases
        inconclusive_cases = [
            nid for nid, val, s in child_statuses
            if s not in ("proven", "bounded_proven")
        ]
        if inconclusive_cases:
            for nid in inconclusive_cases:
                issues.append(f"Case {nid} is inconclusive")
            if not exhaustive:
                issues.append("Case split is not exhaustive")
            memo[node_id] = ("inconclusive", issues)
            return "inconclusive", issues

        # All cases proven or bounded_proven
        if not exhaustive:
            issues.append("Case split is not exhaustive")
            memo[node_id] = ("inconclusive", issues)
            return "inconclusive", issues

        # Exhaustive and all proven/bounded_proven: take weakest
        overall = "proven"
        for _, _, s in child_statuses:
            overall = weaker_status(overall, s)
        memo[node_id] = (overall, issues)
        return overall, issues

    elif strategy == "partition":
        children = node.get("children", [])
        if not children:
            memo[node_id] = ("inconclusive", ["No children in partition node"])
            return "inconclusive", issues

        child_id = children[0]
        child_status, child_issues = propagate_status(
            child_id, nodes_by_id, memo
        )
        issues.extend(child_issues)

        if child_status == "proven":
            # Over-approximation preserves proofs
            memo[node_id] = ("proven", issues)
            return "proven", issues
        elif child_status == "falsified":
            # Counterexample may be spurious due to blackboxing
            issues.append(
                "Partitioned proof falsified - counterexample may be spurious"
            )
            memo[node_id] = ("inconclusive", issues)
            return "inconclusive", issues
        elif child_status == "bounded_proven":
            memo[node_id] = ("bounded_proven", issues)
            return "bounded_proven", issues
        else:
            memo[node_id] = (child_status, issues)
            return child_status, issues

    elif strategy == "stopat":
        children = node.get("children", [])
        if not children:
            memo[node_id] = ("inconclusive", ["No children in stopat node"])
            return "inconclusive", issues

        child_id = children[0]
        child_status, child_issues = propagate_status(
            child_id, nodes_by_id, memo
        )
        issues.extend(child_issues)

        if child_status == "proven":
            # Bounded proof: proven within bound is not a full proof
            bound = node.get("bound", "unknown")
            issues.append(f"Proof is bounded (stopat at depth {bound}), not a full proof")
            memo[node_id] = ("bounded_proven", issues)
            return "bounded_proven", issues
        elif child_status == "falsified":
            # Real counterexample within bound
            memo[node_id] = ("falsified", issues)
            return "falsified", issues
        else:
            memo[node_id] = (child_status, issues)
            return child_status, issues

    else:
        issues.append(f"Unknown strategy: {strategy}")
        memo[node_id] = ("error", issues)
        return "error", issues


def find_root_nodes(proof_nodes):
    """Find root proof nodes for each property.

    A root node is one whose id is not referenced as a child by any other node.
    Returns dict mapping property_id -> root_node_id.
    """
    all_children = set()
    for node in proof_nodes:
        for child_id in node.get("children", []):
            all_children.add(child_id)
        for case in node.get("cases", []):
            all_children.add(case["node"])

    property_roots = {}
    for node in proof_nodes:
        if node["id"] not in all_children:
            prop_id = node["property_id"]
            property_roots[prop_id] = node["id"]

    return property_roots


def analyze(input_path, output_path):
    with open(input_path) as f:
        data = json.load(f)

    properties = {p["id"]: p for p in data["properties"]}
    proof_nodes = data["proof_nodes"]
    nodes_by_id = {n["id"]: n for n in proof_nodes}

    # Find root nodes for each property
    property_roots = find_root_nodes(proof_nodes)

    # Propagate statuses
    memo = {}
    report_properties = {}

    for prop_id, prop in sorted(properties.items()):
        root_id = property_roots.get(prop_id)
        if root_id is None:
            report_properties[prop_id] = {
                "name": prop["name"],
                "status": "error",
                "root_node": None,
                "issues": ["No root proof node found for this property"],
            }
            continue

        status, issues = propagate_status(root_id, nodes_by_id, memo)
        report_properties[prop_id] = {
            "name": prop["name"],
            "status": status,
            "root_node": root_id,
            "issues": issues,
        }

    # Compute summary
    statuses = [p["status"] for p in report_properties.values()]
    total = len(statuses)
    proven_count = statuses.count("proven")

    summary = {
        "total_properties": total,
        "proven": proven_count,
        "bounded_proven": statuses.count("bounded_proven"),
        "falsified": statuses.count("falsified"),
        "inconclusive": statuses.count("inconclusive"),
        "error": statuses.count("error"),
        "signoff_coverage": proven_count / total if total > 0 else 0.0,
    }

    report = {
        "properties": report_properties,
        "summary": summary,
        "signoff_ready": proven_count == total,
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    return report


if __name__ == "__main__":
    input_path = "/app/proof_structure.json"
    output_path = "/app/signoff_report.json"
    report = analyze(input_path, output_path)

    print(f"Signoff report written to {output_path}")
    print(f"Signoff ready: {report['signoff_ready']}")
    print(f"Coverage: {report['summary']['signoff_coverage']:.1%}")
    for pid, pdata in sorted(report["properties"].items()):
        print(f"  {pid} ({pdata['name']}): {pdata['status']}")
        for issue in pdata["issues"]:
            print(f"    - {issue}")
