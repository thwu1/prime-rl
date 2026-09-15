"""Verify the Kerberos incident forensics report.

"""

import hashlib
import json
import os

import pytest


def canonical(obj):
    """Canonical JSON for deterministic hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


@pytest.fixture
def report():
    with open("/app/report.json") as f:
        return json.load(f)


@pytest.fixture
def checks():
    with open("/var/lib/task_verify/checks.json") as f:
        return json.load(f)


# ---- Structural tests ----


def test_report_exists():
    assert os.path.isfile("/app/report.json"), "/app/report.json not found"


def test_report_is_valid_json():
    with open("/app/report.json") as f:
        data = json.load(f)
    assert isinstance(data, dict), "report.json root must be a JSON object"


def test_report_has_required_keys(report):
    required = {
        "keytab_summary",
        "ticket_decryptions",
        "anomalous_tickets",
        "compromised_keytab",
        "attacker_principal",
    }
    missing = required - set(report.keys())
    assert not missing, f"Missing top-level keys: {missing}"


def test_keytab_summary_has_three_files(report):
    assert len(report["keytab_summary"]) == 3, "Expected 3 keytab files in summary"


def test_all_six_tickets_decrypted(report):
    assert len(report["ticket_decryptions"]) == 6, (
        f"Expected 6 ticket decryptions, got {len(report['ticket_decryptions'])}"
    )


def test_ticket_decryption_fields(report):
    required_fields = {
        "service_principal",
        "client_principal",
        "client_realm",
        "encryption_type",
        "auth_time",
        "end_time",
        "decrypted_with_keytab",
        "session_key_hex",
    }
    for tkt, details in report["ticket_decryptions"].items():
        missing = required_fields - set(details.keys())
        assert not missing, f"{tkt} missing fields: {missing}"


# ---- Keytab verification ----


def test_total_keytab_entries(report, checks):
    total = sum(len(v) for v in report["keytab_summary"].values())
    assert total == checks["total_keytab_entries"], (
        f"Expected {checks['total_keytab_entries']} keytab entries, got {total}"
    )


def test_keytab_summary_hash(report, checks):
    h = hashlib.sha256(canonical(report["keytab_summary"]).encode()).hexdigest()
    assert h == checks["keytab_summary_hash"], (
        "Keytab summary content does not match expected values"
    )


# ---- Per-ticket detail verification (hash-based) ----


def test_ticket_01_details(report, checks):
    details = report["ticket_decryptions"]["ticket_01.der"]
    h = hashlib.sha256(canonical(details).encode()).hexdigest()
    assert h == checks["ticket_01_hash"], "ticket_01 details incorrect"


def test_ticket_02_details(report, checks):
    details = report["ticket_decryptions"]["ticket_02.der"]
    h = hashlib.sha256(canonical(details).encode()).hexdigest()
    assert h == checks["ticket_02_hash"], "ticket_02 details incorrect"


def test_ticket_03_details(report, checks):
    details = report["ticket_decryptions"]["ticket_03.der"]
    h = hashlib.sha256(canonical(details).encode()).hexdigest()
    assert h == checks["ticket_03_hash"], "ticket_03 details incorrect"


def test_ticket_04_details(report, checks):
    details = report["ticket_decryptions"]["ticket_04.der"]
    h = hashlib.sha256(canonical(details).encode()).hexdigest()
    assert h == checks["ticket_04_hash"], "ticket_04 details incorrect"


def test_ticket_05_details(report, checks):
    details = report["ticket_decryptions"]["ticket_05.der"]
    h = hashlib.sha256(canonical(details).encode()).hexdigest()
    assert h == checks["ticket_05_hash"], "ticket_05 details incorrect"


def test_ticket_06_details(report, checks):
    details = report["ticket_decryptions"]["ticket_06.der"]
    h = hashlib.sha256(canonical(details).encode()).hexdigest()
    assert h == checks["ticket_06_hash"], "ticket_06 details incorrect"


# ---- Forensic analysis verification ----


def test_anomalous_tickets(report, checks):
    anomalous = sorted(report["anomalous_tickets"])
    h = hashlib.sha256(canonical(anomalous).encode()).hexdigest()
    assert h == checks["anomalous_hash"], (
        "Anomalous ticket identification is incorrect"
    )


def test_anomalous_count(report):
    assert len(report["anomalous_tickets"]) == 2, (
        f"Expected 2 anomalous tickets, got {len(report['anomalous_tickets'])}"
    )


def test_compromised_keytab(report, checks):
    h = hashlib.sha256(report["compromised_keytab"].encode()).hexdigest()
    assert h == checks["compromised_keytab_hash"], (
        "Compromised keytab identification is incorrect"
    )


def test_attacker_principal(report, checks):
    h = hashlib.sha256(report["attacker_principal"].encode()).hexdigest()
    assert h == checks["attacker_principal_hash"], (
        "Attacker principal identification is incorrect"
    )
