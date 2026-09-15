#!/usr/bin/env python3
"""dbt manifest diff-aware selector engine with YAML selector and lineage visualization.

Parses current and previous dbt manifests, builds the dependency graph, resolves
selector queries (string, YAML, and state-comparison), generates results JSON
and a Graphviz DOT lineage graph.
"""

import json
import re
import sys

import yaml


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def build_graph(manifest):
    """Build parent and child adjacency lists from manifest."""
    nodes = manifest["nodes"]
    child_map = manifest.get("child_map", {})
    parents = {}
    children = {}

    for uid in nodes:
        deps = nodes[uid].get("depends_on", {}).get("nodes", [])
        parents[uid] = [d for d in deps if d in nodes]
        children[uid] = [c for c in child_map.get(uid, []) if c in nodes]

    return nodes, parents, children


def compute_state(current_manifest, previous_manifest):
    """Compute state:new and state:modified node sets."""
    curr_nodes = current_manifest["nodes"]
    prev_nodes = previous_manifest["nodes"]

    new_nodes = set()
    modified_nodes = set()

    for uid in curr_nodes:
        if uid not in prev_nodes:
            new_nodes.add(uid)
        else:
            curr = curr_nodes[uid]
            prev = prev_nodes[uid]

            # Check checksum
            curr_cksum = curr.get("checksum", {}).get("checksum")
            prev_cksum = prev.get("checksum", {}).get("checksum")
            if curr_cksum != prev_cksum:
                modified_nodes.add(uid)
                continue

            # Check depends_on.nodes (sorted comparison)
            curr_deps = sorted(curr.get("depends_on", {}).get("nodes", []))
            prev_deps = sorted(prev.get("depends_on", {}).get("nodes", []))
            if curr_deps != prev_deps:
                modified_nodes.add(uid)
                continue

            # Check config (deep equality)
            if curr.get("config") != prev.get("config"):
                modified_nodes.add(uid)

    return new_nodes, modified_nodes


def get_ancestors(node_id, parents, depth=None):
    """BFS upward to collect ancestors. depth=None means unlimited."""
    result = {node_id}
    frontier = {node_id}
    level = 0
    while frontier and (depth is None or level < depth):
        next_frontier = set()
        for n in frontier:
            for p in parents.get(n, []):
                if p not in result:
                    result.add(p)
                    next_frontier.add(p)
        frontier = next_frontier
        level += 1
    return result


def get_descendants(node_id, children, depth=None):
    """BFS downward to collect descendants. depth=None means unlimited."""
    result = {node_id}
    frontier = {node_id}
    level = 0
    while frontier and (depth is None or level < depth):
        next_frontier = set()
        for n in frontier:
            for c in children.get(n, []):
                if c not in result:
                    result.add(c)
                    next_frontier.add(c)
        frontier = next_frontier
        level += 1
    return result


def resolve_base_selector(selector, nodes, state_sets=None):
    """Resolve a base selector (no graph operators) to a set of unique_ids."""
    if ":" in selector:
        method, value = selector.split(":", 1)
        if method == "tag":
            return {uid for uid, n in nodes.items()
                    if value in n.get("tags", [])}
        elif method == "path":
            return {uid for uid, n in nodes.items()
                    if n.get("path", "").startswith(value)}
        elif method == "config.materialized":
            return {uid for uid, n in nodes.items()
                    if n.get("config", {}).get("materialized") == value}
        elif method == "resource_type":
            return {uid for uid, n in nodes.items()
                    if n.get("resource_type") == value}
        elif method == "fqn":
            parts = value.split(".")
            return {uid for uid, n in nodes.items()
                    if n.get("fqn", [])[:len(parts)] == parts}
        elif method == "state":
            if state_sets and value in state_sets:
                return set(state_sets[value])
            return set()
        else:
            return set()
    else:
        # Name selector
        return {uid for uid, n in nodes.items()
                if n.get("name") == selector}


