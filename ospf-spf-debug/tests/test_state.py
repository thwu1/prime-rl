"""
Tests for OSPF SPF route calculator.

Validates the routing table computed from a multi-area OSPF topology
(5 routers, 2 areas, transit/stub/external routes) against RFC 2328.

Topology sketch (root = RT1 = 1.1.1.1):

  Area 0.0.0.0 (backbone)
    RT1 ──5── Net 10.0.12.0/24 ──5── RT2 (stub 10.2.0.0/24)
    RT1 ──5── Net 10.0.13.0/24 ──5── RT3 (stub 10.3.0.0/24, ASBR→172.16.0.0/16)
                                      RT2 ──8── Net 10.0.23.0/24 ──8── RT3

  Area 0.0.0.1
    RT1 ──10── Net 10.1.14.0/24 ──10── RT4 (stub 10.4.0.0/24)
                                        RT4 ──10── Net 10.1.45.0/24 ──10── RT5
                                        RT5: stub 10.5.0.0/24, stub 10.99.99.1/32 (anycast VIP)
"""


import json
import subprocess
import pytest

TOPOLOGY = "/app/topology.json"


def _routes() -> dict:
    """Run the SPF calculator and return parsed routing table."""
    r = subprocess.run(
        ["python3", "/app/ospf_spf.py", TOPOLOGY],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"ospf_spf.py failed:\n{r.stderr}"
    return json.loads(r.stdout)


# ── Route presence ───────────────────────────────────────────────────

class TestRoutePresence:

    def test_anycast_vip_route_exists(self):
        """A /32 stub on a non-loopback interface is a valid host route
        (e.g. anycast VIP), not an unnumbered p2p endpoint."""
        routes = _routes()
        assert "10.99.99.1/32" in routes, (
            "Missing host route 10.99.99.1/32 — the /32 stub on RT5's "
            "non-loopback interface must appear in the routing table"
        )

    def test_all_expected_destinations(self):
        routes = _routes()
        expected = [
            "10.0.12.0/24", "10.0.13.0/24", "10.0.23.0/24",
            "10.2.0.0/24", "10.3.0.0/24",
            "10.1.14.0/24", "10.1.45.0/24",
            "10.4.0.0/24", "10.5.0.0/24", "10.99.99.1/32",
            "172.16.0.0/16",
        ]
        for key in expected:
            assert key in routes, f"Missing route {key}"
        assert len(routes) == len(expected), (
            f"Expected {len(expected)} routes, got {len(routes)}; "
            f"extra = {set(routes) - set(expected)}"
        )


# ── Metric correctness ──────────────────────────────────────────────

class TestMetrics:

    def test_backbone_stub_cost_rt2(self):
        """10.2.0.0/24 via RT2: path cost 5 (to RT2) + 1 (stub) = 6."""
        routes = _routes()
        assert routes["10.2.0.0/24"]["cost"] == 6, (
            f"10.2.0.0/24 cost = {routes['10.2.0.0/24']['cost']}, expected 6 — "
            "check the cost calculation when transitioning from a transit "
            "network vertex to an attached router (RFC 2328 §16.1)"
        )

    def test_backbone_stub_cost_rt3(self):
        """10.3.0.0/24 via RT3: path cost 5 + 1 = 6."""
        routes = _routes()
        assert routes["10.3.0.0/24"]["cost"] == 6

    def test_area1_stub_cost_rt4(self):
        """10.4.0.0/24 via RT4: path cost 10 + 1 = 11."""
        routes = _routes()
        assert routes["10.4.0.0/24"]["cost"] == 11, (
            f"10.4.0.0/24 cost = {routes['10.4.0.0/24']['cost']}, expected 11"
        )

    def test_area1_stub_cost_rt5(self):
        """10.5.0.0/24 via RT5: path cost 20 + 1 = 21."""
        routes = _routes()
        assert routes["10.5.0.0/24"]["cost"] == 21, (
            f"10.5.0.0/24 cost = {routes['10.5.0.0/24']['cost']}, expected 21"
        )

    def test_area1_transit_cost(self):
        """10.1.45.0/24: cost to RT4 (10) + link to net (10) = 20."""
        routes = _routes()
        assert routes["10.1.45.0/24"]["cost"] == 20

    def test_backbone_transit_ecmp_cost(self):
        """10.0.23.0/24: min(5+8, 5+8) = 13."""
        routes = _routes()
        assert routes["10.0.23.0/24"]["cost"] == 13, (
            f"10.0.23.0/24 cost = {routes['10.0.23.0/24']['cost']}, expected 13"
        )

    def test_external_type1_cost(self):
        """172.16.0.0/16: cost-to-ASBR (5) + external metric (2) = 7."""
        routes = _routes()
        r = routes["172.16.0.0/16"]
        assert r["cost"] == 7, (
            f"172.16.0.0/16 cost = {r['cost']}, expected 7"
        )
        assert r["route_type"] == "external-type1"

    def test_anycast_vip_cost(self):
        """10.99.99.1/32: cost-to-RT5 (20) + stub metric (0) = 20."""
        routes = _routes()
        assert "10.99.99.1/32" in routes, "Route missing"
        assert routes["10.99.99.1/32"]["cost"] == 20


# ── ECMP ─────────────────────────────────────────────────────────────

class TestEcmp:

    def test_backbone_ecmp_next_hops(self):
        """10.0.23.0/24 is equidistant through RT2 and RT3.
        Both next-hops must appear."""
        routes = _routes()
        nh = sorted(routes["10.0.23.0/24"]["next_hops"])
        assert nh == ["10.0.12.2", "10.0.13.3"], (
            f"Expected ECMP next-hops [10.0.12.2, 10.0.13.3], got {nh} — "
            "equal-cost candidate paths must merge their next-hop sets"
        )

    def test_single_path_next_hop(self):
        """Non-ECMP routes must have exactly one next-hop."""
        routes = _routes()
        for key in ["10.2.0.0/24", "10.3.0.0/24", "10.4.0.0/24",
                     "10.5.0.0/24", "172.16.0.0/16"]:
            nh = routes[key]["next_hops"]
            assert len(nh) == 1, f"{key} should have 1 next-hop, got {nh}"


# ── Full table ───────────────────────────────────────────────────────

class TestFullTable:

    EXPECTED = {
        "10.0.12.0/24": {"cost": 5,  "route_type": "intra-area"},
        "10.0.13.0/24": {"cost": 5,  "route_type": "intra-area"},
        "10.0.23.0/24": {"cost": 13, "route_type": "intra-area",
                         "next_hops": ["10.0.12.2", "10.0.13.3"]},
        "10.2.0.0/24":  {"cost": 6,  "route_type": "intra-area",
                         "next_hops": ["10.0.12.2"]},
        "10.3.0.0/24":  {"cost": 6,  "route_type": "intra-area",
                         "next_hops": ["10.0.13.3"]},
        "10.1.14.0/24": {"cost": 10, "route_type": "intra-area"},
        "10.1.45.0/24": {"cost": 20, "route_type": "intra-area",
                         "next_hops": ["10.1.14.4"]},
        "10.4.0.0/24":  {"cost": 11, "route_type": "intra-area",
                         "next_hops": ["10.1.14.4"]},
        "10.5.0.0/24":  {"cost": 21, "route_type": "intra-area",
                         "next_hops": ["10.1.14.4"]},
        "10.99.99.1/32": {"cost": 20, "route_type": "intra-area",
                          "next_hops": ["10.1.14.4"]},
        "172.16.0.0/16": {"cost": 7,  "route_type": "external-type1",
                          "next_hops": ["10.0.13.3"]},
    }

    def test_complete_routing_table(self):
        routes = _routes()
        for key, exp in self.EXPECTED.items():
            assert key in routes, f"Missing {key}"
            actual = routes[key]
            assert actual["cost"] == exp["cost"], (
                f"{key}: cost {actual['cost']} != expected {exp['cost']}"
            )
            assert actual["route_type"] == exp["route_type"], (
                f"{key}: type {actual['route_type']} != {exp['route_type']}"
            )
            if "next_hops" in exp:
                assert sorted(actual["next_hops"]) == sorted(exp["next_hops"]), (
                    f"{key}: nh {actual['next_hops']} != {exp['next_hops']}"
                )
