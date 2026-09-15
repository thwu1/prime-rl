"""Tests for breach forensics with anti-forensics detection and security evaluation."""

import json
import os

import pytest

REPORT_PATH = "/app/report.json"

EXPECTED_CREDENTIALS = {
    "webadmin": "Summer2023!",
    "svc_monitor": "M0nit0r@2023",
    "backup_svc": "B@ckup!2023",
    "adm_file": "F1leSvc2023!",
    "dev_ops": "Deploy@23",
}

EXPECTED_GENUINE_CREDENTIALS = {"webadmin", "svc_monitor", "backup_svc", "adm_file"}
EXPECTED_PLANTED_CREDENTIALS = {"dev_ops"}

EXPECTED_PATH = [
    {
        "hop": 1,
        "source_host": "EXTERNAL",
        "source_ip": "203.0.113.45",
        "destination_host": "WEBSVR01",
        "destination_ip": "10.10.10.50",
        "username": "webadmin",
        "tunnel_type_options": [
            "direct_ssh", "direct", "ssh",
        ],
    },
    {
        "hop": 2,
        "source_host": "WEBSVR01",
        "source_ip": "172.16.1.10",
        "destination_host": "JUMPBOX",
        "destination_ip": "172.16.1.25",
        "username": "svc_monitor",
        "tunnel_type_options": [
            "ssh_dynamic_socks", "dynamic_socks", "socks",
            "ssh_dynamic", "dynamic_port_forward",
        ],
    },
    {
        "hop": 3,
        "source_host": "JUMPBOX",
        "source_ip": "172.16.5.1",
        "destination_host": "FILESVR01",
        "destination_ip": "172.16.5.30",
        "username": "backup_svc",
        "tunnel_type_options": [
            "ssh_local_forward", "local_forward",
            "ssh_local", "local_port_forward",
        ],
    },
    {
        "hop": 4,
        "source_host": "FILESVR01",
        "source_ip": "192.168.100.10",
        "destination_host": "DC01",
        "destination_ip": "192.168.100.50",
        "username": "adm_file",
        "tunnel_type_options": [
            "ssh_local_forward", "local_forward",
            "ssh_local", "local_port_forward",
        ],
    },
]

EXPECTED_DUAL_HOMED = {
    "WEBSVR01": {"10.10.10.50", "172.16.1.10"},
    "JUMPBOX": {"172.16.1.25", "172.16.5.1"},
    "FILESVR01": {"172.16.5.30", "192.168.100.10"},
}

# Indicators of fabricated evidence — at least some must be detected
PHANTOM_IP = "172.16.5.50"
PLANTED_USER = "dev_ops"


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), f"Report file not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


# ===== Report structure =====

def test_report_has_required_keys(report):
    required = {
        "true_attack_path", "fabricated_evidence", "cracked_credentials",
        "genuine_attack_credentials", "planted_credentials",
        "dual_homed_hosts", "exfiltrated_data", "policy_violations",
    }
    missing = required - set(report.keys())
    assert not missing, f"Missing top-level keys: {missing}"


# ===== True attack path =====

def test_attack_path_length(report):
    path = report["true_attack_path"]
    assert len(path) == 4, f"Expected 4 hops, got {len(path)}"


def test_attack_path_hop_ordering(report):
    path = sorted(report["true_attack_path"], key=lambda x: x["hop"])
    for i, expected in enumerate(EXPECTED_PATH):
        actual = path[i]
        assert actual["hop"] == expected["hop"]


def test_attack_path_source_hosts(report):
    path = sorted(report["true_attack_path"], key=lambda x: x["hop"])
    for i, expected in enumerate(EXPECTED_PATH):
        actual = path[i]
        assert actual["source_host"].upper() == expected["source_host"].upper(), (
            f"Hop {expected['hop']}: wrong source_host '{actual['source_host']}'"
        )


def test_attack_path_source_ips(report):
    path = sorted(report["true_attack_path"], key=lambda x: x["hop"])
    for i, expected in enumerate(EXPECTED_PATH):
        actual = path[i]
        assert actual["source_ip"] == expected["source_ip"], (
            f"Hop {expected['hop']}: wrong source_ip '{actual['source_ip']}'"
        )


