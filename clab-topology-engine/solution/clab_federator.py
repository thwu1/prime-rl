#!/usr/bin/env python3
"""Containerlab Topology Federation Engine."""

import argparse
import ipaddress
import json
import sys

import yaml


# -- Constants ----------------------------------------------------------------

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

KIND_COLORS = {
    "srl": "#4ECDC4",
    "nokia_srlinux": "#4ECDC4",
    "ceos": "#F38181",
    "arista_ceos": "#F38181",
    "linux": "#95E1D3",
}
DEFAULT_COLOR = "#FCE38A"


# -- Topology Resolution (Go-compatible) ------------------------------------


def resolve_nodes(topo):
    """Resolve 4-level property inheritance matching containerlab's Go implementation.

    Key subtleties from the Go source:
    - GetNodeKind: node.kind > group(node.group).kind > group(defaults.group).kind > defaults.kind
    - GetNodeGroup: node.group > kind(resolved).group > defaults.group
    - getField: uses RESOLVED group and kind for property lookups
    - mergeStringMapFields: merge order is defaults -> kind -> group -> node
    """
    t = topo.get("topology", {}) or {}
    defaults = t.get("defaults", {}) or {}
    kinds_defs = t.get("kinds", {}) or {}
    groups_defs = t.get("groups", {}) or {}
    nodes_defs = t.get("nodes", {}) or {}

    def get_node_kind(node_def):
        """Matches Go GetNodeKind."""
        # Check node's own kind
        if node_def.get("kind"):
            return node_def["kind"]
        # Check node's group's kind
        node_group = node_def.get("group", "")
        if node_group:
            g = groups_defs.get(node_group) or {}
            if g.get("kind"):
                return g["kind"]
        # Check defaults.group -> groups -> kind
        default_group = defaults.get("group", "")
        if default_group:
            dg = groups_defs.get(default_group) or {}
            if dg.get("kind"):
                return dg["kind"]
        # Fall back to defaults.kind
        return defaults.get("kind", "")

    def get_node_group(node_def, kind_name):
        """Matches Go GetNodeGroup."""
        # Check node's own group
        if node_def.get("group"):
            return node_def["group"]
        # Check kind's group field
        if kind_name:
            kd = kinds_defs.get(kind_name) or {}
            if kd.get("group"):
                return kd["group"]
        # Fall back to defaults.group
        return defaults.get("group", "")

    resolved = {}
    for name, node_def in nodes_defs.items():
        node_def = node_def if node_def is not None else {}

        kind_name = get_node_kind(node_def)
        group_name = get_node_group(node_def, kind_name)

        kind_def = (kinds_defs.get(kind_name) or {}) if kind_name else {}
        group_def = (groups_defs.get(group_name) or {}) if group_name else {}

        resolved_node = {}

        # Scalar fields: node > group > kind > defaults (getField)
        for field in SCALAR_FIELDS:
            for source in (node_def, group_def, kind_def, defaults):
                if field in source and source[field] is not None:
                    resolved_node[field] = source[field]
                    break

        # Kind is always the resolved kind
        if kind_name:
            resolved_node["kind"] = kind_name

        # Map fields: merge defaults -> kind -> group -> node (mergeStringMapFields)
        for field in MAP_FIELDS:
            merged = {}
            for source in (defaults, kind_def, group_def, node_def):
                vals = source.get(field)
                if vals:
                    merged.update(vals)
            if merged:
                resolved_node[field] = merged

        resolved[name] = resolved_node

    return resolved


# -- Federation Loading -------------------------------------------------------


def load_federation(spec_path):
    """Load and parse federation specification."""
    with open(spec_path) as f:
        spec = yaml.safe_load(f)
    return spec["federation"]


def load_pod_topology(path):
    """Load a pod topology file."""
    with open(path) as f:
        return yaml.safe_load(f)


# -- Subnet Partitioning -----------------------------------------------------


def partition_subnets(base_cidr, pod_prefix_len, num_pods):
    """Subdivide base CIDR into per-pod subnets."""
    base_net = ipaddress.IPv4Network(base_cidr, strict=False)
    subnets = list(base_net.subnets(new_prefix=pod_prefix_len))
    if len(subnets) < num_pods:
        return None
    return subnets[:num_pods]


# -- Interface Counting -------------------------------------------------------


