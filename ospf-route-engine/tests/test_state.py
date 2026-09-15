"""
Tests for OSPF SPF Route Calculator.
Verifies the computed routing table against manually derived correct values
from a multi-area OSPF topology per RFC 2328.

"""
import json
import os
import pytest


ROUTING_TABLE_PATH = "/app/routing_table.json"

# Complete expected routing table computed by hand per RFC 2328
# Topology: 7 routers (R1-R7), Area 0 (backbone), Area 1, Area 2
# R1=1.1.1.1 (computing router), R2=2.2.2.2 (ABR Area 2),
# R3=3.3.3.3 (ABR Area 1), R4=4.4.4.4 (ABR Area 1 & 2),
# R5=5.5.5.5, R6=6.6.6.6 (ASBR), R7=7.7.7.7 (ASBR)
EXPECTED = {
    # Intra-area routes
    "1.1.1.1/32":   {"cost": 0,  "route_type": "intra-area", "next_hops": ["connected"]},
    "2.2.2.2/32":   {"cost": 10, "route_type": "intra-area", "next_hops": ["10.0.12.2"]},
    "3.3.3.3/32":   {"cost": 5,  "route_type": "intra-area", "next_hops": ["10.0.13.2"]},
    "4.4.4.4/32":   {"cost": 15, "route_type": "intra-area", "next_hops": ["10.0.12.2", "10.0.13.2"]},
    "10.0.12.0/30": {"cost": 10, "route_type": "intra-area", "next_hops": ["connected"]},
    "10.0.13.0/30": {"cost": 5,  "route_type": "intra-area", "next_hops": ["connected"]},
    "10.0.24.0/30": {"cost": 15, "route_type": "intra-area", "next_hops": ["10.0.12.2"]},
    "10.0.34.0/30": {"cost": 15, "route_type": "intra-area", "next_hops": ["10.0.13.2"]},
    # Inter-area routes
    "10.1.35.0/30": {"cost": 10, "route_type": "inter-area", "next_hops": ["10.0.13.2"]},
    "10.1.45.0/30": {"cost": 15, "route_type": "inter-area", "next_hops": ["10.0.13.2"]},
    "10.1.57.0/30": {"cost": 13, "route_type": "inter-area", "next_hops": ["10.0.13.2"]},
    "10.2.26.0/30": {"cost": 20, "route_type": "inter-area", "next_hops": ["10.0.12.2"]},
    "10.2.46.0/30": {"cost": 30, "route_type": "inter-area", "next_hops": ["10.0.12.2", "10.0.13.2"]},
    "10.4.1.0/24":  {"cost": 16, "route_type": "inter-area", "next_hops": ["10.0.12.2", "10.0.13.2"]},
    "10.5.0.0/24":  {"cost": 11, "route_type": "inter-area", "next_hops": ["10.0.13.2"]},
    "10.5.1.0/24":  {"cost": 12, "route_type": "inter-area", "next_hops": ["10.0.13.2"]},
    "10.6.0.0/24":  {"cost": 21, "route_type": "inter-area", "next_hops": ["10.0.12.2"]},
    "10.7.0.0/24":  {"cost": 14, "route_type": "inter-area", "next_hops": ["10.0.13.2"]},
    # External routes
    "172.16.0.0/12":  {"cost": 18, "route_type": "type-1-external", "next_hops": ["10.0.13.2"]},
    "192.168.0.0/16": {"cost": 40, "route_type": "type-1-external", "next_hops": ["10.0.12.2"]},
}


@pytest.fixture(scope="module")
def routing_table():
    """Load the routing table produced by the solution."""
    assert os.path.exists(ROUTING_TABLE_PATH), \
        f"Routing table file not found at {ROUTING_TABLE_PATH}"
    with open(ROUTING_TABLE_PATH) as f:
        table = json.load(f)
    assert isinstance(table, list), "Routing table must be a JSON array"
    # Index by destination for quick lookup
    indexed = {}
    for entry in table:
        dest = entry["destination"]
        assert dest not in indexed, f"Duplicate route for {dest}"
        indexed[dest] = entry
    return indexed


def test_routing_table_exists(routing_table):
    """The routing table file should exist and be valid JSON."""
    assert len(routing_table) > 0


def test_total_route_count(routing_table):
    """Expect exactly 20 routes."""
    assert len(routing_table) == 20, \
        f"Expected 20 routes, got {len(routing_table)}. " \
        f"Destinations: {sorted(routing_table.keys())}"


