
"""
Tests for OSPF SPF routing table computation.

Verifies the routing table computed from router 1.1.1.1's perspective
in a multi-area OSPFv2 network with 7 routers across 3 areas.

Topology (Area 0 backbone):
  rt1 (1.1.1.1) ---p2p--- rt2 (2.2.2.2, ABR)
  rt1 (1.1.1.1) ---p2p--- rt3 (3.3.3.3)
  rt2, rt3, rt4 (4.4.4.4, ABR) share broadcast 10.0.6.0/24 (DR=rt3)

Inter-area:
  rt2 -> Area 1: rt5 (5.5.5.5), rt6 (6.6.6.6) via broadcast
  rt4 -> Area 2 (stub): rt7 (7.7.7.7) via p2p
"""

import json
import pytest


# Expected routing table: 10 routes
# Intra-area: 4 routes (2.2.2.2/32, 3.3.3.3/32, 4.4.4.4/32, 10.0.6.0/24)
# Inter-area: 6 routes (5.5.5.5/32, 6.6.6.6/32, 10.0.10.0/24, 10.0.11.0/24,
#                        7.7.7.7/32, 10.0.20.0/24)
EXPECTED = {
    "2.2.2.2/32":    {"metric": 10, "route_type": "intra-area", "next_hops": ["10.0.1.2"]},
    "3.3.3.3/32":    {"metric": 10, "route_type": "intra-area", "next_hops": ["10.0.2.3"]},
    "4.4.4.4/32":    {"metric": 20, "route_type": "intra-area", "next_hops": ["10.0.1.2", "10.0.2.3"]},
    "10.0.6.0/24":   {"metric": 20, "route_type": "intra-area", "next_hops": ["10.0.1.2", "10.0.2.3"]},
    "5.5.5.5/32":    {"metric": 20, "route_type": "inter-area", "next_hops": ["10.0.1.2"]},
    "6.6.6.6/32":    {"metric": 25, "route_type": "inter-area", "next_hops": ["10.0.1.2"]},
    "10.0.10.0/24":  {"metric": 20, "route_type": "inter-area", "next_hops": ["10.0.1.2"]},
    "10.0.11.0/24":  {"metric": 25, "route_type": "inter-area", "next_hops": ["10.0.1.2"]},
    "7.7.7.7/32":    {"metric": 40, "route_type": "inter-area", "next_hops": ["10.0.1.2", "10.0.2.3"]},
    "10.0.20.0/24":  {"metric": 40, "route_type": "inter-area", "next_hops": ["10.0.1.2", "10.0.2.3"]},
}


@pytest.fixture(scope="module")
def routing_table():
    try:
        with open("/app/results/routing_table.json") as f:
            data = json.load(f)
    except FileNotFoundError:
        pytest.fail("routing_table.json not found at /app/results/routing_table.json")
    except json.JSONDecodeError as e:
        pytest.fail(f"routing_table.json is not valid JSON: {e}")
    assert isinstance(data, list), "routing_table.json must contain a JSON array"
    return {r["destination"]: r for r in data}


def test_route_count(routing_table):
    """Exactly 10 routes expected."""
    extra = set(routing_table) - set(EXPECTED)
    missing = set(EXPECTED) - set(routing_table)
    assert len(routing_table) == len(EXPECTED), (
        f"Expected {len(EXPECTED)} routes, got {len(routing_table)}. "
        f"Extra: {extra or 'none'}. Missing: {missing or 'none'}"
    )


@pytest.mark.parametrize("destination", sorted(EXPECTED.keys()))
def test_route_present(routing_table, destination):
    """Each expected destination must be present."""
    assert destination in routing_table, f"Missing route to {destination}"


@pytest.mark.parametrize("destination", sorted(EXPECTED.keys()))
def test_route_metric(routing_table, destination):
    """Each route must have the correct total metric."""
    if destination not in routing_table:
        pytest.skip(f"Route {destination} not found")
    actual = routing_table[destination]["metric"]
    expected = EXPECTED[destination]["metric"]
    assert actual == expected, (
        f"Route {destination}: expected metric {expected}, got {actual}"
    )


