
import json
import os
import pytest


EXPECTED_OBJECT_COUNTS = {
    "mntner": 4,
    "person": 3,
    "aut-num": 5,
    "inetnum": 6,
    "inet6num": 2,
    "route": 7,
    "route6": 2,
    "dns": 2,
}

EXPECTED_TOTAL_OBJECTS = 31

# Each tuple: (object_relative_path, detail_must_contain, expected_commit_message)
EXPECTED_VIOLATIONS = [
    # Stage 2: Register new autonomous systems
    ("data/aut-num/AS4242420004", "DAVE-DN42", "Register new autonomous systems"),
    ("data/aut-num/AS4242420005", "EVE-DN42", "Register new autonomous systems"),
    ("data/aut-num/AS4242420004", "AS4242420006", "Register new autonomous systems"),
    # Stage 3: Add external routes and update policies
    ("data/route/172.20.14.0_24", "EPSILON-MNT", "Add external routes and update policies"),
    ("data/route/172.20.14.0_24", "AS4242420099", "Add external routes and update policies"),
    ("data/route/172.20.14.0_24", "172.20.14.0", "Add external routes and update policies"),
    ("data/route/172.20.11.128_26", "25", "Add external routes and update policies"),
    ("data/route6/fd00:dead:beef::_48", "dead:beef", "Add external routes and update policies"),
    ("data/route/172.20.13.0_27", "GAMMA-MNT", "Add external routes and update policies"),
    # Stage 4: Add DNS zones and network allocations
    ("data/inetnum/172.20.15.0_28", "ZETA-MNT", "Add DNS zones and network allocations"),
    ("data/dns/beta.dn42", "FRANK-DN42", "Add DNS zones and network allocations"),
]

EXPECTED_IPV4_HOSTS = {
    "172.20.10.0/24": 254,
    "172.20.11.0/25": 126,
    "172.20.11.128/25": 126,
    "172.20.12.0/26": 62,
    "172.20.13.0/27": 30,
    "172.20.15.0/28": 14,
}

EXPECTED_TOTAL_IPV4_USABLE = 612

EXPECTED_ROA = [
    ("172.20.10.0/24", "AS4242420001", 24, True),
    ("172.20.10.128/25", "AS4242420004", 25, True),
    ("172.20.11.0/25", "AS4242420002", 25, True),
    ("172.20.11.128/26", "AS4242420002", 25, True),
    ("172.20.12.0/26", "AS4242420003", 26, True),
    ("172.20.13.0/27", "AS4242420003", 27, False),
    ("172.20.14.0/24", "AS4242420099", 24, False),
    ("fd00:1234:5678::/48", "AS4242420001", 48, True),
    ("fd00:dead:beef::/48", "AS4242420001", 48, False),
]


@pytest.fixture
def report():
    report_path = "/app/forensic_report.json"
    assert os.path.exists(report_path), f"Report file not found at {report_path}"
    with open(report_path) as f:
        data = json.load(f)
    return data


class TestReportStructure:
    def test_has_top_level_keys(self, report):
        for key in ("registry_summary", "violations", "network_analysis",
                     "routing_security", "total_violations"):
            assert key in report, f"Missing top-level key '{key}'"

    def test_registry_summary_keys(self, report):
        summary = report["registry_summary"]
        assert "object_counts" in summary, "Missing 'object_counts' in registry_summary"
        assert "total_objects" in summary, "Missing 'total_objects' in registry_summary"
        assert isinstance(summary["object_counts"], dict)
        assert isinstance(summary["total_objects"], int)

    def test_violations_are_list(self, report):
        assert isinstance(report["violations"], list)

    def test_violation_fields(self, report):
        required_fields = {"category", "object", "detail", "introduced_in"}
        for i, v in enumerate(report["violations"]):
            for field in required_fields:
                assert field in v, f"Violation {i} missing field '{field}'"
                assert isinstance(v[field], str), (
                    f"Violation {i} field '{field}' should be a string, got {type(v[field])}"
                )

    def test_network_analysis_keys(self, report):
        na = report["network_analysis"]
        assert "ipv4_allocations" in na, "Missing 'ipv4_allocations'"
        assert "total_ipv4_usable_hosts" in na, "Missing 'total_ipv4_usable_hosts'"
        assert "ipv6_allocations" in na, "Missing 'ipv6_allocations'"

    def test_routing_security_keys(self, report):
        rs = report["routing_security"]
        assert "roa_entries" in rs, "Missing 'roa_entries'"
        assert "authorized_count" in rs, "Missing 'authorized_count'"
        assert "unauthorized_count" in rs, "Missing 'unauthorized_count'"


