#!/usr/bin/env python3
"""BGP routing anomaly analyzer.

Correlates data from SQLite RIB database, XML topology, RPKI VRPs,
and Cisco IOS-style policy configuration to detect routing anomalies.
"""

import sqlite3
import json
import os
import re
import ipaddress
import xml.etree.ElementTree as ET


def query_rib_entries(db_path):
    """Extract best-path RIB entries with AS path data from SQLite."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute('''
        SELECT r.entry_id, r.router_id, rt.asn AS router_asn, rt.hostname,
               r.prefix, r.prefix_length, r.local_pref, r.is_best,
               r.learned_from_ip, a.segment AS as_path_str
        FROM rib_entries r
        JOIN routers rt ON r.router_id = rt.router_id
        LEFT JOIN as_path_segments a ON r.path_id = a.path_id
        WHERE r.is_best = 1
    ''').fetchall()
    conn.close()

    entries = []
    for row in rows:
        as_path = []
        if row['as_path_str']:
            as_path = [int(x) for x in row['as_path_str'].split()]

        entries.append({
            'entry_id': row['entry_id'],
            'router_id': row['router_id'],
            'router_asn': row['router_asn'],
            'hostname': row['hostname'],
            'prefix': row['prefix'],
            'prefix_length': row['prefix_length'],
            'local_pref': row['local_pref'],
            'learned_from_ip': row['learned_from_ip'],
            'as_path': as_path,
            'is_local': row['learned_from_ip'] is None,
        })

    return entries


def parse_topology_xml(xml_path):
    """Parse namespaced XML topology to extract AS relationships and IP map."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    ns = {
        't': 'urn:example:bgp-topology',
        'bgp': 'urn:example:bgp-policy',
    }

    rel_map = {}
    ip_map = {}

    for link in root.findall('.//t:interconnections/t:link', ns):
        local_as = int(link.find('t:local-as', ns).text)
        remote_as = int(link.find('t:remote-as', ns).text)
        rel_elem = link.find('bgp:relationship', ns)
        rel_type = rel_elem.get('type')

        local_ip = link.find('t:addresses/t:local', ns).text
        remote_ip = link.find('t:addresses/t:remote', ns).text

        if rel_type == 'peer':
            rel_map[(local_as, remote_as)] = 'peer'
            rel_map[(remote_as, local_as)] = 'peer'
        elif rel_type == 'customer-provider':
            provider = int(rel_elem.find('bgp:provider', ns).text)
            customer = int(rel_elem.find('bgp:customer', ns).text)
            rel_map[(provider, customer)] = 'provider-to-customer'
            rel_map[(customer, provider)] = 'customer-to-provider'

        ip_map[local_ip] = local_as
        ip_map[remote_ip] = remote_as

    return rel_map, ip_map


def parse_rpki_vrps(json_path):
    """Read RPKI VRPs, handling 'ASnnnn' format for ASN."""
    with open(json_path) as f:
        data = json.load(f)

    vrps = []
    for roa in data['roas']:
        asn = int(roa['asn'].replace('AS', ''))
        vrps.append({
            'origin_as': asn,
            'prefix': roa['prefix'],
            'max_length': roa['maxLength'],
        })
    return vrps


def parse_bgp_policy(conf_path):
    """Parse Cisco IOS-style config to map neighbor IPs to expected LOCAL_PREF."""
    with open(conf_path) as f:
        lines = f.readlines()

    # Pass 1: extract route-map name -> local-preference value
    route_map_lp = {}
    current_rm = None
    for line in lines:
        stripped = line.strip()
        m = re.match(r'route-map\s+(\S+)\s+permit', stripped)
        if m:
            current_rm = m.group(1)
            continue
        m = re.match(r'set\s+local-preference\s+(\d+)', stripped)
        if m and current_rm:
            route_map_lp[current_rm] = int(m.group(1))
            current_rm = None
            continue
        if stripped.startswith('!') or stripped == '':
            current_rm = None

    # Pass 2: extract neighbor IP -> inbound route-map name
    neighbor_policy = {}
    for line in lines:
        m = re.match(r'\s*neighbor\s+(\S+)\s+route-map\s+(\S+)\s+in', line)
        if m:
            ip = m.group(1)
            rm_name = m.group(2)
            if rm_name in route_map_lp:
                neighbor_policy[ip] = route_map_lp[rm_name]

    return neighbor_policy