def test_attack_path_destination_hosts(report):
    path = sorted(report["true_attack_path"], key=lambda x: x["hop"])
    for i, expected in enumerate(EXPECTED_PATH):
        actual = path[i]
        assert actual["destination_host"].upper() == expected["destination_host"].upper(), (
            f"Hop {expected['hop']}: wrong dest_host '{actual['destination_host']}'"
        )


def test_attack_path_destination_ips(report):
    path = sorted(report["true_attack_path"], key=lambda x: x["hop"])
    for i, expected in enumerate(EXPECTED_PATH):
        actual = path[i]
        assert actual["destination_ip"] == expected["destination_ip"], (
            f"Hop {expected['hop']}: wrong dest_ip '{actual['destination_ip']}'"
        )


def test_attack_path_usernames(report):
    path = sorted(report["true_attack_path"], key=lambda x: x["hop"])
    for i, expected in enumerate(EXPECTED_PATH):
        actual = path[i]
        assert actual["username"] == expected["username"], (
            f"Hop {expected['hop']}: wrong username '{actual['username']}'"
        )


def test_attack_path_passwords(report):
    path = sorted(report["true_attack_path"], key=lambda x: x["hop"])
    for hop in path:
        username = hop["username"]
        assert username in EXPECTED_CREDENTIALS, f"Unknown user: {username}"
        assert hop["password"] == EXPECTED_CREDENTIALS[username], (
            f"Wrong password for {username}"
        )


def test_attack_path_tunnel_types(report):
    path = sorted(report["true_attack_path"], key=lambda x: x["hop"])
    for i, expected in enumerate(EXPECTED_PATH):
        actual = path[i]
        tunnel_type = actual.get("tunnel_type", "").lower().replace(" ", "_")
        assert tunnel_type in expected["tunnel_type_options"], (
            f"Hop {expected['hop']}: unexpected tunnel_type '{actual.get('tunnel_type')}'"
        )


# ===== Fabricated evidence detection =====

def test_fabricated_evidence_nonempty(report):
    fab = report["fabricated_evidence"]
    assert isinstance(fab, list) and len(fab) >= 2, (
        f"Expected at least 2 fabricated evidence items, got {len(fab) if isinstance(fab, list) else 0}"
    )


def test_fabricated_evidence_detects_phantom_ip_or_planted_user(report):
    """At least one fabricated evidence item must reference the phantom IP or planted user."""
    fab = report["fabricated_evidence"]
    fab_text = json.dumps(fab).lower()
    found_phantom = PHANTOM_IP in fab_text
    found_user = PLANTED_USER in fab_text
    assert found_phantom or found_user, (
        f"Fabricated evidence must reference phantom IP {PHANTOM_IP} or planted user {PLANTED_USER}"
    )


def test_fabricated_evidence_multiple_artifact_types(report):
    """Fabricated evidence should span at least 2 different artifact types or hosts."""
    fab = report["fabricated_evidence"]
    hosts_or_artifacts = set()
    for item in fab:
        if isinstance(item, dict):
            h = str(item.get("host", "")).upper()
            a = str(item.get("artifact", "")).lower()
            hosts_or_artifacts.add(f"{h}:{a}")
    assert len(hosts_or_artifacts) >= 2, (
        f"Fabricated evidence should cover at least 2 host:artifact combinations, "
        f"got {hosts_or_artifacts}"
    )


def test_fabricated_evidence_covers_auth_log(report):
    """Must detect fabrication in JUMPBOX auth.log (the core anti-forensics entry)."""
    fab = report["fabricated_evidence"]
    fab_text = json.dumps(fab).lower()
    found_jumpbox_auth = (
        ("jumpbox" in fab_text and "auth" in fab_text) or
        ("jumpbox" in fab_text and "dev_ops" in fab_text) or
        ("jumpbox" in fab_text and "172.16.5.50" in fab_text)
    )
    assert found_jumpbox_auth, (
        "Must identify fabricated auth.log entry on JUMPBOX "
        "(dev_ops from 172.16.5.50)"
    )


# ===== Credential cracking =====

def test_cracked_credentials_complete(report):
    creds = report["cracked_credentials"]
    for user, password in EXPECTED_CREDENTIALS.items():
        assert user in creds, f"Missing cracked credential for '{user}'"
        assert creds[user] == password, (
            f"Wrong password for {user}: got '{creds[user]}'"
        )


# ===== Credential classification =====

def test_genuine_credentials_classified(report):
    genuine = set(report["genuine_attack_credentials"])
    for user in EXPECTED_GENUINE_CREDENTIALS:
        assert user in genuine, (
            f"'{user}' should be classified as genuine attack credential"
        )