def resolve_single_selector(expr, nodes, parents, children, state_sets=None):
    """Resolve a single selector expression, possibly with graph operators."""
    # @ operator: @node = ancestors(node) + descendants of all ancestors
    if expr.startswith("@"):
        base_name = expr[1:]
        base_nodes = resolve_base_selector(base_name, nodes, state_sets)
        all_ancestors = set()
        for n in base_nodes:
            all_ancestors |= get_ancestors(n, parents)
        result = set(all_ancestors)
        for a in all_ancestors:
            result |= get_descendants(a, children)
        return result

    has_prefix = False
    prefix_depth = None
    has_suffix = False
    suffix_depth = None
    base = expr

    # Parse prefix: N+base or +base
    prefix_match = re.match(r'^(\d+)\+(.+)$', base)
    if prefix_match:
        prefix_depth = int(prefix_match.group(1))
        has_prefix = True
        base = prefix_match.group(2)
    elif base.startswith("+"):
        has_prefix = True
        prefix_depth = None
        base = base[1:]

    # Parse suffix: base+N or base+
    suffix_match = re.match(r'^(.+?)\+(\d*)$', base)
    if suffix_match:
        rest, n_str = suffix_match.groups()
        has_suffix = True
        suffix_depth = int(n_str) if n_str else None
        base = rest

    base_nodes = resolve_base_selector(base, nodes, state_sets)
    result = set(base_nodes)

    if has_prefix:
        for n in base_nodes:
            result |= get_ancestors(n, parents, prefix_depth)

    if has_suffix:
        for n in base_nodes:
            result |= get_descendants(n, children, suffix_depth)

    return result


def resolve_selector_group(group_expr, nodes, parents, children, state_sets=None):
    """Resolve a comma-separated group (intersection of parts)."""
    parts = group_expr.split(",")
    if len(parts) == 1:
        return resolve_single_selector(parts[0], nodes, parents, children,
                                       state_sets)

    result = None
    for part in parts:
        part_result = resolve_single_selector(part.strip(), nodes, parents,
                                              children, state_sets)
        if result is None:
            result = part_result
        else:
            result &= part_result
    return result if result is not None else set()


def resolve_full_selector(select_expr, nodes, parents, children,
                          state_sets=None):
    """Resolve a full selector (space-separated groups are unioned)."""
    groups = select_expr.split()
    result = set()
    for group in groups:
        result |= resolve_selector_group(group, nodes, parents, children,
                                         state_sets)
    return result


# ===== YAML Selector Resolution =====

def yaml_method_to_string(definition):
    """Convert a YAML method definition to a dbt string selector with graph ops."""
    method = definition["method"]
    value = definition["value"]

    method_map = {
        "tag": "tag:",
        "path": "path:",
        "fqn": "fqn:",
        "resource_type": "resource_type:",
        "source": "source:",
        "exposure": "exposure:",
        "state": "state:",
    }

    if method in method_map:
        selector = f"{method_map[method]}{value}"
    elif method.startswith("config."):
        selector = f"{method}:{value}"
    else:
        selector = value

    # Apply graph operator properties
    p = definition.get("parents", False)
    c = definition.get("children", False)
    pd = definition.get("parents_depth", 0)
    cd = definition.get("children_depth", 0)
    cp = definition.get("childrens_parents", False)

    if cp:
        selector = f"@{selector}"
    else:
        if p:
            prefix = f"{pd}+" if pd > 0 else "+"
            selector = f"{prefix}{selector}"
        if c:
            suffix = f"+{cd}" if cd > 0 else "+"
            selector = f"{selector}{suffix}"

    return selector


def resolve_yaml_to_strings(definition, named_selectors, cache):
    """Recursively convert a YAML selector definition to (include_strs, exclude_strs)."""
    if "union" in definition:
        return _resolve_yaml_union(definition, named_selectors, cache)
    elif "intersection" in definition:
        return _resolve_yaml_intersection(definition, named_selectors, cache)
    elif "method" in definition:
        return _resolve_yaml_method(definition, named_selectors, cache)
    return [], []


def _resolve_yaml_union(definition, named_selectors, cache):
    include = []
    exclude = []
    for item in definition.get("union", []):
        if isinstance(item, dict) and "exclude" in item:
            for excl in item["exclude"]:
                e_inc, _ = resolve_yaml_to_strings(excl, named_selectors,
                                                   cache)
                exclude.extend(e_inc)
        else:
            i, e = resolve_yaml_to_strings(item, named_selectors, cache)
            include.extend(i)
            exclude.extend(e)
    return include, exclude


def _resolve_yaml_intersection(definition, named_selectors, cache):
    include_parts = []
    exclude = []
    for item in definition.get("intersection", []):
        if isinstance(item, dict) and "exclude" in item:
            for excl in item["exclude"]:
                e_inc, _ = resolve_yaml_to_strings(excl, named_selectors,
                                                   cache)
                exclude.extend(e_inc)
        else:
            i, e = resolve_yaml_to_strings(item, named_selectors, cache)
            include_parts.extend(i)
            exclude.extend(e)
    if include_parts:
        return [",".join(include_parts)], exclude
    return [], exclude


