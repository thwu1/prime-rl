
"""
Tests for IS-IS SPF routing table computation.

Verifies the routing table at /app/routing_table.json against the expected
SPF result for the LSDB stored in /app/isis_lsdb.db.

Output must conform to the YANG module isis-rib.yang using RFC 7951 JSON
encoding: top-level key is "isis-rib:routing-table", route keys use
"destination-prefix", "total-metric", "forwarding-next-hop".
"""

import json
import os
import pytest


ROUTING_TABLE_PATH = "/app/routing_table.json"

# Expected routing table from SPF computation with source = 0000.0000.0001
# Uses YANG-derived field names per isis-rib.yang / RFC 7951
EXPECTED_ROUTES = {
    "2.2.2.2/32":    {"total-metric": 10, "forwarding-next-hop": ["0000.0000.0002"]},
    "3.3.3.3/32":    {"total-metric": 20, "forwarding-next-hop": ["0000.0000.0002"]},
    "4.4.4.4/32":    {"total-metric": 20, "forwarding-next-hop": ["0000.0000.0004"]},
    "5.5.5.5/32":    {"total-metric": 20, "forwarding-next-hop": ["0000.0000.0002", "0000.0000.0005"]},
    "6.6.6.6/32":    {"total-metric": 30, "forwarding-next-hop": ["0000.0000.0002", "0000.0000.0005"]},
    "7.7.7.7/32":    {"total-metric": 35, "forwarding-next-hop": ["0000.0000.0002"]},
    "8.8.8.8/32":    {"total-metric": 20, "forwarding-next-hop": ["0000.0000.0008"]},
    "10.0.2.0/24":   {"total-metric": 20, "forwarding-next-hop": ["0000.0000.0002"]},
    "10.0.3.0/24":   {"total-metric": 20, "forwarding-next-hop": ["0000.0000.0002"]},
    "10.0.4.0/24":   {"total-metric": 30, "forwarding-next-hop": ["0000.0000.0002"]},
    "10.0.5.0/24":   {"total-metric": 35, "forwarding-next-hop": ["0000.0000.0002"]},
    "10.0.6.0/24":   {"total-metric": 30, "forwarding-next-hop": ["0000.0000.0002", "0000.0000.0005"]},
    "10.0.7.0/24":   {"total-metric": 55, "forwarding-next-hop": ["0000.0000.0002", "0000.0000.0005"]},
    "10.0.9.0/24":   {"total-metric": 30, "forwarding-next-hop": ["0000.0000.0008"]},
    "172.16.0.0/16": {"total-metric": 50, "forwarding-next-hop": ["0000.0000.0002", "0000.0000.0005"]},
}

EXPECTED_ABSENT_PREFIXES = [
    "1.1.1.1/32",     # source router's loopback (connected)
    "10.0.1.0/24",    # source router's P2P link subnet (connected)
    "10.0.8.0/24",    # source router's LAN subnet (connected)
    "10.0.10.0/24",   # source router's P2P link subnet (connected)
    "9.9.9.9/32",     # expired LSP
    "10.0.11.0/24",   # expired LSP
]


