#!/usr/bin/env python3
"""BGP configuration and diagnosis verification tests.

Parses FRR configuration files and verifies that all peering bugs are fixed,
all routing policies are correctly implemented, and the structured diagnosis
document is complete and accurate.

"""

import pytest
import re
import os
import json

CONFIG_DIR = "/app/configs"


def read_config(router):
    """Read a router's configuration file."""
    path = os.path.join(CONFIG_DIR, f"{router}.conf")
    with open(path) as f:
        return f.read()


def find_neighbor_lines(config, neighbor_ip):
    """Find all config lines referencing a specific neighbor."""
    escaped = re.escape(neighbor_ip)
    return [l.strip() for l in config.splitlines()
            if re.search(rf'\bneighbor\s+{escaped}\b', l)]


def parse_route_maps(config):
    """Parse route-map definitions from FRR config text.
    Returns: {name: [{'action': str, 'seq': int, 'match': [str], 'set': [str]}, ...]}
    """
    route_maps = {}
    current_rm = None

    for line in config.splitlines():
        stripped = line.strip()

        m = re.match(r'^route-map\s+(\S+)\s+(permit|deny)\s+(\d+)', stripped)
        if m:
            name = m.group(1)
            current_rm = {
                'action': m.group(2),
                'seq': int(m.group(3)),
                'match': [],
                'set': [],
            }
            route_maps.setdefault(name, []).append(current_rm)
            continue

        if current_rm is None:
            continue

        if stripped.startswith('match '):
            current_rm['match'].append(stripped)
        elif stripped.startswith('set '):
            current_rm['set'].append(stripped)
        elif stripped == '!' or stripped == '' or stripped.startswith(
            ('router ', 'ip ', 'hostname', 'address-family', 'exit',
             'neighbor', 'no ', 'bgp ', 'network ')
        ):
            current_rm = None

    for name in route_maps:
        route_maps[name].sort(key=lambda x: x['seq'])

    return route_maps


def parse_prefix_lists(config):
    """Parse prefix-list definitions.
    Returns: {name: [{'seq': int, 'action': str, 'prefix': str}, ...]}
    """
    prefix_lists = {}

    for line in config.splitlines():
        stripped = line.strip()
        m = re.match(
            r'^ip prefix-list\s+(\S+)\s+(?:seq\s+(\d+)\s+)?(permit|deny)\s+(\S+)',
            stripped
        )
        if m:
            name = m.group(1)
            seq = int(m.group(2)) if m.group(2) else 0
            action = m.group(3)
            prefix = m.group(4)
            prefix_lists.setdefault(name, []).append({
                'seq': seq,
                'action': action,
                'prefix': prefix,
            })

    return prefix_lists


def get_inbound_route_map(config, neighbor_ip):
    """Find the name of the inbound route-map applied to a neighbor."""
    escaped = re.escape(neighbor_ip)
    for line in config.splitlines():
        stripped = line.strip()
        m = re.match(
            rf'neighbor\s+{escaped}\s+route-map\s+(\S+)\s+in\b',
            stripped
        )
        if m:
            return m.group(1)
    return None


def get_outbound_route_map(config, neighbor_ip):
    """Find the name of the outbound route-map applied to a neighbor."""
    escaped = re.escape(neighbor_ip)
    for line in config.splitlines():
        stripped = line.strip()
        m = re.match(
            rf'neighbor\s+{escaped}\s+route-map\s+(\S+)\s+out\b',
            stripped
        )
        if m:
            return m.group(1)
    return None


def route_map_denies_prefix(config, rm_name, target_prefix):
    """Check if a route-map would deny a specific prefix.
    Traces through route-map clauses in sequence order.
    Returns True if denied, False if permitted, None if route-map not found.
    """
    route_maps = parse_route_maps(config)
    prefix_lists = parse_prefix_lists(config)

    clauses = route_maps.get(rm_name, [])
    if not clauses:
        return None

    for clause in clauses:
        if not clause['match']:
            # No match conditions = matches everything
            return clause['action'] == 'deny'

        for match_line in clause['match']:
            m = re.match(r'match ip address prefix-list (\S+)', match_line)
            if m:
                pl_name = m.group(1)
                pl_entries = prefix_lists.get(pl_name, [])
                for entry in pl_entries:
                    if entry['prefix'] == target_prefix and entry['action'] == 'permit':
                        return clause['action'] == 'deny'

    # No clause explicitly matched; route-map has implicit deny
    return True


