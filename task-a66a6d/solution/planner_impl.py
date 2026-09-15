#!/usr/bin/env python3
"""
Complete implementation of the dbt Pipeline Execution Planner.
"""

import argparse
import json
import re
import sys
from collections import defaultdict

MANIFEST_PATH = "/app/manifest.json"


def load_manifest(path):
    with open(path) as f:
        data = json.load(f)
    all_nodes = {}
    for section in ("nodes", "sources", "exposures"):
        if section in data:
            all_nodes.update(data[section])
    return all_nodes


def get_name(unique_id):
    parts = unique_id.split(".", 2)
    return parts[2].replace(".", "_") if len(parts) >= 3 else unique_id


def get_resource_name(unique_id):
    parts = unique_id.split(".", 2)
    return parts[2] if len(parts) >= 3 else unique_id


def get_effective_tags(node, all_nodes):
    tags = set(node.get("tags", []))
    if node.get("resource_type") == "test":
        parents = node.get("depends_on", {}).get("nodes", [])
        if parents and parents[0] in all_nodes:
            tags |= set(all_nodes[parents[0]].get("tags", []))
    return tags


def build_children_index(all_nodes):
    children = defaultdict(list)
    for uid, node in all_nodes.items():
        for parent_id in node.get("depends_on", {}).get("nodes", []):
            children[parent_id].append(uid)
    return children


def get_ancestors(node_id, all_nodes, max_depth=-1):
    result = set()
    frontier = [(node_id, 0)]
    visited = {node_id}
    while frontier:
        current, depth = frontier.pop(0)
        if current != node_id:
            result.add(current)
        if max_depth != -1 and depth >= max_depth:
            continue
        for parent_id in all_nodes.get(current, {}).get("depends_on", {}).get("nodes", []):
            if parent_id not in visited and parent_id in all_nodes:
                visited.add(parent_id)
                frontier.append((parent_id, depth + 1))
    return result


def get_descendants(node_id, all_nodes, children_index, max_depth=-1):
    result = set()
    frontier = [(node_id, 0)]
    visited = {node_id}
    while frontier:
        current, depth = frontier.pop(0)
        if current != node_id:
            result.add(current)
        if max_depth != -1 and depth >= max_depth:
            continue
        for child_id in children_index.get(current, []):
            if child_id not in visited and child_id in all_nodes:
                visited.add(child_id)
                frontier.append((child_id, depth + 1))
    return result


def match_base_selector(selector, all_nodes):
    matched = set()
    if selector.startswith("tag:"):
        tag_val = selector[4:]
        for uid, node in all_nodes.items():
            if tag_val in get_effective_tags(node, all_nodes):
                matched.add(uid)
    elif selector.startswith("config."):
        rest = selector[7:]
        key, value = rest.split(":", 1)
        for uid, node in all_nodes.items():
            if str(node.get("config", {}).get(key, "")) == value:
                matched.add(uid)
    elif selector.startswith("fqn:"):
        fqn_val = selector[4:]
        for uid, node in all_nodes.items():
            if ".".join(node.get("fqn", [])) == fqn_val:
                matched.add(uid)
    elif selector.startswith("source:"):
        source_name = selector[7:]
        for uid, node in all_nodes.items():
            if node.get("resource_type") == "source" and get_resource_name(uid) == source_name:
                matched.add(uid)
    else:
        for uid in all_nodes:
            if get_name(uid) == selector:
                matched.add(uid)
    return matched


def parse_graph_selector(expr):
    if expr.startswith("@"):
        return (True, None, expr[1:], None)
    precursor_depth = None
    descendant_depth = None
    m = re.match(r"^(\d+)\+(.+)$", expr)
    if m:
        precursor_depth = int(m.group(1))
        expr = m.group(2)
    elif expr.startswith("+"):
        precursor_depth = -1
        expr = expr[1:]
    m = re.match(r"^(.+?)\+(\d+)$", expr)
    if m:
        expr = m.group(1)
        descendant_depth = int(m.group(2))
    elif expr.endswith("+"):
        expr = expr[:-1]
        descendant_depth = -1
    return (False, precursor_depth, expr, descendant_depth)