class TestObjectCounts:
    @pytest.mark.parametrize("obj_type,expected", list(EXPECTED_OBJECT_COUNTS.items()))
    def test_count(self, report, obj_type, expected):
        counts = report["registry_summary"]["object_counts"]
        actual = counts.get(obj_type, None)
        assert actual == expected, (
            f"Object type '{obj_type}': expected {expected}, got {actual}"
        )

    def test_total_objects(self, report):
        assert report["registry_summary"]["total_objects"] == EXPECTED_TOTAL_OBJECTS, (
            f"Expected total_objects={EXPECTED_TOTAL_OBJECTS}, "
            f"got {report['registry_summary']['total_objects']}"
        )


class TestViolationsCompleteness:
    def test_total_count(self, report):
        assert report["total_violations"] == len(EXPECTED_VIOLATIONS), (
            f"Expected total_violations={len(EXPECTED_VIOLATIONS)}, "
            f"got {report['total_violations']}"
        )

    def test_violations_list_length(self, report):
        assert len(report["violations"]) == len(EXPECTED_VIOLATIONS), (
            f"Expected {len(EXPECTED_VIOLATIONS)} violations in list, "
            f"got {len(report['violations'])}"
        )

    def test_all_expected_present(self, report):
        """For each expected violation, verify a matching entry exists."""
        for obj_path, detail_substr, _ in EXPECTED_VIOLATIONS:
            matches = [
                v for v in report["violations"]
                if v["object"] == obj_path
                and detail_substr.lower() in v["detail"].lower()
            ]
            assert len(matches) >= 1, (
                f"Missing violation: object={obj_path}, "
                f"detail should contain '{detail_substr}'"
            )

    def test_no_extra_objects(self, report):
        """Every reported violation's object must be in the expected set."""
        expected_objects = {obj for obj, _, _ in EXPECTED_VIOLATIONS}
        for v in report["violations"]:
            assert v["object"] in expected_objects, (
                f"Unexpected violation object: {v['object']} "
                f"(category={v['category']})"
            )


class TestCommitAttribution:
    """Verify each violation is attributed to the correct git commit."""

    def test_stage2_violations(self, report):
        """Violations from 'Register new autonomous systems' commit."""
        stage2_expected = [
            (obj, detail) for obj, detail, msg in EXPECTED_VIOLATIONS
            if msg == "Register new autonomous systems"
        ]
        for obj_path, detail_substr in stage2_expected:
            matches = [
                v for v in report["violations"]
                if v["object"] == obj_path
                and detail_substr.lower() in v["detail"].lower()
            ]
            assert len(matches) >= 1, f"Missing violation for {obj_path}/{detail_substr}"
            assert matches[0]["introduced_in"] == "Register new autonomous systems", (
                f"Violation {obj_path}/{detail_substr}: expected commit "
                f"'Register new autonomous systems', "
                f"got '{matches[0]['introduced_in']}'"
            )

    def test_stage3_violations(self, report):
        """Violations from 'Add external routes and update policies' commit."""
        stage3_expected = [
            (obj, detail) for obj, detail, msg in EXPECTED_VIOLATIONS
            if msg == "Add external routes and update policies"
        ]
        for obj_path, detail_substr in stage3_expected:
            matches = [
                v for v in report["violations"]
                if v["object"] == obj_path
                and detail_substr.lower() in v["detail"].lower()
            ]
            assert len(matches) >= 1, f"Missing violation for {obj_path}/{detail_substr}"
            assert matches[0]["introduced_in"] == "Add external routes and update policies", (
                f"Violation {obj_path}/{detail_substr}: expected commit "
                f"'Add external routes and update policies', "
                f"got '{matches[0]['introduced_in']}'"
            )

    def test_stage4_violations(self, report):
        """Violations from 'Add DNS zones and network allocations' commit."""
        stage4_expected = [
            (obj, detail) for obj, detail, msg in EXPECTED_VIOLATIONS
            if msg == "Add DNS zones and network allocations"
        ]
        for obj_path, detail_substr in stage4_expected:
            matches = [
                v for v in report["violations"]
                if v["object"] == obj_path
                and detail_substr.lower() in v["detail"].lower()
            ]
            assert len(matches) >= 1, f"Missing violation for {obj_path}/{detail_substr}"
            assert matches[0]["introduced_in"] == "Add DNS zones and network allocations", (
                f"Violation {obj_path}/{detail_substr}: expected commit "
                f"'Add DNS zones and network allocations', "
                f"got '{matches[0]['introduced_in']}'"
            )

    def test_no_initial_commit_violations(self, report):
        """The initial registry import should have no violations."""
        for v in report["violations"]:
            assert v["introduced_in"] != "Initial registry import", (
                f"Violation {v['object']} should not be attributed to "
                f"'Initial registry import'"
            )