def count_node_interfaces(links, node_name):
    """Count how many interfaces a node uses in existing links."""
    count = 0
    for link in links:
        for ep in link.get("endpoints", []):
            parts = ep.split(":")
            if len(parts) == 2 and parts[0] == node_name:
                count += 1
    return count


# -- Feasibility Check -------------------------------------------------------


def check_federation(federation):
    """Check feasibility and return report."""
    mgmt = federation["mgmt"]
    base_cidr = mgmt["ipv4-base"]
    pod_prefix_len = mgmt["pod-prefix-length"]
    pods = federation["pods"]

    report = {
        "feasible": True,
        "errors": [],
        "pod_subnets": {},
        "naming_conflicts": [],
        "border_link_count": 0,
        "total_node_count": 0,
    }

    subnets = partition_subnets(base_cidr, pod_prefix_len, len(pods))
    if subnets is None:
        report["feasible"] = False
        report["errors"].append(
            f"Cannot partition {base_cidr} into {len(pods)} "
            f"/{pod_prefix_len} subnets"
        )
        return report

    all_node_names = {}
    total_nodes = 0

    for i, pod in enumerate(pods):
        pod_name = pod["name"]
        topo = load_pod_topology(pod["topology"])
        t = topo.get("topology", {}) or {}
        nodes = t.get("nodes", {}) or {}
        num_nodes = len(nodes)
        total_nodes += num_nodes

        subnet = subnets[i]
        report["pod_subnets"][pod_name] = str(subnet)

        usable = subnet.num_addresses - 3
        if usable < 0:
            usable = 0
        if num_nodes > usable:
            report["feasible"] = False
            report["errors"].append(
                f"Pod '{pod_name}': {num_nodes} nodes but subnet "
                f"{subnet} has only {usable} usable addresses"
            )

        for name in nodes:
            if name not in all_node_names:
                all_node_names[name] = []
            all_node_names[name].append(pod_name)

    report["total_node_count"] = total_nodes

    for name in sorted(all_node_names):
        if len(all_node_names[name]) > 1:
            report["naming_conflicts"].append({
                "name": name,
                "pods": all_node_names[name],
            })

    interconnect = federation.get("interconnect", "full-mesh")
    if interconnect == "full-mesh":
        border_count = 0
        for i in range(len(pods)):
            for j in range(i + 1, len(pods)):
                bi = len(pods[i].get("border-nodes", []))
                bj = len(pods[j].get("border-nodes", []))
                border_count += bi * bj
        report["border_link_count"] = border_count

    return report


# -- IP Allocation -----------------------------------------------------------


def allocate_federation_ips(federation):
    """Allocate management IPs for all nodes in the federation."""
    mgmt = federation["mgmt"]
    base_cidr = mgmt["ipv4-base"]
    pod_prefix_len = mgmt["pod-prefix-length"]
    pods = federation["pods"]

    subnets = partition_subnets(base_cidr, pod_prefix_len, len(pods))
    if subnets is None:
        raise ValueError(
            f"Cannot partition {base_cidr} into {len(pods)} "
            f"/{pod_prefix_len} subnets"
        )

    ip_map = {}

    for i, pod in enumerate(pods):
        pod_name = pod["name"]
        topo = load_pod_topology(pod["topology"])
        t = topo.get("topology", {}) or {}
        nodes = t.get("nodes", {}) or {}

        subnet = subnets[i]
        gw = subnet.network_address + 1
        reserved = {subnet.network_address, subnet.broadcast_address, gw}

        prefixed_names = sorted(f"{pod_name}-{n}" for n in nodes)

        next_ip_int = int(gw) + 1
        for pname in prefixed_names:
            while True:
                candidate = ipaddress.IPv4Address(next_ip_int)
                if candidate not in reserved and candidate in subnet:
                    ip_map[pname] = str(candidate)
                    reserved.add(candidate)
                    next_ip_int += 1
                    break
                next_ip_int += 1
                if next_ip_int > int(subnet.broadcast_address):
                    raise ValueError(
                        f"No more IPs in {subnet} for pod {pod_name}"
                    )

    return ip_map


# -- Border Link Generation --------------------------------------------------


