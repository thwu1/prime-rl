
"""Tests for multi-channel C2 protocol forensics with threat deconfliction.

Verifies the agent's answers.json, YARA detection rule, and Sigma
detection rule against independently computed expected values.
"""

import hashlib
import hmac
import base64
import json
import os
import subprocess
import pytest
import yaml


# --- Constants (must match generate_evidence.py) ---

C2_DNS_DOMAIN = "cdn-telemetry.analytics-data.net"
C2_HTTP_DOMAIN = "api.webstats-collector.com"
REDTEAM_DNS_DOMAIN = "tunnel.redteam-ops.net"
DECOY_DNS_1 = "probe.netcheck-monitoring.io"
DECOY_DNS_2 = "resolve.dev-sandbox-testing.org"
COMPROMISED_IP = "10.0.1.42"
CAMPAIGN_ID = "OP-THUNDERSTRIKE-2024"
BEACON_INTERVAL = 30
FIRST_CONTACT_EPOCH = 1709251200

EXFIL_DATA = """# Exfiltrated Configuration - Production Environment
# Last modified: 2024-02-28

[database]
primary_host = prod-db-primary.internal.corp
replica_host = prod-db-replica-01.internal.corp
port = 5432
database = customer_records
username = svc_reporting
password = kJ#9mPx$2vL!qR8n
ssl_mode = require
max_connections = 50

[redis]
host = cache-prod-01.internal.corp
port = 6379
password = r3d1s_pr0d_s3cr3t_2024!

[api_keys]
stripe_live = sk_live_7f3a9b2c4d5e6f1a8b9c0d1e2f3a4b5c
sendgrid = SG.abc123def456.xyz789
aws_access_key = AKIAIOSFODNN7EXAMPLE
aws_secret_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY

[internal_services]
auth_service = http://auth-api.internal.corp:8080
payment_gateway = http://payments.internal.corp:9090
admin_panel_key = adm1n_p4n3l_m4st3r_k3y_2024""".strip()

EXPECTED_CLASSIFICATIONS = {
    C2_DNS_DOMAIN: "active_c2",
    REDTEAM_DNS_DOMAIN: "authorized_redteam",
    DECOY_DNS_1: "benign_monitoring",
    DECOY_DNS_2: "benign_testing",
}