@pytest.mark.parametrize("destination", sorted(EXPECTED.keys()))
def test_route_type(routing_table, destination):
    """Each route must have the correct type (intra-area or inter-area)."""
    if destination not in routing_table:
        pytest.skip(f"Route {destination} not found")
    actual = routing_table[destination]["route_type"]
    expected = EXPECTED[destination]["route_type"]
    assert actual == expected, (
        f"Route {destination}: expected type '{expected}', got '{actual}'"
    )


@pytest.mark.parametrize("destination", sorted(EXPECTED.keys()))
def test_route_nexthops(routing_table, destination):
    """Each route must have the correct sorted next-hop list."""
    if destination not in routing_table:
        pytest.skip(f"Route {destination} not found")
    actual = sorted(routing_table[destination]["next_hops"])
    expected = sorted(EXPECTED[destination]["next_hops"])
    assert actual == expected, (
        f"Route {destination}: expected next_hops {expected}, got {actual}"
    )


def test_no_connected_routes(routing_table):
    """Computing router's own connected routes must be excluded."""
    connected = ["1.1.1.1/32", "10.0.1.0/24", "10.0.2.0/24"]
    for dest in connected:
        assert dest not in routing_table, (
            f"Connected route {dest} should be excluded from the routing table"
        )


def test_ecmp_route_nexthop_count(routing_table):
    """ECMP routes must have exactly 2 next-hops."""
    ecmp_destinations = ["4.4.4.4/32", "10.0.6.0/24", "7.7.7.7/32", "10.0.20.0/24"]
    for dest in ecmp_destinations:
        if dest not in routing_table:
            pytest.skip(f"Route {dest} not found")
        nh_count = len(routing_table[dest]["next_hops"])
        assert nh_count == 2, (
            f"ECMP route {dest}: expected 2 next-hops, got {nh_count}"
        )


def test_single_nexthop_routes(routing_table):
    """Non-ECMP routes must have exactly 1 next-hop."""
    single_nh = ["2.2.2.2/32", "3.3.3.3/32", "5.5.5.5/32", "6.6.6.6/32",
                 "10.0.10.0/24", "10.0.11.0/24"]
    for dest in single_nh:
        if dest not in routing_table:
            pytest.skip(f"Route {dest} not found")
        nh_count = len(routing_table[dest]["next_hops"])
        assert nh_count == 1, (
            f"Route {dest}: expected 1 next-hop, got {nh_count}"
        )


def test_competing_summary_lsa_resolved(routing_table):
    """6.6.6.6/32 has Summary-LSAs from both rt2 (cost 25) and rt4 (cost 50).
    The lower cost via rt2 must win."""
    dest = "6.6.6.6/32"
    if dest not in routing_table:
        pytest.skip("Route 6.6.6.6/32 not found")
    r = routing_table[dest]
    assert r["metric"] == 25, (
        f"6.6.6.6/32 should have metric 25 (via rt2), got {r['metric']}. "
        "The competing Summary-LSA from rt4 (total cost 50) must not win."
    )
    assert r["next_hops"] == ["10.0.1.2"], (
        f"6.6.6.6/32 should route via rt2 (10.0.1.2 only), got {r['next_hops']}"
    )


def test_inter_area_ecmp_through_abr(routing_table):
    """Inter-area routes via rt4 (ABR) should inherit rt4's ECMP next-hops
    since rt4 is reachable via two equal-cost paths through the transit network."""
    for dest in ["7.7.7.7/32", "10.0.20.0/24"]:
        if dest not in routing_table:
            pytest.skip(f"Route {dest} not found")
        r = routing_table[dest]
        assert sorted(r["next_hops"]) == ["10.0.1.2", "10.0.2.3"], (
            f"Inter-area route {dest} via ABR rt4 should have 2 ECMP next-hops "
            f"inherited from rt4's SPF position, got {r['next_hops']}"
        )