def generate_border_links(pods, pod_topos):
    """Generate full-mesh border links between pods."""
    iface_counts = {}
    for pod in pods:
        pod_name = pod["name"]
        topo = pod_topos[pod_name]
        t = topo.get("topology", {}) or {}
        links = t.get("links", []) or []
        nodes = t.get("nodes", {}) or {}

        for name in nodes:
            prefixed = f"{pod_name}-{name}"
            iface_counts[prefixed] = count_node_interfaces(links, name)

    border_links = []
    for i in range(len(pods)):
        for j in range(i + 1, len(pods)):
            pod_i = pods[i]
            pod_j = pods[j]
            for bn_i in pod_i.get("border-nodes", []):
                for bn_j in pod_j.get("border-nodes", []):
                    pn_i = f"{pod_i['name']}-{bn_i}"
                    pn_j = f"{pod_j['name']}-{bn_j}"

                    iface_counts[pn_i] += 1
                    iface_counts[pn_j] += 1

                    border_links.append({
                        "endpoints": [
                            f"{pn_i}:eth{iface_counts[pn_i]}",
                            f"{pn_j}:eth{iface_counts[pn_j]}",
                        ]
                    })

    return border_links


# -- Merge Topology -----------------------------------------------------------


def merge_topology(federation, pod_topos, resolved_pods, ip_map,
                   border_links):
    """Create the merged federated topology."""
    fed_name = federation["name"]
    base_cidr = federation["mgmt"]["ipv4-base"]

    merged_nodes = {}
    merged_links = []

    for pod in federation["pods"]:
        pod_name = pod["name"]
        topo = pod_topos[pod_name]
        resolved = resolved_pods[pod_name]
        t = topo.get("topology", {}) or {}

        for name, props in sorted(resolved.items()):
            prefixed = f"{pod_name}-{name}"
            node = dict(props)
            if prefixed in ip_map:
                node["mgmt-ipv4"] = ip_map[prefixed]
            if "labels" not in node:
                node["labels"] = {}
            node["labels"]["clab-federation-pod"] = pod_name
            node.pop("group", None)
            merged_nodes[prefixed] = node

        for link in (t.get("links", []) or []):
            new_eps = []
            for ep in link.get("endpoints", []):
                parts = ep.split(":")
                if len(parts) == 2:
                    new_eps.append(f"{pod_name}-{parts[0]}:{parts[1]}")
                else:
                    new_eps.append(ep)
            merged_links.append({"endpoints": new_eps})

    merged_links.extend(border_links)

    return {
        "name": fed_name,
        "mgmt": {"ipv4-subnet": base_cidr},
        "topology": {
            "nodes": merged_nodes,
            "links": merged_links,
        },
    }


# -- Ansible Inventory --------------------------------------------------------


def generate_inventory(federation, resolved_pods, ip_map):
    """Generate Ansible inventory for the federated topology."""
    fed_name = federation["name"]
    prefix = "clab"

    groups = {}
    for pod in federation["pods"]:
        pod_name = pod["name"]
        resolved = resolved_pods[pod_name]

        for name, props in sorted(resolved.items()):
            prefixed = f"{pod_name}-{name}"
            kind = props.get("kind", "linux")
            if kind not in groups:
                groups[kind] = {}
            host_name = f"{prefix}-{fed_name}-{prefixed}"
            groups[kind][host_name] = {
                "ansible_host": ip_map.get(prefixed, ""),
            }

    children = {}
    for kind in sorted(groups):
        entry = {"hosts": dict(sorted(groups[kind].items()))}
        if kind in KIND_ANSIBLE_VARS:
            entry["vars"] = dict(KIND_ANSIBLE_VARS[kind])
        children[kind] = entry

    return {"all": {"children": children}}


# -- Graphviz DOT Graph -------------------------------------------------------