@pytest.mark.parametrize("destination", list(EXPECTED.keys()))
def test_route_present(routing_table, destination):
    """Each expected destination must be present."""
    assert destination in routing_table, \
        f"Missing route for {destination}"


@pytest.mark.parametrize("destination", list(EXPECTED.keys()))
def test_route_cost(routing_table, destination):
    """Each route must have the correct OSPF cost."""
    if destination not in routing_table:
        pytest.skip(f"Route {destination} missing")
    actual = routing_table[destination]["cost"]
    expected = EXPECTED[destination]["cost"]
    assert actual == expected, \
        f"{destination}: cost {actual} != expected {expected}"


@pytest.mark.parametrize("destination", list(EXPECTED.keys()))
def test_route_type(routing_table, destination):
    """Each route must have the correct route type."""
    if destination not in routing_table:
        pytest.skip(f"Route {destination} missing")
    actual = routing_table[destination]["route_type"]
    expected = EXPECTED[destination]["route_type"]
    assert actual == expected, \
        f"{destination}: type '{actual}' != expected '{expected}'"


@pytest.mark.parametrize("destination", list(EXPECTED.keys()))
def test_route_next_hops(routing_table, destination):
    """Each route must have the correct sorted next-hop list."""
    if destination not in routing_table:
        pytest.skip(f"Route {destination} missing")
    actual = sorted(routing_table[destination]["next_hops"])
    expected = sorted(EXPECTED[destination]["next_hops"])
    assert actual == expected, \
        f"{destination}: next_hops {actual} != expected {expected}"


# --- Targeted edge-case tests ---

def test_intra_area_ecmp(routing_table):
    """R4 (4.4.4.4/32) must have ECMP via R2 and R3 (equal cost 15)."""
    route = routing_table.get("4.4.4.4/32")
    assert route is not None
    assert route["cost"] == 15
    assert route["route_type"] == "intra-area"
    assert sorted(route["next_hops"]) == ["10.0.12.2", "10.0.13.2"]


def test_inter_area_ecmp_via_abr_with_ecmp(routing_table):
    """10.2.46.0/30 via R4 (ABR with ECMP intra-area paths) should inherit ECMP."""
    route = routing_table.get("10.2.46.0/30")
    assert route is not None
    assert route["cost"] == 30
    assert route["route_type"] == "inter-area"
    assert sorted(route["next_hops"]) == ["10.0.12.2", "10.0.13.2"]


def test_inter_area_ecmp_different_abrs(routing_table):
    """10.4.1.0/24: R3 (cost 5+11=16) and R4 (cost 15+1=16) yield ECMP from different ABRs."""
    route = routing_table.get("10.4.1.0/24")
    assert route is not None
    assert route["cost"] == 16
    assert route["route_type"] == "inter-area"
    assert sorted(route["next_hops"]) == ["10.0.12.2", "10.0.13.2"]


def test_e1_preferred_over_e2(routing_table):
    """172.16.0.0/12: R7 advertises E1 metric 5 (cost 18), R6 advertises E2 metric 100.
    E1 must win per RFC 2328."""
    route = routing_table.get("172.16.0.0/12")
    assert route is not None
    assert route["route_type"] == "type-1-external", \
        f"Expected type-1-external, got {route['route_type']} (E1 must beat E2)"
    assert route["cost"] == 18
    assert sorted(route["next_hops"]) == ["10.0.13.2"]


def test_e1_external_route(routing_table):
    """192.168.0.0/16: E1 from R6 via R2. Cost = path_to_R6 (20) + ext_metric (20) = 40."""
    route = routing_table.get("192.168.0.0/16")
    assert route is not None
    assert route["cost"] == 40
    assert route["route_type"] == "type-1-external"
    assert sorted(route["next_hops"]) == ["10.0.12.2"]


def test_no_unexpected_routes(routing_table):
    """No routes should exist beyond the 20 expected destinations."""
    unexpected = set(routing_table.keys()) - set(EXPECTED.keys())
    assert len(unexpected) == 0, \
        f"Unexpected routes found: {unexpected}"


def test_intra_area_preferred_over_inter_area(routing_table):
    """Intra-area routes must not be overridden by inter-area for same prefix."""
    intra_prefixes = {d for d, v in EXPECTED.items() if v["route_type"] == "intra-area"}
    for prefix in intra_prefixes:
        if prefix in routing_table:
            assert routing_table[prefix]["route_type"] == "intra-area", \
                f"{prefix} should be intra-area, got {routing_table[prefix]['route_type']}"
