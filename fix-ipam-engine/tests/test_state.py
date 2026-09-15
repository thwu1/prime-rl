"""
Tests for the IPAM subnet allocation planner.
Verifies that allocation_plan.json satisfies all expansion requirements
including CIDR alignment, VRF isolation, contiguous blocks, exclusion zones,
and no overlap with existing allocations.

"""
import json
import os
import subprocess

import netaddr
import pytest


@pytest.fixture(scope="module")
def plan():
    """Run allocator if needed and load the allocation plan."""
    plan_path = '/app/allocation_plan.json'
    if not os.path.exists(plan_path):
        result = subprocess.run(
            ['python3', '/app/allocator.py'],
            capture_output=True, text=True, cwd='/app'
        )
        assert result.returncode == 0, f"allocator.py failed:\n{result.stderr}"
    assert os.path.exists(plan_path), "allocation_plan.json not created"
    with open(plan_path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def state():
    with open('/data/network_state.json') as f:
        return json.load(f)


@pytest.fixture(scope="module")
def expansion():
    with open('/data/expansion.json') as f:
        return json.load(f)


# ============================================================
# Plan structure
# ============================================================

class TestPlanStructure:
    def test_has_allocations_key(self, plan):
        assert 'allocations' in plan, "Plan must have 'allocations' key"

    def test_all_requests_present(self, plan):
        for req_id in ['REQ-001', 'REQ-002', 'REQ-003', 'REQ-004',
                        'REQ-005', 'REQ-006', 'REQ-007']:
            assert req_id in plan['allocations'], f"Missing {req_id}"

    def test_allocation_metadata(self, plan):
        for req_id, allocs in plan['allocations'].items():
            for a in allocs:
                assert 'prefix' in a, f"{req_id}: missing 'prefix'"
                assert 'vrf' in a, f"{req_id}: missing 'vrf'"
                assert 'site' in a, f"{req_id}: missing 'site'"


# ============================================================
# REQ-001: 4 contiguous /24s in Production 10.1.0.0/16
# ============================================================

class TestReq001:
    def test_count_and_length(self, plan):
        allocs = plan['allocations']['REQ-001']
        assert len(allocs) == 4
        nets = [netaddr.IPNetwork(a['prefix']) for a in allocs]
        assert all(n.prefixlen == 24 for n in nets)

    def test_within_parent(self, plan):
        parent = netaddr.IPNetwork('10.1.0.0/16')
        for a in plan['allocations']['REQ-001']:
            n = netaddr.IPNetwork(a['prefix'])
            assert n.first >= parent.first and n.last <= parent.last

    def test_forms_cidr_supernet(self, plan):
        """4 contiguous /24s must merge into a single /22."""
        nets = [netaddr.IPNetwork(a['prefix']) for a in plan['allocations']['REQ-001']]
        merged = netaddr.cidr_merge(nets)
        assert len(merged) == 1, f"Expected single /22, got {merged}"
        assert merged[0].prefixlen == 22

    def test_lowest_available_block(self, plan):
        """First available /22-aligned block after existing allocations is 10.1.4.0/22."""
        nets = sorted(
            [netaddr.IPNetwork(a['prefix']) for a in plan['allocations']['REQ-001']],
            key=lambda n: n.first
        )
        assert str(nets[0].cidr) == '10.1.4.0/24', \
            f"Expected start at 10.1.4.0/24, got {nets[0].cidr}"

    def test_vrf(self, plan):
        assert all(a['vrf'] == 'Production' for a in plan['allocations']['REQ-001'])


# ============================================================
# REQ-002: 1 /23 in Management 172.16.0.0/16 with exclusions
# ============================================================

class TestReq002:
    def test_count_and_length(self, plan):
        allocs = plan['allocations']['REQ-002']
        assert len(allocs) == 1
        n = netaddr.IPNetwork(allocs[0]['prefix'])
        assert n.prefixlen == 23

    def test_within_parent(self, plan):
        parent = netaddr.IPNetwork('172.16.0.0/16')
        n = netaddr.IPNetwork(plan['allocations']['REQ-002'][0]['prefix'])
        assert n.first >= parent.first and n.last <= parent.last

    def test_exclusion_zones_avoided(self, plan):
        n = netaddr.IPNetwork(plan['allocations']['REQ-002'][0]['prefix'])
        for excl_str in ['172.16.2.0/23', '172.16.6.0/23']:
            excl = netaddr.IPNetwork(excl_str)
            overlap = n.first <= excl.last and excl.first <= n.last
            assert not overlap, f"Allocation {n} overlaps excluded zone {excl}"

    def test_lowest_available(self, plan):
        """First valid /23 after existing and exclusions is 172.16.4.0/23."""
        n = netaddr.IPNetwork(plan['allocations']['REQ-002'][0]['prefix'])
        assert str(n.cidr) == '172.16.4.0/23', f"Expected 172.16.4.0/23, got {n.cidr}"

    def test_vrf(self, plan):
        assert plan['allocations']['REQ-002'][0]['vrf'] == 'Management'


# ============================================================
# REQ-003: 3 /64s in Production 2001:db8:1::/48 (IPv6)
# ============================================================

class TestReq003:
    def test_count_and_length(self, plan):
        allocs = plan['allocations']['REQ-003']
        assert len(allocs) == 3
        nets = [netaddr.IPNetwork(a['prefix']) for a in allocs]
        assert all(n.prefixlen == 64 for n in nets)

    def test_within_parent(self, plan):
        parent = netaddr.IPNetwork('2001:db8:1::/48')
        for a in plan['allocations']['REQ-003']:
            n = netaddr.IPNetwork(a['prefix'])
            assert n.first >= parent.first and n.last <= parent.last

    def test_not_overlapping_existing(self, plan):
        """Must not overlap existing 2001:db8:1::/64."""
        existing = netaddr.IPNetwork('2001:db8:1::/64')
        for a in plan['allocations']['REQ-003']:
            n = netaddr.IPNetwork(a['prefix'])
            assert n.first != existing.first, f"{n} duplicates existing {existing}"

    def test_lowest_ipv6_addresses(self, plan):
        """First 3 available /64s after 2001:db8:1::/64."""
        nets = sorted(
            [netaddr.IPNetwork(a['prefix']) for a in plan['allocations']['REQ-003']],
            key=lambda n: n.first
        )
        assert str(nets[0].cidr) == '2001:db8:1:1::/64'
        assert str(nets[1].cidr) == '2001:db8:1:2::/64'
        assert str(nets[2].cidr) == '2001:db8:1:3::/64'


# ============================================================
# REQ-004: 5 /31 point-to-point links in Production 10.255.0.0/24
# ============================================================

class TestReq004:
    def test_count_and_length(self, plan):
        allocs = plan['allocations']['REQ-004']
        assert len(allocs) == 5
        nets = [netaddr.IPNetwork(a['prefix']) for a in allocs]
        assert all(n.prefixlen == 31 for n in nets)

    def test_within_parent(self, plan):
        parent = netaddr.IPNetwork('10.255.0.0/24')
        for a in plan['allocations']['REQ-004']:
            n = netaddr.IPNetwork(a['prefix'])
            assert n.first >= parent.first and n.last <= parent.last

    def test_not_overlapping_existing_links(self, plan):
        existing = [netaddr.IPNetwork(p) for p in
                     ['10.255.0.0/31', '10.255.0.2/31', '10.255.0.4/31']]
        for a in plan['allocations']['REQ-004']:
            n = netaddr.IPNetwork(a['prefix'])
            for e in existing:
                assert n.first != e.first, f"{n} duplicates existing {e}"

    def test_lowest_available(self, plan):
        nets = sorted(
            [netaddr.IPNetwork(a['prefix']) for a in plan['allocations']['REQ-004']],
            key=lambda n: n.first
        )
        assert str(nets[0].cidr) == '10.255.0.6/31'


# ============================================================
# REQ-005: 2 /24s in Guest VRF 10.0.0.0/16 (VRF isolation test)
# ============================================================

class TestReq005:
    def test_count_and_length(self, plan):
        allocs = plan['allocations']['REQ-005']
        assert len(allocs) == 2
        nets = [netaddr.IPNetwork(a['prefix']) for a in allocs]
        assert all(n.prefixlen == 24 for n in nets)

    def test_correct_vrf(self, plan):
        """Must be in Guest VRF, not Production."""
        assert all(a['vrf'] == 'Guest' for a in plan['allocations']['REQ-005'])

    def test_not_overlapping_guest_existing(self, plan):
        existing_guest = netaddr.IPNetwork('10.0.0.0/24')
        for a in plan['allocations']['REQ-005']:
            n = netaddr.IPNetwork(a['prefix'])
            assert n.first != existing_guest.first

    def test_lowest_in_guest_vrf(self, plan):
        """In Guest VRF, 10.0.0.0/24 is taken. Next available: 10.0.1.0/24."""
        nets = sorted(
            [netaddr.IPNetwork(a['prefix']) for a in plan['allocations']['REQ-005']],
            key=lambda n: n.first
        )
        assert str(nets[0].cidr) == '10.0.1.0/24', \
            f"Expected 10.0.1.0/24 (Guest VRF), got {nets[0].cidr}"
        assert str(nets[1].cidr) == '10.0.2.0/24'

    def test_pool_flag(self, plan):
        for a in plan['allocations']['REQ-005']:
            assert a.get('is_pool') is True, "REQ-005 allocations must have is_pool=true"


# ============================================================
# REQ-006: 3 /25s in Production 10.0.0.0/16
# ============================================================

class TestReq006:
    def test_count_and_length(self, plan):
        allocs = plan['allocations']['REQ-006']
        assert len(allocs) == 3
        nets = [netaddr.IPNetwork(a['prefix']) for a in allocs]
        assert all(n.prefixlen == 25 for n in nets)

    def test_within_parent(self, plan):
        parent = netaddr.IPNetwork('10.0.0.0/16')
        for a in plan['allocations']['REQ-006']:
            n = netaddr.IPNetwork(a['prefix'])
            assert n.first >= parent.first and n.last <= parent.last

    def test_not_overlapping_existing_production(self, plan):
        """Must not overlap 10.0.0-3.0/24 or 10.0.4.0/23 in Production."""
        existing = [netaddr.IPNetwork(p) for p in [
            '10.0.0.0/24', '10.0.1.0/24', '10.0.2.0/24',
            '10.0.3.0/24', '10.0.4.0/23'
        ]]
        for a in plan['allocations']['REQ-006']:
            n = netaddr.IPNetwork(a['prefix'])
            for e in existing:
                overlap = n.first <= e.last and e.first <= n.last
                assert not overlap, f"REQ-006: {n} overlaps existing {e}"

    def test_lowest_available_25s(self, plan):
        """First free space after 10.0.4.0/23 is 10.0.6.0. First /25: 10.0.6.0/25."""
        nets = sorted(
            [netaddr.IPNetwork(a['prefix']) for a in plan['allocations']['REQ-006']],
            key=lambda n: n.first
        )
        assert str(nets[0].cidr) == '10.0.6.0/25', f"Expected 10.0.6.0/25, got {nets[0].cidr}"

    def test_vrf(self, plan):
        assert all(a['vrf'] == 'Production' for a in plan['allocations']['REQ-006'])


# ============================================================
# REQ-007: 2 contiguous /24s in Management 172.17.0.0/16
# ============================================================

class TestReq007:
    def test_count_and_length(self, plan):
        allocs = plan['allocations']['REQ-007']
        assert len(allocs) == 2
        nets = [netaddr.IPNetwork(a['prefix']) for a in allocs]
        assert all(n.prefixlen == 24 for n in nets)

    def test_forms_cidr_supernet(self, plan):
        """2 contiguous /24s must merge into a single /23."""
        nets = [netaddr.IPNetwork(a['prefix']) for a in plan['allocations']['REQ-007']]
        merged = netaddr.cidr_merge(nets)
        assert len(merged) == 1, f"Expected single /23, got {merged}"
        assert merged[0].prefixlen == 23

    def test_lowest_available(self, plan):
        """172.17.0.0/23 has existing /24. Next /23 block: 172.17.2.0/23."""
        nets = sorted(
            [netaddr.IPNetwork(a['prefix']) for a in plan['allocations']['REQ-007']],
            key=lambda n: n.first
        )
        assert str(nets[0].cidr) == '172.17.2.0/24'
        assert str(nets[1].cidr) == '172.17.3.0/24'

    def test_vrf(self, plan):
        assert all(a['vrf'] == 'Management' for a in plan['allocations']['REQ-007'])


# ============================================================
# Global constraints
# ============================================================

class TestGlobalConstraints:
    def test_cidr_alignment(self, plan):
        """All allocations must use canonical CIDR addresses."""
        for req_id, allocs in plan['allocations'].items():
            for a in allocs:
                n = netaddr.IPNetwork(a['prefix'])
                assert str(n.cidr) == a['prefix'], \
                    f"{req_id}: {a['prefix']} not CIDR-aligned (canonical: {n.cidr})"

    def test_no_internal_overlaps(self, plan):
        """No two new allocations in the same VRF may overlap."""
        by_vrf = {}
        for req_id, allocs in plan['allocations'].items():
            for a in allocs:
                vrf = a['vrf']
                by_vrf.setdefault(vrf, []).append(
                    (req_id, netaddr.IPNetwork(a['prefix']))
                )
        for vrf, entries in by_vrf.items():
            for i, (id1, n1) in enumerate(entries):
                for j, (id2, n2) in enumerate(entries):
                    if i >= j:
                        continue
                    overlap = n1.first <= n2.last and n2.first <= n1.last
                    assert not overlap, \
                        f"Overlap in {vrf}: {id1}:{n1} and {id2}:{n2}"

    def test_no_overlap_with_existing_leaves(self, plan, state):
        """New allocations must not overlap non-container existing prefixes in same VRF."""
        leaves_by_vrf = {}
        for p in state['prefixes']:
            if p.get('status') != 'container':
                vrf = p['vrf']
                leaves_by_vrf.setdefault(vrf, []).append(
                    netaddr.IPNetwork(p['prefix'])
                )
        for req_id, allocs in plan['allocations'].items():
            for a in allocs:
                vrf = a['vrf']
                n = netaddr.IPNetwork(a['prefix'])
                for e in leaves_by_vrf.get(vrf, []):
                    overlap = n.first <= e.last and e.first <= n.last
                    assert not overlap, \
                        f"{req_id}: {n} overlaps existing {e} in VRF {vrf}"