def detect_route_leaks(entries, rel_map):
    """Detect valley-free routing violations in the forwarding chain."""
    leaks = []
    seen = set()

    for entry in entries:
        if entry['is_local'] or not entry['as_path']:
            continue

        router_as = entry['router_asn']
        as_path = entry['as_path']
        prefix = f"{entry['prefix']}/{entry['prefix_length']}"

        # Reconstruct forwarding chain: origin -> ... -> receiver
        chain = list(reversed(as_path)) + [router_as]

        prev_dir = None
        for i in range(len(chain) - 1):
            from_as = chain[i]
            to_as = chain[i + 1]
            rel = rel_map.get((from_as, to_as))
            if rel is None:
                prev_dir = None
                continue

            if rel == 'provider-to-customer':
                direction = 'downhill'
            elif rel == 'customer-to-provider':
                direction = 'uphill'
            else:
                direction = 'lateral'

            # Valley-free violation: lateral/uphill after downhill/lateral
            if prev_dir in ('downhill', 'lateral') and direction in ('uphill', 'lateral'):
                leaker_as = from_as
                key = (leaker_as, prefix)
                if key not in seen:
                    seen.add(key)
                    leaks.append({
                        'prefix': prefix,
                        'leaker_as': leaker_as,
                        'violation': (
                            f'Route leaked by AS {leaker_as}: '
                            f'forwarded to AS {to_as} in violation of '
                            f'business relationship'
                        ),
                    })

            prev_dir = direction

    return leaks


def detect_rpki_violations(entries, vrps):
    """Detect RPKI ROA validation failures (origin mismatch or length exceeded)."""
    violations = []
    seen = set()

    for entry in entries:
        prefix_str = f"{entry['prefix']}/{entry['prefix_length']}"
        if prefix_str in seen:
            continue

        # Determine origin AS
        if entry['is_local']:
            origin_as = entry['router_asn']
        elif entry['as_path']:
            origin_as = entry['as_path'][-1]
        else:
            continue

        prefix_net = ipaddress.ip_network(prefix_str)
        prefix_len = prefix_net.prefixlen

        for vrp in vrps:
            roa_net = ipaddress.ip_network(vrp['prefix'])

            # Check if this VRP covers the announced prefix
            if (prefix_net.network_address in roa_net
                    and prefix_len >= roa_net.prefixlen):
                if origin_as == vrp['origin_as']:
                    if prefix_len <= vrp['max_length']:
                        seen.add(prefix_str)  # Valid
                    else:
                        violations.append({
                            'prefix': prefix_str,
                            'origin_as': origin_as,
                            'violation': 'invalid_length',
                        })
                        seen.add(prefix_str)
                else:
                    violations.append({
                        'prefix': prefix_str,
                        'origin_as': origin_as,
                        'violation': 'invalid_origin',
                    })
                    seen.add(prefix_str)
                break

        seen.add(prefix_str)

    return violations


def detect_policy_violations(entries, neighbor_policy):
    """Detect LOCAL_PREF mismatches against configured routing policy."""
    violations = []

    for entry in entries:
        if entry['is_local']:
            continue

        learned_from = entry['learned_from_ip']
        if learned_from not in neighbor_policy:
            continue

        expected_lp = neighbor_policy[learned_from]
        actual_lp = entry['local_pref']

        if actual_lp != expected_lp:
            prefix = f"{entry['prefix']}/{entry['prefix_length']}"
            violations.append({
                'router_as': entry['router_asn'],
                'prefix': prefix,
                'expected_local_pref': expected_lp,
                'actual_local_pref': actual_lp,
            })

    return violations


def main():
    entries = query_rib_entries('/data/bgp_monitor.db')
    rel_map, ip_map = parse_topology_xml('/data/network_topology.xml')
    vrps = parse_rpki_vrps('/data/rpki/validated_roas.json')
    neighbor_policy = parse_bgp_policy('/data/configs/bgp_policy.conf')

    route_leaks = detect_route_leaks(entries, rel_map)
    rpki_violations = detect_rpki_violations(entries, vrps)
    policy_violations = detect_policy_violations(entries, neighbor_policy)

    os.makedirs('/app/output', exist_ok=True)

    for name, data in [
        ('route_leaks.json', route_leaks),
        ('rpki_violations.json', rpki_violations),
        ('policy_violations.json', policy_violations),
    ]:
        with open(f'/app/output/{name}', 'w') as f:
            json.dump(data, f, indent=2)

    summary = {
        'total_route_leaks': len(route_leaks),
        'total_rpki_violations': len(rpki_violations),
        'total_policy_violations': len(policy_violations),
        'total_issues': (
            len(route_leaks) + len(rpki_violations) + len(policy_violations)
        ),
    }

    with open('/app/output/summary.json', 'w') as f:
        json.dump(summary, f, indent=2)

    print(f"Analysis complete. Found {summary['total_issues']} issues:")
    print(f"  Route leaks: {summary['total_route_leaks']}")
    print(f"  RPKI violations: {summary['total_rpki_violations']}")
    print(f"  Policy violations: {summary['total_policy_violations']}")


if __name__ == '__main__':
    main()
