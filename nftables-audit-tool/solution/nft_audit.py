#!/usr/bin/env python3
"""
nftables Security Audit Tool

Parses nftables rulesets and produces security audit reports including
structural analysis, security posture assessment, packet fate evaluation,
and anomaly detection.
"""

import json
import sys
import re
import os
import ipaddress
from typing import Optional, List, Dict, Any, Tuple, Set


# ====================== Data Model ======================

class NftRule:
    __slots__ = ('raw', 'matches', 'verdict', 'verdict_target')

    def __init__(self, raw: str, matches: list, verdict: Optional[str],
                 verdict_target: Optional[str]):
        self.raw = raw
        self.matches = matches
        self.verdict = verdict
        self.verdict_target = verdict_target


class NftChain:
    __slots__ = ('name', 'table_name', 'family', 'is_base', 'chain_type',
                 'hook', 'priority', 'policy', 'rules')

    def __init__(self, name, table_name, family, is_base, chain_type,
                 hook, priority, policy, rules):
        self.name = name
        self.table_name = table_name
        self.family = family
        self.is_base = is_base
        self.chain_type = chain_type
        self.hook = hook
        self.priority = priority
        self.policy = policy
        self.rules = rules


class NftSet:
    __slots__ = ('name', 'table_name', 'family', 'set_type', 'flags', 'elements')

    def __init__(self, name, table_name, family, set_type, flags, elements):
        self.name = name
        self.table_name = table_name
        self.family = family
        self.set_type = set_type
        self.flags = flags
        self.elements = elements


class NftTable:
    __slots__ = ('name', 'family', 'chains', 'sets')

    def __init__(self, name, family, chains=None, sets=None):
        self.name = name
        self.family = family
        self.chains = chains or {}
        self.sets = sets or {}


# ====================== Constants ======================

PRIORITY_MAP = {
    'raw': -300,
    'mangle': -150,
    'dstnat': -100,
    'filter': 0,
    'security': 50,
    'srcnat': 100,
}

VALID_CT_STATES = {'new', 'established', 'related', 'invalid', 'untracked'}


# ====================== Parser ======================

