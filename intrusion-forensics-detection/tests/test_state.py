#!/usr/bin/env python3
"""Verification tests for the multi-channel exfiltration forensics task.

Validates:
  1. forensic_report.json — correct attack metadata and channel classification
  2. decoded_primary.txt — DNS tunnel decoded credentials
  3. decoded_secondary.txt — HTTP channel decoded credentials
  4. channel_assessment.json — correct channel evaluation and cross-validation
  5. detection.rules — valid Suricata/Snort rules targeting real channels only
"""

import json
import os
import re
import hashlib
import pytest


# ---- Expected values (deterministic from PCAP generation) ----

EXPECTED_ATTACKER_IP = "203.0.113.50"
EXPECTED_TARGET_IP = "10.1.1.100"
EXPECTED_SCAN_COUNT = 150
EXPECTED_OPEN_PORTS = [22, 80, 443, 8080]
EXPECTED_EXPLOIT_PORT = 8080
EXPECTED_EXPLOIT_URI = "/api/diagnostic"
EXPECTED_C2_DOMAIN_SUBSTR = "c2server.xyz"
EXPECTED_HTTP_EXFIL_DEST = "198.51.100.77"
EXPECTED_DECOY_DOMAIN_SUBSTR = "svcmon.io"

EXPECTED_EXFIL = (
    "DB_HOST=proddb.internal:5432\n"
    "DB_USER=admin\n"
    "DB_PASS=xK9mP2vL8qR5nT3w\n"
    "API_KEY=AKIAIOSFODNN7EXAMPLE\n"
    "API_SECRET=wJalrXUtnFEMIbPxRfiCYEXAMPLEKEY"
)

EXPECTED_EXFIL_FRAGMENTS = [
    "DB_HOST=proddb.internal:5432",
    "DB_USER=admin",
    "DB_PASS=xK9mP2vL8qR5nT3w",
    "API_KEY=AKIAIOSFODNN7EXAMPLE",
    "API_SECRET=wJalrXUtnFEMIbPxRfiCYEXAMPLEKEY",
]

EXPECTED_DATA_HASH = hashlib.sha256(EXPECTED_EXFIL.encode()).hexdigest()


# =====================================================================
# forensic_report.json
# =====================================================================

class TestForensicReport:
    """Verify the structured forensic report."""

    @pytest.fixture(scope="class")
    def report(self):
        path = "/app/forensic_report.json"
        assert os.path.isfile(path), f"{path} not found"
        with open(path) as f:
            return json.load(f)

    def test_attacker_ip(self, report):
        assert report.get("attacker_ip") == EXPECTED_ATTACKER_IP, (
            f"Expected attacker_ip={EXPECTED_ATTACKER_IP}, "
            f"got {report.get('attacker_ip')}"
        )

    def test_compromised_host(self, report):
        val = report.get("compromised_host", report.get("target_ip", ""))
        assert val == EXPECTED_TARGET_IP, (
            f"Expected compromised_host={EXPECTED_TARGET_IP}, got {val}"
        )

    def test_scan_type_is_syn(self, report):
        st = report.get("scan_type", "").lower()
        assert "syn" in st, f"Expected SYN-based scan type, got '{st}'"

    def test_ports_scanned(self, report):
        n = report.get("ports_scanned", 0)
        assert n == EXPECTED_SCAN_COUNT, (
            f"Expected {EXPECTED_SCAN_COUNT} ports scanned, got {n}"
        )

    def test_open_ports(self, report):
        found = sorted(report.get("open_ports", []))
        assert found == EXPECTED_OPEN_PORTS, (
            f"Expected open_ports={EXPECTED_OPEN_PORTS}, got {found}"
        )

    def test_exploit_method(self, report):
        m = report.get("exploit_method", "").lower().replace("_", " ")
        assert "command" in m and "injection" in m, (
            f"Expected command injection, got '{m}'"
        )

    def test_exploit_target_port(self, report):
        assert report.get("exploit_target_port") == EXPECTED_EXPLOIT_PORT

    def test_exploit_uri(self, report):
        uri = report.get("exploit_uri", "")
        assert EXPECTED_EXPLOIT_URI in uri, (
            f"Expected URI containing {EXPECTED_EXPLOIT_URI}, got '{uri}'"
        )

    def test_primary_c2_domain(self, report):
        dom = report.get("primary_c2_domain", "")
        assert EXPECTED_C2_DOMAIN_SUBSTR in dom, (
            f"Expected domain containing '{EXPECTED_C2_DOMAIN_SUBSTR}', got '{dom}'"
        )

    def test_primary_exfil_encoding(self, report):
        enc = report.get("primary_exfil_encoding", "").lower()
        assert "base32" in enc, f"Expected base32, got '{enc}'"

    def test_secondary_exfil_dest(self, report):
        dest = report.get("secondary_exfil_dest", "")
        assert EXPECTED_HTTP_EXFIL_DEST in dest, (
            f"Expected '{EXPECTED_HTTP_EXFIL_DEST}', got '{dest}'"
        )

    def test_secondary_exfil_encoding(self, report):
        enc = report.get("secondary_exfil_encoding", "").lower()
        assert "hex" in enc, f"Expected hex encoding, got '{enc}'"

    def test_decoy_domain(self, report):
        dom = report.get("decoy_domain", "")
        assert EXPECTED_DECOY_DOMAIN_SUBSTR in dom, (
            f"Expected domain containing '{EXPECTED_DECOY_DOMAIN_SUBSTR}', got '{dom}'"
        )

    def test_decoy_reason_not_empty(self, report):
        reason = report.get("decoy_reason", "")
        assert len(reason) > 20, "decoy_reason must provide meaningful rationale"

    def test_decoy_reason_quality(self, report):
        reason = report.get("decoy_reason", "").lower()
        indicators = [
            "random", "invalid", "garbage", "meaningless", "not valid",
            "binary", "decoy", "gibberish", "noise", "junk", "fake",
            "non-text", "unreadable", "no meaningful", "not meaningful",
            "nonsensical", "corrupt", "illegible",
        ]
        assert any(ind in reason for ind in indicators), (
            f"decoy_reason must explain why channel data is not valid. Got: {reason}"
        )


