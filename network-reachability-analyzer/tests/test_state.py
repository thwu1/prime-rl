#!/usr/bin/env python3
"""Tests for the network reachability analysis engine."""


import json
import subprocess
import os
import re
import pytest


@pytest.fixture(scope="session")
def engine_result():
    """Run the engine once before all tests."""
    result = subprocess.run(
        ["python3", "/app/engine.py"],
        capture_output=True, timeout=120, cwd="/app"
    )
    return result


@pytest.fixture(scope="session")
def report(engine_result):
    """Load the generated report."""
    assert os.path.exists("/app/report.json"), (
        f"report.json not generated. Engine stderr: {engine_result.stderr.decode()[:500]}"
    )
    with open("/app/report.json") as f:
        data = json.load(f)
    assert isinstance(data, dict), "report.json root must be a JSON object"
    return data


def _find_reach(report, src, dst):
    """Find reachability result for a src->dst pair."""
    for entry in report.get("reachability", []):
        if entry.get("src") == src and entry.get("dst") == dst:
            return entry.get("reachable")
    return None


# ── Engine execution ────────────────────────────────────────────────

class TestEngineExecution:
    def test_engine_file_exists(self):
        assert os.path.exists("/app/engine.py"), "engine.py not found at /app/"

    def test_engine_exits_zero(self, engine_result):
        assert engine_result.returncode == 0, (
            f"engine.py exited with code {engine_result.returncode}: "
            f"{engine_result.stderr.decode()[:500]}"
        )

    def test_report_file_exists(self, engine_result):
        assert os.path.exists("/app/report.json"), "report.json not generated"


# ── Report structure ────────────────────────────────────────────────

class TestReportStructure:
    def test_has_reachability_key(self, report):
        assert "reachability" in report

    def test_has_misconfigurations_key(self, report):
        assert "misconfigurations" in report

    def test_reachability_is_list(self, report):
        assert isinstance(report["reachability"], list)

    def test_reachability_count(self, report):
        """7 hosts => 42 ordered pairs"""
        assert len(report["reachability"]) == 42, (
            f"Expected 42 reachability entries, got {len(report['reachability'])}"
        )

    def test_reachability_entry_fields(self, report):
        for entry in report["reachability"]:
            assert "src" in entry, f"Missing 'src' in entry: {entry}"
            assert "dst" in entry, f"Missing 'dst' in entry: {entry}"
            assert "reachable" in entry, f"Missing 'reachable' in entry: {entry}"
            assert isinstance(entry["reachable"], bool), (
                f"'reachable' must be bool, got {type(entry['reachable'])}"
            )


# ── Same-subnet reachability ───────────────────────────────────────

class TestSameSubnet:
    def test_server1_to_server2(self, report):
        assert _find_reach(report, "10.1.0.10", "10.1.0.11") is True

    def test_server2_to_server1(self, report):
        assert _find_reach(report, "10.1.0.11", "10.1.0.10") is True

    def test_user1_to_user2(self, report):
        assert _find_reach(report, "10.2.0.10", "10.2.0.11") is True

    def test_user2_to_user1(self, report):
        assert _find_reach(report, "10.2.0.11", "10.2.0.10") is True


# ── Cross-subnet reachability (should work) ─────────────────────────

class TestCrossSubnetReachable:
    def test_server_to_user(self, report):
        """Server1 -> User1 via R2->R1->R3"""
        assert _find_reach(report, "10.1.0.10", "10.2.0.10") is True

    def test_user_to_server(self, report):
        """User1 -> Server1 via R3->R1->R2"""
        assert _find_reach(report, "10.2.0.10", "10.1.0.10") is True

    def test_server_to_branch(self, report):
        """Server1 -> Branch1 via R2->R4"""
        assert _find_reach(report, "10.1.0.10", "10.4.0.10") is True

    def test_branch_to_server(self, report):
        """Branch1 -> Server1 via R4->R2 (directly connected)"""
        assert _find_reach(report, "10.4.0.10", "10.1.0.10") is True

    def test_user_to_branch(self, report):
        """User1 -> Branch1 via R3->R1->R2->R4"""
        assert _find_reach(report, "10.2.0.10", "10.4.0.10") is True

    def test_branch_to_user(self, report):
        """Branch1 -> User1 via R4->R2->R1->R3"""
        assert _find_reach(report, "10.4.0.10", "10.2.0.10") is True

    def test_guest_to_user_same_router(self, report):
        """Guest1 -> User1: both on R3, directly connected"""
        assert _find_reach(report, "10.3.0.10", "10.2.0.10") is True

    def test_user_to_guest_same_router(self, report):
        """User1 -> Guest1: both on R3, directly connected"""
        assert _find_reach(report, "10.2.0.10", "10.3.0.10") is True


