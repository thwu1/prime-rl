"""Tests for DN42 Registry Audit with BIRD2 ROA Integration."""

import json
import csv
import re
import os
import shutil
import subprocess
import ipaddress
import pytest

VIOLATIONS_PATH = "/app/violations.json"
ROA_PATH = "/app/roa_table.csv"
BIRD_CONF_PATH = "/app/bird.conf"
EXPANDED_SETS_PATH = "/app/expanded_sets.json"


def load_violations():
    with open(VIOLATIONS_PATH) as f:
        return json.load(f)


def violation_matches(report, *search_terms):
    """Check if any violation's JSON representation contains ALL search terms (case-insensitive)."""
    for v in report:
        dump = json.dumps(v).lower()
        if all(term.lower() in dump for term in search_terms):
            return True
    return False


def load_roa_rows():
    """Load ROA CSV and return list of dicts."""
    with open(ROA_PATH) as f:
        reader = csv.DictReader(f)
        return list(reader)


def normalize_prefix(prefix):
    try:
        return str(ipaddress.ip_network(prefix.strip(), strict=False))
    except ValueError:
        return prefix.strip()


# ============================================================
# Violation report structure
# ============================================================

class TestViolationStructure:
    def test_report_exists_and_is_list(self):
        report = load_violations()
        assert isinstance(report, list), "violations.json must be a JSON array"

    def test_minimum_violation_count(self):
        report = load_violations()
        assert len(report) >= 16, (
            f"Expected at least 16 violations, found {len(report)}"
        )

    def test_entries_have_required_fields(self):
        report = load_violations()
        required = {"object_type", "object_name", "rule", "message"}
        for i, v in enumerate(report):
            for field in required:
                assert field in v, (
                    f"Violation {i} missing required field '{field}': {v}"
                )


# ============================================================
# Schema violations: missing required fields
# ============================================================

class TestMissingRequiredFields:
    def test_delta_mnt_missing_auth(self):
        """DELTA-MNT is missing the required 'auth' field per MNTNER-SCHEMA."""
        report = load_violations()
        assert violation_matches(report, "DELTA-MNT", "auth"), (
            "Should report DELTA-MNT missing required 'auth' field"
        )

    def test_as4242420004_missing_as_name(self):
        """AS4242420004 is missing required 'as-name' per AUT-NUM-SCHEMA."""
        report = load_violations()
        assert violation_matches(report, "AS4242420004", "as-name"), (
            "Should report AS4242420004 missing required 'as-name' field"
        )


# ============================================================
# Schema violations: invalid enum values
# ============================================================

class TestInvalidEnumValues:
    def test_inetnum_status_pending(self):
        """172.22.0.0_24 has status PENDING, not in enum {ASSIGNED, ALLOCATED}."""
        report = load_violations()
        assert violation_matches(report, "172.22.0.0", "PENDING") or \
               violation_matches(report, "172.22.0.0", "status"), (
            "Should report invalid status 'PENDING' on 172.22.0.0_24"
        )

    def test_route6_source_ripe(self):
        """route6 fd86:cafe::_48 has source RIPE, not in enum {DN42}."""
        report = load_violations()
        assert violation_matches(report, "fd86", "RIPE") or \
               violation_matches(report, "fd86", "source"), (
            "Should report invalid source 'RIPE' on fd86:cafe route6"
        )


# ============================================================
# Schema violations: broken lookups
# ============================================================