class NftParser:
    """Parses nftables configuration text into structured table objects."""

    def parse(self, text: str) -> Dict[str, NftTable]:
        tables = {}
        lines = text.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            m = re.match(r'table\s+(\w+)\s+(\w+)\s*\{', line)
            if m:
                family, name = m.group(1), m.group(2)
                table, i = self._parse_table(lines, i + 1, name, family)
                tables[f"{family}:{name}"] = table
            else:
                i += 1
        return tables

    def _parse_table(self, lines, start, name, family):
        table = NftTable(name=name, family=family)
        i = start
        while i < len(lines):
            line = lines[i].strip()
            if line == '}':
                return table, i + 1

            m = re.match(r'set\s+(\w+)\s*\{', line)
            if m:
                nft_set, i = self._parse_set(lines, i + 1, m.group(1),
                                             name, family)
                table.sets[nft_set.name] = nft_set
                continue

            m = re.match(r'chain\s+([\w-]+)\s*\{', line)
            if m:
                chain, i = self._parse_chain(lines, i + 1, m.group(1),
                                             name, family)
                table.chains[chain.name] = chain
                continue

            i += 1
        return table, i

    def _parse_set(self, lines, start, set_name, table_name, family):
        set_type = ''
        flags = []
        elements = []
        i = start
        while i < len(lines):
            line = lines[i].strip()
            if line == '}':
                return NftSet(set_name, table_name, family, set_type,
                              flags, elements), i + 1
            if line.startswith('type '):
                set_type = line.split()[1]
            elif line.startswith('flags '):
                flags = [f.strip() for f in line[6:].split(',')]
            elif 'elements' in line:
                m = re.search(r'\{([^}]*)\}', line)
                if m:
                    elements = [e.strip() for e in m.group(1).split(',')
                                if e.strip()]
            i += 1
        return NftSet(set_name, table_name, family, set_type,
                      flags, elements), i

    def _parse_chain(self, lines, start, chain_name, table_name, family):
        is_base = False
        chain_type = None
        hook = None
        priority = None
        policy = None
        rules = []
        i = start
        checked_header = False

        while i < len(lines):
            line = lines[i].strip()
            if line == '}':
                return NftChain(chain_name, table_name, family, is_base,
                                chain_type, hook, priority, policy,
                                rules), i + 1

            if not checked_header and line.startswith('type '):
                checked_header = True
                m = re.match(
                    r'type\s+(\w+)\s+hook\s+(\w+)\s+priority\s+([\w-]+)\s*;'
                    r'(?:\s*policy\s+(\w+)\s*;)?',
                    line
                )
                if m:
                    is_base = True
                    chain_type = m.group(1)
                    hook = m.group(2)
                    pri_str = m.group(3)
                    if pri_str in PRIORITY_MAP:
                        priority = PRIORITY_MAP[pri_str]
                    else:
                        try:
                            priority = int(pri_str)
                        except ValueError:
                            priority = 0
                    policy = m.group(4) if m.group(4) else 'accept'
                    i += 1
                    continue

            checked_header = True

            if not line or line.startswith('#'):
                i += 1
                continue

            rule = self._parse_rule(line)
            if rule:
                rules.append(rule)
            i += 1

        return NftChain(chain_name, table_name, family, is_base,
                        chain_type, hook, priority, policy, rules), i

    def _parse_rule(self, text: str) -> Optional[NftRule]:
        text = re.sub(r'\s+comment\s+"[^"]*"\s*$', '', text)
        text = text.strip()
        if not text:
            return None

        matches = []

        # iifname (check before iif)
        m = re.search(r'\biifname\s+"?(\w+)"?', text)
        if m:
            matches.append(('iifname', m.group(1)))

        # oifname
        m = re.search(r'\boifname\s+"?(\w+)"?', text)
        if m:
            matches.append(('oifname', m.group(1)))

        # iif (only if iifname not present)
        if not re.search(r'\biifname\b', text):
            m = re.search(r'\biif\b\s+(\w+)', text)
            if m:
                matches.append(('iif', m.group(1)))

        # ct state (set form)
        m = re.search(r'\bct\s+state\s+\{([^}]+)\}', text)
        if m:
            states = [s.strip() for s in m.group(1).split(',')]
            matches.append(('ct_state', states))
        else:
            m = re.search(r'\bct\s+state\s+(\w+)', text)
            if m and m.group(1) in VALID_CT_STATES:
                matches.append(('ct_state', [m.group(1)]))

        # meta l4proto (set form)
        m = re.search(r'\bmeta\s+l4proto\s+\{([^}]+)\}', text)
        if m:
            protos = [p.strip() for p in m.group(1).split(',')]
            matches.append(('l4proto', protos))
        else:
            m = re.search(r'\bmeta\s+l4proto\s+([\w-]+)', text)
            if m:
                matches.append(('l4proto', [m.group(1)]))

        # ip saddr (set reference or CIDR)
        m = re.search(r'\bip\s+saddr\s+@(\w+)', text)
        if m:
            matches.append(('ip_saddr_set', m.group(1)))
        else:
            m = re.search(r'\bip\s+saddr\s+([\d./]+)', text)
            if m:
                matches.append(('ip_saddr', m.group(1)))

        # ip daddr
        m = re.search(r'\bip\s+daddr\s+@(\w+)', text)
        if m:
            matches.append(('ip_daddr_set', m.group(1)))
        else:
            m = re.search(r'\bip\s+daddr\s+([\d./]+)', text)
            if m:
                matches.append(('ip_daddr', m.group(1)))

        # tcp dport (set form)
        m = re.search(r'\btcp\s+dport\s+\{([^}]+)\}', text)
        if m:
            ports = [int(p.strip()) for p in m.group(1).split(',')]
            matches.append(('tcp_dport', ports))
        else:
            m = re.search(r'\btcp\s+dport\s+(\d+)', text)
            if m:
                matches.append(('tcp_dport', [int(m.group(1))]))

        # udp dport (set form)
        m = re.search(r'\budp\s+dport\s+\{([^}]+)\}', text)
        if m:
            ports = [int(p.strip()) for p in m.group(1).split(',')]
            matches.append(('udp_dport', ports))
        else:
            m = re.search(r'\budp\s+dport\s+(\d+)', text)
            if m:
                matches.append(('udp_dport', [int(m.group(1))]))

        # limit rate
        m = re.search(r'\blimit\s+rate\s+(?:over\s+)?(\d+/\w+)', text)
        if m:
            matches.append(('limit', m.group(1)))

        # Determine verdict
        verdict = None
        verdict_target = None

        m = re.search(r'\bjump\s+([\w-]+)', text)
        if m:
            verdict = 'jump'
            verdict_target = m.group(1)
        else:
            m = re.search(r'\bgoto\s+([\w-]+)', text)
            if m:
                verdict = 'goto'
                verdict_target = m.group(1)
            elif re.search(r'\bdnat\s+to\s+([\d.:]+)', text):
                m2 = re.search(r'\bdnat\s+to\s+([\d.:]+)', text)
                verdict = 'dnat'
                verdict_target = m2.group(1)
            elif re.search(r'\bmasquerade\b', text):
                verdict = 'masquerade'
            elif re.search(r'\baccept\b', text):
                verdict = 'accept'
            elif re.search(r'\bdrop\b', text):
                verdict = 'drop'
            elif re.search(r'\breject\b', text):
                verdict = 'reject'
            elif re.search(r'\breturn\b', text):
                verdict = 'return'

        return NftRule(raw=text, matches=matches, verdict=verdict,
                       verdict_target=verdict_target)


