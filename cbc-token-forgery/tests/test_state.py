
import json
import hashlib
import hmac
import os

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

AUDIT_PATH = "/app/audit.json"
VFY_DIR = "/var/run/svc"
PORTS = ["5001", "5002", "5003"]


def _load_audit():
    with open(AUDIT_PATH) as f:
        return json.load(f)


def test_audit_file_exists():
    assert os.path.exists(AUDIT_PATH), f"{AUDIT_PATH} not found"


def test_audit_structure():
    data = _load_audit()
    for port in PORTS:
        assert port in data, f"Missing entry for port {port}"
        entry = data[port]
        for field in ("cipher_mode", "exploitable", "flag"):
            assert field in entry, f"Port {port}: missing field '{field}'"
        assert isinstance(entry["exploitable"], bool), (
            f"Port {port}: 'exploitable' must be boolean"
        )
        assert entry["cipher_mode"] in ("ecb", "cbc", "ctr", "gcm", "cfb", "ofb"), (
            f"Port {port}: invalid cipher_mode '{entry['cipher_mode']}'"
        )


def test_exploitable_services_have_correct_flags():
    data = _load_audit()
    verified = 0
    for port in PORTS:
        entry = data[port]
        if not entry["exploitable"]:
            continue
        fh_path = os.path.join(VFY_DIR, f"{port}.fh")
        assert os.path.exists(fh_path), f"Verification file missing for port {port}"
        with open(fh_path) as f:
            expected_hash = f.read().strip()
        assert entry["flag"] is not None and len(entry["flag"]) > 0, (
            f"Port {port}: marked exploitable but no flag provided"
        )
        actual_hash = hashlib.sha256(entry["flag"].encode()).hexdigest()
        assert actual_hash == expected_hash, (
            f"Port {port}: flag is incorrect"
        )
        verified += 1
    assert verified >= 2, "Expected at least 2 exploitable services with correct flags"


def test_exploitable_services_have_correct_modes():
    data = _load_audit()
    for port in PORTS:
        entry = data[port]
        if not entry["exploitable"]:
            continue
        mm_path = os.path.join(VFY_DIR, f"{port}.mm")
        assert os.path.exists(mm_path), f"Mode verification file missing for port {port}"
        with open(mm_path) as f:
            expected_mac = f.read().strip()
        mac = hmac.new(
            entry["flag"].encode(),
            entry["cipher_mode"].encode(),
            hashlib.sha256,
        )
        assert mac.hexdigest() == expected_mac, (
            f"Port {port}: cipher_mode '{entry['cipher_mode']}' is incorrect"
        )


def test_secure_service_classification():
    data = _load_audit()
    secure_ports = [p for p in PORTS if not data[p]["exploitable"]]
    assert len(secure_ports) >= 1, "Expected at least 1 non-exploitable service"
    for port in secure_ports:
        entry = data[port]
        assert entry["flag"] is None or entry["flag"] == "", (
            f"Port {port}: non-exploitable service should not have a flag"
        )
        assert entry["cipher_mode"] in ("gcm", "ccm", "siv", "eax"), (
            f"Port {port}: non-exploitable service should use authenticated encryption, "
            f"got '{entry['cipher_mode']}'"
        )


def test_vulnerability_counts():
    data = _load_audit()
    exploitable = sum(1 for p in PORTS if data[p]["exploitable"])
    secure = sum(1 for p in PORTS if not data[p]["exploitable"])
    assert exploitable == 2, f"Expected exactly 2 exploitable services, got {exploitable}"
    assert secure == 1, f"Expected exactly 1 secure service, got {secure}"


def test_flags_are_distinct():
    data = _load_audit()
    flags = [
        data[p]["flag"] for p in PORTS
        if data[p]["exploitable"] and data[p]["flag"]
    ]
    assert len(flags) == len(set(flags)), "Extracted flags must be distinct across services"


def test_services_still_running():
    for port in PORTS:
        try:
            if port == "5003":
                r = requests.get(
                    f"https://localhost:{port}/api/health",
                    timeout=5, verify=False)
            else:
                r = requests.get(
                    f"http://localhost:{port}/api/health",
                    timeout=5)
            assert r.status_code == 200, (
                f"Port {port}: health check returned {r.status_code}"
            )
        except requests.ConnectionError:
            assert False, f"Port {port}: service not reachable"
