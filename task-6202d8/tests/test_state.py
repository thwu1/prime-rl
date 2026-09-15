
"""
Verification tests for Enterprise Network + DNA Center Compliance Audit task.
Checks all nine output artifacts for correctness.
"""

import json
import os
import pytest

OUTPUT_DIR = "/app/output"


def load_json(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    assert os.path.exists(path), f"Output file {filename} not found at {path}"
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Adjacency Audit
# ---------------------------------------------------------------------------
class TestAdjacencyAudit:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("adjacency_audit.json")

    def test_is_list(self):
        assert isinstance(self.data, list), "adjacency_audit.json must be a JSON array"

    def test_finds_at_least_three_issues(self):
        assert len(self.data) >= 3, f"Expected >= 3 adjacency issues, found {len(self.data)}"

    def test_finds_hello_timer_mismatch(self):
        found = False
        for issue in self.data:
            routers = set(issue.get("routers", []))
            text = json.dumps(issue).lower()
            if {"R2", "R4"}.issubset(routers) and ("hello" in text or "timer" in text or "dead" in text):
                found = True
                break
        assert found, "Must detect OSPF hello/dead timer mismatch between R2 and R4"

    def test_finds_mtu_mismatch(self):
        found = False
        for issue in self.data:
            routers = set(issue.get("routers", []))
            text = json.dumps(issue).lower()
            if {"R2", "R3"}.issubset(routers) and "mtu" in text:
                found = True
                break
        assert found, "Must detect OSPF MTU mismatch between R2 and R3 on backup link"

    def test_finds_area_type_mismatch(self):
        found = False
        for issue in self.data:
            routers = set(issue.get("routers", []))
            text = json.dumps(issue).lower()
            if {"R3", "R5"}.issubset(routers) and ("area" in text or "stub" in text or "nssa" in text):
                found = True
                break
        assert found, "Must detect OSPF area type mismatch (NSSA vs Stub) between R3 and R5"


# ---------------------------------------------------------------------------
# Redistribution Audit
# ---------------------------------------------------------------------------
class TestRedistributionAudit:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("redistribution_audit.json")

    def test_identifies_r4(self):
        routers = set(self.data.get("routers_with_issues", []))
        assert "R4" in routers, "Must identify R4 as having redistribution issues"

    def test_identifies_r5(self):
        routers = set(self.data.get("routers_with_issues", []))
        assert "R5" in routers, "Must identify R5 as having redistribution issues"

    def test_at_least_four_issues(self):
        issues = self.data.get("issues", [])
        assert len(issues) >= 4, (
            "Must find >= 4 redistribution issues "
            "(EIGRP->OSPF and OSPF->EIGRP on both R4 and R5)"
        )

    def test_issues_mention_missing_controls(self):
        issues = self.data.get("issues", [])
        for issue in issues:
            text = json.dumps(issue).lower()
            has_keyword = any(
                kw in text
                for kw in ["route-map", "route_map", "routemap", "tag", "filter", "prefix"]
            )
            assert has_keyword, (
                f"Each redistribution issue should mention missing route-map/tag/filter: {issue}"
            )


# ---------------------------------------------------------------------------
# BGP Audit
# ---------------------------------------------------------------------------
class TestBGPAudit:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("bgp_audit.json")

    def test_finds_next_hop_issue_on_r1(self):
        issues = self.data.get("issues", [])
        found = False
        for issue in issues:
            text = json.dumps(issue).lower()
            if issue.get("router") == "R1" and "next-hop" in text:
                found = True
                break
        assert found, "Must identify missing next-hop-self on R1 for iBGP peers"

    def test_affected_neighbors_include_r2_loopback(self):
        issues = self.data.get("issues", [])
        for issue in issues:
            if issue.get("router") == "R1":
                neighbors = issue.get("affected_neighbors", [])
                text = json.dumps(neighbors).lower()
                assert "10.0.0.2" in text, (
                    "R1 BGP issue must list 10.0.0.2 (R2) as affected neighbor"
                )
                return
        pytest.fail("No BGP issue found for R1")

    def test_affected_neighbors_include_r3_loopback(self):
        issues = self.data.get("issues", [])
        for issue in issues:
            if issue.get("router") == "R1":
                neighbors = issue.get("affected_neighbors", [])
                text = json.dumps(neighbors).lower()
                assert "10.0.0.3" in text, (
                    "R1 BGP issue must list 10.0.0.3 (R3) as affected neighbor"
                )
                return
        pytest.fail("No BGP issue found for R1")


# ---------------------------------------------------------------------------
# Security Audit
# ---------------------------------------------------------------------------
class TestSecurityAudit:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("security_audit.json")

    def test_finds_copp_issue(self):
        issues = self.data.get("issues", [])
        found = False
        for issue in issues:
            text = json.dumps(issue).lower()
            if issue.get("router") in ("R1", "R6") and (
                "copp" in text
                or "control-plane" in text
                or "control plane" in text
                or "service-policy" in text
            ):
                found = True
                break
        assert found, "Must identify missing CoPP / control-plane service-policy"

    def test_finds_vty_issue_r4(self):
        issues = self.data.get("issues", [])
        found = False
        for issue in issues:
            text = json.dumps(issue).lower()
            if issue.get("router") == "R4" and (
                "vty" in text or "access-class" in text or "access class" in text
            ):
                found = True
                break
        assert found, "Must identify missing VTY access-class on R4"

    def test_finds_vty_issue_r5(self):
        issues = self.data.get("issues", [])
        found = False
        for issue in issues:
            text = json.dumps(issue).lower()
            if issue.get("router") == "R5" and (
                "vty" in text or "access-class" in text or "access class" in text
            ):
                found = True
                break
        assert found, "Must identify missing VTY access-class on R5"


# ---------------------------------------------------------------------------
# IP Plan Audit
# ---------------------------------------------------------------------------
class TestIPPlanAudit:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("ip_plan_audit.json")

    def test_is_dict(self):
        assert isinstance(self.data, dict), "ip_plan_audit.json must be a JSON object"

    def test_total_planned_count(self):
        total = self.data.get("total_planned", 0)
        assert total == 23, f"Expected 23 planned IP allocations, got {total}"

    def test_has_deviations(self):
        devs = self.data.get("deviations", [])
        assert len(devs) >= 2, f"Expected >= 2 IP plan deviations, got {len(devs)}"

    def test_detects_r6_gi0_prefix_mismatch(self):
        devs = self.data.get("deviations", [])
        found = False
        for d in devs:
            if d.get("router") == "R6" and "GigabitEthernet0/0" in d.get("interface", ""):
                assert d.get("type") in (
                    "prefix_length_mismatch", "prefix_mismatch", "mask_mismatch"
                ), f"R6 Gi0/0 deviation type should indicate prefix length mismatch, got {d.get('type')}"
                planned = d.get("planned", {})
                assert planned.get("prefix_length") == 24, (
                    f"Design specifies prefix_length=24 for R6 Gi0/0, got {planned.get('prefix_length')}"
                )
                actual = d.get("actual", {})
                assert actual.get("prefix_length") == 30, (
                    f"Actual prefix_length should be 30 for R6 Gi0/0, got {actual.get('prefix_length')}"
                )
                found = True
                break
        assert found, "Must detect R6 GigabitEthernet0/0 prefix_length mismatch (design=24 vs actual=30)"

    def test_detects_r6_loopback1_missing(self):
        devs = self.data.get("deviations", [])
        found = False
        for d in devs:
            if d.get("router") == "R6" and "Loopback1" in d.get("interface", ""):
                assert d.get("type") in (
                    "missing_interface", "missing", "not_configured"
                ), f"R6 Loopback1 should be flagged as missing, got type={d.get('type')}"
                found = True
                break
        assert found, "Must detect R6 Loopback1 planned but not present in config"


# ---------------------------------------------------------------------------
# Topology Diagram (Graphviz SVG)
# ---------------------------------------------------------------------------
class TestTopologyDiagram:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.svg_path = os.path.join(OUTPUT_DIR, "topology.svg")

    def test_svg_exists(self):
        assert os.path.exists(self.svg_path), "topology.svg must exist in /app/output/"

    def test_svg_not_empty(self):
        size = os.path.getsize(self.svg_path)
        assert size > 500, f"topology.svg too small ({size} bytes), likely invalid"

    def test_svg_is_valid_xml(self):
        with open(self.svg_path) as f:
            content = f.read()
        assert "<svg" in content, "topology.svg must contain an <svg> element"

    def test_svg_contains_all_routers(self):
        with open(self.svg_path) as f:
            content = f.read()
        for router in ["R1", "R2", "R3", "R4", "R5", "R6"]:
            assert router in content, f"topology.svg must contain router {router}"

    def test_svg_has_issue_annotations(self):
        with open(self.svg_path) as f:
            content = f.read().lower()
        assert "red" in content or "#ff0000" in content or "#ff" in content, (
            "topology.svg must use red coloring for links with issues"
        )


# ---------------------------------------------------------------------------
# Path Analysis
# ---------------------------------------------------------------------------
class TestPathAnalysis:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("path_analysis.json")

    def _find_flow(self, flow_id):
        for flow in self.data.get("flows", []):
            if flow.get("id") == flow_id:
                return flow
        return None

    # -- Flow A: 10.4.1.0/24 -> 10.5.1.0/24 --
    def test_flow_a_exists(self):
        assert self._find_flow("flow_a") is not None, "Must include flow_a"

    def test_flow_a_reachable(self):
        flow = self._find_flow("flow_a")
        assert flow["status"] == "reachable", "flow_a must be reachable"

    def test_flow_a_path(self):
        flow = self._find_flow("flow_a")
        path = flow.get("path", [])
        assert path == ["R4", "R2", "R1", "R3", "R5"], (
            f"flow_a path should be [R4,R2,R1,R3,R5], got {path}"
        )

    # -- Flow B: 10.4.1.0/24 -> 10.0.0.1/32 --
    def test_flow_b_exists(self):
        assert self._find_flow("flow_b") is not None, "Must include flow_b"

    def test_flow_b_reachable(self):
        flow = self._find_flow("flow_b")
        assert flow["status"] == "reachable", "flow_b must be reachable"

    def test_flow_b_path(self):
        flow = self._find_flow("flow_b")
        path = flow.get("path", [])
        assert path == ["R4", "R2", "R1"], (
            f"flow_b path should be [R4,R2,R1], got {path}"
        )

    # -- Flow C: 10.5.1.0/24 -> 172.16.0.0/16 --
    def test_flow_c_exists(self):
        assert self._find_flow("flow_c") is not None, "Must include flow_c"

    def test_flow_c_unreachable(self):
        flow = self._find_flow("flow_c")
        assert flow["status"] == "unreachable", (
            "flow_c must be unreachable (BGP routes not redistributed into IGP)"
        )


# ---------------------------------------------------------------------------
# Remediation
# ---------------------------------------------------------------------------
class TestRemediation:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("remediation.json")

    def test_has_fixes(self):
        fixes = self.data.get("fixes", [])
        assert len(fixes) >= 5, "Must provide at least 5 remediation entries"

    def test_has_timer_fix(self):
        fixes = self.data.get("fixes", [])
        found = False
        for fix in fixes:
            text = json.dumps(fix).lower()
            if fix.get("router") in ("R4", "R2") and (
                "hello" in text or "timer" in text or "dead" in text
            ):
                found = True
                break
        assert found, "Must include fix for OSPF hello/dead timer mismatch"

    def test_has_mtu_fix(self):
        fixes = self.data.get("fixes", [])
        found = False
        for fix in fixes:
            text = json.dumps(fix).lower()
            if fix.get("router") in ("R2", "R3") and "mtu" in text:
                found = True
                break
        assert found, "Must include fix for MTU mismatch"

    def test_has_area_type_fix(self):
        fixes = self.data.get("fixes", [])
        found = False
        for fix in fixes:
            text = json.dumps(fix).lower()
            if fix.get("router") == "R5" and "nssa" in text:
                found = True
                break
        assert found, "Must include fix changing R5 area 20 from stub to NSSA"

    def test_has_next_hop_self_fix(self):
        fixes = self.data.get("fixes", [])
        found = False
        for fix in fixes:
            text = json.dumps(fix).lower()
            if fix.get("router") == "R1" and "next-hop-self" in text:
                found = True
                break
        assert found, "Must include BGP next-hop-self fix on R1"

    def test_has_redistribution_fix(self):
        fixes = self.data.get("fixes", [])
        found = False
        for fix in fixes:
            text = json.dumps(fix).lower()
            if fix.get("router") in ("R4", "R5") and "route-map" in text:
                found = True
                break
        assert found, "Must include route-map based redistribution fix"


# ---------------------------------------------------------------------------
# DNA Center Reconciliation
# ---------------------------------------------------------------------------
class TestDNACReconciliation:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("dnac_reconciliation.json")

    def test_is_dict(self):
        assert isinstance(self.data, dict), "dnac_reconciliation.json must be a JSON object"

    def test_identifies_unmanaged_device(self):
        unmanaged = self.data.get("unmanaged_devices", [])
        assert "R6" in unmanaged, "R6 must be listed as unmanaged (not in DNA Center inventory)"

    def test_managed_device_count(self):
        count = self.data.get("managed_device_count", 0)
        assert count == 5, f"Expected 5 managed devices, got {count}"

    def test_has_true_positives(self):
        tp = self.data.get("dnac_accuracy", {}).get("true_positives", [])
        assert len(tp) >= 2, f"Expected >= 2 true positives, got {len(tp)}"
        tp_text = json.dumps(tp).lower()
        assert "mtu" in tp_text or "r3" in tp_text.upper(), \
            "True positives should include R3 MTU issue"
        assert "area" in tp_text or "nssa" in tp_text or "stub" in tp_text or "r5" in tp_text.upper(), \
            "True positives should include R5 area type issue"

    def test_has_false_negatives(self):
        fn = self.data.get("dnac_accuracy", {}).get("false_negatives", [])
        assert len(fn) >= 3, f"Expected >= 3 false negatives, got {len(fn)}"
        fn_text = json.dumps(fn).lower()
        has_r1 = any(
            x in fn_text for x in ["next-hop", "next_hop", "nexthop"]
        ) or any(
            item.get("router") == "R1" for item in fn
        )
        assert has_r1, \
            "False negatives should include R1 BGP next-hop-self issue missed by DNAC"
        has_r4 = any(
            item.get("router") == "R4" for item in fn
        )
        assert has_r4, \
            "False negatives should include R4 issues missed by DNAC"

    def test_has_false_positive(self):
        fp = self.data.get("dnac_accuracy", {}).get("false_positives", [])
        assert len(fp) >= 1, f"Expected >= 1 false positive, got {len(fp)}"
        fp_text = json.dumps(fp).lower()
        assert "dhcp" in fp_text or "helper" in fp_text or "relay" in fp_text, \
            "False positives should include DHCP relay issue not in design spec"

    def test_r1_classified_inaccurate(self):
        per_device = self.data.get("per_device", {})
        r1 = per_device.get("R1", {})
        assert r1.get("dnac_status") == "COMPLIANT", \
            "R1 should show DNAC status as COMPLIANT"
        assert r1.get("assessment") in ("inaccurate", "incomplete", "false_negative"), \
            f"R1 assessment should indicate DNAC was inaccurate, got {r1.get('assessment')}"

    def test_r4_classified_inaccurate(self):
        per_device = self.data.get("per_device", {})
        r4 = per_device.get("R4", {})
        assert r4.get("dnac_status") == "COMPLIANT", \
            "R4 should show DNAC status as COMPLIANT"
        assert r4.get("assessment") in ("inaccurate", "incomplete", "false_negative"), \
            f"R4 assessment should indicate DNAC was inaccurate, got {r4.get('assessment')}"
