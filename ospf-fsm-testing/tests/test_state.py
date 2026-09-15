
import json
import os
import pytest


def load_json(path):
    with open(path) as f:
        return json.load(f)


def find_pair(adjacencies, rid_a, rid_b):
    """Find adjacency entry matching a router pair in either order."""
    for adj in adjacencies:
        ra = adj.get("router_a", "")
        rb = adj.get("router_b", "")
        if (rid_a in ra and rid_b in rb) or (rid_a in rb and rid_b in ra):
            return adj
    return None


def find_violations_for_router(violations, rid):
    """Find all violations mentioning a specific router ID."""
    return [v for v in violations if rid in v.get("router_id", "")]


# ==================== Packet Inventory Tests ====================

class TestPacketInventory:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.inv = load_json("/app/output/packet_inventory.json")

    def test_file_exists(self):
        assert os.path.isfile("/app/output/packet_inventory.json")

    def test_total_packets(self):
        assert self.inv["total_packets"] == 46, (
            f"Expected 46 total packets, got {self.inv['total_packets']}"
        )

    def test_hello_count(self):
        assert self.inv["hello_packets"] == 25, (
            f"Expected 25 Hello packets, got {self.inv['hello_packets']}"
        )

    def test_dd_count(self):
        assert self.inv["dd_packets"] == 21, (
            f"Expected 21 DD packets, got {self.inv['dd_packets']}"
        )

    def test_five_routers_observed(self):
        routers = self.inv["routers_observed"]
        assert len(routers) == 5, f"Expected 5 routers, got {len(routers)}: {routers}"

    def test_all_router_ids_present(self):
        expected = {"1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4", "5.5.5.5"}
        observed = set(self.inv["routers_observed"])
        assert expected == observed, f"Missing: {expected - observed}, extra: {observed - expected}"

    def test_packets_array_populated(self):
        assert len(self.inv["packets"]) == 46

    def test_hello_packets_have_interval_field(self):
        hellos = [p for p in self.inv["packets"] if p["ospf_type"] == 1]
        assert len(hellos) == 25
        for h in hellos:
            assert "hello_interval" in h, f"Packet {h.get('packet_number')}: missing hello_interval"

    def test_dd_packets_have_mtu_field(self):
        dds = [p for p in self.inv["packets"] if p["ospf_type"] == 2]
        assert len(dds) == 21
        for d in dds:
            assert "mtu" in d, f"Packet {d.get('packet_number')}: missing mtu"

    def test_r3_hello_interval_captured(self):
        """R3's misconfigured HelloInterval=30 must be visible in inventory."""
        r3_hellos = [p for p in self.inv["packets"]
                     if p["ospf_type"] == 1 and p["router_id"] == "3.3.3.3"]
        assert len(r3_hellos) >= 1
        assert r3_hellos[0]["hello_interval"] == 30, (
            f"R3 HelloInterval should be 30, got {r3_hellos[0]['hello_interval']}"
        )

    def test_r4_mtu_captured(self):
        """R4's MTU=9000 in DD packets must be visible in inventory."""
        r4_dds = [p for p in self.inv["packets"]
                  if p["ospf_type"] == 2 and p["router_id"] == "4.4.4.4"]
        assert len(r4_dds) >= 1
        assert r4_dds[0]["mtu"] == 9000, (
            f"R4 DD MTU should be 9000, got {r4_dds[0]['mtu']}"
        )

    def test_r5_ebit_captured(self):
        """R5's E-bit=false must be visible in inventory."""
        r5_hellos = [p for p in self.inv["packets"]
                     if p["ospf_type"] == 1 and p["router_id"] == "5.5.5.5"]
        assert len(r5_hellos) >= 1
        assert r5_hellos[0]["options_e_bit"] is False, (
            f"R5 E-bit should be False, got {r5_hellos[0]['options_e_bit']}"
        )


# ==================== Adjacency Matrix Tests ====================