# ====================== Packet Evaluator ======================

class PacketEvaluator:
    """Evaluates packet fate through an nftables ruleset."""

    def __init__(self, tables: Dict[str, NftTable]):
        self.tables = tables

    def evaluate(self, packet: dict) -> str:
        hook = packet.get('hook', 'input')

        # Find all base chains for this hook, sorted by priority
        base_chains = []
        for table in self.tables.values():
            for chain in table.chains.values():
                if chain.is_base and chain.hook == hook:
                    base_chains.append((table, chain))

        base_chains.sort(key=lambda tc: tc[1].priority)

        for table, chain in base_chains:
            result = self._evaluate_chain(table, chain, packet)
            if result in ('accept', 'drop', 'reject'):
                return result

        return 'accept'

    def _evaluate_chain(self, table: NftTable, chain: NftChain,
                        packet: dict) -> Optional[str]:
        for rule in chain.rules:
            if self._matches_rule(table, rule, packet):
                v = rule.verdict
                if v in ('accept', 'drop', 'reject'):
                    return v
                elif v == 'jump':
                    target = table.chains.get(rule.verdict_target)
                    if target:
                        result = self._evaluate_chain(table, target, packet)
                        if result in ('accept', 'drop', 'reject'):
                            return result
                        # target returned None: continue to next rule
                elif v == 'goto':
                    target = table.chains.get(rule.verdict_target)
                    if target:
                        result = self._evaluate_chain(table, target, packet)
                        if result:
                            return result
                        # goto: don't continue this chain
                        if chain.is_base:
                            return chain.policy
                        return None
                elif v == 'return':
                    return None
                elif v in ('masquerade', 'dnat'):
                    return 'accept'
                # No verdict (counter only, log, etc): continue

        # End of chain
        if chain.is_base:
            return chain.policy
        return None

    def _matches_rule(self, table: NftTable, rule: NftRule,
                      packet: dict) -> bool:
        for match_type, match_value in rule.matches:
            if not self._check_match(table, match_type, match_value, packet):
                return False
        return True

    def _check_match(self, table: NftTable, match_type: str,
                     match_value: Any, packet: dict) -> bool:
        if match_type == 'iif':
            v = packet.get('iif') or packet.get('iifname')
            return v == match_value
        elif match_type == 'iifname':
            return packet.get('iifname') == match_value
        elif match_type == 'oifname':
            return packet.get('oifname') == match_value
        elif match_type == 'ct_state':
            return packet.get('ct_state') in match_value
        elif match_type == 'l4proto':
            return packet.get('protocol') in match_value
        elif match_type == 'ip_saddr_set':
            return self._ip_in_set(packet.get('src_ip', ''),
                                   match_value, table)
        elif match_type == 'ip_saddr':
            return self._ip_matches_cidr(packet.get('src_ip', ''),
                                         match_value)
        elif match_type == 'ip_daddr_set':
            return self._ip_in_set(packet.get('dst_ip', ''),
                                   match_value, table)
        elif match_type == 'ip_daddr':
            return self._ip_matches_cidr(packet.get('dst_ip', ''),
                                         match_value)
        elif match_type == 'tcp_dport':
            if packet.get('protocol') != 'tcp':
                return False
            return packet.get('dst_port') in match_value
        elif match_type == 'udp_dport':
            if packet.get('protocol') != 'udp':
                return False
            return packet.get('dst_port') in match_value
        elif match_type == 'limit':
            return True  # Static analysis: assume limit not exceeded
        return True

    def _ip_matches_cidr(self, ip_str: str, cidr_str: str) -> bool:
        try:
            ip = ipaddress.ip_address(ip_str)
            network = ipaddress.ip_network(cidr_str, strict=False)
            return ip in network
        except ValueError:
            return False

    def _ip_in_set(self, ip_str: str, set_name: str,
                   table: NftTable) -> bool:
        nft_set = table.sets.get(set_name)
        if not nft_set:
            return False
        for elem in nft_set.elements:
            if self._ip_matches_cidr(ip_str, elem):
                return True
        return False


