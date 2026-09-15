#!/usr/bin/env python3
"""
Multi-source nftables firewall security audit tool.

Cross-references the nftables ruleset, nft monitor trace capture,
conntrack state dump, and declared security policy to produce a
comprehensive audit report.
"""

import json
import re
from collections import defaultdict

import yaml


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_policy(path):
    """Parse YAML security policy."""
    with open(path) as f:
        return yaml.safe_load(f)


def parse_nft_ruleset(path):
    """Parse `nft -a list ruleset` output.

    Returns a list of rule dicts (handle, table, chain) for rules that
    belong to forwarding or NAT chains only.
    """
    rules = []
    current_table = None
    current_chain = None
    in_set = False
    is_fwd_nat_chain = False

    with open(path) as f:
        for line in f:
            stripped = line.rstrip()
            bare = stripped.strip()

            # --- set blocks (skip entirely) ---
            if re.match(r'\s+set\s+\S+\s*\{', stripped):
                in_set = True
                continue
            if in_set:
                if bare == '}':
                    in_set = False
                continue

            # --- table ---
            tm = re.match(r'^table\s+\S+\s+(\S+)\s*\{', stripped)
            if tm:
                current_table = tm.group(1)
                continue

            # --- chain ---
            cm = re.match(r'\s+chain\s+(\S+)\s*\{', stripped)
            if cm:
                current_chain = cm.group(1)
                is_fwd_nat_chain = False
                continue

            # --- chain type declaration ---
            if current_chain and bare.startswith('type '):
                if re.search(
                    r'filter\s+hook\s+forward|'
                    r'nat\s+hook\s+prerouting|'
                    r'nat\s+hook\s+postrouting',
                    bare,
                ):
                    is_fwd_nat_chain = True
                continue

            # --- closing brace ---
            if bare == '}':
                if current_chain:
                    current_chain = None
                    is_fwd_nat_chain = False
                elif current_table:
                    current_table = None
                continue

            # --- rule with handle inside a forwarding/NAT chain ---
            if is_fwd_nat_chain and current_table and current_chain:
                hm = re.search(r'#\s*handle\s+(\d+)', stripped)
                if hm:
                    handle = int(hm.group(1))
                    rule_text = re.sub(r'\s*#\s*handle\s+\d+', '', bare)
                    if rule_text and not rule_text.startswith('type '):
                        rules.append({
                            'handle': handle,
                            'table': current_table,
                            'chain': current_chain,
                        })

    return rules


def parse_trace(path):
    """Parse nft monitor trace output → dict[trace_id → list of events]."""
    flows = defaultdict(list)
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            m = re.match(r'trace id ([0-9a-fA-F]+) ip (\S+) (\S+) (.+)', line)
            if not m:
                continue
            trace_id, table, chain, rest = m.groups()
            event = {'table': table, 'chain': chain}

            if rest.startswith('packet:'):
                event['type'] = 'packet'
                event['fields'] = _parse_packet_fields(rest[len('packet:'):])
            elif rest.startswith('rule '):
                event['type'] = 'rule'
                event['rule_text'] = rest
                hm = re.search(r'handle (\d+)', rest)
                if hm:
                    event['handle'] = int(hm.group(1))
                vm = re.search(r'\(verdict (\w+)\)', rest)
                if vm:
                    event['verdict'] = vm.group(1)
                if 'masquerade' in rest:
                    event['nat'] = 'masquerade'
                dm = re.search(r'dnat to ([\d.]+):(\d+)', rest)
                if dm:
                    event['nat'] = 'dnat'
                    event['dnat_addr'] = dm.group(1)
                    event['dnat_port'] = int(dm.group(2))
                sm = re.search(r'snat to ([\d.]+)', rest)
                if sm:
                    event['nat'] = 'snat'
                    event['snat_addr'] = sm.group(1)
            elif rest.startswith('verdict '):
                event['type'] = 'verdict'
                event['verdict'] = rest.split()[1]
            elif rest.startswith('policy '):
                event['type'] = 'policy'
                event['verdict'] = rest.split()[1]
            else:
                event['type'] = 'unknown'

            flows[trace_id].append(event)
    return flows


