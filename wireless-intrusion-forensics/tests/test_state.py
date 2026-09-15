
import hashlib
import json
import os
import re
import subprocess
import pytest

PCAP = "/app/evidence08.pcap"
REPORT = "/app/assessment.json"

# Pre-computed SHA-256 digests — no plaintext answers in this file.
# Each digest is sha256(expected_value.encode()).hexdigest().
_H = {
    "ssid": "9b53b55c408144bc1265a2a9a5be34adacc847e20f9c24f95c7d828da84ce923",
    "bssid": "412749e7b4b7bbe7bbcc21a003e454eab00a5c7e9ffbd2614af4e24f62cbd560",
    "wep_key": "c9366fb195e4a8e4a527ea20841487b18cf6d708133395fc224a0c225134d598",
    "attacker_mac": "5930990b55fa44e8ab4876a38fcc194a6802ccf557d659b304a1f9d06a5625b9",
    "attack_technique": "7893f439f241305eaa200d753d0f4b6ce22b1da9eab6fa25a2d0cd8f83b019d1",
    "admin_username": "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918",
    "admin_password": "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918",
    "new_admin_passphrase": "8c4d3a28f5906d1ee05247675ee8c6d091159c48c1c849a8790132f023875dd2",
    "capture_duration": "8111eb1556229541d7d2720a51203037e78ee57fb2e407e0da4a805473dab7af",
    "total_wep_data_frames": "091d2d620e53400245b6fad0612d3c0e384260085e623ed4f34b2f2d9cc528d1",
    "total_unique_ivs": "2d494105d3f4c9c8a0acb3eca50951194ee6d7631eb0a051e6327a5c76741231",
}


def _sha(value):
    """SHA-256 hex digest of a string."""
    return hashlib.sha256(str(value).encode()).hexdigest()


def _norm_mac(mac):
    return mac.strip().lower().replace("-", ":")


def _norm_key(key):
    return key.strip().upper().replace("-", ":")


def _parse_int_field(val_str):
    """Parse a tshark integer field value robustly.
    Handles hex (0x...), plain decimal, or decimal followed by text."""
    v = val_str.strip().split(",")[0].strip()
    if not v:
        return None
    if v.startswith("0x"):
        return int(v, 16)
    m = re.match(r'(\d+)', v)
    if m:
        return int(m.group(1))
    return None