class TestBrokenLookups:
    def test_delta_mnt_admin_c_missing_person(self):
        """DELTA-MNT references admin-c MISSING-DN42 which doesn't exist in person/."""
        report = load_violations()
        assert violation_matches(report, "DELTA-MNT", "MISSING-DN42"), (
            "Should report broken admin-c lookup for MISSING-DN42"
        )

    def test_epsilon_mnt_broken_mnt_by(self):
        """EPSILON-MNT references mnt-by NONEXIST-MNT which doesn't exist in mntner/."""
        report = load_violations()
        assert violation_matches(report, "EPSILON-MNT", "NONEXIST-MNT"), (
            "Should report broken mnt-by lookup for NONEXIST-MNT"
        )

    def test_as4242420004_broken_mnt_by(self):
        """AS4242420004 references mnt-by GHOST-MNT which doesn't exist in mntner/."""
        report = load_violations()
        assert violation_matches(report, "AS4242420004", "GHOST-MNT"), (
            "Should report broken mnt-by lookup for GHOST-MNT"
        )

    def test_route_unregistered_origin_9999(self):
        """route 172.20.200.0_24 has origin AS4242429999 not in aut-num/."""
        report = load_violations()
        assert violation_matches(report, "AS4242429999"), (
            "Should report unregistered origin AS4242429999"
        )

    def test_route6_unregistered_origin_8888(self):
        """route6 fd86:cafe::_48 has origin AS4242428888 not in aut-num/."""
        report = load_violations()
        assert violation_matches(report, "AS4242428888"), (
            "Should report unregistered origin AS4242428888"
        )


# ============================================================
# Policy violations: IP range
# ============================================================

class TestIPRangeViolations:
    def test_ipv4_out_of_range_10(self):
        """10.0.0.0/24 is outside valid dn42 range 172.20.0.0/14."""
        report = load_violations()
        assert violation_matches(report, "10.0.0.0"), (
            "Should report 10.0.0.0/24 out of range"
        )

    def test_ipv4_out_of_range_172_24(self):
        """172.24.0.0/24 is outside 172.20.0.0/14 (boundary case)."""
        report = load_violations()
        assert violation_matches(report, "172.24.0.0"), (
            "Should report 172.24.0.0/24 out of range"
        )

    def test_ipv6_out_of_range(self):
        """2001:db8::/48 is outside valid dn42 ULA range fd00::/8."""
        report = load_violations()
        assert violation_matches(report, "2001:db8") or \
               violation_matches(report, "2001:0db8"), (
            "Should report 2001:db8::/48 out of range"
        )


# ============================================================
# Policy violations: overlapping allocations
# ============================================================

class TestOverlapViolations:
    def test_ipv4_overlap_10_27_and_10_28(self):
        """172.20.10.0/27 and 172.20.10.16/28 overlap."""
        report = load_violations()
        dump = json.dumps(report).lower()
        assert "172.20.10.0" in dump and "172.20.10.16" in dump, (
            "Should report overlap between 172.20.10.0/27 and 172.20.10.16/28"
        )

    def test_ipv4_overlap_100_25_and_100_26(self):
        """172.20.100.0/25 and 172.20.100.64/26 overlap."""
        report = load_violations()
        dump = json.dumps(report).lower()
        assert "172.20.100.0" in dump and "172.20.100.64" in dump, (
            "Should report overlap between 172.20.100.0/25 and 172.20.100.64/26"
        )

    def test_ipv6_overlap(self):
        """fd42:d42:d42::/48 and fd42:d42:d42:1::/64 overlap."""
        report = load_violations()
        dump = json.dumps(report).lower()
        has_parent = "fd42:d42:d42::" in dump or "fd42:0d42:0d42::" in dump
        has_child = "fd42:d42:d42:1::" in dump or "fd42:0d42:0d42:0001::" in dump
        assert has_parent and has_child, (
            "Should report overlap between fd42:d42:d42::/48 and fd42:d42:d42:1::/64"
        )


# ============================================================
# Policy violations: route coverage and max-length
# ============================================================

class TestRoutePolicyViolations:
    def test_uncovered_prefix(self):
        """route 172.20.200.0/24 is not covered by any inetnum allocation."""
        report = load_violations()
        assert violation_matches(report, "172.20.200.0"), (
            "Should report uncovered prefix 172.20.200.0/24"
        )

    def test_max_length_violation(self):
        """route 172.21.0.0/24 has max-length 20 which is < prefix length 24."""
        report = load_violations()
        found = violation_matches(report, "172.21.0.0", "max") or \
                violation_matches(report, "172.21.0.0", "20")
        assert found, (
            "Should report max-length violation on 172.21.0.0/24 (max-length 20 < /24)"
        )