def _parse_packet_fields(s):
    fields = {}
    patterns = [
        (r'iif "([^"]+)"', 'iif'),
        (r'oif "([^"]+)"', 'oif'),
        (r'ip saddr (\S+)', 'ip_saddr'),
        (r'ip daddr (\S+)', 'ip_daddr'),
        (r'ip protocol (\S+)', 'ip_protocol'),
        (r'tcp sport (\d+)', 'tcp_sport'),
        (r'tcp dport (\d+)', 'tcp_dport'),
        (r'udp sport (\d+)', 'udp_sport'),
        (r'udp dport (\d+)', 'udp_dport'),
        (r'icmp type (\S+)', 'icmp_type'),
        (r'icmp id (\d+)', 'icmp_id'),
    ]
    for pattern, key in patterns:
        m = re.search(pattern, s)
        if m:
            val = m.group(1)
            if key.endswith(('sport', 'dport', 'id')):
                val = int(val)
            fields[key] = val
    return fields


def parse_conntrack(path):
    """Parse conntrack -L dump → list of dicts (original direction only)."""
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            proto = parts[0]
            entry = {'protocol': proto}

            if proto == 'icmp':
                m = re.search(
                    r'src=(\S+)\s+dst=(\S+)\s+type=(\d+)\s+code=(\d+)\s+id=(\d+)',
                    line,
                )
                if m:
                    entry['src'] = m.group(1)
                    entry['dst'] = m.group(2)
                    entry['sport'] = None
                    entry['dport'] = None
            else:
                m = re.search(
                    r'src=(\S+)\s+dst=(\S+)\s+sport=(\d+)\s+dport=(\d+)', line
                )
                if m:
                    entry['src'] = m.group(1)
                    entry['dst'] = m.group(2)
                    entry['sport'] = int(m.group(3))
                    entry['dport'] = int(m.group(4))

            if 'src' in entry:
                entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# Flow analysis
# ---------------------------------------------------------------------------

def analyze_flow(trace_id, events, iface_zones, policy):
    """Reconstruct a single flow from its trace events."""
    # First packet event → original addresses
    first_pkt = None
    for e in events:
        if e['type'] == 'packet':
            first_pkt = e['fields']
            break
    if not first_pkt:
        return None

    protocol = first_pkt.get('ip_protocol', 'unknown')
    src_addr = first_pkt.get('ip_saddr')
    dst_addr = first_pkt.get('ip_daddr')

    src_port = None
    dst_port = None
    if protocol == 'tcp':
        src_port = first_pkt.get('tcp_sport')
        dst_port = first_pkt.get('tcp_dport')
    elif protocol == 'udp':
        src_port = first_pkt.get('udp_sport')
        dst_port = first_pkt.get('udp_dport')

    ingress = first_pkt.get('iif')
    egress = None
    for e in events:
        if e['type'] == 'packet' and 'oif' in e.get('fields', {}):
            egress = e['fields']['oif']
            break

    # Ordered chain path (deduplicated, preserving order)
    chain_path = []
    seen = set()
    for e in events:
        key = f"{e['table']}/{e['chain']}"
        if key not in seen:
            chain_path.append(key)
            seen.add(key)

    # Collect matched rule handles
    matched_handles = set()
    for e in events:
        if e['type'] == 'rule' and 'handle' in e:
            matched_handles.add(e['handle'])

    # Final verdict: last verdict-bearing event
    verdict = 'accept'
    for e in reversed(events):
        if e['type'] in ('verdict', 'policy') and 'verdict' in e:
            verdict = e['verdict']
            break
        if e['type'] == 'rule' and 'verdict' in e:
            verdict = e['verdict']
            break

    # NAT detection
    nat_type = None
    dnat_port = None
    for e in events:
        if e['type'] == 'rule':
            nat_kind = e.get('nat')
            if nat_kind in ('masquerade', 'snat'):
                nat_type = 'snat'
            elif nat_kind == 'dnat':
                nat_type = 'dnat'
                dnat_port = e.get('dnat_port')

    # Zones from interfaces
    from_zone = iface_zones.get(ingress, 'UNKNOWN')
    to_zone = iface_zones.get(egress, 'UNKNOWN') if egress else 'UNKNOWN'

    # Policy evaluation — DNAT: use post-DNAT destination port
    eval_dst_port = (
        dnat_port if nat_type == 'dnat' and dnat_port is not None else dst_port
    )
    policy_compliant = _evaluate_policy(
        from_zone, to_zone, protocol, eval_dst_port, verdict, policy
    )

    return {
        'trace_id': trace_id,
        'protocol': protocol,
        'src_addr': src_addr,
        'dst_addr': dst_addr,
        'src_port': src_port,
        'dst_port': dst_port,
        'ingress_interface': ingress,
        'egress_interface': egress,
        'from_zone': from_zone,
        'to_zone': to_zone,
        'verdict': verdict,
        'chain_path': chain_path,
        'nat_type': nat_type,
        'policy_compliant': policy_compliant,
        '_matched_handles': matched_handles,
    }


