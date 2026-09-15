#!/usr/bin/env python3
"""Containerlab Topology Processing Engine."""

import argparse
import ipaddress
import json
import sys

import yaml


# ── Helpers ──────────────────────────────────────────────────────────────────

SCALAR_FIELDS = [
    "kind", "image", "type", "user", "memory", "cmd", "entrypoint",
    "startup-config", "network-mode", "mgmt-ipv4", "mgmt-ipv6",
    "cpu", "cpuset", "shm-size", "restart-policy",
]

MAP_FIELDS = ["env", "labels"]

KIND_ANSIBLE_VARS = {
    "srl": {
        "ansible_network_os": "nokia.srlinux.srlinux",
        "ansible_connection": "ansible.netcommon.httpapi",
        "ansible_user": "admin",
        "ansible_password": "NokiaSrl1!",
    },
    "nokia_srlinux": {
        "ansible_network_os": "nokia.srlinux.srlinux",
        "ansible_connection": "ansible.netcommon.httpapi",
        "ansible_user": "admin",
        "ansible_password": "NokiaSrl1!",
    },
    "ceos": {
        "ansible_network_os": "arista.eos.eos",
        "ansible_connection": "ansible.netcommon.httpapi",
        "ansible_user": "admin",
        "ansible_password": "admin",
    },
    "arista_ceos": {
        "ansible_network_os": "arista.eos.eos",
        "ansible_connection": "ansible.netcommon.httpapi",
        "ansible_user": "admin",
        "ansible_password": "admin",
    },
}


def load_topology(filepath):
    with open(filepath) as f:
        return yaml.safe_load(f)


# ── resolve ──────────────────────────────────────────────────────────────────


def resolve_nodes(topo):
    """Resolve 4-level property inheritance for every node."""
    t = topo.get("topology", {}) or {}
    defaults = t.get("defaults", {}) or {}
    kinds_defs = t.get("kinds", {}) or {}
    groups_defs = t.get("groups", {}) or {}
    nodes_defs = t.get("nodes", {}) or {}

    resolved = {}
    for name, node_def in nodes_defs.items():
        node_def = node_def if node_def is not None else {}

        # Determine group (from node only)
        group_name = node_def.get("group")
        group_def = (groups_defs.get(group_name) or {}) if group_name else {}

        # Determine kind: node > group > defaults
        kind_name = (
            node_def.get("kind")
            or group_def.get("kind")
            or defaults.get("kind")
        )
        kind_def = (kinds_defs.get(kind_name) or {}) if kind_name else {}

        resolved_node = {}

        # Scalar fields: node > group > kind > defaults
        for field in SCALAR_FIELDS:
            for source in (node_def, group_def, kind_def, defaults):
                if field in source and source[field] is not None:
                    resolved_node[field] = source[field]
                    break

        # Ensure kind is always set
        if kind_name:
            resolved_node["kind"] = kind_name

        # Map fields: merge all levels (defaults → kind → group → node)
        for field in MAP_FIELDS:
            merged = {}
            for source in (defaults, kind_def, group_def, node_def):
                vals = source.get(field)
                if vals:
                    merged.update(vals)
            if merged:
                resolved_node[field] = merged

        # Preserve group info
        if group_name:
            resolved_node["group"] = group_name

        resolved[name] = resolved_node

    return resolved


# ── validate ─────────────────────────────────────────────────────────────────


