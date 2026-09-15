
import json
import os
import pytest


def load_output(filename):
    path = f"/app/output/{filename}"
    assert os.path.exists(path), f"Expected output file {path} does not exist"
    with open(path) as f:
        return json.load(f)


class TestRouteLeaks:
    def test_route_leaks_file_exists(self):
        assert os.path.exists("/app/output/route_leaks.json")

    def test_route_leaks_is_list(self):
        leaks = load_output("route_leaks.json")
        assert isinstance(leaks, list), "route_leaks.json must contain a JSON array"

    def test_route_leaks_minimum_count(self):
        leaks = load_output("route_leaks.json")
        assert len(leaks) >= 2, f"Expected at least 2 route leaks, found {len(leaks)}"

    def test_leak_10_1_by_as65010(self):
        """AS 65010 leaks provider-learned 10.1.0.0/16 to peer AS 65020."""
        leaks = load_output("route_leaks.json")
        found = any(
            str(leak.get("prefix", "")) == "10.1.0.0/16"
            and int(leak.get("leaker_as", 0)) == 65010
            for leak in leaks
        )
        assert found, "Expected route leak: prefix 10.1.0.0/16 leaked by AS 65010"

    def test_leak_10_2_by_as65020(self):
        """AS 65020 leaks provider-learned 10.2.0.0/16 to peer AS 65010."""
        leaks = load_output("route_leaks.json")
        found = any(
            str(leak.get("prefix", "")) == "10.2.0.0/16"
            and int(leak.get("leaker_as", 0)) == 65020
            for leak in leaks
        )
        assert found, "Expected route leak: prefix 10.2.0.0/16 leaked by AS 65020"

    def test_no_false_positive_customer_routes(self):
        """Customer-originated routes propagated normally should NOT be flagged."""
        leaks = load_output("route_leaks.json")
        false_positives = [
            leak for leak in leaks
            if str(leak.get("prefix", "")) in (
                "10.100.0.0/16", "10.200.0.0/16", "10.20.0.0/16"
            )
        ]
        assert len(false_positives) == 0, (
            f"Customer-learned routes should not be flagged as leaks: {false_positives}"
        )


class TestRPKIViolations:
    def test_rpki_file_exists(self):
        assert os.path.exists("/app/output/rpki_violations.json")

    def test_rpki_is_list(self):
        violations = load_output("rpki_violations.json")
        assert isinstance(violations, list), "rpki_violations.json must contain a JSON array"

    def test_rpki_minimum_count(self):
        violations = load_output("rpki_violations.json")
        assert len(violations) >= 2, f"Expected at least 2 RPKI violations, found {len(violations)}"

    def test_hijack_10_100_24(self):
        """10.100.0.0/24 originated by AS 65200 but ROA says AS 65100."""
        violations = load_output("rpki_violations.json")
        found = any(
            str(v.get("prefix", "")) == "10.100.0.0/24"
            and int(v.get("origin_as", 0)) == 65200
            and "origin" in str(v.get("violation", "")).lower()
            for v in violations
        )
        assert found, "Expected RPKI violation: 10.100.0.0/24 invalid origin AS 65200 (should be 65100)"

    def test_invalid_length_10_10_24(self):
        """10.10.0.0/24 exceeds ROA maxLength of /16."""
        violations = load_output("rpki_violations.json")
        found = any(
            str(v.get("prefix", "")) == "10.10.0.0/24"
            and "length" in str(v.get("violation", "")).lower()
            for v in violations
        )
        assert found, "Expected RPKI violation: 10.10.0.0/24 prefix length exceeds maxLength /16"

    def test_no_false_positive_valid_prefixes(self):
        """Valid prefixes must not be reported."""
        violations = load_output("rpki_violations.json")
        valid_prefixes = {
            "10.1.0.0/16", "10.2.0.0/16", "10.10.0.0/16",
            "10.20.0.0/16", "10.100.0.0/16", "10.200.0.0/16",
        }
        false_positives = [
            v for v in violations if str(v.get("prefix", "")) in valid_prefixes
        ]
        assert len(false_positives) == 0, (
            f"Valid prefixes should not be flagged as RPKI violations: {false_positives}"
        )


class TestPolicyViolations:
    def test_policy_file_exists(self):
        assert os.path.exists("/app/output/policy_violations.json")

    def test_policy_is_list(self):
        violations = load_output("policy_violations.json")
        assert isinstance(violations, list), "policy_violations.json must contain a JSON array"

    def test_policy_minimum_count(self):
        violations = load_output("policy_violations.json")
        assert len(violations) >= 1, f"Expected at least 1 policy violation, found {len(violations)}"

    def test_wrong_local_pref_r1(self):
        """R1 (AS 65001) has LOCAL_PREF 80 for customer-learned 10.10.0.0/16 (expected 150)."""
        violations = load_output("policy_violations.json")
        found = any(
            int(v.get("router_as", 0)) == 65001
            and str(v.get("prefix", "")) == "10.10.0.0/16"
            and int(v.get("actual_local_pref", 0)) == 80
            and int(v.get("expected_local_pref", 0)) == 150
            for v in violations
        )
        assert found, (
            "Expected policy violation: R1/AS 65001 has LOCAL_PREF 80 "
            "instead of 150 for customer-learned 10.10.0.0/16"
        )


class TestSummary:
    def test_summary_file_exists(self):
        assert os.path.exists("/app/output/summary.json")

    def test_summary_is_dict(self):
        summary = load_output("summary.json")
        assert isinstance(summary, dict), "summary.json must contain a JSON object"

    def test_summary_route_leaks(self):
        summary = load_output("summary.json")
        assert int(summary.get("total_route_leaks", 0)) >= 2, (
            f"Expected total_route_leaks >= 2, got {summary.get('total_route_leaks')}"
        )

    def test_summary_rpki_violations(self):
        summary = load_output("summary.json")
        assert int(summary.get("total_rpki_violations", 0)) >= 2, (
            f"Expected total_rpki_violations >= 2, got {summary.get('total_rpki_violations')}"
        )

    def test_summary_policy_violations(self):
        summary = load_output("summary.json")
        assert int(summary.get("total_policy_violations", 0)) >= 1, (
            f"Expected total_policy_violations >= 1, got {summary.get('total_policy_violations')}"
        )

    def test_summary_total_issues(self):
        summary = load_output("summary.json")
        assert int(summary.get("total_issues", 0)) >= 5, (
            f"Expected total_issues >= 5, got {summary.get('total_issues')}"
        )
