"""
Verify forensic analysis findings and detection rules against ground truth.

"""

import json
import os
import re
import pytest

FINDINGS_PATH = "/app/findings.json"
RULES_PATH = "/app/detection.rules"


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def findings():
    assert os.path.isfile(FINDINGS_PATH), (
        f"Findings file not found at {FINDINGS_PATH}"
    )
    with open(FINDINGS_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def rules_text():
    assert os.path.isfile(RULES_PATH), (
        f"Detection rules not found at {RULES_PATH}"
    )
    with open(RULES_PATH) as f:
        return f.read()


@pytest.fixture(scope="module")
def parsed_rules(rules_text):
    lines = [l.strip() for l in rules_text.splitlines()
             if l.strip() and not l.strip().startswith("#")]
    return lines


# ── Part 1: Forensic findings tests ──────────────────────────────────

def test_victim_ip(findings):
    assert findings.get("victim_ip") == "10.13.37.105", (
        "Incorrect victim IP"
    )


def test_c2_server_ip(findings):
    assert findings.get("c2_server_ip") == "91.234.99.71", (
        "Incorrect C2 server IP"
    )


def test_c2_port(findings):
    assert findings.get("c2_port") == 8443, (
        "Incorrect C2 port"
    )


def test_encryption_key(findings):
    assert findings.get("encryption_key") == "5a7b3e2f", (
        "Incorrect encryption key"
    )


def test_victim_hostname(findings):
    assert findings.get("victim_hostname") == "WS-PC0117", (
        "Incorrect victim hostname"
    )


def test_victim_username(findings):
    assert findings.get("victim_username") == "j.morrison", (
        "Incorrect victim username"
    )


def test_c2_commands(findings):
    expected = {"enum_shares", "dump_creds", "exfil", "cleanup"}
    actual = set(findings.get("c2_commands", []))
    assert actual == expected, (
        f"C2 commands mismatch: expected {expected}, got {actual}"
    )


def test_compromised_credentials(findings):
    expected = {
        "admin": "P@ssw0rd!2024",
        "svc_backup": "Backup#Str0ng",
    }
    actual = findings.get("compromised_credentials", {})
    assert actual == expected, (
        f"Credentials mismatch: expected {expected}, got {actual}"
    )


def test_exfiltrated_data(findings):
    expected = (
        "CONFIDENTIAL: Q3 Revenue Projection - $4.7M shortfall. "
        "Board meeting moved to Dec 15. "
        "Contact: CFO j.morrison@corp.local"
    )
    actual = findings.get("exfiltrated_data", "")
    assert actual == expected, (
        f"Exfiltrated data mismatch.\n"
        f"Expected: {expected!r}\n"
        f"Got:      {actual!r}"
    )


def test_exfil_domain(findings):
    assert findings.get("exfil_domain") == "telemetry-cdn.net", (
        "Incorrect exfiltration domain"
    )


# ── Part 2: Detection rules tests ────────────────────────────────────

def test_detection_rules_file_nonempty(rules_text):
    assert len(rules_text.strip()) > 50, (
        "detection.rules file is empty or too short"
    )


def test_detection_rules_minimum_count(parsed_rules):
    assert len(parsed_rules) >= 3, (
        f"Expected at least 3 detection rules, found {len(parsed_rules)}"
    )


def test_detection_rules_syntax(parsed_rules):
    for i, rule in enumerate(parsed_rules):
        assert rule.startswith("alert "), (
            f"Rule {i+1} must start with 'alert': {rule[:80]}"
        )
        assert "msg:" in rule, (
            f"Rule {i+1} missing required 'msg' field"
        )
        assert "sid:" in rule, (
            f"Rule {i+1} missing required 'sid' field"
        )
        assert "rev:" in rule, (
            f"Rule {i+1} missing required 'rev' field"
        )
        assert "content:" in rule, (
            f"Rule {i+1} missing 'content' match — rules must detect "
            f"specific protocol artifacts"
        )


def test_detection_c2_port_targeted(rules_text):
    """At least one rule must reference the C2 port."""
    assert "8443" in rules_text, (
        "No detection rule references C2 port 8443"
    )


def test_detection_c2_protocol_magic(rules_text):
    """At least one rule must match the C2 protocol's magic byte header."""
    normalized = rules_text.upper()
    has_magic = bool(re.search(r'\|[^|]*DE\s*AD[^|]*\|', normalized))
    assert has_magic, (
        "No rule contains a hex content match for the C2 magic bytes "
        "(0xDEAD). Rules must use Suricata pipe-hex syntax, e.g. "
        'content:"|DE AD|";'
    )


def test_detection_exfil_domain_targeted(rules_text):
    """At least one rule must detect queries to the exfiltration domain."""
    assert "telemetry-cdn.net" in rules_text, (
        "No detection rule references the exfiltration domain "
        "'telemetry-cdn.net'"
    )
