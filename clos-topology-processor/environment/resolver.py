#!/usr/bin/env python3
"""Containerlab topology property resolver.

Implements containerlab's property inheritance model:
- Scalar fields: resolved via first-match (node > group > kind > defaults)
- Map fields: resolved via overlay merge (defaults < kind < group < node)

This is a read-only reference implementation.
"""

import json
import sys

import yaml


def load_topology(path):
    with open(path) as f:
        return yaml.safe_load(f)


class TopologyResolver:
    """Resolves containerlab topology properties through the inheritance chain."""

    SCALAR_FIELDS = ("image", "type")
    MAP_FIELDS = ("env", "labels")

    def __init__(self, topo):
        self.name = topo.get("name", "")
        t = topo.get("topology", {})
        self.defaults = t.get("defaults") or {}
        self.kinds_defs = t.get("kinds") or {}
        self.groups_defs = t.get("groups") or {}
        self.nodes_defs = t.get("nodes") or {}
        self.links_defs = t.get("links") or []

    def get_node_kind(self, node_name):
        """Resolve kind: node > group > defaults."""
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
        """Resolve group: node > kind > defaults."""
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
        """Resolve scalar: node > group > kind > defaults (first match)."""
        node = self.nodes_defs.get(node_name) or {}
        if node.get(field):
            return node[field]
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
        """Merge map: defaults < kind < group < node (overlay)."""
        result = {}
        if self.defaults.get(field):
            result.update(self.defaults[field])
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
        """Resolve all nodes to their final property state."""
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


def resolve_topology(topo_data):
    """Resolve a topology dict and return resolved state."""
    resolver = TopologyResolver(topo_data)
    return resolver.resolve()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: resolver.py <topology.yml>", file=sys.stderr)
        sys.exit(1)
    topo = load_topology(sys.argv[1])
    result = resolve_topology(topo)
    print(json.dumps(result, indent=2))