# ====================== Audit Analyzer ======================

class AuditAnalyzer:
    """Produces security audit reports from parsed nftables tables."""

    def __init__(self, tables: Dict[str, NftTable]):
        self.tables = tables
        self.evaluator = PacketEvaluator(tables)

    def analyze(self, config_name: str, queries: dict) -> dict:
        result = {}

        # Structural analysis
        result['tables'] = self._get_tables()
        result['base_chains'] = self._get_base_chains()
        result['named_sets'] = self._get_named_sets()
        result['jump_graph'] = self._get_jump_graph()

        # Security analysis
        open_tcp, open_udp = self._get_open_ports()
        result['open_tcp_ports'] = open_tcp
        result['open_udp_ports'] = open_udp
        result['allows_loopback'] = self._check_allows_loopback()
        result['allows_icmp'] = self._check_allows_icmp()
        result['uses_connection_tracking'] = self._check_uses_ct()
        result['has_rate_limiting'] = self._check_has_rate_limiting()
        result['rate_limited_ports'] = self._get_rate_limited_ports()
        result['has_nat'] = self._check_has_nat()
        result['has_masquerade'] = self._check_has_masquerade()

        # Packet verdict tests
        packet_tests = queries.get('packet_tests', {}).get(config_name, [])
        verdicts = {}
        for test in packet_tests:
            packet = {k: v for k, v in test.items()
                      if k not in ('id', 'description', 'expected_verdict')}
            verdict = self.evaluator.evaluate(packet)
            verdicts[test['id']] = verdict
        result['packet_verdicts'] = verdicts

        # Anomaly detection
        result['anomalies'] = self._get_anomalies()

        return result

    # -- Structural --

    def _get_tables(self) -> list:
        tables = []
        for table in self.tables.values():
            tables.append({'name': table.name, 'family': table.family})
        return sorted(tables, key=lambda t: t['name'])

    def _get_base_chains(self) -> dict:
        chains = {}
        for table in self.tables.values():
            for chain in table.chains.values():
                if chain.is_base:
                    chains[chain.name] = {
                        'table': table.name,
                        'family': table.family,
                        'hook': chain.hook,
                        'priority': chain.priority,
                        'policy': chain.policy,
                    }
        return chains

    def _get_named_sets(self) -> dict:
        sets = {}
        for table in self.tables.values():
            for nft_set in table.sets.values():
                sets[nft_set.name] = {
                    'table': table.name,
                    'family': table.family,
                    'type': nft_set.set_type,
                    'flags': nft_set.flags,
                    'elements': nft_set.elements,
                }
        return sets

    def _get_jump_graph(self) -> dict:
        graph = {}
        for table in self.tables.values():
            for chain in table.chains.values():
                targets = set()
                for rule in chain.rules:
                    if rule.verdict in ('jump', 'goto') and rule.verdict_target:
                        targets.add(rule.verdict_target)
                if targets:
                    graph[chain.name] = sorted(targets)
        return graph

    # -- Security --

    def _get_open_ports(self) -> Tuple[list, list]:
        tcp_ports: Set[int] = set()
        udp_ports: Set[int] = set()
        for table in self.tables.values():
            for chain in table.chains.values():
                if chain.is_base and chain.hook == 'input':
                    self._collect_open_ports(chain, table, tcp_ports,
                                             udp_ports, False)
        return sorted(tcp_ports), sorted(udp_ports)

    def _collect_open_ports(self, chain: NftChain, table: NftTable,
                            tcp_ports: set, udp_ports: set,
                            ip_restricted: bool):
        for rule in chain.rules:
            has_ip = any(mt in ('ip_saddr', 'ip_saddr_set')
                         for mt, _ in rule.matches)
            restricted = ip_restricted or has_ip

            if rule.verdict == 'accept' and not restricted:
                for mt, mv in rule.matches:
                    if mt == 'tcp_dport':
                        tcp_ports.update(mv)
                    elif mt == 'udp_dport':
                        udp_ports.update(mv)

            if rule.verdict in ('jump', 'goto'):
                target = table.chains.get(rule.verdict_target)
                if target:
                    self._collect_open_ports(target, table, tcp_ports,
                                             udp_ports, restricted)

            # Unconditional terminal verdict: remaining rules are shadowed
            if not rule.matches and rule.verdict in ('accept', 'drop', 'reject'):
                break

    def _check_allows_loopback(self) -> bool:
        for table in self.tables.values():
            for chain in table.chains.values():
                for rule in chain.rules:
                    if rule.verdict == 'accept':
                        for mt, mv in rule.matches:
                            if mt == 'iif' and mv == 'lo':
                                return True
        return False

    def _check_allows_icmp(self) -> bool:
        for table in self.tables.values():
            for chain in table.chains.values():
                for rule in chain.rules:
                    if rule.verdict == 'accept':
                        for mt, mv in rule.matches:
                            if mt == 'l4proto':
                                if 'icmp' in mv or 'ipv6-icmp' in mv:
                                    return True
        return False

    def _check_uses_ct(self) -> bool:
        for table in self.tables.values():
            for chain in table.chains.values():
                for rule in chain.rules:
                    for mt, _ in rule.matches:
                        if mt == 'ct_state':
                            return True
        return False

    def _check_has_rate_limiting(self) -> bool:
        for table in self.tables.values():
            for chain in table.chains.values():
                for rule in chain.rules:
                    for mt, _ in rule.matches:
                        if mt == 'limit':
                            return True
        return False

    def _get_rate_limited_ports(self) -> dict:
        result: Dict[str, Dict[str, str]] = {}
        for table in self.tables.values():
            for chain in table.chains.values():
                if chain.is_base:
                    self._find_rate_limits(chain, table, result,
                                          {'tcp': [], 'udp': []})
        return result

    def _find_rate_limits(self, chain: NftChain, table: NftTable,
                          result: dict, parent_ports: dict):
        for rule in chain.rules:
            rule_tcp = []
            rule_udp = []
            rate = None

            for mt, mv in rule.matches:
                if mt == 'tcp_dport':
                    rule_tcp = mv
                elif mt == 'udp_dport':
                    rule_udp = mv
                elif mt == 'limit':
                    rate = mv

            eff_tcp = rule_tcp if rule_tcp else parent_ports.get('tcp', [])
            eff_udp = rule_udp if rule_udp else parent_ports.get('udp', [])

            if rate and rule.verdict == 'accept':
                for port in eff_tcp:
                    result.setdefault('tcp', {})[str(port)] = rate
                for port in eff_udp:
                    result.setdefault('udp', {})[str(port)] = rate

            if rule.verdict in ('jump', 'goto'):
                target = table.chains.get(rule.verdict_target)
                if target:
                    new_ports = {
                        'tcp': rule_tcp if rule_tcp else parent_ports.get('tcp', []),
                        'udp': rule_udp if rule_udp else parent_ports.get('udp', []),
                    }
                    self._find_rate_limits(target, table, result, new_ports)

            # Unconditional terminal verdict: remaining rules are shadowed
            if not rule.matches and rule.verdict in ('accept', 'drop', 'reject'):
                break

    def _check_has_nat(self) -> bool:
        for table in self.tables.values():
            for chain in table.chains.values():
                if chain.is_base and chain.chain_type == 'nat':
                    return True
        return False

    def _check_has_masquerade(self) -> bool:
        for table in self.tables.values():
            for chain in table.chains.values():
                for rule in chain.rules:
                    if rule.verdict == 'masquerade':
                        return True
        return False

    # -- Anomaly Detection --

    def _get_anomalies(self) -> dict:
        return {
            'unreachable_chains': sorted(self._find_unreachable_chains()),
            'shadowed_rules': self._find_shadowed_rules(),
        }

    def _find_unreachable_chains(self) -> List[str]:
        all_non_base: Set[str] = set()
        all_targets: Set[str] = set()

        for table in self.tables.values():
            for chain in table.chains.values():
                if not chain.is_base:
                    all_non_base.add(chain.name)
                for rule in chain.rules:
                    if rule.verdict in ('jump', 'goto') and rule.verdict_target:
                        all_targets.add(rule.verdict_target)

        return list(all_non_base - all_targets)

    def _find_shadowed_rules(self) -> List[dict]:
        shadowed = []
        for table in self.tables.values():
            for chain in table.chains.values():
                seen_unconditional = False
                for i, rule in enumerate(chain.rules):
                    if seen_unconditional:
                        shadowed.append({
                            'table': table.name,
                            'chain': chain.name,
                            'position': i,
                        })
                    elif (not rule.matches and
                          rule.verdict in ('accept', 'drop', 'reject')):
                        seen_unconditional = True
        return shadowed


# ====================== Main ======================

def main():
    if len(sys.argv) != 4:
        print("Usage: nft_audit.py <config_path> <queries_path> <output_path>",
              file=sys.stderr)
        sys.exit(1)

    config_path = sys.argv[1]
    queries_path = sys.argv[2]
    output_path = sys.argv[3]

    with open(config_path) as f:
        config_text = f.read()

    with open(queries_path) as f:
        queries = json.load(f)

    parser = NftParser()
    tables = parser.parse(config_text)

    config_name = os.path.splitext(os.path.basename(config_path))[0]

    analyzer = AuditAnalyzer(tables)
    result = analyzer.analyze(config_name, queries)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)


if __name__ == '__main__':
    main()