# =====================================================================
# decoded_primary.txt
# =====================================================================

class TestDecodedPrimary:
    """Verify the DNS-tunneled exfiltrated data was correctly decoded."""

    @pytest.fixture(scope="class")
    def decoded(self):
        path = "/app/decoded_primary.txt"
        assert os.path.isfile(path), f"{path} not found"
        with open(path) as f:
            return f.read()

    def test_contains_db_host(self, decoded):
        assert "proddb.internal:5432" in decoded

    def test_contains_db_user(self, decoded):
        assert "DB_USER=admin" in decoded

    def test_contains_db_password(self, decoded):
        assert "xK9mP2vL8qR5nT3w" in decoded

    def test_contains_api_key(self, decoded):
        assert "AKIAIOSFODNN7EXAMPLE" in decoded

    def test_contains_api_secret(self, decoded):
        assert "wJalrXUtnFEMIbPxRfiCYEXAMPLEKEY" in decoded


# =====================================================================
# decoded_secondary.txt
# =====================================================================

class TestDecodedSecondary:
    """Verify the HTTP-channel exfiltrated data was correctly decoded."""

    @pytest.fixture(scope="class")
    def decoded(self):
        path = "/app/decoded_secondary.txt"
        assert os.path.isfile(path), f"{path} not found"
        with open(path) as f:
            return f.read()

    def test_contains_db_host(self, decoded):
        assert "proddb.internal:5432" in decoded

    def test_contains_db_user(self, decoded):
        assert "DB_USER=admin" in decoded

    def test_contains_db_password(self, decoded):
        assert "xK9mP2vL8qR5nT3w" in decoded

    def test_contains_api_key(self, decoded):
        assert "AKIAIOSFODNN7EXAMPLE" in decoded

    def test_contains_api_secret(self, decoded):
        assert "wJalrXUtnFEMIbPxRfiCYEXAMPLEKEY" in decoded


# =====================================================================
# channel_assessment.json
# =====================================================================