def _evaluate_policy(from_zone, to_zone, protocol, dst_port, actual, policy):
    global_default = policy.get('default_action', 'drop')
    expected = global_default

    for entry in policy.get('inter_zone_policies', []):
        if entry['from_zone'] == from_zone and entry['to_zone'] == to_zone:
            matched_rule = False
            for rule in entry.get('rules', []):
                rp = rule.get('protocol', 'any')
                if rp == 'any' or rp == protocol:
                    if 'dst_ports' in rule:
                        if dst_port is not None and dst_port in rule['dst_ports']:
                            expected = rule['action']
                            matched_rule = True
                            break
                    else:
                        expected = rule['action']
                        matched_rule = True
                        break
            if not matched_rule:
                expected = entry.get('default_action', global_default)
            break

    return actual == expected


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # ---- load all data sources ----
    policy = parse_policy('/app/policy.yaml')
    nft_rules = parse_nft_ruleset('/app/nft_ruleset.conf')
    trace_flows = parse_trace('/app/trace.log')
    ct_entries = parse_conntrack('/app/conntrack.dump')

    # ---- build interface → zone map from policy ----
    iface_zones = {}
    for zone_name, zone_info in policy.get('zones', {}).items():
        for iface in zone_info.get('interfaces', []):
            iface_zones[iface] = zone_name

    # ---- analyse each flow ----
    all_matched_handles = set()
    flows = []
    for tid, events in trace_flows.items():
        flow = analyze_flow(tid, events, iface_zones, policy)
        if flow:
            all_matched_handles.update(flow.pop('_matched_handles'))
            flows.append(flow)
    flows.sort(key=lambda f: f['trace_id'])

    # ---- policy violations ----
    violations = []
    for flow in flows:
        if not flow['policy_compliant']:
            fz, tz = flow['from_zone'], flow['to_zone']
            expected = policy.get('default_action', 'drop')
            for entry in policy.get('inter_zone_policies', []):
                if entry['from_zone'] == fz and entry['to_zone'] == tz:
                    expected = entry.get('default_action', expected)
                    break
            violations.append({
                'trace_id': flow['trace_id'],
                'from_zone': fz,
                'to_zone': tz,
                'expected_action': expected,
                'actual_verdict': flow['verdict'],
            })

    # ---- stale rules ----
    stale_rules = []
    for rule in nft_rules:
        if rule['handle'] not in all_matched_handles:
            stale_rules.append({
                'handle': rule['handle'],
                'table': rule['table'],
                'chain': rule['chain'],
            })

    # ---- conntrack anomalies ----
    # Build set of traced-flow signatures for matching
    flow_sigs = set()
    for flow in flows:
        if flow['protocol'] == 'icmp':
            flow_sigs.add(('icmp', flow['src_addr'], flow['dst_addr']))
        else:
            flow_sigs.add((
                flow['protocol'],
                flow['src_addr'],
                flow['dst_addr'],
                flow['src_port'],
                flow['dst_port'],
            ))

    anomalies = []
    for ct in ct_entries:
        matched = False
        if ct['protocol'] == 'icmp':
            for fs in flow_sigs:
                if (fs[0] == 'icmp' and fs[1] == ct['src']
                        and fs[2] == ct['dst']):
                    matched = True
                    break
        else:
            key = (ct['protocol'], ct['src'], ct['dst'],
                   ct.get('sport'), ct.get('dport'))
            matched = key in flow_sigs

        if not matched:
            anomalies.append({
                'protocol': ct['protocol'],
                'src': ct['src'],
                'dst': ct['dst'],
                'sport': ct.get('sport'),
                'dport': ct.get('dport'),
            })

    # ---- summary ----
    summary = {
        'total_flows': len(flows),
        'accepted_flows': sum(1 for f in flows if f['verdict'] == 'accept'),
        'dropped_flows': sum(1 for f in flows if f['verdict'] == 'drop'),
        'snat_flows': sum(1 for f in flows if f['nat_type'] == 'snat'),
        'dnat_flows': sum(1 for f in flows if f['nat_type'] == 'dnat'),
        'policy_violations': len(violations),
        'stale_rules': len(stale_rules),
        'conntrack_anomalies': len(anomalies),
    }

    report = {
        'flows': flows,
        'policy_violations': violations,
        'stale_rules': stale_rules,
        'conntrack_anomalies': anomalies,
        'summary': summary,
    }

    with open('/app/audit_report.json', 'w') as f:
        json.dump(report, f, indent=2)


if __name__ == '__main__':
    main()