def evaluate_single_selector(expr, all_nodes, children_index):
    at_op, pre_depth, base, desc_depth = parse_graph_selector(expr)
    roots = match_base_selector(base, all_nodes)
    if at_op:
        all_desc = set()
        for r in roots:
            all_desc |= get_descendants(r, all_nodes, children_index)
        combined = roots | all_desc
        all_anc = set()
        for n in combined:
            all_anc |= get_ancestors(n, all_nodes)
        return roots | all_desc | all_anc
    result = set(roots)
    if pre_depth is not None:
        for r in roots:
            result |= get_ancestors(r, all_nodes, pre_depth)
    if desc_depth is not None:
        for r in roots:
            result |= get_descendants(r, all_nodes, children_index, desc_depth)
    return result


def evaluate_select_expr(expr, all_nodes, children_index):
    parts = [p.strip() for p in expr.split(",")]
    result = None
    for part in parts:
        part_result = evaluate_single_selector(part, all_nodes, children_index)
        if result is None:
            result = part_result
        else:
            result &= part_result
    return result if result is not None else set()


def resolve_selection(selects, excludes, all_nodes, children_index):
    if not selects:
        return set(all_nodes.keys())
    selected = set()
    for expr in selects:
        selected |= evaluate_select_expr(expr, all_nodes, children_index)
    excluded = set()
    for expr in excludes:
        excluded |= evaluate_select_expr(expr, all_nodes, children_index)
    return selected - excluded


def filter_executable(selected, all_nodes, test_behavior):
    executable = set()
    for uid in selected:
        node = all_nodes.get(uid, {})
        rt = node.get("resource_type", "")
        if rt in ("source", "exposure"):
            continue
        if rt == "test" and test_behavior == "none":
            continue
        executable.add(uid)
    return executable


def compute_schedule(executable, all_nodes, max_parallel, test_behavior, children_index):
    deps = {}
    for uid in executable:
        node = all_nodes[uid]
        parents = [p for p in node.get("depends_on", {}).get("nodes", [])
                   if p in executable]
        deps[uid] = set(parents)

    if test_behavior == "barrier":
        for uid in list(executable):
            node = all_nodes[uid]
            if node.get("resource_type") == "test":
                parents = node.get("depends_on", {}).get("nodes", [])
                if parents and parents[0] in executable:
                    first_parent = parents[0]
                    fp_node = all_nodes[first_parent]
                    if fp_node.get("resource_type") in ("model", "seed", "snapshot"):
                        for child_uid in children_index.get(first_parent, []):
                            if (child_uid in executable and child_uid != uid):
                                child_node = all_nodes[child_uid]
                                if child_node.get("resource_type") in (
                                        "model", "seed", "snapshot"):
                                    deps[child_uid].add(uid)

    completed = set()
    stages = []
    remaining = set(executable)

    while remaining:
        ready = sorted(
            [uid for uid in remaining if deps[uid].issubset(completed)])
        if not ready:
            break
        batch = ready[:max_parallel]
        durations = [all_nodes[uid].get("execution_time_seconds", 0)
                     for uid in batch]
        stage_dur = max(durations) if durations else 0
        stages.append({
            "stage": len(stages) + 1,
            "nodes": batch,
            "duration": stage_dur,
        })
        for uid in batch:
            completed.add(uid)
            remaining.discard(uid)

    return {
        "stages": stages,
        "total_stages": len(stages),
        "total_duration": sum(s["duration"] for s in stages),
    }


