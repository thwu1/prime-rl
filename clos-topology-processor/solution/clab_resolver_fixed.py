#!/usr/bin/env python3
"""Containerlab topology processor - corrected version.

"""

import argparse
import json
import sys

import yaml


def load_topology(path):
    with open(path) as f:
        return yaml.safe_load(f)


class TopologyResolver:
    def __init__(self, topo):
        self.name = topo.get("name", "")
        t = topo.get("topology", {})
        self.defaults = t.get("defaults") or {}
        self.kinds_defs = t.get("kinds") or {}
        self.groups_defs = t.get("groups") or {}
        self.nodes_defs = t.get("nodes") or {}
        self.links_defs = t.get("links") or []

    def get_node_kind(self, node_name):
        """Resolve the kind for a node: node > group > defaults."""
        node = self.nodes_defs.get(node_name) or {}
        if node.get("kind"):
            return node["kind"]
        group_name = node.get("group", "")
        if group_name and group_name in self.groups_defs:
            group = self.groups_defs[group_name]
            if group and group.get("kind"):
                return group["kind"]
        return self.defaults.get("kind", "")

    def get_node_group(self, node_name):
        """Resolve the group for a node."""
        node = self.nodes_defs.get(node_name) or {}
        if node.get("group"):
            return node["group"]
        kind_name = self.get_node_kind(node_name)
        if kind_name and kind_name in self.kinds_defs:
            kind_def = self.kinds_defs[kind_name]
            if kind_def and kind_def.get("group"):
                return kind_def["group"]
        return self.defaults.get("group", "")

    def _resolve_scalar(self, node_name, field):
        """Resolve a scalar field: node > group > kind > defaults.

        Matches Go getField which checks node, then group, then kind,
        then defaults, returning the first non-empty value found.
        """
        node = self.nodes_defs.get(node_name) or {}
        if node.get(field):
            return node[field]
        # FIX: group before kind (matching Go's getField order)
        group_name = self.get_node_group(node_name)
        if group_name and group_name in self.groups_defs:
            group = self.groups_defs[group_name]
            if group and group.get(field):
                return group[field]
        kind_name = self.get_node_kind(node_name)
        if kind_name and kind_name in self.kinds_defs:
            kind_def = self.kinds_defs[kind_name]
            if kind_def and kind_def.get(field):
                return kind_def[field]
        return self.defaults.get(field, "")

    def _merge_map(self, node_name, field):
        """Merge a map field: defaults < kind < group < node.

        Matches Go's MergeStringMaps(defaults, kind, group, node)
        where each subsequent level overlays the previous.
        """
        result = {}
        if self.defaults.get(field):
            result.update(self.defaults[field])
        # FIX: kind before group (matching Go's merge call order)
        kind_name = self.get_node_kind(node_name)
        if kind_name and kind_name in self.kinds_defs:
            kind_def = self.kinds_defs[kind_name]
            if kind_def and kind_def.get(field):
                result.update(kind_def[field])
        group_name = self.get_node_group(node_name)
        if group_name and group_name in self.groups_defs:
            group = self.groups_defs[group_name]
            if group and group.get(field):
                result.update(group[field])
        node = self.nodes_defs.get(node_name) or {}
        if node.get(field):
            result.update(node[field])
        return result

    def resolve(self):
        nodes = {}
        for name in self.nodes_defs:
            nodes[name] = {
                "kind": self.get_node_kind(name),
                "image": self._resolve_scalar(name, "image"),
                "type": self._resolve_scalar(name, "type"),
                "env": self._merge_map(name, "env"),
                "labels": self._merge_map(name, "labels"),
            }
        return {"name": self.name, "nodes": nodes}


def cmd_resolve(args):
    topo = load_topology(args.topology_file)
    resolver = TopologyResolver(topo)
    result = resolver.resolve()
    print(json.dumps(result))


def cmd_generate_clos(args):
    tiers = []
    for part in args.tiers.split(","):
        pieces = part.split(":", 2)
        count = int(pieces[0])
        kind = pieces[1] if len(pieces) > 1 else "linux"
        image = pieces[2] if len(pieces) > 2 else ""
        tiers.append({"count": count, "kind": kind, "image": image})

    nodes = {}
    links = []
    num_tiers = len(tiers)

    for tier_idx, tier in enumerate(tiers):
        for node_idx in range(tier["count"]):
            name = "node{}-{}".format(tier_idx + 1, node_idx + 1)
            nodes[name] = {"kind": tier["kind"], "image": tier["image"]}

    for i in range(num_tiers - 1):
        # FIX: use previous tier's node count as interface offset
        interface_offset = 0
        if i > 0:
            interface_offset = tiers[i - 1]["count"]

        lower_tier = tiers[i]
        upper_tier = tiers[i + 1]

        for j in range(lower_tier["count"]):
            node1 = "node{}-{}".format(i + 1, j + 1)
            for k in range(upper_tier["count"]):
                node2 = "node{}-{}".format(i + 2, k + 1)
                iface1 = "eth{}".format(k + 1 + interface_offset)
                iface2 = "eth{}".format(j + 1)
                links.append(
                    {"endpoints": ["{}:{}".format(node1, iface1), "{}:{}".format(node2, iface2)]}
                )

    topo = {
        "name": args.name,
        "topology": {
            "nodes": nodes,
            "links": links,
        },
    }
    print(yaml.dump(topo, default_flow_style=False))


def cmd_ansible_inventory(args):
    topo = load_topology(args.topology_file)
    resolver = TopologyResolver(topo)
    lab_name = topo.get("name", "")

    groups = {}
    for name in resolver.nodes_defs:
        # FIX: use resolved kind instead of raw node-level kind
        kind = resolver.get_node_kind(name)

        if kind not in groups:
            groups[kind] = {}
        host = "clab-{}-{}".format(lab_name, name)
        groups[kind][host] = {}

    inv = {"all": {"children": {}}}
    for kind_name in sorted(groups):
        inv["all"]["children"][kind_name] = {"hosts": groups[kind_name]}

    print(yaml.dump(inv, default_flow_style=False))


def cmd_graph(args):
    topo = load_topology(args.topology_file)
    lab_name = topo.get("name", "")
    links = topo.get("topology", {}).get("links", [])

    lines = ['graph "{}" {{'.format(lab_name)]
    for link in links:
        eps = link.get("endpoints", [])
        if len(eps) == 2:
            n1 = eps[0].split(":")[0]
            n2 = eps[1].split(":")[0]
            lines.append("    {} -- {}".format(n1, n2))
    lines.append("}")
    print("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Containerlab topology processor")
    subparsers = parser.add_subparsers(dest="command")

    p_resolve = subparsers.add_parser("resolve")
    p_resolve.add_argument("topology_file")
    p_resolve.set_defaults(func=cmd_resolve)

    p_clos = subparsers.add_parser("generate-clos")
    p_clos.add_argument("--name", required=True)
    p_clos.add_argument("--tiers", required=True)
    p_clos.set_defaults(func=cmd_generate_clos)

    p_inv = subparsers.add_parser("ansible-inventory")
    p_inv.add_argument("topology_file")
    p_inv.set_defaults(func=cmd_ansible_inventory)

    p_graph = subparsers.add_parser("graph")
    p_graph.add_argument("topology_file")
    p_graph.set_defaults(func=cmd_graph)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
