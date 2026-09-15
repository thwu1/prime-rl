
import json
import os
import pytest


def load_json(path):
    with open(path) as f:
        return json.load(f)


# ──────────────────────────────────────────────
# Output files must exist
# ──────────────────────────────────────────────

class TestOutputFilesExist:
    def test_ospf_costs_exists(self):
        assert os.path.isfile("/app/output/ospf_costs.json"), "ospf_costs.json not found"

    def test_bgp_best_paths_exists(self):
        assert os.path.isfile("/app/output/bgp_best_paths.json"), "bgp_best_paths.json not found"

    def test_rib_exists(self):
        assert os.path.isfile("/app/output/rib.json"), "rib.json not found"

    def test_issues_exists(self):
        assert os.path.isfile("/app/output/issues.json"), "issues.json not found"


# ──────────────────────────────────────────────
# OSPF intra-area costs (Area 0 backbone)
# ──────────────────────────────────────────────

class TestOSPFIntraArea0:
    @pytest.fixture
    def costs(self):
        return load_json("/app/output/ospf_costs.json")

    def test_r1_r2(self, costs):
        assert costs["R1"]["R2"] == 5

    def test_r1_r3(self, costs):
        assert costs["R1"]["R3"] == 10

    def test_r1_r4(self, costs):
        assert costs["R1"]["R4"] == 15

    def test_r2_r3(self, costs):
        assert costs["R2"]["R3"] == 15

    def test_r2_r4(self, costs):
        assert costs["R2"]["R4"] == 10

    def test_r3_r4(self, costs):
        assert costs["R3"]["R4"] == 20

    def test_r4_r1(self, costs):
        assert costs["R4"]["R1"] == 15

    def test_r4_r3(self, costs):
        assert costs["R4"]["R3"] == 20


# ──────────────────────────────────────────────
# OSPF intra-area costs (non-backbone)
# ──────────────────────────────────────────────

class TestOSPFIntraAreaNonBackbone:
    @pytest.fixture
    def costs(self):
        return load_json("/app/output/ospf_costs.json")

    def test_r3_r5(self, costs):
        assert costs["R3"]["R5"] == 10

    def test_r5_r3(self, costs):
        assert costs["R5"]["R3"] == 10

    def test_r4_r6(self, costs):
        assert costs["R4"]["R6"] == 10

    def test_r6_r4(self, costs):
        assert costs["R6"]["R4"] == 10


# ──────────────────────────────────────────────
# OSPF inter-area costs
# ──────────────────────────────────────────────

class TestOSPFInterArea:
    @pytest.fixture
    def costs(self):
        return load_json("/app/output/ospf_costs.json")

    def test_r1_r5(self, costs):
        assert costs["R1"]["R5"] == 20

    def test_r1_r6(self, costs):
        assert costs["R1"]["R6"] == 25

    def test_r2_r5(self, costs):
        assert costs["R2"]["R5"] == 25

    def test_r2_r6(self, costs):
        assert costs["R2"]["R6"] == 20

    def test_r3_r6(self, costs):
        assert costs["R3"]["R6"] == 30

    def test_r4_r5(self, costs):
        assert costs["R4"]["R5"] == 30

    def test_r5_r6_cross_area(self, costs):
        assert costs["R5"]["R6"] == 40

    def test_r6_r5_cross_area(self, costs):
        assert costs["R6"]["R5"] == 40

    def test_r5_r1(self, costs):
        assert costs["R5"]["R1"] == 20

    def test_r6_r2(self, costs):
        assert costs["R6"]["R2"] == 20

    def test_r6_r1(self, costs):
        assert costs["R6"]["R1"] == 25

    def test_r5_r4(self, costs):
        assert costs["R5"]["R4"] == 30


# ──────────────────────────────────────────────
# BGP best path selection
# ──────────────────────────────────────────────

class TestBGPBestPath:
    @pytest.fixture
    def bgp(self):
        return load_json("/app/output/bgp_best_paths.json")

    def test_r1_203_selects_ibgp(self, bgp):
        """R1 has eBGP from ISP-A (LP 150) and iBGP from R2 (LP 200).
        BGP selects iBGP due to higher local-pref."""
        path = bgp["R1"]["203.0.113.0/24"]
        assert path["selected_via"] == "ibgp"
        assert path["local_pref"] == 200
        assert path["decision_reason"] == "local_pref"

    def test_r2_203_selects_ebgp(self, bgp):
        """R2 has eBGP from ISP-B (LP 200) and iBGP from R1 (LP 150).
        BGP selects eBGP due to higher local-pref."""
        path = bgp["R2"]["203.0.113.0/24"]
        assert path["selected_via"] == "ebgp"
        assert path["local_pref"] == 200

    def test_r1_198_ebgp_only(self, bgp):
        """198.51.100.0/24 only received by R1 via eBGP from ISP-A."""
        path = bgp["R1"]["198.51.100.0/24"]
        assert path["as_path"] == [65100, 65300]
        assert path["local_pref"] == 150
        assert path["selected_via"] == "ebgp"

    def test_r2_192_incomplete_origin(self, bgp):
        """192.0.2.0/24 has origin incomplete."""
        path = bgp["R2"]["192.0.2.0/24"]
        assert path["origin"] == "incomplete"
        assert path["as_path"] == [65200, 65400]

    def test_r1_has_three_prefixes(self, bgp):
        """R1 should have exactly 3 BGP prefixes."""
        assert len(bgp["R1"]) == 3

    def test_r2_has_three_prefixes(self, bgp):
        """R2 should have exactly 3 BGP prefixes."""
        assert len(bgp["R2"]) == 3

    def test_r1_192_via_ibgp(self, bgp):
        """192.0.2.0/24 only available to R1 via iBGP from R2."""
        path = bgp["R1"]["192.0.2.0/24"]
        assert path["selected_via"] == "ibgp"
        assert path["local_pref"] == 200

    def test_r2_198_via_ibgp(self, bgp):
        """198.51.100.0/24 only available to R2 via iBGP from R1."""
        path = bgp["R2"]["198.51.100.0/24"]
        assert path["selected_via"] == "ibgp"
        assert path["local_pref"] == 150