# ============================================================
# Policy violations: AS-SET member references
# ============================================================

class TestASSetViolations:
    def test_delta_broken_member_reference(self):
        """AS-DELTA references AS-NONEXIST which doesn't exist in as-set/."""
        report = load_violations()
        assert violation_matches(report, "AS-DELTA", "AS-NONEXIST"), (
            "Should report broken AS-SET member reference for AS-NONEXIST in AS-DELTA"
        )


# ============================================================
# ROA table validation
# ============================================================

class TestROATableStructure:
    def test_file_exists(self):
        assert os.path.exists(ROA_PATH), f"ROA table not found at {ROA_PATH}"

    def test_has_correct_header(self):
        with open(ROA_PATH) as f:
            header = f.readline().strip()
        assert header == "prefix,max_length,asn", (
            f"ROA header should be 'prefix,max_length,asn', got '{header}'"
        )

    def test_exactly_four_entries(self):
        rows = load_roa_rows()
        assert len(rows) == 4, (
            f"Expected exactly 4 valid ROA entries, got {len(rows)}"
        )


class TestROATableContent:
    def test_contains_route_alpha_27(self):
        """172.20.10.0/27 with AS4242420001 should be in ROA."""
        rows = load_roa_rows()
        found = any(
            normalize_prefix(r["prefix"]) == "172.20.10.0/27"
            and r["asn"].strip() == "AS4242420001"
            and int(r["max_length"]) == 27
            for r in rows
        )
        assert found, "ROA should include 172.20.10.0/27,27,AS4242420001"

    def test_contains_route_beta_24(self):
        """172.20.50.0/24 with AS4242420002 should be in ROA."""
        rows = load_roa_rows()
        found = any(
            normalize_prefix(r["prefix"]) == "172.20.50.0/24"
            and r["asn"].strip() == "AS4242420002"
            and int(r["max_length"]) == 24
            for r in rows
        )
        assert found, "ROA should include 172.20.50.0/24,24,AS4242420002"

    def test_contains_route_gamma_25(self):
        """172.20.100.0/25 with AS4242420003 and max-length 25 should be in ROA."""
        rows = load_roa_rows()
        found = any(
            normalize_prefix(r["prefix"]) == "172.20.100.0/25"
            and r["asn"].strip() == "AS4242420003"
            and int(r["max_length"]) == 25
            for r in rows
        )
        assert found, "ROA should include 172.20.100.0/25,25,AS4242420003"

    def test_contains_route6_alpha_48(self):
        """fd42:d42:d42::/48 with AS4242420001 should be in ROA."""
        rows = load_roa_rows()
        found = any(
            normalize_prefix(r["prefix"]) == "fd42:d42:d42::/48"
            and r["asn"].strip() == "AS4242420001"
            and int(r["max_length"]) == 48
            for r in rows
        )
        assert found, "ROA should include fd42:d42:d42::/48,48,AS4242420001"


class TestROATableExclusions:
    def test_excludes_unregistered_origin_9999(self):
        """Routes with unregistered origin AS4242429999 should be excluded."""
        rows = load_roa_rows()
        found = any("AS4242429999" in r.get("asn", "") for r in rows)
        assert not found, "ROA should NOT include routes with origin AS4242429999"

    def test_excludes_unregistered_origin_8888(self):
        """Routes with unregistered origin AS4242428888 should be excluded."""
        rows = load_roa_rows()
        found = any("AS4242428888" in r.get("asn", "") for r in rows)
        assert not found, "ROA should NOT include routes with origin AS4242428888"

    def test_excludes_max_length_violation_route(self):
        """Route 172.21.0.0/24 with max-length 20 < prefix 24 should be excluded."""
        rows = load_roa_rows()
        found = any(
            normalize_prefix(r["prefix"]) == "172.21.0.0/24"
            for r in rows
        )
        assert not found, "ROA should NOT include route 172.21.0.0/24 (max-length violation)"