def _tshark(args, timeout=300):
    """Run tshark with given args, return stdout. Raises on non-zero exit."""
    cmd = ["tshark"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, f"tshark failed: {result.stderr[:500]}"
    return result.stdout


@pytest.fixture
def report():
    assert os.path.exists(REPORT), f"{REPORT} does not exist"
    with open(REPORT) as f:
        return json.load(f)


# ---------- structural tests ----------

def test_report_valid_json():
    """assessment.json exists and is valid JSON with required keys."""
    assert os.path.exists(REPORT)
    with open(REPORT) as f:
        data = json.load(f)
    assert isinstance(data, dict)
    required = [
        "ssid", "bssid", "wep_key", "attacker_mac", "attack_technique",
        "technique_evidence", "capture_duration_seconds", "total_wep_data_frames",
        "total_unique_ivs", "attacker_unique_ivs", "attacker_iv_share",
        "deauth_frame_count", "admin_username", "admin_password",
        "new_admin_passphrase", "deauth_detection_filter", "replay_detection_filter",
    ]
    for key in required:
        assert key in data, f"Missing required key: {key}"


# ---------- network identification (hashed) ----------

def test_ssid(report):
    assert _sha(report["ssid"]) == _H["ssid"], "SSID does not match expected value"


def test_bssid(report):
    bssid = _norm_mac(report["bssid"])
    assert _sha(bssid) == _H["bssid"], "BSSID does not match expected value"


# ---------- key recovery (hashed) ----------

def test_wep_key(report):
    key = _norm_key(report["wep_key"])
    assert _sha(key) == _H["wep_key"], "WEP key does not match expected value"


# ---------- attacker identification (hashed) ----------

def test_attacker_mac(report):
    mac = _norm_mac(report["attacker_mac"])
    assert _sha(mac) == _H["attacker_mac"], "Attacker MAC does not match expected value"


# ---------- attack technique evaluation (hashed) ----------

def test_attack_technique(report):
    technique = report["attack_technique"].strip().lower()
    assert _sha(technique) == _H["attack_technique"], \
        "Attack technique classification incorrect"


def test_technique_evidence_nonempty(report):
    evidence = report["technique_evidence"]
    assert isinstance(evidence, str) and len(evidence) > 20, \
        "technique_evidence must be a substantive explanation (>20 chars)"
    # Must reference at least one number (concrete observation)
    assert any(c.isdigit() for c in evidence), \
        "technique_evidence must reference a concrete numeric observation"


# ---------- capture statistics (hashed with tolerance) ----------

def test_capture_duration(report):
    dur = str(int(report["capture_duration_seconds"]))
    assert _sha(dur) == _H["capture_duration"], \
        "Capture duration does not match expected value"


def test_total_wep_data_frames(report):
    frames = str(int(report["total_wep_data_frames"]))
    assert _sha(frames) == _H["total_wep_data_frames"], \
        "Total WEP data frame count does not match expected value"


def test_total_unique_ivs(report):
    ivs = str(int(report["total_unique_ivs"]))
    assert _sha(ivs) == _H["total_unique_ivs"], \
        "Total unique IV count does not match expected value"


def test_attacker_unique_ivs(report):
    """Attacker unique IVs — validated by independent PCAP computation."""
    submitted_ivs = int(report["attacker_unique_ivs"])
    attacker_mac = _norm_mac(report["attacker_mac"])
    bssid = _norm_mac(report["bssid"])
    out = _tshark([
        "-r", PCAP, "-Y",
        f"(wlan.bssid == {bssid}) && wlan.wep.iv && (wlan.sa == {attacker_mac})",
        "-T", "fields", "-e", "wlan.wep.iv"
    ])
    ivs_from_pcap = set(l.strip() for l in out.strip().split('\n') if l.strip())
    expected = len(ivs_from_pcap)
    assert abs(submitted_ivs - expected) <= 1, \
        f"Attacker unique IV count mismatch: submitted {submitted_ivs}, independently computed {expected}"


def test_attacker_iv_share(report):
    """attacker_iv_share must be consistent with attacker_unique_ivs / total_unique_ivs."""
    share = float(report["attacker_iv_share"])
    attacker_ivs = int(report["attacker_unique_ivs"])
    total_ivs = int(report["total_unique_ivs"])
    expected_share = round((attacker_ivs / total_ivs) * 100, 1) if total_ivs > 0 else 0.0
    assert abs(share - expected_share) <= 0.2, \
        f"attacker_iv_share ({share}) inconsistent with attacker_unique_ivs/total_unique_ivs ({expected_share})"


# ---------- deauth analysis (PCAP-derived validation) ----------

def test_deauth_frame_count(report):
    """Validate deauth count by independently computing from PCAP."""
    submitted_count = int(report["deauth_frame_count"])
    bssid = _norm_mac(report["bssid"])
    out = _tshark([
        "-r", PCAP, "-Y",
        f"(wlan.fc.type_subtype == 0x000c) && (wlan.bssid == {bssid})",
        "-T", "fields", "-e", "frame.number"
    ])
    expected_lines = [l for l in out.strip().split('\n') if l.strip()]
    expected_count = len(expected_lines)
    assert submitted_count == expected_count, \
        f"Deauth frame count mismatch: submitted {submitted_count}, independently computed {expected_count}"


# ---------- post-compromise (hashed) ----------

def test_admin_username(report):
    assert _sha(report["admin_username"]) == _H["admin_username"], \
        "Admin username does not match expected value"


def test_admin_password(report):
    assert _sha(report["admin_password"]) == _H["admin_password"], \
        "Admin password does not match expected value"


def test_new_admin_passphrase(report):
    assert _sha(report["new_admin_passphrase"]) == _H["new_admin_passphrase"], \
        "New admin passphrase does not match expected value"


# ---------- detection engineering (execution validation) ----------

def test_deauth_detection_filter(report):
    """Validate the deauth detection filter by running it against the PCAP.
    All matched frames must be deauth type (0x000c = 12). Count must be substantial."""
    filter_str = report["deauth_detection_filter"]
    assert isinstance(filter_str, str) and len(filter_str) > 5, \
        "deauth_detection_filter must be a non-trivial filter string"

    # Run filter and extract type_subtype for validation
    out = _tshark([
        "-r", PCAP, "-Y", filter_str,
        "-T", "fields", "-e", "wlan.fc.type_subtype"
    ])

    lines = [l.strip() for l in out.strip().split('\n') if l.strip()]
    assert len(lines) > 0, "Deauth detection filter matched no frames"

    # Sanity: deauth filter should find a substantial number of frames
    assert len(lines) >= 100, \
        f"Deauth filter matched too few frames ({len(lines)}), expected hundreds"

    # Verify ALL unique type_subtype values are deauth (12)
    # Using set-based check is faster and more robust than per-line iteration
    unique_types = set()
    for line in lines:
        parsed = _parse_int_field(line)
        if parsed is not None:
            unique_types.add(parsed)

    assert len(unique_types) > 0, "Could not parse any type_subtype values from tshark output"
    assert unique_types == {12}, \
        f"Deauth filter matched non-deauth frame types: {unique_types} (expected only 12)"


def test_replay_detection_filter(report):
    """Validate the replay detection filter by running it against the PCAP.
    Matched frames must be WEP data frames from the reported attacker MAC."""
    filter_str = report["replay_detection_filter"]
    assert isinstance(filter_str, str) and len(filter_str) > 5, \
        "replay_detection_filter must be a non-trivial filter string"

    # Run filter and extract type_subtype + source MAC for validation
    out = _tshark([
        "-r", PCAP, "-Y", filter_str,
        "-T", "fields", "-e", "wlan.fc.type_subtype", "-e", "wlan.sa"
    ])

    lines = [l.strip() for l in out.strip().split('\n') if l.strip()]
    assert len(lines) > 1000, \
        f"Replay filter should match thousands of frames, got {len(lines)}"

    # Collect unique type_subtype values and source MACs across all output
    attacker_mac_reported = _norm_mac(report["attacker_mac"])
    unique_types = set()
    unique_macs = set()

    for line in lines:
        parts = line.split('\t')
        if len(parts) >= 1:
            parsed = _parse_int_field(parts[0])
            if parsed is not None:
                unique_types.add(parsed)
        if len(parts) >= 2:
            mac_val = parts[1].strip().split(",")[0].strip()
            if mac_val:
                unique_macs.add(_norm_mac(mac_val))

    # All type values should be data (32 = 0x0020)
    assert len(unique_types) > 0, "Could not parse type_subtype values"
    assert unique_types == {32}, \
        f"Replay filter matched non-data frame types: {unique_types} (expected only 32)"

    # All source MACs should be the reported attacker
    assert len(unique_macs) > 0, "Could not parse source MAC values"
    assert unique_macs == {attacker_mac_reported}, \
        f"Replay filter matched frames from unexpected stations: {unique_macs} (expected only {attacker_mac_reported})"
