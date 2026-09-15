#!/usr/bin/env python3
"""Containerlab topology processor - resolves properties, generates CLOS,
produces Ansible inventory and DOT graphs.

"""

import argparse
import json
import sys

import yaml


# ─── helpers ──────────────────────────────────────────────────────────


def _get(d, key, default=None):
    """Safely get from a dict that might be None."""
    if d is None:
        return default
    return d.get(key, default)


def _safe_dict(d):
    """Return d if it is a dict, else empty dict."""
    return d if isinstance(d, dict) else {}


def load_topology(path):
    with open(path) as f:
        return yaml.safe_load(f)


# ─── property resolution ─────────────────────────────────────────────


def resolve_kind(topo_section, node_name):
    """Resolve kind: node.kind > node's group.kind > defaults.kind."""
    nodes = _safe_dict(_get(topo_section, "nodes"))
    defaults = _safe_dict(_get(topo_section, "defaults"))
    groups = _safe_dict(_get(topo_section, "groups"))

    node = _safe_dict(nodes.get(node_name))

    # node level
    if node.get("kind"):
        return node["kind"]

    # group level
    group_name = node.get("group", "")
    if group_name:
        group = _safe_dict(groups.get(group_name))
        if group.get("kind"):
            return group["kind"]

    # defaults level
    return defaults.get("kind", "")


def resolve_simple(topo_section, node_name, prop):
    """Resolve a simple string property: node > group > kind > defaults."""
    nodes = _safe_dict(_get(topo_section, "nodes"))
    defaults = _safe_dict(_get(topo_section, "defaults"))
    kinds_defs = _safe_dict(_get(topo_section, "kinds"))
    groups = _safe_dict(_get(topo_section, "groups"))

    node = _safe_dict(nodes.get(node_name))

    # node level
    val = node.get(prop, "")
    if val:
        return val

    # group level
    group_name = node.get("group", "")
    if group_name:
        group = _safe_dict(groups.get(group_name))
        val = group.get(prop, "")
        if val:
            return val

    # kind level
    kind_name = resolve_kind(topo_section, node_name)
    if kind_name:
        kind_def = _safe_dict(kinds_defs.get(kind_name))
        val = kind_def.get(prop, "")
        if val:
            return val

    # defaults level
    return defaults.get(prop, "")


def resolve_merged_map(topo_section, node_name, prop):
    """Merge a map property across all levels (defaults < kind < group < node)."""
    nodes = _safe_dict(_get(topo_section, "nodes"))
    defaults = _safe_dict(_get(topo_section, "defaults"))
    kinds_defs = _safe_dict(_get(topo_section, "kinds"))
    groups = _safe_dict(_get(topo_section, "groups"))

    node = _safe_dict(nodes.get(node_name))
    result = {}

    # defaults (least specific)
    result.update(_safe_dict(defaults.get(prop)))

    # kind
    kind_name = resolve_kind(topo_section, node_name)
    if kind_name:
        kind_def = _safe_dict(kinds_defs.get(kind_name))
        result.update(_safe_dict(kind_def.get(prop)))

    # group
    group_name = node.get("group", "")
    if group_name:
        group = _safe_dict(groups.get(group_name))
        result.update(_safe_dict(group.get(prop)))

    # node (most specific)
    result.update(_safe_dict(node.get(prop)))

    return result


def resolve_topology(topo):
    """Fully resolve all node properties."""
    topo_section = _safe_dict(_get(topo, "topology"))
    nodes = _safe_dict(_get(topo_section, "nodes"))
    lab_name = topo.get("name", "")

    resolved = {"name": lab_name, "nodes": {}}

    for node_name in nodes:
        kind = resolve_kind(topo_section, node_name)
        image = resolve_simple(topo_section, node_name, "image")
        ntype = resolve_simple(topo_section, node_name, "type")
        env = resolve_merged_map(topo_section, node_name, "env")
        labels = resolve_merged_map(topo_section, node_name, "labels")

        resolved["nodes"][node_name] = {
            "kind": kind,
            "image": image,
            "type": ntype,
            "env": env,
            "labels": labels,
        }

    return resolved


# ─── CLOS generation ─────────────────────────────────────────────────


def parse_tier_spec(spec):
    """Parse 'count:kind:image' — split on first two colons only."""
    parts = spec.split(":", 2)
    count = int(parts[0])
    kind = parts[1] if len(parts) > 1 else "linux"
    image = parts[2] if len(parts) > 2 else ""
    return count, kind, image