class TestSpecificViolations:
    """Spot-check specific violations for correct detail content."""

    def test_dangling_admin_c_dave(self, report):
        matches = [
            v for v in report["violations"]
            if v["object"] == "data/aut-num/AS4242420004"
            and "DAVE-DN42" in v["detail"]
        ]
        assert len(matches) == 1, "Expected exactly 1 violation for DAVE-DN42"

    def test_dangling_tech_c_eve(self, report):
        matches = [
            v for v in report["violations"]
            if v["object"] == "data/aut-num/AS4242420005"
            and "EVE-DN42" in v["detail"]
        ]
        assert len(matches) == 1, "Expected exactly 1 violation for EVE-DN42"

    def test_dangling_policy_as(self, report):
        """Policy import references non-existent AS4242420006."""
        matches = [
            v for v in report["violations"]
            if v["object"] == "data/aut-num/AS4242420004"
            and "AS4242420006" in v["detail"]
        ]
        assert len(matches) == 1, "Expected exactly 1 violation for AS4242420006 policy ref"

    def test_dangling_mntner_epsilon(self, report):
        matches = [
            v for v in report["violations"]
            if v["object"] == "data/route/172.20.14.0_24"
            and "EPSILON-MNT" in v["detail"]
        ]
        assert len(matches) == 1, "Expected exactly 1 violation for EPSILON-MNT"

    def test_dangling_origin_as99(self, report):
        matches = [
            v for v in report["violations"]
            if v["object"] == "data/route/172.20.14.0_24"
            and "AS4242420099" in v["detail"]
        ]
        assert len(matches) == 1, "Expected exactly 1 violation for AS4242420099"

    def test_unallocated_route(self, report):
        matches = [
            v for v in report["violations"]
            if v["object"] == "data/route/172.20.14.0_24"
            and "172.20.14.0" in v["detail"]
            and "EPSILON-MNT" not in v["detail"]
            and "AS4242420099" not in v["detail"]
        ]
        assert len(matches) == 1, "Expected exactly 1 unallocated route violation for 172.20.14.0"

    def test_max_length_violation(self, report):
        matches = [
            v for v in report["violations"]
            if v["object"] == "data/route/172.20.11.128_26"
        ]
        assert len(matches) == 1, "Expected exactly 1 violation for 172.20.11.128/26"
        detail = matches[0]["detail"]
        assert "26" in detail and "25" in detail, (
            f"max-length violation detail should mention both 26 and 25, got: {detail}"
        )

    def test_unallocated_route6(self, report):
        matches = [
            v for v in report["violations"]
            if v["object"] == "data/route6/fd00:dead:beef::_48"
        ]
        assert len(matches) == 1, "Expected exactly 1 violation for fd00:dead:beef::/48"
        assert "dead:beef" in matches[0]["detail"].lower()

    def test_unauthorized_route_auth_chain(self, report):
        """Route 172.20.13.0/27 maintained by GAMMA-MNT but allocation is DELTA-MNT."""
        matches = [
            v for v in report["violations"]
            if v["object"] == "data/route/172.20.13.0_27"
            and "GAMMA-MNT" in v["detail"]
        ]
        assert len(matches) == 1, "Expected exactly 1 authorization chain violation for 172.20.13.0/27"
        detail = matches[0]["detail"]
        assert "DELTA-MNT" in detail or "unauthor" in detail.lower() or "not authorized" in detail.lower(), (
            f"Auth chain violation should reference DELTA-MNT or authorization failure: {detail}"
        )

    def test_dangling_mntner_zeta(self, report):
        matches = [
            v for v in report["violations"]
            if v["object"] == "data/inetnum/172.20.15.0_28"
            and "ZETA-MNT" in v["detail"]
        ]
        assert len(matches) == 1, "Expected exactly 1 violation for ZETA-MNT"

    def test_dangling_tech_c_frank(self, report):
        matches = [
            v for v in report["violations"]
            if v["object"] == "data/dns/beta.dn42"
            and "FRANK-DN42" in v["detail"]
        ]
        assert len(matches) == 1, "Expected exactly 1 violation for FRANK-DN42"