# ── Black hole: traffic TO guest subnet via R2 is unreachable ───────

class TestBlackHole:
    def test_server_to_guest_unreachable(self, report):
        """Server1 -> Guest1: R2 has bad route 10.3.0.0/24 via 10.0.0.13"""
        assert _find_reach(report, "10.1.0.10", "10.3.0.10") is False

    def test_server2_to_guest_unreachable(self, report):
        """Server2 -> Guest1: same black hole at R2"""
        assert _find_reach(report, "10.1.0.11", "10.3.0.10") is False

    def test_branch_to_guest_unreachable(self, report):
        """Branch1 -> Guest1: R4->R2, then R2 black-holes 10.3.0.0/24"""
        assert _find_reach(report, "10.4.0.10", "10.3.0.10") is False

    def test_guest_to_server_reachable_asymmetric(self, report):
        """Guest1 -> Server1 IS reachable: R3->R1->R2 (bypasses R2's bad route)"""
        assert _find_reach(report, "10.3.0.10", "10.1.0.10") is True

    def test_guest_to_branch_reachable_asymmetric(self, report):
        """Guest1 -> Branch1 IS reachable: R3->R1->R2->R4"""
        assert _find_reach(report, "10.3.0.10", "10.4.0.10") is True


# ── ACL: external to internal blocked ──────────────────────────────

class TestACLBlocking:
    def test_external_to_server1(self, report):
        """External -> Server1: denied by R1 eth0_in ACL rule 10"""
        assert _find_reach(report, "203.0.113.100", "10.1.0.10") is False

    def test_external_to_server2(self, report):
        assert _find_reach(report, "203.0.113.100", "10.1.0.11") is False

    def test_external_to_user1(self, report):
        assert _find_reach(report, "203.0.113.100", "10.2.0.10") is False

    def test_external_to_user2(self, report):
        assert _find_reach(report, "203.0.113.100", "10.2.0.11") is False

    def test_external_to_guest(self, report):
        assert _find_reach(report, "203.0.113.100", "10.3.0.10") is False

    def test_external_to_branch(self, report):
        assert _find_reach(report, "203.0.113.100", "10.4.0.10") is False


# ── NAT: internal to external works ────────────────────────────────

class TestNATOutbound:
    def test_server_to_external(self, report):
        """Server1 -> External1 via R2->R1->NAT"""
        assert _find_reach(report, "10.1.0.10", "203.0.113.100") is True

    def test_user_to_external(self, report):
        """User1 -> External1 via R3->R1->NAT"""
        assert _find_reach(report, "10.2.0.10", "203.0.113.100") is True

    def test_guest_to_external(self, report):
        """Guest1 -> External1 via R3->R1->NAT"""
        assert _find_reach(report, "10.3.0.10", "203.0.113.100") is True

    def test_branch_to_external(self, report):
        """Branch1 -> External1 via R4->R2->R1->NAT"""
        assert _find_reach(report, "10.4.0.10", "203.0.113.100") is True


# ── Misconfiguration detection ──────────────────────────────────────

class TestMisconfigDetection:
    def test_exactly_two_misconfigs(self, report):
        misconfigs = report.get("misconfigurations", [])
        assert len(misconfigs) == 2, (
            f"Expected exactly 2 misconfigurations, got {len(misconfigs)}: {misconfigs}"
        )

    def test_black_hole_detected(self, report):
        """Must detect unreachable next-hop 10.0.0.13 on R2"""
        misconfigs = report.get("misconfigurations", [])
        text = json.dumps(misconfigs).lower()
        patterns = [
            r"black.?hole",
            r"unreachable.*next.?hop",
            r"10\.0\.0\.13",
            r"invalid.*route",
            r"next.?hop.*not.*reachable",
            r"next.?hop.*unreachable",
            r"no.*connected",
            r"cannot.*reach.*next",
        ]
        found = any(re.search(p, text) for p in patterns)
        assert found, (
            f"Black hole misconfiguration not detected in: {misconfigs}"
        )

    def test_acl_shadow_detected(self, report):
        """Must detect that deny rule 10 shadows permit rule 20 on R1"""
        misconfigs = report.get("misconfigurations", [])
        text = json.dumps(misconfigs).lower()
        patterns = [
            r"shadow",
            r"acl.*order",
            r"rule.*order",
            r"deny.*before.*permit",
            r"never.*match",
            r"never.*evaluated",
            r"unreachable.*rule",
            r"rule.?10.*rule.?20",
            r"permit.*shadow",
            r"blocked.*by.*deny",
            r"overshadow",
            r"mask.*permit",
        ]
        found = any(re.search(p, text) for p in patterns)
        assert found, (
            f"ACL shadow misconfiguration not detected in: {misconfigs}"
        )
