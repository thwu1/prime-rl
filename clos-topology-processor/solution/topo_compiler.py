#!/usr/bin/env python3
"""Topology factoring compiler for containerlab.

Takes a flat topology (all properties on nodes) and produces a factored
equivalent using containerlab's defaults, kinds, and groups inheritance
to eliminate redundancy while preserving exact semantic equivalence.

"""

import sys
from collections import defaultdict

import yaml


def load_topology(path):
    with open(path) as f:
        return yaml.safe_load(f)


def intersect_maps(*maps):
    """Return {k: v} pairs present in ALL given maps with the same value."""
    if not maps:
        return {}
    result = dict(maps[0])
    for m in maps[1:]:
        result = {k: v for k, v in result.items() if m.get(k) == v}
    return result


def subtract_map(full, remove):
    """Return entries from full whose key isn't in remove with the same value."""
    return {k: v for k, v in full.items() if remove.get(k) != v}


def factor_topology(topo):
    """Transform a flat topology into a factored one using inheritance.

    Algorithm:
    1. Compute defaults: intersection of ALL nodes' properties.
       - Scalars: only if uniform across all nodes.
       - Maps: only key-value pairs present in every node.
    2. Compute kind-level: intersection of same-kind nodes, minus defaults.
    3. Compute groups (clustered by type): intersection of members'
       desired state minus defaults (NOT minus kind for maps, because
       group overlays kind in map merge).
       - Group scalars only set if ALL members agree on the value.
    4. Compute per-node remainders after simulating full resolution chain.
    """
    name = topo.get("name", "")
    t = topo.get("topology", {})
    raw_nodes = t.get("nodes") or {}
    links = t.get("links") or []

    # Normalize all nodes
    nodes = {}
    for n, d in raw_nodes.items():
        d = d or {}
        nodes[n] = {
            "kind": d.get("kind", ""),
            "image": d.get("image", ""),
            "type": d.get("type", ""),
            "env": dict(d.get("env") or {}),
            "labels": dict(d.get("labels") or {}),
        }

    if not nodes:
        return topo

    all_names = list(nodes.keys())

    # ---- Phase 1: Defaults ----
    # Most common kind becomes default
    kind_counts = defaultdict(int)
    for d in nodes.values():
        kind_counts[d["kind"]] += 1
    default_kind = max(kind_counts, key=kind_counts.get)

    # Map fields: only keys present in ALL nodes with same value
    # This is safe because map merge is additive -- a key at defaults
    # level will appear in every node's resolved state. We must only
    # include keys that every node actually wants.
    default_env = intersect_maps(*(d["env"] for d in nodes.values()))
    default_labels = intersect_maps(*(d["labels"] for d in nodes.values()))

    # Scalar fields: only if uniform
    all_images = set(d["image"] for d in nodes.values())
    default_image = list(all_images)[0] if len(all_images) == 1 else ""
    all_types = set(d["type"] for d in nodes.values())
    default_type = list(all_types)[0] if len(all_types) == 1 else ""

    defaults = {}
    if default_kind:
        defaults["kind"] = default_kind
    if default_image:
        defaults["image"] = default_image
    if default_type:
        defaults["type"] = default_type
    if default_env:
        defaults["env"] = dict(default_env)
    if default_labels:
        defaults["labels"] = dict(default_labels)

    # ---- Phase 2: Kind-level properties ----
    kind_node_map = defaultdict(list)
    for n in all_names:
        kind_node_map[nodes[n]["kind"]].append(n)

    kinds_config = {}
    for kind_name, kn_list in kind_node_map.items():
        kc = {}
        kd = [nodes[n] for n in kn_list]

        # Kind image: only if all nodes of this kind have the same image
        k_images = set(d["image"] for d in kd)
        if len(k_images) == 1:
            img = list(k_images)[0]
            if img and img != default_image:
                kc["image"] = img

        # Kind type: only if all same and different from default
        k_types = set(d["type"] for d in kd)
        if len(k_types) == 1:
            kt = list(k_types)[0]
            if kt and kt != default_type:
                kc["type"] = kt

        # Kind env: intersection of this kind's env, minus defaults.
        # Safe because map merge goes defaults < kind < group < node,
        # and we only include keys ALL nodes of this kind have.
        k_env = intersect_maps(*(d["env"] for d in kd))
        k_env = subtract_map(k_env, default_env)
        if k_env:
            kc["env"] = dict(k_env)

        # Kind labels: intersection minus defaults
        k_labels = intersect_maps(*(d["labels"] for d in kd))
        k_labels = subtract_map(k_labels, default_labels)
        if k_labels:
            kc["labels"] = dict(k_labels)

        if kc:
            kinds_config[kind_name] = kc

    # ---- Phase 3: Groups via type-based clustering ----
    type_clusters = defaultdict(list)
    for n in all_names:
        type_clusters[nodes[n]["type"]].append(n)

    groups_config = {}
    node_group = {}

    for type_val, cn_list in type_clusters.items():
        if len(cn_list) < 2:
            continue

        # Group map fields: intersection of desired minus defaults.
        # Crucially, we do NOT subtract kind-level values here because
        # in map merge order (defaults < kind < group < node), group
        # values overlay kind values. Setting a key at both kind and
        # group level is redundant but not harmful, and it correctly
        # handles cross-kind groups where different members have
        # different kinds.
        g_envs = [subtract_map(nodes[n]["env"], default_env) for n in cn_list]
        g_env = intersect_maps(*g_envs)

        g_labels_list = [
            subtract_map(nodes[n]["labels"], default_labels) for n in cn_list
        ]
        g_labels = intersect_maps(*g_labels_list)

        # Group scalar fields: only if ALL members have the same value.
        # This is critical because scalar resolution is
        # node > group > kind > defaults -- a group scalar OVERRIDES
        # the kind-level value. So if members have different kinds with
        # different images, setting group image would break some members.
        g_images = set(nodes[n]["image"] for n in cn_list)
        g_image = ""
        if len(g_images) == 1:
            gi = list(g_images)[0]
            if gi and gi != default_image:
                g_image = gi

        gc = {}
        if type_val and type_val != default_type:
            gc["type"] = type_val
        if g_image:
            gc["image"] = g_image
        if g_env:
            gc["env"] = dict(g_env)
        if g_labels:
            gc["labels"] = dict(g_labels)

        if not gc:
            continue

        # Generate group name from the type
        gn = type_val.lower() + "s" if type_val else "group{}".format(
            len(groups_config) + 1
        )
        while gn in groups_config:
            gn += "_x"

        groups_config[gn] = gc
        for n in cn_list:
            node_group[n] = gn

    # ---- Phase 4: Per-node remainders ----
    out_nodes = {}
    for n in all_names:
        d = nodes[n]
        out = {}

        # Kind: only if different from default
        if d["kind"] != default_kind:
            out["kind"] = d["kind"]

        # Group assignment
        gn = node_group.get(n)
        if gn:
            out["group"] = gn

        gc = groups_config.get(gn, {}) if gn else {}
        kc = kinds_config.get(d["kind"], {})

        # Image (scalar: node > group > kind > defaults)
        eff_image = gc.get("image") or kc.get("image") or default_image
        if d["image"] and d["image"] != eff_image:
            out["image"] = d["image"]

        # Type (scalar: node > group > kind > defaults)
        eff_type = gc.get("type") or kc.get("type") or default_type
        if d["type"] and d["type"] != eff_type:
            out["type"] = d["type"]

        # Env (map: defaults < kind < group < node)
        resolved_env = {}
        resolved_env.update(default_env)
        resolved_env.update(kc.get("env", {}))
        resolved_env.update(gc.get("env", {}))
        rem_env = subtract_map(d["env"], resolved_env)
        if rem_env:
            out["env"] = dict(rem_env)

        # Labels (map: same merge order)
        resolved_labels = {}
        resolved_labels.update(default_labels)
        resolved_labels.update(kc.get("labels", {}))
        resolved_labels.update(gc.get("labels", {}))
        rem_labels = subtract_map(d["labels"], resolved_labels)
        if rem_labels:
            out["labels"] = dict(rem_labels)

        out_nodes[n] = out if out else None

    # ---- Build output ----
    output = {"name": name, "topology": {}}
    if defaults:
        output["topology"]["defaults"] = defaults
    if kinds_config:
        output["topology"]["kinds"] = kinds_config
    if groups_config:
        output["topology"]["groups"] = groups_config
    output["topology"]["nodes"] = out_nodes
    if links:
        output["topology"]["links"] = links

    return output


def main():
    if len(sys.argv) != 2:
        print("Usage: topo_compiler.py <flat_topology.yml>", file=sys.stderr)
        sys.exit(1)

    topo = load_topology(sys.argv[1])
    result = factor_topology(topo)
    print(yaml.dump(result, default_flow_style=False, sort_keys=False))


if __name__ == "__main__":
    main()