class TestChannelAssessment:
    """Verify the structured evaluation of exfiltration channels."""

    @pytest.fixture(scope="class")
    def assessment(self):
        path = "/app/channel_assessment.json"
        assert os.path.isfile(path), f"{path} not found"
        with open(path) as f:
            return json.load(f)

    def test_has_at_least_three_channels(self, assessment):
        channels = assessment.get("channels", [])
        assert len(channels) >= 3, (
            f"Expected at least 3 channels, found {len(channels)}"
        )

    def test_has_active_exfiltration_channels(self, assessment):
        active = [c for c in assessment["channels"]
                  if c.get("classification") == "active_exfiltration"]
        assert len(active) >= 2, (
            f"Expected at least 2 active exfiltration channels, found {len(active)}"
        )

    def test_has_decoy_channel(self, assessment):
        decoys = [c for c in assessment["channels"]
                  if c.get("classification") == "decoy"]
        assert len(decoys) >= 1, "Expected at least 1 decoy channel"

    def test_decoy_data_invalid(self, assessment):
        decoys = [c for c in assessment["channels"]
                  if c.get("classification") == "decoy"]
        for d in decoys:
            assert d.get("data_valid") is False, (
                "Decoy channel data_valid must be false"
            )

    def test_active_data_valid(self, assessment):
        active = [c for c in assessment["channels"]
                  if c.get("classification") == "active_exfiltration"]
        for a in active:
            assert a.get("data_valid") is True, (
                f"Active channel '{a.get('id')}' data_valid must be true"
            )

    def test_dns_primary_encoding(self, assessment):
        dns_active = [c for c in assessment["channels"]
                      if c.get("classification") == "active_exfiltration"
                      and "dns" in c.get("type", "").lower()]
        assert len(dns_active) >= 1, (
            "Expected at least one active DNS exfiltration channel"
        )
        assert any("base32" in c.get("encoding", "").lower()
                    for c in dns_active)

    def test_http_channel_encoding(self, assessment):
        http_active = [c for c in assessment["channels"]
                       if c.get("classification") == "active_exfiltration"
                       and "http" in c.get("type", "").lower()]
        assert len(http_active) >= 1, (
            "Expected at least one active HTTP exfiltration channel"
        )
        assert any("hex" in c.get("encoding", "").lower()
                    for c in http_active)

    def test_cross_validation_match(self, assessment):
        cv = assessment.get("cross_validation", {})
        assert cv.get("primary_secondary_match") is True, (
            "Primary and secondary decoded data should match"
        )

    def test_cross_validation_hash(self, assessment):
        cv = assessment.get("cross_validation", {})
        assert cv.get("data_sha256") == EXPECTED_DATA_HASH, (
            f"Expected SHA-256 hash {EXPECTED_DATA_HASH}, "
            f"got {cv.get('data_sha256')}"
        )


# =====================================================================
# detection.rules
# =====================================================================

class TestDetectionRules:
    """Verify IDS rules detect real channels and exclude decoy traffic."""

    @pytest.fixture(scope="class")
    def rules(self):
        path = "/app/detection.rules"
        assert os.path.isfile(path), f"{path} not found"
        with open(path) as f:
            return f.read()

    def test_not_empty(self, rules):
        assert len(rules.strip()) > 50, "Rules file appears too short"

    def test_has_alert_keyword(self, rules):
        assert "alert" in rules.lower(), "Rules must use 'alert' action"

    def test_has_at_least_two_sids(self, rules):
        sids = re.findall(r"sid:\s*(\d+)", rules)
        assert len(sids) >= 2, f"Expected at least 2 SIDs, found {len(sids)}"

    def test_unique_sids(self, rules):
        sids = re.findall(r"sid:\s*(\d+)", rules)
        assert len(sids) == len(set(sids)), "All SIDs must be unique"

    def test_has_msgs(self, rules):
        msgs = re.findall(r'msg:"[^"]+"', rules)
        assert len(msgs) >= 2, "Each rule must have a msg field"

    def test_references_real_c2_domain(self, rules):
        assert "c2server" in rules.lower(), (
            "Rules should reference the real c2server domain"
        )

    def test_has_http_exfil_rule(self, rules):
        lo = rules.lower()
        assert ("events" in lo or "payload" in lo or "metric" in lo
                or "198.51.100.77" in lo or "exfil" in lo), (
            "Should include a rule for the HTTP exfiltration channel"
        )

    def test_does_not_trigger_on_decoy(self, rules):
        for line in rules.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                assert "svcmon" not in line.lower(), (
                    "Detection rules must not target the decoy domain svcmon.io"
                )

    def test_at_least_two_rules(self, rules):
        alert_count = len(re.findall(r"(?i)^alert\s", rules, re.MULTILINE))
        assert alert_count >= 2, (
            f"Expected at least 2 alert rules, found {alert_count}"
        )