def _compute_expected():
    """Compute all expected values from constants."""
    # Key derivation: HMAC-SHA256
    key = hmac.new(
        CAMPAIGN_ID.encode(), b"c2-exfil-key", hashlib.sha256
    ).digest()[:16]

    data_bytes = EXFIL_DATA.encode()
    split_point = len(data_bytes) // 2
    part1 = data_bytes[:split_point]
    part2 = data_bytes[split_point:]

    # Full hash
    exfil_sha256 = hashlib.sha256(EXFIL_DATA.encode()).hexdigest()

    # DNS query count: init + data chunks + fini
    dns_encrypted = bytes(
        d ^ key[i % len(key)] for i, d in enumerate(part1)
    )
    dns_encoded = base64.b32encode(dns_encrypted).decode().lower().rstrip("=")
    dns_chunk_count = -(-len(dns_encoded) // 50)  # ceil division
    dns_total_queries = 1 + dns_chunk_count + 1  # init + data + fini

    # HTTP POST count
    http_encrypted = bytes(
        d ^ key[(split_point + i) % len(key)]
        for i, d in enumerate(part2)
    )
    http_encoded = base64.b64encode(http_encrypted).decode()
    http_chunk_count = -(-len(http_encoded) // 200)  # ceil division

    return {
        "c2_dns_domain": C2_DNS_DOMAIN,
        "redteam_dns_domain": REDTEAM_DNS_DOMAIN,
        "decoy_domains": sorted([DECOY_DNS_1, DECOY_DNS_2]),
        "c2_http_domain": C2_HTTP_DOMAIN,
        "compromised_host_ip": COMPROMISED_IP,
        "campaign_id": CAMPAIGN_ID,
        "encryption_key_hex": key.hex(),
        "exfiltrated_data_sha256": exfil_sha256,
        "dns_exfil_query_count": dns_total_queries,
        "http_exfil_post_count": http_chunk_count,
        "beacon_interval_seconds": BEACON_INTERVAL,
        "first_c2_contact_epoch": FIRST_CONTACT_EPOCH,
    }


@pytest.fixture(scope="module")
def answers():
    """Load the agent's answers from /app/answers.json."""
    answers_path = "/app/answers.json"
    assert os.path.exists(answers_path), (
        f"answers.json not found at {answers_path}"
    )
    with open(answers_path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def expected():
    """Compute expected values."""
    return _compute_expected()


# --- Basic existence tests ---

def test_answers_file_exists():
    assert os.path.exists("/app/answers.json"), "answers.json not found"


def test_yara_rule_exists():
    assert os.path.exists("/app/detection/implant.yar"), \
        "YARA rule not found at /app/detection/implant.yar"


def test_sigma_rule_exists():
    assert os.path.exists("/app/detection/c2_dns_tunnel.yml"), \
        "Sigma rule not found at /app/detection/c2_dns_tunnel.yml"


# --- Answer field tests ---

def test_c2_dns_domain(answers, expected):
    assert answers.get("c2_dns_domain") == expected["c2_dns_domain"], (
        f"Expected DNS C2 domain '{expected['c2_dns_domain']}', "
        f"got '{answers.get('c2_dns_domain')}'"
    )


def test_redteam_dns_domain(answers, expected):
    assert answers.get("redteam_dns_domain") == expected["redteam_dns_domain"], (
        f"Expected red team domain '{expected['redteam_dns_domain']}', "
        f"got '{answers.get('redteam_dns_domain')}'"
    )


def test_decoy_domains(answers, expected):
    actual = sorted(answers.get("decoy_domains", []))
    assert actual == expected["decoy_domains"], (
        f"Expected decoy domains {expected['decoy_domains']}, got {actual}"
    )


def test_c2_http_domain(answers, expected):
    assert answers.get("c2_http_domain") == expected["c2_http_domain"], (
        f"Expected HTTP C2 domain '{expected['c2_http_domain']}', "
        f"got '{answers.get('c2_http_domain')}'"
    )


def test_compromised_host_ip(answers, expected):
    assert answers.get("compromised_host_ip") == expected["compromised_host_ip"], (
        f"Expected compromised IP '{expected['compromised_host_ip']}', "
        f"got '{answers.get('compromised_host_ip')}'"
    )


def test_campaign_id(answers, expected):
    assert answers.get("campaign_id") == expected["campaign_id"], (
        f"Expected campaign ID '{expected['campaign_id']}', "
        f"got '{answers.get('campaign_id')}'"
    )


def test_encryption_key(answers, expected):
    assert answers.get("encryption_key_hex") == expected["encryption_key_hex"], (
        f"Expected key '{expected['encryption_key_hex']}', "
        f"got '{answers.get('encryption_key_hex')}'"
    )


def test_exfiltrated_data_sha256(answers, expected):
    assert answers.get("exfiltrated_data_sha256") == expected["exfiltrated_data_sha256"], (
        f"Expected SHA-256 '{expected['exfiltrated_data_sha256']}', "
        f"got '{answers.get('exfiltrated_data_sha256')}'"
    )


def test_dns_exfil_query_count(answers, expected):
    actual = int(answers.get("dns_exfil_query_count", 0))
    assert actual == expected["dns_exfil_query_count"], (
        f"Expected {expected['dns_exfil_query_count']} DNS exfil queries, got {actual}"
    )


def test_http_exfil_post_count(answers, expected):
    actual = int(answers.get("http_exfil_post_count", 0))
    assert actual == expected["http_exfil_post_count"], (
        f"Expected {expected['http_exfil_post_count']} HTTP exfil POSTs, got {actual}"
    )


def test_beacon_interval(answers, expected):
    actual = int(answers.get("beacon_interval_seconds", 0))
    assert actual == expected["beacon_interval_seconds"], (
        f"Expected beacon interval {expected['beacon_interval_seconds']}s, got {actual}s"
    )


def test_first_c2_contact_epoch(answers, expected):
    actual = int(answers.get("first_c2_contact_epoch", 0))
    # Allow +-5 second tolerance due to jitter in beacon generation
    assert abs(actual - expected["first_c2_contact_epoch"]) <= 5, (
        f"Expected first contact epoch ~{expected['first_c2_contact_epoch']}, "
        f"got {actual} (diff={abs(actual - expected['first_c2_contact_epoch'])}s)"
    )


# --- Threat classification tests ---

def test_classification_c2(answers):
    """C2 domain must be classified as active_c2."""
    classifications = answers.get("threat_classifications", {})
    assert classifications.get(C2_DNS_DOMAIN) == "active_c2", (
        f"Expected '{C2_DNS_DOMAIN}' classified as 'active_c2', "
        f"got '{classifications.get(C2_DNS_DOMAIN)}'"
    )


def test_classification_redteam(answers):
    """Red team domain must be classified as authorized_redteam."""
    classifications = answers.get("threat_classifications", {})
    assert classifications.get(REDTEAM_DNS_DOMAIN) == "authorized_redteam", (
        f"Expected '{REDTEAM_DNS_DOMAIN}' classified as 'authorized_redteam', "
        f"got '{classifications.get(REDTEAM_DNS_DOMAIN)}'"
    )


def test_classification_decoy1(answers):
    """Network monitoring decoy must be classified as benign_monitoring."""
    classifications = answers.get("threat_classifications", {})
    assert classifications.get(DECOY_DNS_1) == "benign_monitoring", (
        f"Expected '{DECOY_DNS_1}' classified as 'benign_monitoring', "
        f"got '{classifications.get(DECOY_DNS_1)}'"
    )


def test_classification_decoy2(answers):
    """Developer testing decoy must be classified as benign_testing."""
    classifications = answers.get("threat_classifications", {})
    assert classifications.get(DECOY_DNS_2) == "benign_testing", (
        f"Expected '{DECOY_DNS_2}' classified as 'benign_testing', "
        f"got '{classifications.get(DECOY_DNS_2)}'"
    )


def test_classification_completeness(answers):
    """All four suspicious domains must be classified."""
    classifications = answers.get("threat_classifications", {})
    expected_domains = {C2_DNS_DOMAIN, REDTEAM_DNS_DOMAIN, DECOY_DNS_1, DECOY_DNS_2}
    actual_domains = set(classifications.keys())
    missing = expected_domains - actual_domains
    assert not missing, f"Missing classifications for: {missing}"


# --- YARA rule validation tests ---

def test_yara_rule_matches_malware():
    """YARA rule must match the recovered malware fragment."""
    result = subprocess.run(
        ["yara", "/app/detection/implant.yar",
         "/app/evidence/recovered/svc_update.py.fragment"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"YARA scan failed: stderr={result.stderr}"
    )
    assert result.stdout.strip(), (
        "YARA rule did not match the malware fragment — "
        "expected at least one rule match"
    )


def test_yara_rule_no_false_positive():
    """YARA rule must NOT match the clean Python sample."""
    result = subprocess.run(
        ["yara", "/app/detection/implant.yar",
         "/app/evidence/clean_sample.py"],
        capture_output=True, text=True, timeout=30,
    )
    # returncode 0 with no stdout = no matches (correct)
    # returncode 0 with stdout = false positive (bad)
    assert not result.stdout.strip(), (
        f"YARA rule false-positived on clean sample: {result.stdout.strip()}"
    )


# --- Sigma detection rule validation tests ---

def test_sigma_rule_valid_yaml():
    """Sigma rule must be valid YAML with required Sigma fields."""
    with open("/app/detection/c2_dns_tunnel.yml") as f:
        rule = yaml.safe_load(f)

    assert isinstance(rule, dict), "Sigma rule must be a YAML mapping"
    assert "title" in rule, "Sigma rule missing required 'title' field"
    assert "logsource" in rule, "Sigma rule missing required 'logsource' field"
    assert "detection" in rule, "Sigma rule missing required 'detection' field"
    assert "level" in rule, "Sigma rule missing required 'level' field"


def test_sigma_rule_targets_dns():
    """Sigma rule logsource must target DNS logs."""
    with open("/app/detection/c2_dns_tunnel.yml") as f:
        rule = yaml.safe_load(f)

    logsource = rule.get("logsource", {})
    logsource_str = json.dumps(logsource).lower()
    assert "dns" in logsource_str, (
        "Sigma rule logsource must reference DNS "
        f"(category: dns or product: zeek), got: {logsource}"
    )


def test_sigma_rule_has_c2_indicators():
    """Sigma detection must reference C2-specific indicators."""
    with open("/app/detection/c2_dns_tunnel.yml") as f:
        rule = yaml.safe_load(f)

    detection = rule.get("detection", {})
    detection_str = json.dumps(detection).lower()

    # Must reference at least one C2-specific indicator
    c2_indicators = [".d.", "txt", "base32", C2_DNS_DOMAIN.lower(),
                     "analytics-data"]
    matched = [ind for ind in c2_indicators if ind in detection_str]
    assert matched, (
        "Sigma detection section should reference C2-specific indicators "
        "(e.g., TXT query type, '.d.' separator, or C2 domain name). "
        f"Found none of {c2_indicators} in detection: {detection}"
    )