# ============================================================
# BIRD2 configuration: syntax validation
# ============================================================

class TestBIRD2Syntax:
    def test_bird_conf_exists(self):
        assert os.path.exists(BIRD_CONF_PATH), f"BIRD2 config not found at {BIRD_CONF_PATH}"

    def test_bird_parse_check(self):
        """BIRD2 configuration must pass bird -p syntax validation."""
        bird_path = shutil.which("bird")
        if bird_path is None:
            bird_path = "/usr/sbin/bird"
        result = subprocess.run(
            [bird_path, "-p", "-c", BIRD_CONF_PATH],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"BIRD2 parse check failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ============================================================
# BIRD2 configuration: ROA table content
# ============================================================

class TestBIRD2ROAContent:
    def test_declares_roa4_table(self):
        with open(BIRD_CONF_PATH) as f:
            content = f.read()
        assert re.search(r'roa4\s+table', content), (
            "bird.conf must declare a roa4 table"
        )

    def test_declares_roa6_table(self):
        with open(BIRD_CONF_PATH) as f:
            content = f.read()
        assert re.search(r'roa6\s+table', content), (
            "bird.conf must declare a roa6 table"
        )

    def test_contains_valid_roa4_entries(self):
        """bird.conf must contain the 3 valid IPv4 ROA entries."""
        with open(BIRD_CONF_PATH) as f:
            content = f.read()
        assert "172.20.10.0/27" in content, "Missing ROA entry 172.20.10.0/27"
        assert "172.20.50.0/24" in content, "Missing ROA entry 172.20.50.0/24"
        assert "172.20.100.0/25" in content, "Missing ROA entry 172.20.100.0/25"

    def test_contains_valid_roa6_entry(self):
        """bird.conf must contain the valid IPv6 ROA entry."""
        with open(BIRD_CONF_PATH) as f:
            content = f.read()
        assert "fd42:d42:d42::/48" in content, "Missing ROA6 entry fd42:d42:d42::/48"

    def test_excludes_invalid_asns(self):
        """Routes with violated ASNs must not appear in BIRD2 ROA entries."""
        with open(BIRD_CONF_PATH) as f:
            content = f.read()
        assert "4242429999" not in content, (
            "bird.conf should not contain AS4242429999 (unregistered origin)"
        )
        assert "4242428888" not in content, (
            "bird.conf should not contain AS4242428888 (unregistered origin)"
        )

    def test_excludes_max_length_violation_route(self):
        """Route 172.21.0.0/24 (max-length violation) must not be a ROA entry."""
        with open(BIRD_CONF_PATH) as f:
            content = f.read()
        roa_lines = [
            l.strip() for l in content.split('\n')
            if 'route' in l.lower() and '172.21' in l
        ]
        assert len(roa_lines) == 0, (
            f"bird.conf should not contain ROA entry for 172.21.0.0/24: {roa_lines}"
        )


# ============================================================
# BIRD2 configuration: filter logic
# ============================================================

class TestBIRD2Filter:
    def test_uses_roa_check(self):
        """Filter must use roa_check() for ROA validation."""
        with open(BIRD_CONF_PATH) as f:
            content = f.read()
        assert "roa_check" in content, "bird.conf must use roa_check() in filters"

    def test_references_roa_valid(self):
        """Filter must reference ROA_VALID state."""
        with open(BIRD_CONF_PATH) as f:
            content = f.read()
        assert "ROA_VALID" in content, "bird.conf filter must reference ROA_VALID"

    def test_references_roa_invalid(self):
        """Filter must reference ROA_INVALID state and reject."""
        with open(BIRD_CONF_PATH) as f:
            content = f.read()
        assert "ROA_INVALID" in content, "bird.conf filter must reference ROA_INVALID"
        assert "reject" in content, "bird.conf filter must reject ROA_INVALID routes"

    def test_community_values_from_policy(self):
        """Filter must use the community values from the policy file (64511,1/2/3)."""
        with open(BIRD_CONF_PATH) as f:
            content = f.read()
        assert re.search(r'64511\s*,\s*1', content), (
            "bird.conf must tag ROA_VALID with community (64511,1)"
        )
        assert re.search(r'64511\s*,\s*2', content), (
            "bird.conf must tag ROA_INVALID with community (64511,2)"
        )
        assert re.search(r'64511\s*,\s*3', content), (
            "bird.conf must tag ROA_UNKNOWN with community (64511,3)"
        )


# ============================================================
# AS-SET expansion
# ============================================================

class TestASSetExpansion:
    def test_file_exists(self):
        assert os.path.exists(EXPANDED_SETS_PATH), (
            f"expanded_sets.json not found at {EXPANDED_SETS_PATH}"
        )

    def test_is_valid_json_object(self):
        with open(EXPANDED_SETS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict), "expanded_sets.json must be a JSON object"

    def test_contains_all_sets(self):
        """All 5 as-set objects must appear in the expansion."""
        with open(EXPANDED_SETS_PATH) as f:
            data = json.load(f)
        for name in ["AS-ALPHA", "AS-BETA", "AS-GAMMA", "AS-CYCLE", "AS-DELTA"]:
            assert name in data, f"Missing AS-SET '{name}' in expanded_sets.json"

    def test_alpha_expansion(self):
        """AS-ALPHA = {AS4242420001} + expand(AS-BETA) = {AS4242420001, AS4242420002, AS4242420003}."""
        with open(EXPANDED_SETS_PATH) as f:
            data = json.load(f)
        members = sorted(data.get("AS-ALPHA", []))
        assert members == ["AS4242420001", "AS4242420002", "AS4242420003"], (
            f"AS-ALPHA expansion should be [AS4242420001, AS4242420002, AS4242420003], got {members}"
        )

    def test_beta_expansion(self):
        """AS-BETA = {AS4242420002, AS4242420003}."""
        with open(EXPANDED_SETS_PATH) as f:
            data = json.load(f)
        members = sorted(data.get("AS-BETA", []))
        assert members == ["AS4242420002", "AS4242420003"], (
            f"AS-BETA expansion should be [AS4242420002, AS4242420003], got {members}"
        )

    def test_gamma_cycle_handling(self):
        """AS-GAMMA and AS-CYCLE have mutual references — must resolve without infinite loop."""
        with open(EXPANDED_SETS_PATH) as f:
            data = json.load(f)
        gamma = sorted(data.get("AS-GAMMA", []))
        cycle = sorted(data.get("AS-CYCLE", []))
        assert "AS4242420003" in gamma, "AS-GAMMA should contain AS4242420003"
        assert "AS4242420004" in gamma, "AS-GAMMA should contain AS4242420004"
        assert gamma == ["AS4242420003", "AS4242420004"], (
            f"AS-GAMMA should expand to [AS4242420003, AS4242420004], got {gamma}"
        )
        assert cycle == ["AS4242420003", "AS4242420004"], (
            f"AS-CYCLE should expand to [AS4242420003, AS4242420004], got {cycle}"
        )

    def test_delta_broken_ref_graceful(self):
        """AS-DELTA has AS-NONEXIST — expansion includes only resolvable ASNs."""
        with open(EXPANDED_SETS_PATH) as f:
            data = json.load(f)
        members = sorted(data.get("AS-DELTA", []))
        assert members == ["AS4242420001"], (
            f"AS-DELTA should expand to [AS4242420001], got {members}"
        )