def compute_critical_path(executable, all_nodes):
    if not executable:
        return {"path": [], "total_duration": 0}

    deps = {}
    for uid in executable:
        node = all_nodes[uid]
        parents = [p for p in node.get("depends_on", {}).get("nodes", [])
                   if p in executable]
        deps[uid] = parents

    in_degree = {uid: len(deps[uid]) for uid in executable}
    children_local = defaultdict(list)
    for uid in executable:
        for p in deps[uid]:
            children_local[p].append(uid)

    topo_order = []
    queue = sorted([uid for uid in executable if in_degree[uid] == 0])
    while queue:
        node_id = queue.pop(0)
        topo_order.append(node_id)
        for child in sorted(children_local[node_id]):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
                queue.sort()

    longest = {}
    predecessor = {}
    for uid in topo_order:
        node_time = all_nodes[uid].get("execution_time_seconds", 0)
        best_parent = None
        best_dist = 0
        for p in sorted(deps[uid]):
            if longest[p] > best_dist or (
                    longest[p] == best_dist and
                    (best_parent is None or p < best_parent)):
                best_dist = longest[p]
                best_parent = p
        longest[uid] = best_dist + node_time
        predecessor[uid] = best_parent

    max_val = max(longest.values())
    candidates = sorted([u for u in executable if longest[u] == max_val])
    max_node = candidates[0]

    path = []
    current = max_node
    while current is not None:
        path.append(current)
        current = predecessor[current]
    path.reverse()

    return {"path": path, "total_duration": max_val}


def compute_impact(node_id, all_nodes, children_index):
    descendants = get_descendants(node_id, all_nodes, children_index)
    affected = sorted(descendants)
    total_cost = sum(
        all_nodes.get(uid, {}).get("execution_time_seconds", 0)
        for uid in affected)
    affected_tests = sorted(
        uid for uid in affected
        if all_nodes.get(uid, {}).get("resource_type") == "test")
    return {
        "affected_nodes": affected,
        "total_rebuild_cost": total_cost,
        "affected_tests": affected_tests,
    }


def main():
    parser = argparse.ArgumentParser(
        description="dbt Pipeline Execution Planner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_sel = subparsers.add_parser("select")
    p_sel.add_argument("--select", action="append", dest="selects", default=[])
    p_sel.add_argument("--exclude", action="append", dest="excludes",
                       default=[])

    p_sched = subparsers.add_parser("schedule")
    p_sched.add_argument("--select", action="append", dest="selects",
                         default=[])
    p_sched.add_argument("--exclude", action="append", dest="excludes",
                         default=[])
    p_sched.add_argument("--max-parallel", type=int, required=True)
    p_sched.add_argument("--test-behavior",
                         choices=["none", "included", "barrier"],
                         default="none")

    p_cp = subparsers.add_parser("critical-path")
    p_cp.add_argument("--select", action="append", dest="selects", default=[])
    p_cp.add_argument("--exclude", action="append", dest="excludes",
                      default=[])
    p_cp.add_argument("--test-behavior",
                      choices=["none", "included", "barrier"], default="none")

    p_imp = subparsers.add_parser("impact")
    p_imp.add_argument("--node", required=True)

    args = parser.parse_args()
    all_nodes = load_manifest(MANIFEST_PATH)
    children_index = build_children_index(all_nodes)

    if args.command == "select":
        selected = resolve_selection(args.selects, args.excludes, all_nodes,
                                     children_index)
        for uid in sorted(selected):
            print(uid)
    elif args.command == "schedule":
        selected = resolve_selection(args.selects, args.excludes, all_nodes,
                                     children_index)
        executable = filter_executable(selected, all_nodes,
                                       args.test_behavior)
        result = compute_schedule(executable, all_nodes, args.max_parallel,
                                  args.test_behavior, children_index)
        print(json.dumps(result))
    elif args.command == "critical-path":
        selected = resolve_selection(args.selects, args.excludes, all_nodes,
                                     children_index)
        executable = filter_executable(selected, all_nodes,
                                       args.test_behavior)
        result = compute_critical_path(executable, all_nodes)
        print(json.dumps(result))
    elif args.command == "impact":
        result = compute_impact(args.node, all_nodes, children_index)
        print(json.dumps(result))


if __name__ == "__main__":
    main()