def generate_clos(name, tiers_str):
    """Generate a CLOS fabric topology dict."""
    tier_specs = [parse_tier_spec(t.strip()) for t in tiers_str.split(",")]
    num_tiers = len(tier_specs)

    # Build nodes
    nodes = {}
    for tier_idx, (count, kind, image) in enumerate(tier_specs, start=1):
        for node_idx in range(1, count + 1):
            node_name = f"node{tier_idx}-{node_idx}"
            node_def = {"kind": kind}
            if image:
                node_def["image"] = image
            nodes[node_name] = node_def

    # Build links with interface tracking
    iface_counters = {n: 1 for n in nodes}
    links = []

    for pair_idx in range(num_tiers - 1):
        lower_tier = pair_idx + 1  # 1-indexed
        upper_tier = pair_idx + 2
        lower_count = tier_specs[pair_idx][0]
        upper_count = tier_specs[pair_idx + 1][0]

        for ui in range(1, upper_count + 1):
            upper_node = f"node{upper_tier}-{ui}"
            for li in range(1, lower_count + 1):
                lower_node = f"node{lower_tier}-{li}"
                upper_iface = f"eth{iface_counters[upper_node]}"
                lower_iface = f"eth{iface_counters[lower_node]}"
                links.append({
                    "endpoints": [
                        f"{upper_node}:{upper_iface}",
                        f"{lower_node}:{lower_iface}",
                    ]
                })
                iface_counters[upper_node] += 1
                iface_counters[lower_node] += 1

    return {
        "name": name,
        "topology": {
            "nodes": nodes,
            "links": links,
        },
    }


# ─── Ansible inventory ───────────────────────────────────────────────


def generate_ansible_inventory(topo):
    """Generate Ansible inventory YAML dict."""
    resolved = resolve_topology(topo)
    lab_name = resolved["name"]

    groups = {}
    for node_name, props in resolved["nodes"].items():
        kind = props["kind"] or "linux"
        if kind not in groups:
            groups[kind] = {}
        host_name = f"clab-{lab_name}-{node_name}"
        groups[kind][host_name] = {}

    children = {}
    for kind in sorted(groups):
        children[kind] = {"hosts": groups[kind]}

    return {"all": {"children": children}}


# ─── DOT graph ────────────────────────────────────────────────────────


def generate_dot(topo):
    """Generate DOT format string."""
    topo_section = _safe_dict(_get(topo, "topology"))
    lab_name = topo.get("name", "unnamed")
    links = topo_section.get("links", []) or []

    lines = [f'graph "{lab_name}" {{']
    for link in links:
        eps = link.get("endpoints", [])
        if len(eps) == 2:
            node_a = eps[0].split(":")[0]
            node_b = eps[1].split(":")[0]
            lines.append(f'    "{node_a}" -- "{node_b}"')
    lines.append("}")
    return "\n".join(lines) + "\n"


# ─── CLI ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Containerlab topology processor")
    sub = parser.add_subparsers(dest="command")

    # resolve
    p_resolve = sub.add_parser("resolve")
    p_resolve.add_argument("topology", help="Path to .clab.yml file")

    # generate-clos
    p_gen = sub.add_parser("generate-clos")
    p_gen.add_argument("--name", required=True)
    p_gen.add_argument("--tiers", required=True)

    # ansible-inventory
    p_inv = sub.add_parser("ansible-inventory")
    p_inv.add_argument("topology", help="Path to .clab.yml file")

    # graph
    p_graph = sub.add_parser("graph")
    p_graph.add_argument("topology", help="Path to .clab.yml file")

    args = parser.parse_args()

    if args.command == "resolve":
        topo = load_topology(args.topology)
        resolved = resolve_topology(topo)
        print(json.dumps(resolved, indent=2))

    elif args.command == "generate-clos":
        result = generate_clos(args.name, args.tiers)
        print(yaml.dump(result, default_flow_style=False, sort_keys=False))

    elif args.command == "ansible-inventory":
        topo = load_topology(args.topology)
        inv = generate_ansible_inventory(topo)
        print(yaml.dump(inv, default_flow_style=False, sort_keys=False))

    elif args.command == "graph":
        topo = load_topology(args.topology)
        print(generate_dot(topo), end="")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
