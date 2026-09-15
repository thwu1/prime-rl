#!/usr/bin/env python3
"""
Linux netfilter packet flow simulator with conntrack modeling.
Parses iptables-save and sysctl.conf formats.
"""

import json
import sys
import ipaddress
from pathlib import Path


# ── Input parsers ──


def parse_iptables_save(filepath):
    """Parse iptables-save output into internal rules representation."""
    tables = {}
    current_table = None
    rule_counter = 0

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if line.startswith('*'):
                current_table = line[1:]
                tables[current_table] = {}
                continue

            if line == 'COMMIT':
                current_table = None
                continue

            if line.startswith(':'):
                parts = line.split()
                chain_name = parts[0][1:]
                policy = parts[1]
                tables[current_table][chain_name] = {
                    'policy': policy,
                    'rules': []
                }
                continue

            if line.startswith('-A') and current_table is not None:
                rule_counter += 1
                chain, rule = _parse_rule_line(line, rule_counter)
                if chain in tables[current_table]:
                    tables[current_table][chain]['rules'].append(rule)
                continue

    return {'tables': tables}


def _parse_rule_line(line, rule_id):
    """Parse a single -A rule line from iptables-save."""
    tokens = line.split()
    chain = tokens[1]
    rule = {'id': rule_id, 'match': {}, 'target': 'ACCEPT'}

    i = 2
    while i < len(tokens):
        tok = tokens[i]
        if tok == '-p':
            rule['match']['protocol'] = tokens[i + 1]
            i += 2
        elif tok == '-m':
            # Skip module load (-m tcp, -m udp, -m conntrack, etc.)
            i += 2
        elif tok == '--dport':
            rule['match']['dst_port'] = int(tokens[i + 1])
            i += 2
        elif tok == '--sport':
            rule['match']['src_port'] = int(tokens[i + 1])
            i += 2
        elif tok == '-s':
            rule['match']['src_ip'] = tokens[i + 1]
            i += 2
        elif tok == '-d':
            rule['match']['dst_ip'] = tokens[i + 1]
            i += 2
        elif tok == '--ctstate':
            rule['match']['ctstate'] = tokens[i + 1].split(',')
            i += 2
        elif tok == '--tcp-flags':
            mask = tokens[i + 1].split(',')
            flag_set = tokens[i + 2].split(',')
            rule['match']['tcp_flags'] = {'mask': mask, 'set': flag_set}
            i += 3
        elif tok == '-j':
            rule['target'] = tokens[i + 1]
            i += 2
        else:
            i += 1

    return chain, rule


def parse_sysctl(filepath):
    """Parse sysctl.conf format for conntrack tunables."""
    settings = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, _, value = line.partition('=')
                settings[key.strip()] = value.strip()

    return {
        'max_entries': int(settings.get('net.netfilter.nf_conntrack_max', 65536)),
        'tcp_loose': int(settings.get('net.netfilter.nf_conntrack_tcp_loose', 1)) != 0,
    }


def load_config(config_dir):
    config_dir = Path(config_dir)
    rules = parse_iptables_save(config_dir / 'iptables.rules')
    conntrack = parse_sysctl(config_dir / 'sysctl.conf')
    with open(config_dir / 'packets.json') as f:
        packets = json.load(f)
    return rules, conntrack, packets


# ── Matching helpers ──


def ip_in_cidr(addr, cidr):
    if '/' in cidr:
        return ipaddress.ip_address(addr) in ipaddress.ip_network(cidr, strict=False)
    return addr == cidr


def tcp_flags_match(packet_flags, rule_flags):
    mask = set(rule_flags['mask'])
    required = set(rule_flags['set'])
    actual = set(packet_flags) if packet_flags else set()
    return (actual & mask) == required


def rule_matches(rule, packet, conntrack_state):
    match = rule.get('match', {})

    if 'protocol' in match and packet['protocol'] != match['protocol']:
        return False
    if 'dst_port' in match and packet['dst_port'] != match['dst_port']:
        return False
    if 'src_port' in match and packet['src_port'] != match['src_port']:
        return False
    if 'src_ip' in match and not ip_in_cidr(packet['src_ip'], match['src_ip']):
        return False
    if 'dst_ip' in match and not ip_in_cidr(packet['dst_ip'], match['dst_ip']):
        return False
    if 'ctstate' in match:
        if conntrack_state not in match['ctstate']:
            return False
    if 'tcp_flags' in match:
        if packet['protocol'] != 'tcp':
            return False
        if not tcp_flags_match(packet.get('tcp_flags', []), match['tcp_flags']):
            return False
    return True


# ── Chain evaluation ──