def validate_topology(topo):
    """Return a list of error strings (empty = valid)."""
    errors = []
    t = topo.get("topology", {}) or {}
    nodes = t.get("nodes", {}) or {}
    links = t.get("links", []) or []
    mgmt = topo.get("mgmt", {}) or {}

    used_interfaces = {}  # "node:iface" → link index

    for i, link in enumerate(links):
        endpoints = link.get("endpoints", [])
        if len(endpoints) != 2:
            errors.append(f"link {i}: expected 2 endpoints, got {len(endpoints)}")
            continue

        for ep in endpoints:
            parts = ep.split(":")
            if len(parts) != 2:
                errors.append(f"link {i}: invalid endpoint format: {ep}")
                continue
            node, iface = parts

            # Check node exists
            if node not in nodes:
                errors.append(
                    f"unknown node '{node}' in link endpoint '{ep}'"
                )

            # Check interface name length
            if len(iface) > 15:
                errors.append(
                    f"invalid interface name '{iface}' on node '{node}': "
                    f"exceeds 15 characters"
                )

            # Check for spaces and slashes
            if " " in iface or "/" in iface:
                errors.append(
                    f"invalid interface name '{iface}' on node '{node}': "
                    f"contains spaces or slashes"
                )

            # Check duplicate
            key = f"{node}:{iface}"
            if key in used_interfaces:
                errors.append(
                    f"duplicate interface '{key}': "
                    f"used in links {used_interfaces[key]} and {i}"
                )
            else:
                used_interfaces[key] = i

    # Check management subnet capacity
    subnet_str = mgmt.get("ipv4-subnet")
    if subnet_str:
        net = ipaddress.IPv4Network(subnet_str, strict=False)
        # Reserved: network addr, broadcast addr, gateway
        total_usable = net.num_addresses - 3
        if total_usable < 0:
            total_usable = 0
        num_nodes = len(nodes)
        if num_nodes > total_usable:
            errors.append(
                f"insufficient management IPs: need {num_nodes} "
                f"but subnet {subnet_str} has {total_usable} usable addresses"
            )

    return errors


# ── allocate-ips ─────────────────────────────────────────────────────────────


def allocate_mgmt_ips(topo, resolved_nodes=None):
    """Allocate management IPv4 addresses from the configured subnet."""
    if resolved_nodes is None:
        resolved_nodes = resolve_nodes(topo)

    mgmt = topo.get("mgmt", {}) or {}
    subnet_str = mgmt.get("ipv4-subnet", "172.20.20.0/24")
    gw_str = mgmt.get("ipv4-gw")

    net = ipaddress.IPv4Network(subnet_str, strict=False)
    gw = ipaddress.IPv4Address(gw_str) if gw_str else (net.network_address + 1)

    # Collect explicit assignments
    assignments = {}
    explicit_ips = set()
    for name, node in resolved_nodes.items():
        ip = node.get("mgmt-ipv4")
        if ip:
            ip_str = str(ip)
            assignments[name] = ip_str
            explicit_ips.add(ipaddress.IPv4Address(ip_str))

    # Reserved addresses
    reserved = {net.network_address, net.broadcast_address, gw}
    reserved.update(explicit_ips)

    # Auto-allocate in alphabetical order
    remaining = sorted(n for n in resolved_nodes if n not in assignments)
    next_ip_int = int(gw) + 1

    for name in remaining:
        while True:
            candidate = ipaddress.IPv4Address(next_ip_int)
            if candidate not in reserved and candidate in net:
                assignments[name] = str(candidate)
                reserved.add(candidate)
                next_ip_int += 1
                break
            next_ip_int += 1
            if next_ip_int > int(net.broadcast_address):
                raise ValueError(f"No more IPs available in {subnet_str}")

    return assignments


# ── inventory ────────────────────────────────────────────────────────────────


def generate_ansible_inventory(topo, resolved_nodes=None, ip_assignments=None):
    """Generate Ansible inventory YAML in containerlab format."""
    if resolved_nodes is None:
        resolved_nodes = resolve_nodes(topo)
    if ip_assignments is None:
        ip_assignments = allocate_mgmt_ips(topo, resolved_nodes)

    lab_name = topo.get("name", "lab")
    prefix = topo.get("prefix", "clab")

    # Group nodes by kind
    groups = {}
    for name, node in sorted(resolved_nodes.items()):
        kind = node.get("kind", "linux")
        if kind not in groups:
            groups[kind] = {}
        host_name = f"{prefix}-{lab_name}-{name}"
        groups[kind][host_name] = {
            "ansible_host": ip_assignments.get(name, ""),
        }

    # Build inventory structure
    children = {}
    for kind in sorted(groups):
        entry = {"hosts": dict(sorted(groups[kind].items()))}
        if kind in KIND_ANSIBLE_VARS:
            entry["vars"] = dict(KIND_ANSIBLE_VARS[kind])
        children[kind] = entry

    return {"all": {"children": children}}


# ── generate-clos ────────────────────────────────────────────────────────────