# ──────────────────────────────────────────────
# RIB: admin distance and protocol selection
# ──────────────────────────────────────────────

class TestRIB:
    @pytest.fixture
    def rib(self):
        return load_json("/app/output/rib.json")

    def test_r1_static_shadows_ospf(self, rib):
        """R1 has static route (AD 1) to 172.16.5.0/24 via null0,
        which shadows the OSPF E2 route (AD 110)."""
        entry = rib["R1"]["172.16.5.0/24"]
        assert entry["protocol"] == "static"
        assert entry["admin_distance"] == 1
        assert entry["next_hop"] == "null0"

    def test_r2_ospf_e2_172_16_5(self, rib):
        """R2 installs OSPF E2 route for 172.16.5.0/24 (no static)."""
        entry = rib["R2"]["172.16.5.0/24"]
        assert entry["protocol"] == "ospf_e2"
        assert entry["admin_distance"] == 110
        assert entry["metric"] == 100

    def test_r2_ospf_e2_172_16_6(self, rib):
        """R2 installs OSPF E2 route for 172.16.6.0/24."""
        entry = rib["R2"]["172.16.6.0/24"]
        assert entry["protocol"] == "ospf_e2"
        assert entry["admin_distance"] == 110
        assert entry["metric"] == 100

    def test_r1_bgp_203_ibgp_ad(self, rib):
        """R1's best BGP path for 203.0.113.0/24 is iBGP -> AD 200."""
        entry = rib["R1"]["203.0.113.0/24"]
        assert entry["admin_distance"] == 200
        assert entry["protocol"] == "ibgp"

    def test_r2_bgp_203_ebgp_ad(self, rib):
        """R2's best BGP path for 203.0.113.0/24 is eBGP -> AD 20."""
        entry = rib["R2"]["203.0.113.0/24"]
        assert entry["admin_distance"] == 20
        assert entry["protocol"] == "ebgp"

    def test_r1_bgp_198_ebgp_ad(self, rib):
        """R1's best BGP path for 198.51.100.0/24 is eBGP -> AD 20."""
        entry = rib["R1"]["198.51.100.0/24"]
        assert entry["admin_distance"] == 20
        assert entry["protocol"] == "ebgp"

    def test_r6_ospf_route_to_r1(self, rib):
        """R6 reaches R1's loopback via OSPF inter-area, cost 25."""
        entry = rib["R6"]["10.0.0.1/32"]
        assert entry["protocol"] == "ospf"
        assert entry["metric"] == 25

    def test_r5_ospf_route_to_r2(self, rib):
        """R5 reaches R2's loopback via OSPF inter-area, cost 25."""
        entry = rib["R5"]["10.0.0.2/32"]
        assert entry["protocol"] == "ospf"
        assert entry["metric"] == 25

    def test_r5_connected_172(self, rib):
        """R5 is directly connected to 172.16.5.0/24."""
        entry = rib["R5"]["172.16.5.0/24"]
        assert entry["protocol"] == "connected"
        assert entry["admin_distance"] == 0


# ──────────────────────────────────────────────
# Issue detection
# ──────────────────────────────────────────────

class TestIssues:
    @pytest.fixture
    def issues(self):
        return load_json("/app/output/issues.json")

    def test_at_least_two_issues(self, issues):
        assert len(issues) >= 2, "Should detect at least 2 routing anomalies"

    def test_static_shadowing_detected(self, issues):
        """Must detect the null0 static route shadowing OSPF E2 for 172.16.5.0/24."""
        text = json.dumps(issues).lower()
        assert "172.16.5.0" in text, "Must reference the shadowed prefix 172.16.5.0/24"
        has_keyword = any(w in text for w in [
            "shadow", "blackhole", "null0", "masked", "hidden", "unreachable", "static"
        ])
        assert has_keyword, "Must describe the route shadowing / blackhole condition"

    def test_bgp_suboptimality_detected(self, issues):
        """Must detect BGP selecting iBGP over available eBGP for 203.0.113.0/24 on R1."""
        text = json.dumps(issues).lower()
        assert "203.0.113.0" in text, "Must reference the BGP prefix 203.0.113.0/24"
        has_keyword = any(w in text for w in [
            "suboptimal", "ibgp", "local_pref", "local-pref", "bgp"
        ])
        assert has_keyword, "Must describe the BGP suboptimality condition"

    def test_issues_have_required_fields(self, issues):
        """Each issue must have type, router, prefix, description."""
        for issue in issues:
            assert "type" in issue, f"Issue missing 'type' field: {issue}"
            assert "router" in issue, f"Issue missing 'router' field: {issue}"
            assert "prefix" in issue, f"Issue missing 'prefix' field: {issue}"
            assert "description" in issue, f"Issue missing 'description' field: {issue}"