class TestAdjacencyMatrix:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.matrix = load_json("/app/output/adjacency_matrix.json")
        self.adjs = self.matrix["adjacencies"]

    def test_file_exists(self):
        assert os.path.isfile("/app/output/adjacency_matrix.json")

    def test_has_adjacency_entries(self):
        assert len(self.adjs) >= 5, f"Expected >= 5 adjacency pairs, got {len(self.adjs)}"

    def test_r1_r2_full(self):
        pair = find_pair(self.adjs, "1.1.1.1", "2.2.2.2")
        assert pair is not None, "Missing R1-R2 adjacency entry"
        assert "Full" in pair["final_state"], (
            f"R1-R2 should reach Full, got {pair['final_state']}"
        )
        assert pair["successful"] is True, "R1-R2 should be successful"

    def test_r1_r4_exstart(self):
        pair = find_pair(self.adjs, "1.1.1.1", "4.4.4.4")
        assert pair is not None, "Missing R1-R4 adjacency entry"
        assert "ExStart" in pair["final_state"], (
            f"R1-R4 should stall at ExStart, got {pair['final_state']}"
        )
        assert pair["successful"] is False

    def test_r2_r4_exstart(self):
        pair = find_pair(self.adjs, "2.2.2.2", "4.4.4.4")
        assert pair is not None, "Missing R2-R4 adjacency entry"
        assert "ExStart" in pair["final_state"], (
            f"R2-R4 should stall at ExStart, got {pair['final_state']}"
        )
        assert pair["successful"] is False

    def test_r1_r3_down(self):
        pair = find_pair(self.adjs, "1.1.1.1", "3.3.3.3")
        assert pair is not None, "Missing R1-R3 adjacency entry"
        assert pair["final_state"] == "Down", (
            f"R1-R3 should be Down (Hello rejected), got {pair['final_state']}"
        )
        assert pair["successful"] is False

    def test_r1_r5_down(self):
        pair = find_pair(self.adjs, "1.1.1.1", "5.5.5.5")
        assert pair is not None, "Missing R1-R5 adjacency entry"
        assert pair["final_state"] == "Down", (
            f"R1-R5 should be Down (Hello rejected), got {pair['final_state']}"
        )
        assert pair["successful"] is False

    def test_r1_r4_failure_mentions_mtu(self):
        pair = find_pair(self.adjs, "1.1.1.1", "4.4.4.4")
        assert pair is not None
        reason = pair.get("failure_reason", "").lower()
        assert "mtu" in reason, (
            f"R1-R4 failure reason should mention MTU: '{pair.get('failure_reason')}'"
        )

    def test_r1_r3_failure_mentions_hello_or_timer(self):
        pair = find_pair(self.adjs, "1.1.1.1", "3.3.3.3")
        assert pair is not None
        reason = pair.get("failure_reason", "").lower()
        assert "hello" in reason or "interval" in reason or "timer" in reason, (
            f"R1-R3 failure should mention hello/interval/timer: '{pair.get('failure_reason')}'"
        )

    def test_r1_r5_failure_mentions_ebit_or_options(self):
        pair = find_pair(self.adjs, "1.1.1.1", "5.5.5.5")
        assert pair is not None
        reason = pair.get("failure_reason", "").lower()
        assert "e-bit" in reason or "e_bit" in reason or "option" in reason or "ebit" in reason or "stub" in reason, (
            f"R1-R5 failure should mention E-bit/options: '{pair.get('failure_reason')}'"
        )


# ==================== Protocol Violations Tests ====================