def load_routing_table():
    """Load and parse the computed routing table."""
    assert os.path.exists(ROUTING_TABLE_PATH), (
        f"Routing table not found at {ROUTING_TABLE_PATH}"
    )
    with open(ROUTING_TABLE_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def raw_data():
    return load_routing_table()


@pytest.fixture(scope="module")
def routing_table(raw_data):
    """Extract the routing-table container per RFC 7951 encoding."""
    assert "isis-rib:routing-table" in raw_data, (
        "Top-level key must be 'isis-rib:routing-table' per RFC 7951 "
        f"YANG JSON encoding. Found keys: {list(raw_data.keys())}"
    )
    return raw_data["isis-rib:routing-table"]


@pytest.fixture(scope="module")
def route_map(routing_table):
    """Convert the route list to a dict keyed by destination-prefix."""
    rm = {}
    for route in routing_table["route"]:
        rm[route["destination-prefix"]] = {
            "total-metric": route["total-metric"],
            "forwarding-next-hop": sorted(route["forwarding-next-hop"]),
        }
    return rm


def test_yang_toplevel_namespace(raw_data):
    """RFC 7951: top-level container must use module-name:container-name."""
    assert "isis-rib:routing-table" in raw_data


def test_yang_field_names(routing_table):
    """Route entries must use YANG leaf names from isis-rib.yang."""
    assert "route" in routing_table, "Missing 'route' list"
    assert len(routing_table["route"]) > 0, "Route list is empty"
    first = routing_table["route"][0]
    assert "destination-prefix" in first, (
        f"Route entry missing 'destination-prefix'. Keys: {list(first.keys())}"
    )
    assert "total-metric" in first, (
        f"Route entry missing 'total-metric'. Keys: {list(first.keys())}"
    )
    assert "forwarding-next-hop" in first, (
        f"Route entry missing 'forwarding-next-hop'. Keys: {list(first.keys())}"
    )


def test_source_router(routing_table):
    """Source router field must be correct."""
    assert routing_table["source-router"] == "0000.0000.0001"


def test_route_count(route_map):
    """Exactly the expected number of routes."""
    assert len(route_map) == len(EXPECTED_ROUTES), (
        f"Expected {len(EXPECTED_ROUTES)} routes, got {len(route_map)}. "
        f"Extra: {set(route_map) - set(EXPECTED_ROUTES)}. "
        f"Missing: {set(EXPECTED_ROUTES) - set(route_map)}."
    )


def test_absent_prefixes(route_map):
    """Connected and expired prefixes must be absent."""
    for prefix in EXPECTED_ABSENT_PREFIXES:
        assert prefix not in route_map, (
            f"Prefix {prefix} should NOT be in the routing table"
        )


@pytest.mark.parametrize("prefix,expected", list(EXPECTED_ROUTES.items()))
def test_route_metric_and_nexthops(route_map, prefix, expected):
    """Each route must have exact metric and sorted next-hops."""
    assert prefix in route_map, f"Missing route for {prefix}"
    actual = route_map[prefix]
    assert actual["total-metric"] == expected["total-metric"], (
        f"Prefix {prefix}: expected total-metric {expected['total-metric']}, "
        f"got {actual['total-metric']}"
    )
    assert actual["forwarding-next-hop"] == expected["forwarding-next-hop"], (
        f"Prefix {prefix}: expected forwarding-next-hop "
        f"{expected['forwarding-next-hop']}, got {actual['forwarding-next-hop']}"
    )


# --- Edge-case specific tests ---

def test_overload_router_prefix_reachable(route_map):
    """
    rt8 has the overload bit set but its loopback (8.8.8.8/32) must still
    be reachable via the LAN at cost 20.
    """
    assert "8.8.8.8/32" in route_map
    assert route_map["8.8.8.8/32"]["total-metric"] == 20
    assert route_map["8.8.8.8/32"]["forwarding-next-hop"] == ["0000.0000.0008"]


def test_overload_transit_blocked(route_map):
    """
    10.0.9.0/24 is advertised by both rt7 (cost 45) and rt8 (cost 30).
    Despite rt8 being overloaded, its own prefix should win at cost 30.
    rt7 must be at cost 35 (via rt3), not 30 (which would indicate
    illegal transit through overloaded rt8).
    """
    assert route_map["10.0.9.0/24"]["total-metric"] == 30
    assert route_map["10.0.9.0/24"]["forwarding-next-hop"] == ["0000.0000.0008"]
    assert route_map["7.7.7.7/32"]["total-metric"] == 35
    assert route_map["7.7.7.7/32"]["forwarding-next-hop"] == ["0000.0000.0002"]


def test_expired_lsp_excluded(route_map):
    """rt9's LSP has remaining_lifetime=0; no routes from rt9 may appear."""
    assert "9.9.9.9/32" not in route_map
    assert "10.0.11.0/24" not in route_map


def test_fragment_handling(route_map):
    """
    rt3's link to rt7 and prefix 10.0.5.0/24 are in LSP fragment 00-01.
    Without proper fragment aggregation these would be missing.
    """
    assert "10.0.5.0/24" in route_map
    assert route_map["10.0.5.0/24"]["total-metric"] == 35
    assert "7.7.7.7/32" in route_map
    assert route_map["7.7.7.7/32"]["total-metric"] == 35


def test_pseudonode_nexthop_resolution(route_map):
    """
    rt4 is on a LAN with the source. Its next-hop must be rt4 itself
    (0000.0000.0004), NOT the pseudonode ID.
    """
    assert "4.4.4.4/32" in route_map
    nh = route_map["4.4.4.4/32"]["forwarding-next-hop"]
    assert nh == ["0000.0000.0004"], (
        f"LAN neighbor rt4 should have forwarding-next-hop "
        f"0000.0000.0004, got {nh}"
    )
    # Ensure no pseudonode IDs leak into any next-hop
    for prefix, data in route_map.items():
        for hop in data["forwarding-next-hop"]:
            parts = hop.split(".")
            assert len(parts) == 3, (
                f"Next-hop {hop} for {prefix} is not a valid system-id "
                f"(expected XXXX.XXXX.XXXX format)"
            )


def test_ecmp_node_level(route_map):
    """
    rt5 is reachable at cost 20 via two first-hops: rt2 and rt5 directly.
    """
    assert route_map["5.5.5.5/32"]["forwarding-next-hop"] == [
        "0000.0000.0002", "0000.0000.0005"
    ]


def test_ecmp_propagation(route_map):
    """
    rt6 at cost 30 is reachable via multiple paths. The distinct
    first-hops are rt2 and rt5.
    """
    assert route_map["6.6.6.6/32"]["forwarding-next-hop"] == [
        "0000.0000.0002", "0000.0000.0005"
    ]


def test_ecmp_prefix_level_multi_advertiser(route_map):
    """
    172.16.0.0/16 is advertised by multiple routers at equal total cost.
    The union of all first-hop next-hops must appear.
    """
    assert "172.16.0.0/16" in route_map
    assert route_map["172.16.0.0/16"]["total-metric"] == 50
    assert route_map["172.16.0.0/16"]["forwarding-next-hop"] == [
        "0000.0000.0002", "0000.0000.0005"
    ]
