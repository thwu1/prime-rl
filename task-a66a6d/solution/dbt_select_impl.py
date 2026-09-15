#!/usr/bin/env python3
"""dbt graph node selector engine."""

import argparse
import json
import re
import sys
from collections import defaultdict


def parse_args():
    parser = argparse.ArgumentParser(description="dbt graph node selector engine")
    parser.add_argument("--manifest", default="/app/manifest.json")
    parser.add_argument("--select", action="append", dest="selects", default=[])
    parser.add_argument("--exclude", action="append", dest="excludes", default=[])
    return parser.parse_args()


def load_manifest(path):
    """Load manifest and merge nodes, sources, exposures into one dict."""
    with open(path) as f:
        data = json.load(f)
    all_nodes = {}
    for section in ("nodes", "sources", "exposures"):
        if section in data:
            all_nodes.update(data[section])
    return all_nodes


def get_name(unique_id):
    """Derive name: everything after the second dot, dots replaced by underscores."""
    parts = unique_id.split(".", 2)
    return parts[2].replace(".", "_") if len(parts) >= 3 else unique_id


def get_resource_name(unique_id):
    """Derive resource_name: everything after the second dot."""
    parts = unique_id.split(".", 2)
    return parts[2] if len(parts) >= 3 else unique_id


def get_effective_tags(node, all_nodes):
    """Get tags for a node. Test nodes inherit tags from their first parent."""
    tags = set(node.get("tags", []))
    if node.get("resource_type") == "test":
        parents = node.get("depends_on", {}).get("nodes", [])
        if parents and parents[0] in all_nodes:
            tags |= set(all_nodes[parents[0]].get("tags", []))
    return tags


def build_children_index(all_nodes):
    """Build parent -> [children] reverse index."""
    children = defaultdict(list)
    for uid, node in all_nodes.items():
        for parent_id in node.get("depends_on", {}).get("nodes", []):
            children[parent_id].append(uid)
    return children


def get_ancestors(node_id, all_nodes, max_depth=-1):
    """BFS upward through depends_on. max_depth=-1 means unlimited."""
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
    """BFS downward through children index. max_depth=-1 means unlimited."""
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
    """Match nodes by a base selector (no graph operators)."""
    matched = set()

    if selector.startswith("tag:"):
        tag_val = selector[4:]
        for uid, node in all_nodes.items():
            if tag_val in get_effective_tags(node, all_nodes):
                matched.add(uid)

    elif selector.startswith("path:"):
        path_val = selector[5:].rstrip("*")
        for uid, node in all_nodes.items():
            if path_val in node.get("original_file_path", ""):
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
        # Plain name match
        for uid in all_nodes:
            if get_name(uid) == selector:
                matched.add(uid)

    return matched


def parse_graph_selector(expr):
    """Parse selector into (at_operator, precursor_depth, base_selector, descendant_depth).

    Depths: None = no graph op, -1 = unlimited, N = N levels.
    """
    # @ operator
    if expr.startswith("@"):
        return (True, None, expr[1:], None)

    precursor_depth = None
    descendant_depth = None

    # Check prefix: N+ or just +
    m = re.match(r"^(\d+)\+(.+)$", expr)
    if m:
        precursor_depth = int(m.group(1))
        expr = m.group(2)
    elif expr.startswith("+"):
        precursor_depth = -1
        expr = expr[1:]

    # Check suffix: +N or just +
    m = re.match(r"^(.+?)\+(\d+)$", expr)
    if m:
        expr = m.group(1)
        descendant_depth = int(m.group(2))
    elif expr.endswith("+"):
        expr = expr[:-1]
        descendant_depth = -1

    return (False, precursor_depth, expr, descendant_depth)


def evaluate_single_selector(expr, all_nodes, children_index):
    """Evaluate one selector expression (no commas)."""
    at_op, pre_depth, base, desc_depth = parse_graph_selector(expr)
    roots = match_base_selector(base, all_nodes)

    if at_op:
        # @ operator: all descendants of roots, then all ancestors of (roots + descendants)
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
    """Evaluate a --select expression. Comma-separated parts are intersected."""
    parts = [p.strip() for p in expr.split(",")]

    result = None
    for part in parts:
        part_result = evaluate_single_selector(part, all_nodes, children_index)
        if result is None:
            result = part_result
        else:
            result &= part_result

    return result if result is not None else set()


def main():
    args = parse_args()
    all_nodes = load_manifest(args.manifest)
    children_index = build_children_index(all_nodes)

    # Union of all --select expressions
    selected = set()
    for expr in args.selects:
        selected |= evaluate_select_expr(expr, all_nodes, children_index)

    # Union of all --exclude expressions, then subtract
    excluded = set()
    for expr in args.excludes:
        excluded |= evaluate_select_expr(expr, all_nodes, children_index)

    result = selected - excluded

    for uid in sorted(result):
        print(uid)


if __name__ == "__main__":
    main()