class TestProtocolViolations:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.viols = load_json("/app/output/protocol_violations.json")
        self.violations = self.viols["violations"]

    def test_file_exists(self):
        assert os.path.isfile("/app/output/protocol_violations.json")

    def test_at_least_three_violations(self):
        assert len(self.violations) >= 3, (
            f"Expected >= 3 violations, got {len(self.violations)}"
        )

    def test_r3_hello_interval_violation(self):
        r3_viols = find_violations_for_router(self.violations, "3.3.3.3")
        assert len(r3_viols) >= 1, "No violation found for R3 (3.3.3.3)"
        vtype = " ".join(v.get("violation_type", "") for v in r3_viols).lower()
        assert "hello" in vtype or "interval" in vtype or "timer" in vtype, (
            f"R3 violation should mention hello/interval/timer: {[v['violation_type'] for v in r3_viols]}"
        )

    def test_r3_cites_section_10_5(self):
        r3_viols = find_violations_for_router(self.violations, "3.3.3.3")
        assert any("10.5" in v.get("rfc_section", "") for v in r3_viols), (
            f"R3 violation should cite RFC section 10.5"
        )

    def test_r4_mtu_violation(self):
        r4_viols = find_violations_for_router(self.violations, "4.4.4.4")
        assert len(r4_viols) >= 1, "No violation found for R4 (4.4.4.4)"
        vtype = " ".join(v.get("violation_type", "") for v in r4_viols).lower()
        assert "mtu" in vtype, (
            f"R4 violation should mention MTU: {[v['violation_type'] for v in r4_viols]}"
        )

    def test_r4_cites_section_10_6(self):
        r4_viols = find_violations_for_router(self.violations, "4.4.4.4")
        assert any("10.6" in v.get("rfc_section", "") for v in r4_viols), (
            f"R4 violation should cite RFC section 10.6"
        )

    def test_r5_ebit_violation(self):
        r5_viols = find_violations_for_router(self.violations, "5.5.5.5")
        assert len(r5_viols) >= 1, "No violation found for R5 (5.5.5.5)"
        vtype = " ".join(v.get("violation_type", "") for v in r5_viols).lower()
        assert "e-bit" in vtype or "e_bit" in vtype or "option" in vtype or "ebit" in vtype, (
            f"R5 violation should mention E-bit/options: {[v['violation_type'] for v in r5_viols]}"
        )

    def test_r5_cites_section_10_5(self):
        r5_viols = find_violations_for_router(self.violations, "5.5.5.5")
        assert any("10.5" in v.get("rfc_section", "") for v in r5_viols), (
            f"R5 violation should cite RFC section 10.5"
        )

    def test_violations_have_evidence(self):
        for v in self.violations:
            assert "evidence" in v and len(v["evidence"]) > 0, (
                f"Violation for {v.get('router_id')} missing evidence"
            )

    def test_violations_have_affected_pairs(self):
        for v in self.violations:
            assert "affected_pairs" in v and len(v["affected_pairs"]) > 0, (
                f"Violation for {v.get('router_id')} missing affected_pairs"
            )


# ==================== Root Cause Report Tests ====================

class TestRootCauseReport:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.report = load_json("/app/output/root_cause_report.json")

    def test_file_exists(self):
        assert os.path.isfile("/app/output/root_cause_report.json")

    def test_successful_count(self):
        assert self.report["successful_adjacencies"] == 1, (
            f"Expected 1 successful adjacency, got {self.report['successful_adjacencies']}"
        )

    def test_failed_count(self):
        assert self.report["failed_adjacencies"] >= 3, (
            f"Expected >= 3 failed adjacencies, got {self.report['failed_adjacencies']}"
        )

    def test_at_least_three_root_causes(self):
        rcs = self.report["root_causes"]
        assert len(rcs) >= 3, f"Expected >= 3 root causes, got {len(rcs)}"

    def test_root_cause_covers_timer(self):
        rcs = self.report["root_causes"]
        texts = " ".join(
            f"{rc.get('category','')} {rc.get('description','')}".lower()
            for rc in rcs
        )
        assert "timer" in texts or "hello" in texts or "interval" in texts, (
            "Root causes should include timer/HelloInterval mismatch"
        )

    def test_root_cause_covers_mtu(self):
        rcs = self.report["root_causes"]
        texts = " ".join(
            f"{rc.get('category','')} {rc.get('description','')}".lower()
            for rc in rcs
        )
        assert "mtu" in texts, "Root causes should include MTU mismatch"

    def test_root_cause_covers_ebit(self):
        rcs = self.report["root_causes"]
        texts = " ".join(
            f"{rc.get('category','')} {rc.get('description','')}".lower()
            for rc in rcs
        )
        assert "e-bit" in texts or "e_bit" in texts or "option" in texts or "ebit" in texts or "stub" in texts, (
            "Root causes should include E-bit/Options mismatch"
        )

    def test_root_causes_have_required_fields(self):
        for rc in self.report["root_causes"]:
            assert "category" in rc, f"Root cause missing 'category'"
            assert "affected_router" in rc, f"Root cause missing 'affected_router'"
            assert "description" in rc and len(rc["description"]) > 20, (
                f"Root cause missing or too-short 'description'"
            )
            assert "rfc_reference" in rc, f"Root cause missing 'rfc_reference'"
            assert "remediation" in rc and len(rc["remediation"]) > 10, (
                f"Root cause missing or too-short 'remediation'"
            )

    def test_root_cause_routers_identified(self):
        rcs = self.report["root_causes"]
        affected = {rc.get("affected_router", "") for rc in rcs}
        assert "3.3.3.3" in affected, "Root causes should identify R3 (3.3.3.3)"
        assert "4.4.4.4" in affected, "Root causes should identify R4 (4.4.4.4)"
        assert "5.5.5.5" in affected, "Root causes should identify R5 (5.5.5.5)"