def route_map_has_elevated_localpref(config, rm_name, target_prefix, min_lp=101):
    """Check if a route-map sets local-preference >= min_lp for a prefix."""
    route_maps = parse_route_maps(config)
    prefix_lists = parse_prefix_lists(config)

    clauses = route_maps.get(rm_name, [])

    for clause in clauses:
        if clause['action'] == 'deny':
            for match_line in clause['match']:
                m = re.match(r'match ip address prefix-list (\S+)', match_line)
                if m:
                    for entry in prefix_lists.get(m.group(1), []):
                        if entry['prefix'] == target_prefix and entry['action'] == 'permit':
                            return False
            continue

        matches_target = False
        for match_line in clause['match']:
            m = re.match(r'match ip address prefix-list (\S+)', match_line)
            if m:
                pl_entries = prefix_lists.get(m.group(1), [])
                for entry in pl_entries:
                    if entry['prefix'] == target_prefix and entry['action'] == 'permit':
                        matches_target = True

        if matches_target:
            for set_line in clause['set']:
                m = re.match(r'set local-preference (\d+)', set_line)
                if m and int(m.group(1)) >= min_lp:
                    return True

    return False


# ====================================================================
# Test Classes
# ====================================================================

class TestPeeringFixes:
    """Verify that all BGP peering bugs are fixed."""

    def test_r2_update_source(self):
        """r2 must have update-source lo for iBGP peer 10.255.0.3."""
        config = read_config('r2')
        neighbor_lines = find_neighbor_lines(config, '10.255.0.3')
        has_update_source = any(
            re.search(r'update-source\s+(lo|[Ll]oopback)', l)
            for l in neighbor_lines
        )
        assert has_update_source, (
            "r2 must have 'neighbor 10.255.0.3 update-source lo' for iBGP peering"
        )

    def test_r4_correct_neighbor_ip(self):
        """r4 must peer with r1 at 10.0.14.1 (not 10.0.14.3)."""
        config = read_config('r4')
        assert 'neighbor 10.0.14.3' not in config, (
            "r4 still has incorrect neighbor IP 10.0.14.3"
        )
        neighbor_lines = find_neighbor_lines(config, '10.0.14.1')
        has_remote_as = any('remote-as 65001' in l for l in neighbor_lines)
        assert has_remote_as, (
            "r4 must have 'neighbor 10.0.14.1 remote-as 65001'"
        )

    def test_r3_static_route_to_r4_loopback(self):
        """r3 must have a static route to r4's loopback for eBGP multihop."""
        config = read_config('r3')
        has_route = bool(re.search(
            r'ip route 10\.255\.0\.4(/32)?\s+10\.0\.34\.2',
            config
        ))
        assert has_route, (
            "r3 must have 'ip route 10.255.0.4/32 10.0.34.2' for eBGP multihop"
        )

    def test_r4_static_route_to_r3_loopback(self):
        """r4 must have a static route to r3's loopback for eBGP multihop."""
        config = read_config('r4')
        has_route = bool(re.search(
            r'ip route 10\.255\.0\.3(/32)?\s+10\.0\.34\.1',
            config
        ))
        assert has_route, (
            "r4 must have 'ip route 10.255.0.3/32 10.0.34.1' for eBGP multihop"
        )

    def test_r4_activate_correct_neighbor(self):
        """r4 must not activate the old incorrect neighbor IP."""
        config = read_config('r4')
        assert 'neighbor 10.0.14.3 activate' not in config, (
            "r4 still has 'neighbor 10.0.14.3 activate' for wrong IP"
        )


class TestNextHopSelf:
    """Verify r3 has next-hop-self for iBGP client."""

    def test_r3_next_hop_self(self):
        """r3 must set next-hop-self for iBGP client r2."""
        config = read_config('r3')
        neighbor_lines = find_neighbor_lines(config, '10.255.0.2')
        has_nhs = any('next-hop-self' in l for l in neighbor_lines)
        assert has_nhs, (
            "r3 must have 'neighbor 10.255.0.2 next-hop-self'"
        )


class TestASPathPrepend:
    """Verify r4 prepends AS65003 toward r3."""

    def test_r4_has_outbound_route_map_for_r3(self):
        """r4 must have an outbound route-map applied to r3."""
        config = read_config('r4')
        rm_name = get_outbound_route_map(config, '10.255.0.3')
        assert rm_name is not None, (
            "r4 must have a route-map applied outbound to neighbor 10.255.0.3"
        )

    def test_r4_prepend_count(self):
        """r4's outbound route-map must prepend AS65003 at least 3 times."""
        config = read_config('r4')
        rm_name = get_outbound_route_map(config, '10.255.0.3')
        assert rm_name is not None, "No outbound route-map found for r3"

        route_maps = parse_route_maps(config)
        clauses = route_maps.get(rm_name, [])

        max_prepend_count = 0
        for clause in clauses:
            for s in clause['set']:
                if 'as-path prepend' in s:
                    count = s.count('65003')
                    max_prepend_count = max(max_prepend_count, count)

        assert max_prepend_count >= 3, (
            f"Route-map {rm_name} must prepend AS65003 at least 3 times, "
            f"found {max_prepend_count}"
        )