def generate_dot_graph(federation, pod_topos, resolved_pods, border_links):
    """Generate Graphviz DOT-format undirected graph."""
    fed_name = federation["name"]
    lines = [f'graph "{fed_name}" {{']
    lines.append("  rankdir=LR;")
    lines.append(f'  label="{fed_name} Federation";')
    lines.append("  node [shape=box, style=filled];")
    lines.append("")

    # Subgraph clusters for each pod
    for pod in federation["pods"]:
        pod_name = pod["name"]
        resolved = resolved_pods[pod_name]
        lines.append(f"  subgraph cluster_{pod_name} {{")
        lines.append(f'    label="{pod_name}";')
        lines.append("    style=filled;")
        lines.append("    color=lightgrey;")
        for name in sorted(resolved):
            prefixed = f"{pod_name}-{name}"
            kind = resolved[name].get("kind", "linux")
            color = KIND_COLORS.get(kind, DEFAULT_COLOR)
            lines.append(
                f'    "{prefixed}" [label="{prefixed}", fillcolor="{color}"];'
            )
        lines.append("  }")
        lines.append("")

    # Internal links (solid)
    for pod in federation["pods"]:
        pod_name = pod["name"]
        topo = pod_topos[pod_name]
        t = topo.get("topology", {}) or {}
        for link in (t.get("links", []) or []):
            eps = link.get("endpoints", [])
            if len(eps) == 2:
                parts_a = eps[0].split(":")
                parts_b = eps[1].split(":")
                node_a = f"{pod_name}-{parts_a[0]}"
                node_b = f"{pod_name}-{parts_b[0]}"
                iface_a = parts_a[1] if len(parts_a) > 1 else ""
                iface_b = parts_b[1] if len(parts_b) > 1 else ""
                lines.append(
                    f'  "{node_a}" -- "{node_b}" '
                    f'[label="{iface_a}:{iface_b}"];'
                )

    lines.append("")

    # Border links (dashed)
    for link in border_links:
        eps = link["endpoints"]
        parts_a = eps[0].split(":")
        parts_b = eps[1].split(":")
        node_a = parts_a[0]
        node_b = parts_b[0]
        iface_a = parts_a[1] if len(parts_a) > 1 else ""
        iface_b = parts_b[1] if len(parts_b) > 1 else ""
        lines.append(
            f'  "{node_a}" -- "{node_b}" '
            f'[label="{iface_a}:{iface_b}", style=dashed, color=red];'
        )

    lines.append("}")
    return "\n".join(lines)


# -- Shared Loading -----------------------------------------------------------


def load_all_pods(federation):
    """Load and resolve all pod topologies."""
    pod_topos = {}
    resolved_pods = {}
    for pod in federation["pods"]:
        topo = load_pod_topology(pod["topology"])
        pod_topos[pod["name"]] = topo
        resolved_pods[pod["name"]] = resolve_nodes(topo)
    return pod_topos, resolved_pods


def check_and_fail(federation):
    """Run feasibility check; exit 1 if infeasible."""
    report = check_federation(federation)
    if not report["feasible"]:
        for err in report["errors"]:
            print(err, file=sys.stderr)
        sys.exit(1)
    return report


# -- CLI ----------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Containerlab Topology Federation Engine"
    )
    sub = parser.add_subparsers(dest="command")

    for cmd in ("federate", "allocate-ips", "inventory", "check", "graph"):
        p = sub.add_parser(cmd)
        p.add_argument("spec")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    federation = load_federation(args.spec)

    if args.command == "check":
        report = check_federation(federation)
        print(json.dumps(report, indent=2))

    elif args.command == "allocate-ips":
        check_and_fail(federation)
        ip_map = allocate_federation_ips(federation)
        print(json.dumps(ip_map, indent=2, sort_keys=True))

    elif args.command == "inventory":
        check_and_fail(federation)
        pod_topos, resolved_pods = load_all_pods(federation)
        ip_map = allocate_federation_ips(federation)
        inv = generate_inventory(federation, resolved_pods, ip_map)
        print(yaml.dump(inv, default_flow_style=False, sort_keys=True))

    elif args.command == "federate":
        check_and_fail(federation)
        pod_topos, resolved_pods = load_all_pods(federation)
        ip_map = allocate_federation_ips(federation)
        border_links = generate_border_links(federation["pods"], pod_topos)
        merged = merge_topology(
            federation, pod_topos, resolved_pods, ip_map, border_links
        )
        print(yaml.dump(merged, default_flow_style=False, sort_keys=False))

    elif args.command == "graph":
        check_and_fail(federation)
        pod_topos, resolved_pods = load_all_pods(federation)
        border_links = generate_border_links(federation["pods"], pod_topos)
        dot = generate_dot_graph(
            federation, pod_topos, resolved_pods, border_links
        )
        print(dot)


if __name__ == "__main__":
    main()