def test_planted_credentials_classified(report):
    planted = set(report["planted_credentials"])
    for user in EXPECTED_PLANTED_CREDENTIALS:
        assert user in planted, (
            f"'{user}' should be classified as planted credential"
        )


def test_no_credential_classification_overlap(report):
    genuine = set(report["genuine_attack_credentials"])
    planted = set(report["planted_credentials"])
    overlap = genuine & planted
    assert not overlap, f"Credentials in both genuine and planted: {overlap}"


def test_planted_not_in_genuine(report):
    genuine = set(report["genuine_attack_credentials"])
    for user in EXPECTED_PLANTED_CREDENTIALS:
        assert user not in genuine, (
            f"Planted credential '{user}' should not appear in genuine list"
        )


# ===== Dual-homed hosts =====

def test_dual_homed_hosts_identified(report):
    dual = report["dual_homed_hosts"]
    for host, expected_ips in EXPECTED_DUAL_HOMED.items():
        matching_key = None
        for k in dual:
            if k.upper() == host.upper():
                matching_key = k
                break
        assert matching_key is not None, f"Missing dual-homed host: {host}"
        actual_ips = set(dual[matching_key])
        assert actual_ips == expected_ips, (
            f"Wrong IPs for {host}: got {actual_ips}, expected {expected_ips}"
        )


# ===== Exfiltration =====

def test_exfiltrated_data_source_host(report):
    exfil = report["exfiltrated_data"]
    source = exfil.get("source_host", "").upper()
    assert source == "DC01", f"Wrong exfiltration source: '{source}'"


def test_exfiltrated_data_type(report):
    exfil = report["exfiltrated_data"]
    data_type = exfil.get("data_type", "").lower()
    keywords = ["ntds", "sam.ldb", "active directory", "ad database",
                "directory database", "domain database", "samba"]
    assert any(kw in data_type for kw in keywords), (
        f"Exfiltrated data_type should reference AD/NTDS/sam.ldb, got: '{data_type}'"
    )


# ===== Policy violations =====

def test_policy_violations_nonempty(report):
    violations = report["policy_violations"]
    assert isinstance(violations, list) and len(violations) >= 2, (
        f"Expected at least 2 policy violations, got {len(violations) if isinstance(violations, list) else 0}"
    )


def _violation_text(violations):
    """Concatenate all violation fields into one searchable string."""
    parts = []
    for v in violations:
        if isinstance(v, dict):
            for val in v.values():
                parts.append(str(val).lower())
    return " ".join(parts)


def test_policy_violation_shadow_permissions(report):
    """Must identify WEBSVR01 shadow file permission misconfiguration."""
    vtext = _violation_text(report["policy_violations"])
    shadow_detected = (
        ("shadow" in vtext and ("644" in vtext or "permission" in vtext or "world" in vtext or "readable" in vtext)) or
        ("shadow" in vtext and "misconfigur" in vtext)
    )
    assert shadow_detected, (
        "Must identify shadow file permission violation (644/world-readable on WEBSVR01)"
    )


def test_policy_violation_server_restricted_access(report):
    """Must identify that FILESVR01 should not have SSH to Restricted zone."""
    vtext = _violation_text(report["policy_violations"])
    server_restricted = (
        ("filesvr" in vtext or "file server" in vtext) and
        ("restricted" in vtext or "dc01" in vtext or "rule 4" in vtext or "admin" in vtext)
    ) or (
        "server" in vtext and "restricted" in vtext and
        ("ssh" in vtext or "access" in vtext or "rule 4" in vtext)
    )
    assert server_restricted, (
        "Must identify FILESVR01 (non-admin) having SSH access to Restricted zone"
    )


def test_policy_violation_restricted_exfiltration(report):
    """Must identify data exfiltration from Restricted zone violating air-gap policy."""
    vtext = _violation_text(report["policy_violations"])
    exfil_violation = (
        ("restricted" in vtext or "dc01" in vtext or "air" in vtext) and
        ("exfiltrat" in vtext or "deny" in vtext or "outbound" in vtext or
         "tunnel" in vtext or "rule 5" in vtext or "bypass" in vtext)
    )
    assert exfil_violation, (
        "Must identify Restricted zone data exfiltration violating DENY ALL / air-gap policy"
    )