def generate_clos(args):
    """Generate a CLOS fabric topology."""
    num_tiers = getattr(args, "tiers", 2) or 2
    num_leaves = args.leaves
    num_spines = args.spines
    num_superspines = getattr(args, "superspines", 0) or 0
    clients_per_leaf = args.clients_per_leaf
    node_image = args.node_image
    client_image = args.client_image

    nodes = {}
    links = []
    iface_counter = {}

    def next_iface(node):
        if node not in iface_counter:
            iface_counter[node] = 0
        iface_counter[node] += 1
        return f"eth{iface_counter[node]}"

    # ── Create nodes ──

    if num_tiers >= 3 and num_superspines > 0:
        for ss in range(1, num_superspines + 1):
            nodes[f"superspine{ss}"] = {
                "kind": "linux",
                "image": node_image,
                "labels": {"role": "superspine"},
            }

    for s in range(1, num_spines + 1):
        nodes[f"spine{s}"] = {
            "kind": "linux",
            "image": node_image,
            "labels": {"role": "spine"},
        }

    for l in range(1, num_leaves + 1):
        nodes[f"leaf{l}"] = {
            "kind": "linux",
            "image": node_image,
            "labels": {"role": "leaf"},
        }

    for l in range(1, num_leaves + 1):
        for c in range(1, clients_per_leaf + 1):
            idx = (l - 1) * clients_per_leaf + c
            nodes[f"client{idx}"] = {
                "kind": "linux",
                "image": client_image,
                "labels": {"role": "client"},
            }

    # ── Create links (order: superspine-spine, spine-leaf, leaf-client) ──

    if num_tiers >= 3 and num_superspines > 0:
        for ss in range(1, num_superspines + 1):
            for s in range(1, num_spines + 1):
                ss_if = next_iface(f"superspine{ss}")
                s_if = next_iface(f"spine{s}")
                links.append({
                    "endpoints": [
                        f"superspine{ss}:{ss_if}",
                        f"spine{s}:{s_if}",
                    ]
                })

    for s in range(1, num_spines + 1):
        for l in range(1, num_leaves + 1):
            s_if = next_iface(f"spine{s}")
            l_if = next_iface(f"leaf{l}")
            links.append({
                "endpoints": [f"spine{s}:{s_if}", f"leaf{l}:{l_if}"]
            })

    for l in range(1, num_leaves + 1):
        for c in range(1, clients_per_leaf + 1):
            idx = (l - 1) * clients_per_leaf + c
            l_if = next_iface(f"leaf{l}")
            c_if = next_iface(f"client{idx}")
            links.append({
                "endpoints": [f"leaf{l}:{l_if}", f"client{idx}:{c_if}"]
            })

    return {
        "name": args.name,
        "mgmt": {"ipv4-subnet": args.mgmt_subnet},
        "topology": {"nodes": nodes, "links": links},
    }


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Containerlab Topology Processor"
    )
    sub = parser.add_subparsers(dest="command")

    # resolve
    p = sub.add_parser("resolve")
    p.add_argument("topology")

    # validate
    p = sub.add_parser("validate")
    p.add_argument("topology")

    # allocate-ips
    p = sub.add_parser("allocate-ips")
    p.add_argument("topology")

    # inventory
    p = sub.add_parser("inventory")
    p.add_argument("topology")

    # generate-clos
    p = sub.add_parser("generate-clos")
    p.add_argument("--name", required=True)
    p.add_argument("--tiers", type=int, default=2)
    p.add_argument("--leaves", type=int, required=True)
    p.add_argument("--spines", type=int, required=True)
    p.add_argument("--superspines", type=int, default=0)
    p.add_argument("--clients-per-leaf", type=int, default=0)
    p.add_argument("--mgmt-subnet", required=True)
    p.add_argument("--node-image", required=True)
    p.add_argument("--client-image", required=True)

    args = parser.parse_args()

    if args.command in ("resolve", "validate", "allocate-ips", "inventory"):
        topo = load_topology(args.topology)

    if args.command == "resolve":
        print(json.dumps(resolve_nodes(topo), indent=2, sort_keys=True))

    elif args.command == "validate":
        print(json.dumps(validate_topology(topo), indent=2))

    elif args.command == "allocate-ips":
        print(json.dumps(allocate_mgmt_ips(topo), indent=2, sort_keys=True))

    elif args.command == "inventory":
        inv = generate_ansible_inventory(topo)
        print(yaml.dump(inv, default_flow_style=False, sort_keys=True))

    elif args.command == "generate-clos":
        topo = generate_clos(args)
        print(yaml.dump(topo, default_flow_style=False, sort_keys=False))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