def _resolve_yaml_method(definition, named_selectors, cache):
    method = definition.get("method")

    # Handle selector references
    if method == "selector":
        ref_name = definition["value"]
        if ref_name in cache:
            return cache[ref_name]
        if ref_name in named_selectors:
            result = resolve_yaml_to_strings(named_selectors[ref_name],
                                             named_selectors, cache)
            cache[ref_name] = result
            return result
        return [], []

    # Convert method definition to string selector
    selector_str = yaml_method_to_string(definition)

    # Handle inline exclude
    exclude = []
    if "exclude" in definition:
        for excl in definition["exclude"]:
            e_inc, _ = resolve_yaml_to_strings(excl, named_selectors, cache)
            exclude.extend(e_inc)

    return [selector_str], exclude


def resolve_named_selector(name, selectors_data, nodes, parents, children,
                           state_sets=None):
    """Resolve a named YAML selector to a set of node unique_ids."""
    named_selectors = {}
    for sel in selectors_data.get("selectors", []):
        named_selectors[sel["name"]] = sel["definition"]

    if name not in named_selectors:
        return set()

    cache = {}
    include_strs, exclude_strs = resolve_yaml_to_strings(
        named_selectors[name], named_selectors, cache
    )

    # Resolve include strings as union
    selected = set()
    for sel_str in include_strs:
        selected |= resolve_full_selector(sel_str, nodes, parents, children,
                                          state_sets)

    # Resolve exclude strings
    excluded = set()
    for excl_str in exclude_strs:
        excluded |= resolve_full_selector(excl_str, nodes, parents, children,
                                          state_sets)

    return selected - excluded


# ===== DOT Lineage Graph Generation =====

def generate_dot(nodes, children, output_path):
    """Generate Graphviz DOT file of the full manifest DAG."""
    shapes = {"model": "box", "seed": "cylinder", "test": "diamond"}
    colors = {"model": "#87CEEB", "seed": "#98FB98", "test": "#FFB6C1"}

    lines = ["digraph dbt_lineage {"]
    lines.append("  rankdir=LR;")
    lines.append('  node [fontname="Arial", fontsize=10];')
    lines.append("")

    for uid in sorted(nodes):
        rtype = nodes[uid].get("resource_type", "model")
        name = nodes[uid].get("name", uid)
        shape = shapes.get(rtype, "box")
        color = colors.get(rtype, "#FFFFFF")
        lines.append(
            f'  "{uid}" [label="{name}", shape={shape}, '
            f'style=filled, fillcolor="{color}"];'
        )

    lines.append("")

    for uid in sorted(nodes):
        for child in sorted(children.get(uid, [])):
            if child in nodes:
                lines.append(f'  "{uid}" -> "{child}";')

    lines.append("}")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")


# ===== Main =====

def process_queries(manifest_path, prev_manifest_path, queries_path,
                    selectors_path, output_path, dot_path):
    manifest = load_json(manifest_path)
    prev_manifest = load_json(prev_manifest_path)
    nodes, parents, children = build_graph(manifest)

    new_nodes, modified_nodes = compute_state(manifest, prev_manifest)
    state_sets = {"new": new_nodes, "modified": modified_nodes}

    queries = load_json(queries_path)
    selectors_data = load_yaml(selectors_path)

    results = []
    for query in queries:
        if "selector" in query and query.get("selector"):
            selected = resolve_named_selector(
                query["selector"], selectors_data, nodes, parents, children,
                state_sets
            )
        else:
            selected = resolve_full_selector(
                query["select"], nodes, parents, children, state_sets
            )
            if query.get("exclude"):
                excluded = resolve_full_selector(
                    query["exclude"], nodes, parents, children, state_sets
                )
                selected -= excluded

        results.append({
            "id": query["id"],
            "nodes": sorted(selected),
        })

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    generate_dot(nodes, children, dot_path)


if __name__ == "__main__":
    process_queries(
        "/app/manifest.json",
        "/app/manifest_previous.json",
        "/app/queries.json",
        "/app/selectors.yml",
        "/app/results.json",
        "/app/lineage.dot",
    )
