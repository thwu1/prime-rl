"""
Tests for OSPF Remediation Plan Evaluation task.
Validates that:
  1. Corrected FRR configs fix all three faults
  2. The evaluation report correctly identifies flaws in both proposals
  3. The diagnosis report identifies faulty devices
"""

import json
import os
import sys

import pytest

sys.path.insert(0, "/app")
from validate import FRRConfigParser, load_topology, validate_configs


# ============================================================
# Config Correctness Tests (existing)
# ============================================================


class TestValidatorPasses:
    """The corrected configs must pass all validator checks."""

    def test_fixed_configs_directory_exists(self):
        assert os.path.isdir("/app/fixed_configs"), (
            "/app/fixed_configs/ directory not found"
        )

    def test_all_config_files_present(self):
        topology = load_topology()
        for router_name in topology["routers"]:
            path = f"/app/fixed_configs/{router_name}.conf"
            assert os.path.isfile(path), f"Missing config: {path}"

    def test_validator_passes(self):
        topology = load_topology()
        errors = validate_configs("/app/fixed_configs", topology)
        assert len(errors) == 0, (
            f"Validator found {len(errors)} error(s):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


class TestFault1PassiveInterface:
    """Fault 1: dist_rtr2 must have eth0 non-passive."""

    def test_dist_rtr2_eth0_not_passive(self):
        config_path = "/app/fixed_configs/dist_rtr2.conf"
        if not os.path.isfile(config_path):
            pytest.skip("dist_rtr2.conf not found")
        with open(config_path) as f:
            parser = FRRConfigParser(f.read())
        assert not parser.is_interface_passive("eth0"), (
            "dist_rtr2 eth0 is still passive - OSPF adjacency with core_rtr "
            "cannot form"
        )


class TestFault2DistributeList:
    """Fault 2: core_rtr must not block 10.3.0.0/24 via distribute-list."""

    def test_core_rtr_does_not_block_host3_subnet(self):
        config_path = "/app/fixed_configs/core_rtr.conf"
        if not os.path.isfile(config_path):
            pytest.skip("core_rtr.conf not found")
        with open(config_path) as f:
            parser = FRRConfigParser(f.read())
        assert not parser.does_distribute_list_block("10.3.0.0/24"), (
            "core_rtr still blocks 10.3.0.0/24 via distribute-list"
        )

    def test_core_rtr_does_not_block_any_host_subnet(self):
        config_path = "/app/fixed_configs/core_rtr.conf"
        if not os.path.isfile(config_path):
            pytest.skip("core_rtr.conf not found")
        with open(config_path) as f:
            parser = FRRConfigParser(f.read())
        for subnet in ["10.1.0.0/24", "10.2.0.0/24", "10.3.0.0/24",
                        "10.100.0.0/24"]:
            assert not parser.does_distribute_list_block(subnet), (
                f"core_rtr blocks {subnet} via distribute-list"
            )


class TestFault3NetworkStatement:
    """Fault 3: dist_rtr1 must have correct OSPF network statement."""

    def test_dist_rtr1_eth1_in_ospf(self):
        config_path = "/app/fixed_configs/dist_rtr1.conf"
        if not os.path.isfile(config_path):
            pytest.skip("dist_rtr1.conf not found")
        with open(config_path) as f:
            parser = FRRConfigParser(f.read())
        assert parser.is_address_in_ospf("10.1.0.1/24"), (
            "dist_rtr1 eth1 (10.1.0.1/24) is not covered by any OSPF "
            "network statement - the host subnet 10.1.0.0/24 will not be "
            "advertised"
        )

    def test_dist_rtr1_no_wrong_network(self):
        config_path = "/app/fixed_configs/dist_rtr1.conf"
        if not os.path.isfile(config_path):
            pytest.skip("dist_rtr1.conf not found")
        with open(config_path) as f:
            parser = FRRConfigParser(f.read())
        assert not parser.is_address_in_ospf("10.10.0.1/24"), (
            "dist_rtr1 still has erroneous network 10.10.0.0/24 in OSPF"
        )


class TestNoRegressions:
    """Verify fixes don't introduce new issues."""

    def test_core_rtr_transit_links_not_passive(self):
        config_path = "/app/fixed_configs/core_rtr.conf"
        if not os.path.isfile(config_path):
            pytest.skip("core_rtr.conf not found")
        with open(config_path) as f:
            parser = FRRConfigParser(f.read())
        for iface in ["eth0", "eth1", "eth2"]:
            assert not parser.is_interface_passive(iface), (
                f"core_rtr {iface} became passive after fix"
            )

    def test_dist_rtr3_unchanged(self):
        config_path = "/app/fixed_configs/dist_rtr3.conf"
        if not os.path.isfile(config_path):
            pytest.skip("dist_rtr3.conf not found")
        with open(config_path) as f:
            parser = FRRConfigParser(f.read())
        assert not parser.is_interface_passive("eth0"), (
            "dist_rtr3 eth0 should remain non-passive"
        )
        assert parser.is_address_in_ospf("10.3.0.1/24"), (
            "dist_rtr3 eth1 should remain in OSPF"
        )

    def test_bogon_filter_preserved(self):
        """The BOGON_FILTER prefix-list is a security control and must be
        preserved in the corrected core_rtr config."""
        config_path = "/app/fixed_configs/core_rtr.conf"
        if not os.path.isfile(config_path):
            pytest.skip("core_rtr.conf not found")
        with open(config_path) as f:
            content = f.read()
        import re
        assert re.search(r"ip prefix-list\s+BOGON_FILTER\s+seq", content), (
            "BOGON_FILTER prefix-list definitions were removed from "
            "core_rtr - this is a security regression"
        )

    def test_dist_rtr1_network_not_overly_broad(self):
        """dist_rtr1 should use a specific /24 network statement, not a
        broad /8 that violates least privilege."""
        config_path = "/app/fixed_configs/dist_rtr1.conf"
        if not os.path.isfile(config_path):
            pytest.skip("dist_rtr1.conf not found")
        with open(config_path) as f:
            parser = FRRConfigParser(f.read())
        for net in parser.ospf["networks"]:
            try:
                import ipaddress
                ospf_net = ipaddress.ip_network(net["prefix"], strict=False)
                assert ospf_net.prefixlen >= 16, (
                    f"dist_rtr1 has overly broad OSPF network statement "
                    f"{net['prefix']} (/{ospf_net.prefixlen}) - violates "
                    f"principle of least privilege"
                )
            except ValueError:
                continue


# ============================================================
# Evaluation Report Tests (new - Bloom level: evaluate)
# ============================================================


class TestEvaluationReportExists:
    """Basic structure checks on the evaluation report."""

    def test_evaluation_file_exists(self):
        assert os.path.isfile("/app/evaluation.json"), (
            "/app/evaluation.json not found"
        )

    def test_evaluation_has_both_plans(self):
        with open("/app/evaluation.json") as f:
            data = json.load(f)
        assert "plan_a" in data, "evaluation.json must have 'plan_a' key"
        assert "plan_b" in data, "evaluation.json must have 'plan_b' key"

    def test_evaluation_has_required_fields(self):
        with open("/app/evaluation.json") as f:
            data = json.load(f)
        for plan_key in ["plan_a", "plan_b"]:
            plan = data[plan_key]
            for field in ["faults_correctly_fixed", "faults_missed",
                          "regressions_introduced", "recommendation"]:
                assert field in plan, (
                    f"evaluation.json {plan_key} missing '{field}'"
                )

    def test_evaluation_has_final_approach(self):
        with open("/app/evaluation.json") as f:
            data = json.load(f)
        assert "final_approach" in data, (
            "evaluation.json must have 'final_approach' key"
        )
        assert len(data["final_approach"]) > 20, (
            "final_approach description is too short"
        )


class TestPlanAEvaluation:
    """Verify the evaluation correctly identifies Plan A's flaws."""

    def test_plan_a_identifies_dist_rtr3_regression(self):
        """Plan A removes 'no passive-interface eth0' from dist_rtr3,
        breaking its OSPF adjacency with core_rtr. The evaluation must
        flag this."""
        with open("/app/evaluation.json") as f:
            data = json.load(f)
        plan_a = data["plan_a"]
        regressions = plan_a.get("regressions_introduced", [])
        regressions_text = json.dumps(regressions).lower()
        assert any(term in regressions_text for term in
                   ["dist_rtr3", "rtr3", "building c"]), (
            "Plan A evaluation must identify the dist_rtr3 passive-interface "
            "regression (eth0 made passive, breaking core adjacency)"
        )

    def test_plan_a_identifies_security_regression(self):
        """Plan A removes the BOGON_FILTER prefix-list, which is a
        defense-in-depth security control. The evaluation must flag this."""
        with open("/app/evaluation.json") as f:
            data = json.load(f)
        plan_a = data["plan_a"]
        regressions = plan_a.get("regressions_introduced", [])
        regressions_text = json.dumps(regressions).lower()
        assert any(term in regressions_text for term in
                   ["bogon", "security", "filter removal",
                    "prefix-list removal", "defense"]), (
            "Plan A evaluation must identify the BOGON_FILTER removal as a "
            "security regression"
        )

    def test_plan_a_has_regressions(self):
        """Plan A introduces at least 2 regressions."""
        with open("/app/evaluation.json") as f:
            data = json.load(f)
        plan_a = data["plan_a"]
        regressions = plan_a.get("regressions_introduced", [])
        assert len(regressions) >= 2, (
            f"Plan A has 2 regressions (dist_rtr3 passive, BOGON_FILTER "
            f"removed) but evaluation only found {len(regressions)}"
        )

    def test_plan_a_not_accepted(self):
        """Plan A should not be accepted as-is due to regressions."""
        with open("/app/evaluation.json") as f:
            data = json.load(f)
        rec = data["plan_a"]["recommendation"].lower()
        assert rec != "accept", (
            "Plan A should not be 'accept' - it introduces regressions"
        )


class TestPlanBEvaluation:
    """Verify the evaluation correctly identifies Plan B's flaws."""

    def test_plan_b_identifies_missed_dist_rtr2_fault(self):
        """Plan B does not fix dist_rtr2's passive-interface issue.
        The evaluation must flag this as a missed fault."""
        with open("/app/evaluation.json") as f:
            data = json.load(f)
        plan_b = data["plan_b"]
        missed = plan_b.get("faults_missed", [])
        missed_text = json.dumps(missed).lower()
        assert any(term in missed_text for term in
                   ["dist_rtr2", "rtr2", "passive", "building b"]), (
            "Plan B evaluation must identify that dist_rtr2's "
            "passive-interface fault was missed"
        )

    def test_plan_b_identifies_overly_broad_network(self):
        """Plan B uses 10.0.0.0/8 as an OSPF network statement on
        dist_rtr1, which is overly broad and violates least privilege.
        The evaluation must flag this."""
        with open("/app/evaluation.json") as f:
            data = json.load(f)
        plan_b = data["plan_b"]
        regressions = plan_b.get("regressions_introduced", [])
        regressions_text = json.dumps(regressions).lower()
        assert any(term in regressions_text for term in
                   ["broad", "10.0.0.0", "/8", "overl", "wide",
                    "privilege", "specific"]), (
            "Plan B evaluation must identify the overly broad 10.0.0.0/8 "
            "network statement on dist_rtr1"
        )

    def test_plan_b_not_accepted(self):
        """Plan B should not be accepted as-is due to missed fault and
        overly broad network statement."""
        with open("/app/evaluation.json") as f:
            data = json.load(f)
        rec = data["plan_b"]["recommendation"].lower()
        assert rec != "accept", (
            "Plan B should not be 'accept' - it misses a fault and "
            "introduces an overly broad network statement"
        )


# ============================================================
# Diagnosis Report Tests (existing)
# ============================================================


class TestDiagnosisReport:
    """Verify the diagnosis report exists and identifies the right devices."""

    def test_diagnosis_file_exists(self):
        assert os.path.isfile("/app/diagnosis.json"), (
            "/app/diagnosis.json not found"
        )

    def test_diagnosis_has_three_faults(self):
        with open("/app/diagnosis.json") as f:
            data = json.load(f)
        assert "faults" in data, "diagnosis.json must have a 'faults' key"
        assert len(data["faults"]) >= 3, (
            f"Expected at least 3 faults, found {len(data['faults'])}"
        )

    def test_diagnosis_identifies_faulty_devices(self):
        with open("/app/diagnosis.json") as f:
            data = json.load(f)
        devices = set()
        for fault in data["faults"]:
            dev = fault.get("device", "").lower().replace("-", "_")
            devices.add(dev)

        assert any("dist" in d and "2" in d for d in devices), (
            "Diagnosis should identify dist_rtr2 as faulty"
        )
        assert any("core" in d for d in devices), (
            "Diagnosis should identify core_rtr as faulty"
        )
        assert any("dist" in d and "1" in d for d in devices), (
            "Diagnosis should identify dist_rtr1 as faulty"
        )

    def test_diagnosis_has_root_causes(self):
        with open("/app/diagnosis.json") as f:
            data = json.load(f)
        for fault in data["faults"]:
            assert "root_cause" in fault, (
                f"Fault entry for {fault.get('device', '?')} missing "
                f"root_cause"
            )
            assert len(fault["root_cause"]) > 10, (
                f"Root cause for {fault.get('device', '?')} is too short"
            )
