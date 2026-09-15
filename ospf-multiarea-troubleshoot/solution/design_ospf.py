#!/usr/bin/env python3
"""
Design and implement complete FRR OSPF configurations for a 6-router
multi-area topology.

Reads the topology specification (including requirements) from
/app/topology.json and generates correct FRR configuration files
that satisfy all constraints: area types, cost overrides,
summarization, and selective external route redistribution.
"""

import json
import os

CONFIGS_DIR = '/app/configs'
TOPO_FILE = '/app/topology.json'


def load_topology():
    with open(TOPO_FILE) as f:
        return json.load(f)


def build_config(topo, router_name):
    """Build a complete FRR config for a router based on topology spec."""
    router_info = topo['routers'][router_name]
    loopback = router_info['loopback']
    loopback_area = router_info['loopback_area']
    loopback_ip = loopback.split('/')[0]

    requirements = topo['requirements']
    area_types = requirements['area_types']
    summarization_reqs = requirements['summarization']
    cost_overrides = requirements['cost_overrides']

    # Find all links this router participates in
    router_links = []
    for link in topo['links']:
        if router_name in link['endpoints']:
            router_links.append(link)

    # Determine which areas this router belongs to
    areas = set()
    areas.add(loopback_area)
    for link in router_links:
        areas.add(link['area'])

    is_abr = len(areas) > 1

    # Build interface blocks for cost overrides
    interface_blocks = []
    for co in cost_overrides:
        if co['router'] == router_name:
            interface_blocks.append(
                f"interface {co['interface']}\n"
                f" ip ospf cost {co['cost']}\n"
                f"exit"
            )

    # Build router ospf block
    ospf_lines = [f" ospf router-id {loopback_ip}"]

    # Network statements
    ospf_lines.append(f" network {loopback} area {loopback_area}")
    for link in router_links:
        ospf_lines.append(f" network {link['subnet']} area {link['area']}")

    # Area type directives
    for area_id in sorted(areas):
        area_str = str(area_id)
        if area_str in area_types:
            at = area_types[area_str]
            if at == 'totally_stub':
                if is_abr:
                    ospf_lines.append(
                        f" area {area_id} stub no-summary")
                else:
                    ospf_lines.append(f" area {area_id} stub")
            elif at == 'nssa':
                ospf_lines.append(f" area {area_id} nssa")
            # 'normal' requires no directive

    # Area range for summarization (only on ABRs that are listed)
    for s in summarization_reqs:
        if s['router'] == router_name:
            ospf_lines.append(
                f" area {s['area']} range {s['range']}")

    # External route redistribution
    ext_routes = [e for e in topo['external_routes']
                  if e['origin'] == router_name]
    if ext_routes:
        ospf_lines.append(" redistribute static route-map REDISTRIBUTE")

    # Assemble full config
    config_parts = [
        f"hostname {router_name}",
        "log syslog informational",
        "!"
    ]

    # Static routes (if this router originates external routes)
    if ext_routes:
        for sr in topo['external_routes']:
            if sr['origin'] == router_name:
                config_parts.append(
                    f"ip route {sr['prefix']} blackhole")
        config_parts.append("!")

    # Prefix-list and route-map for redistribution
    if ext_routes:
        permitted = [e for e in ext_routes
                     if e.get('expected_action') == 'permit']
        seq = 10
        for p in permitted:
            config_parts.append(
                f"ip prefix-list ALLOWED_NETS seq {seq} "
                f"permit {p['prefix']}")
            seq += 10
        config_parts.append("!")
        config_parts.append("route-map REDISTRIBUTE permit 10")
        config_parts.append(
            " match ip address prefix-list ALLOWED_NETS")
        config_parts.append("exit")
        config_parts.append("!")

    # Interface blocks with cost overrides
    for ib in interface_blocks:
        config_parts.append(ib)
        config_parts.append("!")

    # Router OSPF block
    config_parts.append("router ospf")
    config_parts.extend(ospf_lines)
    config_parts.append("exit")
    config_parts.append("!")

    return '\n'.join(config_parts) + '\n'


def main():
    topo = load_topology()

    for router_name in sorted(topo['routers'].keys()):
        config = build_config(topo, router_name)
        filepath = os.path.join(CONFIGS_DIR, f'{router_name}.conf')
        with open(filepath, 'w') as f:
            f.write(config)
        print(f"Wrote config for {router_name}")


if __name__ == '__main__':
    main()