class TestRoutingPolicy:
    """Verify route filtering and LOCAL_PREF on r1."""

    def test_r1_transit_peer_has_inbound_map(self):
        """r1 must have an inbound route-map on transit peer (10.0.12.2)."""
        config = read_config('r1')
        rm_name = get_inbound_route_map(config, '10.0.12.2')
        assert rm_name is not None, (
            "r1 must have a route-map applied inbound to transit peer 10.0.12.2"
        )

    def test_r1_direct_peer_has_inbound_map(self):
        """r1 must have an inbound route-map on direct peer (10.0.14.2)."""
        config = read_config('r1')
        rm_name = get_inbound_route_map(config, '10.0.14.2')
        assert rm_name is not None, (
            "r1 must have a route-map applied inbound to direct peer 10.0.14.2"
        )

    def test_r1_filters_10_4_3_from_transit(self):
        """10.4.3.0/24 must be denied by r1's transit peer inbound route-map."""
        config = read_config('r1')
        rm_name = get_inbound_route_map(config, '10.0.12.2')
        assert rm_name is not None

        denied = route_map_denies_prefix(config, rm_name, '10.4.3.0/24')
        assert denied, (
            f"Route-map {rm_name} on r1 must deny prefix 10.4.3.0/24"
        )

    def test_r1_filters_10_4_3_from_direct(self):
        """10.4.3.0/24 must be denied by r1's direct peer inbound route-map."""
        config = read_config('r1')
        rm_name = get_inbound_route_map(config, '10.0.14.2')
        assert rm_name is not None

        denied = route_map_denies_prefix(config, rm_name, '10.4.3.0/24')
        assert denied, (
            f"Route-map {rm_name} on r1 must deny prefix 10.4.3.0/24"
        )

    def test_r1_elevated_local_pref_for_transit_10_4_1(self):
        """r1's transit inbound route-map must set elevated LOCAL_PREF for 10.4.1.0/24."""
        config = read_config('r1')
        rm_name = get_inbound_route_map(config, '10.0.12.2')
        assert rm_name is not None

        has_elevated = route_map_has_elevated_localpref(
            config, rm_name, '10.4.1.0/24', min_lp=101
        )
        assert has_elevated, (
            f"Route-map {rm_name} on r1 must set local-preference above default (100) "
            f"for prefix 10.4.1.0/24 to prefer transit over direct path"
        )

    def test_r1_no_local_pref_boost_for_other_prefixes(self):
        """r1's transit inbound route-map must NOT set elevated LOCAL_PREF
        for prefixes other than 10.4.1.0/24."""
        config = read_config('r1')
        rm_name = get_inbound_route_map(config, '10.0.12.2')
        assert rm_name is not None

        route_maps = parse_route_maps(config)
        prefix_lists = parse_prefix_lists(config)
        clauses = route_maps.get(rm_name, [])

        for clause in clauses:
            if clause['action'] != 'permit':
                continue

            sets_high_lp = False
            for s in clause['set']:
                m = re.match(r'set local-preference (\d+)', s)
                if m and int(m.group(1)) > 100:
                    sets_high_lp = True

            if sets_high_lp:
                assert len(clause['match']) > 0, (
                    "Route-map clause with elevated LOCAL_PREF must have match "
                    "conditions to restrict the boost to 10.4.1.0/24 only"
                )
                for match_line in clause['match']:
                    m_pl = re.match(
                        r'match ip address prefix-list (\S+)', match_line
                    )
                    if m_pl:
                        pl_entries = prefix_lists.get(m_pl.group(1), [])
                        for entry in pl_entries:
                            if entry['action'] == 'permit':
                                assert entry['prefix'] == '10.4.1.0/24', (
                                    f"LOCAL_PREF boost clause matches "
                                    f"{entry['prefix']} but should only "
                                    f"match 10.4.1.0/24"
                                )

    def test_r1_permits_other_prefixes(self):
        """r1's route-maps must have a catch-all permit to allow valid prefixes."""
        config = read_config('r1')

        for peer_ip in ['10.0.12.2', '10.0.14.2']:
            rm_name = get_inbound_route_map(config, peer_ip)
            assert rm_name is not None

            route_maps = parse_route_maps(config)
            clauses = route_maps.get(rm_name, [])

            has_permit = any(c['action'] == 'permit' for c in clauses)
            assert has_permit, (
                f"Route-map {rm_name} for peer {peer_ip} must have at least "
                f"one permit clause to allow valid prefixes through"
            )