class TestNetworkAnalysis:
    def test_ipv4_allocations_count(self, report):
        allocs = report["network_analysis"]["ipv4_allocations"]
        assert len(allocs) == 6, f"Expected 6 IPv4 allocations, got {len(allocs)}"

    @pytest.mark.parametrize("cidr,expected_hosts", list(EXPECTED_IPV4_HOSTS.items()))
    def test_ipv4_usable_hosts(self, report, cidr, expected_hosts):
        allocs = report["network_analysis"]["ipv4_allocations"]
        matches = [a for a in allocs if a["cidr"] == cidr]
        assert len(matches) == 1, f"Expected allocation for {cidr}, found {len(matches)}"
        assert matches[0]["usable_hosts"] == expected_hosts, (
            f"For {cidr}: expected {expected_hosts} usable hosts, "
            f"got {matches[0]['usable_hosts']}"
        )

    def test_total_ipv4_usable_hosts(self, report):
        total = report["network_analysis"]["total_ipv4_usable_hosts"]
        assert total == EXPECTED_TOTAL_IPV4_USABLE, (
            f"Expected total_ipv4_usable_hosts={EXPECTED_TOTAL_IPV4_USABLE}, got {total}"
        )

    def test_ipv6_allocations_count(self, report):
        allocs = report["network_analysis"]["ipv6_allocations"]
        assert len(allocs) == 2, f"Expected 2 IPv6 allocations, got {len(allocs)}"

    def test_ipv6_prefix_lengths(self, report):
        allocs = report["network_analysis"]["ipv6_allocations"]
        cidrs = {a["cidr"] for a in allocs}
        assert "fd00:1234:5678::/48" in cidrs, "Missing IPv6 allocation fd00:1234:5678::/48"
        assert "fd00:abcd:ef01::/48" in cidrs, "Missing IPv6 allocation fd00:abcd:ef01::/48"
        for a in allocs:
            assert a["prefix_length"] == 48, (
                f"Expected prefix_length 48 for {a['cidr']}, got {a['prefix_length']}"
            )


class TestRoutingSecurity:
    """Verify the ROA table and authorization analysis."""

    def test_roa_entries_count(self, report):
        entries = report["routing_security"]["roa_entries"]
        assert len(entries) == 9, f"Expected 9 ROA entries, got {len(entries)}"

    def test_authorized_count(self, report):
        count = report["routing_security"]["authorized_count"]
        assert count == 6, f"Expected authorized_count=6, got {count}"

    def test_unauthorized_count(self, report):
        count = report["routing_security"]["unauthorized_count"]
        assert count == 3, f"Expected unauthorized_count=3, got {count}"

    @pytest.mark.parametrize("prefix,origin,max_len,authorized", EXPECTED_ROA)
    def test_roa_entry(self, report, prefix, origin, max_len, authorized):
        entries = report["routing_security"]["roa_entries"]
        matches = [e for e in entries if e["prefix"] == prefix]
        assert len(matches) == 1, f"Expected 1 ROA entry for {prefix}, found {len(matches)}"
        entry = matches[0]
        assert entry["origin"] == origin, (
            f"ROA {prefix}: expected origin {origin}, got {entry['origin']}"
        )
        assert entry["max_length"] == max_len, (
            f"ROA {prefix}: expected max_length {max_len}, got {entry['max_length']}"
        )
        assert entry["authorized"] == authorized, (
            f"ROA {prefix}: expected authorized={authorized}, got {entry['authorized']}"
        )

    def test_counts_match_entries(self, report):
        """Verify counts match actual ROA entry authorized statuses."""
        entries = report["routing_security"]["roa_entries"]
        actual_auth = sum(1 for e in entries if e["authorized"])
        actual_unauth = sum(1 for e in entries if not e["authorized"])
        assert report["routing_security"]["authorized_count"] == actual_auth
        assert report["routing_security"]["unauthorized_count"] == actual_unauth