def evaluate_chain(rules_config, table_name, chain_name, packet, conntrack_state, counters):
    table = rules_config['tables'].get(table_name, {})
    chain = table.get(chain_name, {})
    rules = chain.get('rules', [])
    policy = chain.get('policy', 'ACCEPT')

    for rule in rules:
        if rule_matches(rule, packet, conntrack_state):
            rid = rule['id']
            counters[rid]['packets'] += 1
            counters[rid]['bytes'] += packet['size_bytes']
            return rule['target'], rid

    return policy, None


# ── Conntrack table lookup ──


def conntrack_lookup(table, packet):
    fwd = (packet['protocol'], packet['src_ip'], packet['src_port'],
           packet['dst_ip'], packet['dst_port'])
    rev = (packet['protocol'], packet['dst_ip'], packet['dst_port'],
           packet['src_ip'], packet['src_port'])
    return fwd in table or rev in table


# ── Main simulation ──


def simulate(rules_config, conntrack_config, packets):
    max_entries = conntrack_config['max_entries']
    tcp_loose = conntrack_config.get('tcp_loose', True)

    ct_table = set()
    counters = {}
    for table_data in rules_config['tables'].values():
        for chain_data in table_data.values():
            for rule in chain_data.get('rules', []):
                counters[rule['id']] = {'packets': 0, 'bytes': 0}

    overflow_drops = 0
    unconfirmed_drops = 0
    results = []

    for pkt in packets:
        pid = pkt['id']
        matched = []
        ct_state = None
        notrack = False

        # Stage: raw PREROUTING
        target, rid = evaluate_chain(
            rules_config, 'raw', 'PREROUTING', pkt, ct_state, counters
        )
        if rid is not None:
            matched.append(rid)

        if target == 'DROP':
            results.append({
                'packet_id': pid, 'verdict': 'DROP',
                'drop_layer': 'raw_PREROUTING',
                'conntrack_state': None, 'matched_rules': matched,
            })
            continue

        if target == 'NOTRACK':
            notrack = True
            ct_state = 'UNTRACKED'

        # Stage: connection tracking
        if not notrack:
            if conntrack_lookup(ct_table, pkt):
                ct_state = 'ESTABLISHED'
            else:
                is_new = True

                if pkt['protocol'] == 'tcp' and not tcp_loose:
                    flags = set(pkt.get('tcp_flags', []))
                    if 'SYN' not in flags:
                        ct_state = 'INVALID'
                        is_new = False

                if is_new:
                    if len(ct_table) >= max_entries:
                        overflow_drops += 1
                        results.append({
                            'packet_id': pid, 'verdict': 'DROP',
                            'drop_layer': 'conntrack_overflow',
                            'conntrack_state': None,
                            'matched_rules': matched,
                        })
                        continue
                    else:
                        ct_state = 'NEW'

        # Stage: mangle PREROUTING
        target, rid = evaluate_chain(
            rules_config, 'mangle', 'PREROUTING', pkt, ct_state, counters
        )
        if rid is not None:
            matched.append(rid)

        if target == 'DROP':
            if ct_state == 'NEW':
                unconfirmed_drops += 1
            results.append({
                'packet_id': pid, 'verdict': 'DROP',
                'drop_layer': 'mangle_PREROUTING',
                'conntrack_state': ct_state, 'matched_rules': matched,
            })
            continue

        # Stage: filter INPUT
        target, rid = evaluate_chain(
            rules_config, 'filter', 'INPUT', pkt, ct_state, counters
        )
        if rid is not None:
            matched.append(rid)

        if target == 'DROP':
            if ct_state == 'NEW':
                unconfirmed_drops += 1
            results.append({
                'packet_id': pid, 'verdict': 'DROP',
                'drop_layer': 'filter_INPUT',
                'conntrack_state': ct_state, 'matched_rules': matched,
            })
            continue

        # Packet accepted — confirm conntrack entry
        if ct_state == 'NEW':
            entry = (pkt['protocol'], pkt['src_ip'], pkt['src_port'],
                     pkt['dst_ip'], pkt['dst_port'])
            ct_table.add(entry)

        results.append({
            'packet_id': pid, 'verdict': 'ACCEPT',
            'drop_layer': None, 'conntrack_state': ct_state,
            'matched_rules': matched,
        })

    return {
        'packet_results': results,
        'rule_counters': {
            str(k): v for k, v in sorted(counters.items())
        },
        'conntrack_stats': {
            'confirmed_entries': len(ct_table),
            'overflow_drops': overflow_drops,
            'unconfirmed_drops': unconfirmed_drops,
        },
    }


def main():
    if len(sys.argv) != 3:
        print(f'Usage: {sys.argv[0]} <config_dir> <output_file>', file=sys.stderr)
        sys.exit(1)

    config_dir = sys.argv[1]
    output_file = sys.argv[2]

    rules, conntrack, packets = load_config(config_dir)
    output = simulate(rules, conntrack, packets)

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)


if __name__ == '__main__':
    main()
