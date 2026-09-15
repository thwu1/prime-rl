#!/usr/bin/env python3
"""
Pipeline: pcap topology discovery, graphviz visualization, audit report.

"""

import subprocess
import struct
import json
import sys
import os

sys.path.insert(0, '/app')
from routing_engine import RoutingEngine

NLSP_PORT = 47891
ROUTER_NAMES = {1: 'A', 2: 'B', 3: 'C', 4: 'D', 5: 'E', 6: 'F'}


def discover_topology():
    """Use tshark to extract NLSP packets, decode binary payloads, build topology."""
    # Try different tshark field names for UDP payload
    payload_lines = None
    for field in ['data.data', 'data', 'udp.payload']:
        result = subprocess.run(
            ['tshark', '-r', '/app/network_capture.pcap',
             '-Y', f'udp.port == {NLSP_PORT}',
             '-T', 'fields', '-e', field],
            capture_output=True, text=True
        )
        lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
        if lines:
            payload_lines = lines
            break

    if not payload_lines:
        raise RuntimeError("tshark could not extract NLSP payloads")

    # Parse binary NLSP payloads, track latest seq per (src, dst)
    latest = {}  # (src_id, dst_id) -> (cost, seq, flags)

    for line in payload_lines:
        hex_str = line.replace(':', '')
        if len(hex_str) < 32:  # need at least 16 bytes = 32 hex chars
            continue
        try:
            raw = bytes.fromhex(hex_str)
        except ValueError:
            continue

        magic = raw[0:2]
        if magic != b'NL':
            continue

        version = raw[2]
        if version != 1:
            continue

        flags = raw[3]
        src_id = raw[4]
        dst_id = raw[5]
        cost = struct.unpack('!H', raw[6:8])[0]
        seq_num = struct.unpack('!I', raw[8:12])[0]

        key = (src_id, dst_id)
        if key not in latest or seq_num > latest[key][1]:
            latest[key] = (cost, seq_num, flags)

    # Build topology from active links
    routers = set()
    links = []

    for (src_id, dst_id), (cost, _, flags) in latest.items():
        if flags & 0x01 == 0:
            continue
        src_name = ROUTER_NAMES.get(src_id)
        dst_name = ROUTER_NAMES.get(dst_id)
        if not src_name or not dst_name:
            continue
        routers.add(src_name)
        routers.add(dst_name)
        links.append({"src": src_name, "dst": dst_name, "cost": cost})

    topology = {
        "routers": sorted(routers),
        "links": sorted(links, key=lambda x: (x["src"], x["dst"]))
    }

    with open('/app/discovered_topology.json', 'w') as f:
        json.dump(topology, f, indent=2)

    return topology


def generate_visualization(topology):
    """Generate Graphviz DOT diagram and render to PNG."""
    lines = ['graph network {']
    lines.append('  rankdir=LR;')
    lines.append('  node [shape=box, style=filled, fillcolor=lightblue];')

    for router in topology['routers']:
        lines.append(f'  {router};')

    seen_edges = set()
    for link in topology['links']:
        edge = tuple(sorted([link['src'], link['dst']]))
        if edge not in seen_edges:
            seen_edges.add(edge)
            lines.append(f'  {edge[0]} -- {edge[1]} [label="{link["cost"]}"];')

    lines.append('}')

    with open('/app/topology.dot', 'w') as f:
        f.write('\n'.join(lines) + '\n')

    subprocess.run(['dot', '-Tpng', '/app/topology.dot', '-o', '/app/topology.png'],
                   check=True)


def generate_audit_report(topology):
    """Build routing engine, compute forwarding table and coverage, check policy."""
    engine = RoutingEngine()
    for link in topology['links']:
        engine.update_link(link['src'], link['dst'], link['cost'])

    with open('/app/routing_policy.json') as f:
        policy = json.load(f)

    source = policy['audit_source']
    table = engine.forwarding_table(source)
    coverage = engine.backup_coverage(source)

    fwd_table = {}
    for dest, entry in sorted(table.items()):
        fwd_table[dest] = {
            "cost": entry['cost'],
            "primary_next_hops": sorted(entry['primary']),
            "backup_next_hops": {
                "link_protecting": sorted(entry['link_backup']),
                "node_protecting": sorted(entry['node_backup'])
            }
        }

    critical = policy.get('critical_destinations', [])
    all_reachable = all(d in table for d in critical)
    critical_have_backup = all(
        len(table.get(d, {}).get('link_backup', frozenset())) > 0
        for d in critical
    )
    max_cost = policy.get('max_acceptable_cost', float('inf'))
    exceeded = sorted([d for d, e in table.items() if e['cost'] > max_cost])

    report = {
        "forwarding_table": fwd_table,
        "coverage": {
            "link_protecting_pct": coverage['link_protecting_pct'],
            "node_protecting_pct": coverage['node_protecting_pct'],
            "unprotected_destinations": sorted(coverage['unprotected'])
        },
        "policy_compliance": {
            "all_destinations_reachable": all_reachable,
            "critical_destinations_have_backup": critical_have_backup,
            "max_cost_exceeded": exceeded
        }
    }

    with open('/app/audit_report.json', 'w') as f:
        json.dump(report, f, indent=2)


if __name__ == '__main__':
    topology = discover_topology()
    print(f"Discovered {len(topology['routers'])} routers, {len(topology['links'])} links")
    generate_visualization(topology)
    print("Generated topology.dot and topology.png")
    generate_audit_report(topology)
    print("Generated audit_report.json")
