#!/usr/bin/env python3
"""
Fixed proof management pipeline for formal verification signoff.

Fixes applied:
1. CSV parsing: use csv.reader instead of naive split to handle quoted fields
2. Cycle detection: DFS-based detection for transitive cycles (not just pairwise)
3. Partition handler: correctly propagates bounded_proven and error statuses
4. Status override: checks status_override field on leaf nodes before engine results
"""

import csv
import json
import sys
import os

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


def load_engine_results(csv_path):
    """Load engine verification results from CSV file.

    Uses csv.reader to properly handle quoted fields containing commas.
    """
    results = {}
    with open(csv_path) as f:
        reader = csv.reader(f)
        columns = next(reader)
        status_idx = columns.index('status')
        depth_idx = columns.index('depth')
        for row in reader:
            if not row:
                continue
            node_id = row[0].strip()
            status = row[status_idx].strip() if status_idx < len(row) else 'inconclusive'
            depth_str = row[depth_idx].strip() if depth_idx < len(row) else ''
            depth = int(depth_str) if depth_str else None
            results[node_id] = {
                'status': status if status in STATUS_ORDER else 'inconclusive',
                'depth': depth,
            }
    return results


def detect_circular_deps(assumptions):
    """Check for circular dependencies using DFS-based cycle detection.

    Detects transitive cycles (A->B->C->A), not just direct mutual deps.
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


def get_leaf_status(node, engine_results):
    """Get status for a leaf node.

    Checks status_override first (manual review override), then engine results.
    """
    if 'status_override' in node:
        override = node['status_override']
        if override in STATUS_ORDER:
            return override
    node_id = node['id']
    if node_id in engine_results:
        return engine_results[node_id]['status']
    return 'inconclusive'


def propagate_status(node_id, nodes_by_id, engine_results, memo):
    """Bottom-up status propagation through the proof tree.

    Returns (status, issues) tuple.
    """
    if node_id in memo:
        return memo[node_id]

    node = nodes_by_id[node_id]
    strategy = node['strategy']
    issues = []

    if strategy == 'leaf':
        status = get_leaf_status(node, engine_results)
        if status == 'falsified' and node_id in engine_results:
            depth = engine_results[node_id].get('depth')
            if depth is not None:
                node['counterexample_depth'] = depth
        memo[node_id] = (status, issues)
        return status, issues

    elif strategy == 'assume_guarantee':
        children = node.get('children', [])
        assumptions = node.get('assumptions', {})

        cycle_found, cycle_participants = detect_circular_deps(assumptions)
        if cycle_found:
            cycle_info = sorted(cycle_participants)
            issues.append(
                f"Circular assume-guarantee dependency detected among: "
                f"{', '.join(cycle_info)}"
            )
            memo[node_id] = ('error', issues)
            return 'error', issues

        overall_status = 'proven'
        for child_id in children:
            child_status, child_issues = propagate_status(
                child_id, nodes_by_id, engine_results, memo
            )
            issues.extend(child_issues)
            overall_status = weaker_status(overall_status, child_status)

        memo[node_id] = (overall_status, issues)
        return overall_status, issues

    elif strategy == 'case_split':
        cases = node.get('cases', [])
        exhaustive = node.get('exhaustive', False)

        child_statuses = []
        for case in cases:
            case_node_id = case['node']
            child_status, child_issues = propagate_status(
                case_node_id, nodes_by_id, engine_results, memo
            )
            issues.extend(child_issues)
            child_statuses.append(
                (case_node_id, case.get('value', '?'), child_status)
            )

        falsified_cases = [
            (nid, val) for nid, val, s in child_statuses if s == 'falsified'
        ]
        if falsified_cases:
            for nid, val in falsified_cases:
                cex_node = nodes_by_id.get(nid, {})
                depth = cex_node.get('counterexample_depth', 'unknown')
                issues.append(
                    f"Case {nid} is falsified (counterexample at depth {depth})"
                )
            if not exhaustive:
                issues.append("Case split is not exhaustive")
            memo[node_id] = ('falsified', issues)
            return 'falsified', issues

        inconclusive_cases = [
            nid for nid, val, s in child_statuses
            if s not in ('proven', 'bounded_proven')
        ]
        if inconclusive_cases:
            for nid in inconclusive_cases:
                issues.append(f"Case {nid} is inconclusive")
            if not exhaustive:
                issues.append("Case split is not exhaustive")
            memo[node_id] = ('inconclusive', issues)
            return 'inconclusive', issues

        if not exhaustive:
            issues.append("Case split is not exhaustive")
            memo[node_id] = ('inconclusive', issues)
            return 'inconclusive', issues

        overall = 'proven'
        for _, _, s in child_statuses:
            overall = weaker_status(overall, s)
        memo[node_id] = (overall, issues)
        return overall, issues

    elif strategy == 'partition':
        children = node.get('children', [])
        if not children:
            memo[node_id] = ('inconclusive', ['No children in partition node'])
            return 'inconclusive', issues

        child_id = children[0]
        child_status, child_issues = propagate_status(
            child_id, nodes_by_id, engine_results, memo
        )
        issues.extend(child_issues)

        if child_status == 'proven':
            memo[node_id] = ('proven', issues)
            return 'proven', issues
        elif child_status == 'bounded_proven':
            memo[node_id] = ('bounded_proven', issues)
            return 'bounded_proven', issues
        elif child_status == 'falsified':
            issues.append(
                "Partitioned proof falsified - counterexample may be spurious"
            )
            memo[node_id] = ('inconclusive', issues)
            return 'inconclusive', issues
        elif child_status == 'error':
            memo[node_id] = ('error', issues)
            return 'error', issues
        else:
            memo[node_id] = (child_status, issues)
            return child_status, issues

    elif strategy == 'stopat':
        children = node.get('children', [])
        if not children:
            memo[node_id] = ('inconclusive', ['No children in stopat node'])
            return 'inconclusive', issues

        child_id = children[0]
        child_status, child_issues = propagate_status(
            child_id, nodes_by_id, engine_results, memo
        )
        issues.extend(child_issues)

        if child_status == 'proven':
            bound = node.get('bound', 'unknown')
            issues.append(
                f"Proof is bounded (stopat at depth {bound}), not a full proof"
            )
            memo[node_id] = ('bounded_proven', issues)
            return 'bounded_proven', issues
        elif child_status == 'falsified':
            memo[node_id] = ('falsified', issues)
            return 'falsified', issues
        else:
            memo[node_id] = (child_status, issues)
            return child_status, issues

    else:
        issues.append(f"Unknown strategy: {strategy}")
        memo[node_id] = ('error', issues)
        return 'error', issues


def analyze(structure_path, csv_path, output_path):
    with open(structure_path) as f:
        data = json.load(f)

    engine_results = load_engine_results(csv_path)

    properties = {p['id']: p for p in data['properties']}
    proof_nodes = data['proof_nodes']
    nodes_by_id = {n['id']: n for n in proof_nodes}

    # Find root nodes
    all_children = set()
    for node in proof_nodes:
        for child_id in node.get('children', []):
            all_children.add(child_id)
        for case in node.get('cases', []):
            all_children.add(case['node'])

    property_roots = {}
    for node in proof_nodes:
        if node['id'] not in all_children:
            property_roots[node['property_id']] = node['id']

    memo = {}
    report_properties = {}

    for prop_id, prop in sorted(properties.items()):
        root_id = property_roots.get(prop_id)
        if root_id is None:
            report_properties[prop_id] = {
                'name': prop['name'],
                'status': 'error',
                'root_node': None,
                'issues': ['No root proof node found for this property'],
            }
            continue

        status, issues = propagate_status(
            root_id, nodes_by_id, engine_results, memo
        )
        report_properties[prop_id] = {
            'name': prop['name'],
            'status': status,
            'root_node': root_id,
            'issues': issues,
        }

    statuses = [p['status'] for p in report_properties.values()]
    total = len(statuses)
    proven_count = statuses.count('proven')

    summary = {
        'total_properties': total,
        'proven': proven_count,
        'bounded_proven': statuses.count('bounded_proven'),
        'falsified': statuses.count('falsified'),
        'inconclusive': statuses.count('inconclusive'),
        'error': statuses.count('error'),
        'signoff_coverage': proven_count / total if total > 0 else 0.0,
    }

    report = {
        'properties': report_properties,
        'summary': summary,
        'signoff_ready': proven_count == total,
    }

    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    return report


if __name__ == '__main__':
    structure_path = '/app/proof_structure.json'
    csv_path = '/app/engine_results.csv'
    output_path = '/app/signoff_report.json'

    report = analyze(structure_path, csv_path, output_path)

    print(f"Signoff report written to {output_path}")
    print(f"Signoff ready: {report['signoff_ready']}")
    print(f"Coverage: {report['summary']['signoff_coverage']:.1%}")
    for pid, pdata in sorted(report['properties'].items()):
        print(f"  {pid} ({pdata['name']}): {pdata['status']}")
        for issue in pdata['issues']:
            print(f"    - {issue}")