class TestConfigConsistency:
    """Verify overall config consistency is preserved."""

    def test_r1_still_announces_prefixes(self):
        """r1 must still announce its own prefixes."""
        config = read_config('r1')
        assert 'network 10.1.0.0/24' in config
        assert 'network 10.1.1.0/24' in config

    def test_r4_still_announces_prefixes(self):
        """r4 must still announce all its prefixes."""
        config = read_config('r4')
        for prefix in ['10.4.0.0/22', '10.4.0.0/24', '10.4.1.0/24',
                        '10.4.2.0/24', '10.4.3.0/24']:
            assert f'network {prefix}' in config, (
                f"r4 must still announce {prefix}"
            )

    def test_r3_route_reflector_client(self):
        """r3 must still have r2 as route-reflector-client."""
        config = read_config('r3')
        assert 'route-reflector-client' in config

    def test_r2_still_has_correct_peering(self):
        """r2 must still peer with r1 and r3."""
        config = read_config('r2')
        assert 'neighbor 10.0.12.1 remote-as 65001' in config
        assert 'neighbor 10.255.0.3 remote-as 65002' in config

    def test_r1_still_has_correct_peering(self):
        """r1 must still peer with r2 and r4."""
        config = read_config('r1')
        assert 'neighbor 10.0.12.2 remote-as 65002' in config
        assert 'neighbor 10.0.14.2 remote-as 65003' in config


class TestDiagnosis:
    """Verify the structured diagnosis document is complete and accurate."""

    def test_diagnosis_file_exists(self):
        """diagnosis.json must exist at /app/diagnosis.json."""
        assert os.path.exists('/app/diagnosis.json'), (
            "Missing /app/diagnosis.json — must document session failures and policy decisions"
        )

    def test_diagnosis_valid_json(self):
        """diagnosis.json must be valid JSON with required top-level keys."""
        with open('/app/diagnosis.json') as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert 'session_failures' in data, "Missing 'session_failures' key"
        assert 'policy_decisions' in data, "Missing 'policy_decisions' key"

    def test_session_failures_count(self):
        """Exactly 3 session failures must be documented."""
        with open('/app/diagnosis.json') as f:
            data = json.load(f)
        failures = data['session_failures']
        assert isinstance(failures, list)
        assert len(failures) == 3, (
            f"Expected 3 session failures, found {len(failures)}"
        )

    def test_session_failures_identify_correct_sessions(self):
        """The three failed sessions must be correctly identified."""
        with open('/app/diagnosis.json') as f:
            data = json.load(f)
        failures = data['session_failures']

        sessions = set()
        for failure in failures:
            assert 'session' in failure, "Each failure must have a 'session' field"
            parts = failure['session'].lower().replace(' ', '').split('-')
            sessions.add(tuple(sorted(parts)))

        expected = {('r1', 'r4'), ('r2', 'r3'), ('r3', 'r4')}
        assert sessions == expected, (
            f"Expected failed sessions {expected}, got {sessions}"
        )

    def test_session_failures_have_affected_router(self):
        """Each failure must identify the affected router."""
        with open('/app/diagnosis.json') as f:
            data = json.load(f)

        for failure in data['session_failures']:
            assert 'affected_router' in failure, (
                "Each failure must have an 'affected_router' field"
            )
            affected = failure['affected_router'].lower()
            parts = failure['session'].lower().replace(' ', '').split('-')
            session = tuple(sorted(parts))

            if session == ('r2', 'r3'):
                assert 'r2' in affected, (
                    "r2-r3 failure: affected router should include r2"
                )
            elif session == ('r1', 'r4'):
                assert 'r4' in affected, (
                    "r1-r4 failure: affected router should include r4"
                )
            elif session == ('r3', 'r4'):
                assert 'r3' in affected or 'r4' in affected, (
                    "r3-r4 failure: affected router should include r3 or r4"
                )

    def test_session_failures_have_root_causes(self):
        """Each failure must have a substantive root cause explanation."""
        with open('/app/diagnosis.json') as f:
            data = json.load(f)

        for failure in data['session_failures']:
            assert 'root_cause' in failure, (
                "Each failure must have a 'root_cause' field"
            )
            assert isinstance(failure['root_cause'], str)
            assert len(failure['root_cause'].strip()) >= 15, (
                f"Root cause too brief for session {failure.get('session', '?')}: "
                f"'{failure['root_cause']}'"
            )

    def test_policy_decisions_complete(self):
        """All four policy decisions must be documented with substantive explanations."""
        with open('/app/diagnosis.json') as f:
            data = json.load(f)

        decisions = data['policy_decisions']
        assert isinstance(decisions, dict)

        required_keys = [
            'prefix_steering', 'prefix_filtering',
            'path_inflation', 'ibgp_reachability'
        ]
        for key in required_keys:
            assert key in decisions, f"Missing policy decision: '{key}'"
            assert isinstance(decisions[key], str)
            assert len(decisions[key].strip()) >= 15, (
                f"Policy decision '{key}' too brief: '{decisions[key]}'"
            )
