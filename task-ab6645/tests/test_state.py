
import json
import os
import subprocess
import pytest


def load_report():
    with open("/app/analysis_report.json") as f:
        return json.load(f)


def normalize_hex(s):
    """Normalize hex string: strip 0x prefix, lowercase, remove separators."""
    s = str(s).lower().strip()
    s = s.replace("0x", "").replace(" ", "").replace(":", "").replace("-", "")
    return s


# --- Report structure tests ---

def test_report_exists():
    assert os.path.exists("/app/analysis_report.json"), \
        "analysis_report.json not found at /app/"


def test_report_valid_json():
    data = load_report()
    assert isinstance(data, dict), "Report must be a JSON object"


# --- IOC value tests (must match real config A) ---

def test_c2_primary():
    data = load_report()
    assert data.get("c2_primary") == "update-service.darkcloud.network", \
        f"Wrong c2_primary: {data.get('c2_primary')}"


def test_c2_secondary():
    data = load_report()
    assert data.get("c2_secondary") == "cdn-static.shadownet.io", \
        f"Wrong c2_secondary: {data.get('c2_secondary')}"


def test_campaign_id():
    data = load_report()
    assert data.get("campaign_id") == "ECHO-7391-KAPPA", \
        f"Wrong campaign_id: {data.get('campaign_id')}"


def test_rc4_key_hex():
    data = load_report()
    expected = "4f70657261746f72"
    actual = normalize_hex(data.get("rc4_key_hex", ""))
    assert actual == expected, \
        f"Wrong rc4_key_hex: expected {expected}, got {actual}"


def test_xor_key_hex():
    data = load_report()
    expected = "a7b3c1d9"
    actual = normalize_hex(data.get("xor_key_hex", ""))
    assert actual == expected, \
        f"Wrong xor_key_hex: expected {expected}, got {actual}"


def test_mutex():
    data = load_report()
    actual = data.get("mutex", "")
    expected = "Global\\{8F14E45F-CEEA-4E3F-A3B0-4BE6B2626E33}"
    assert actual == expected, \
        f"Wrong mutex: expected {expected!r}, got {actual!r}"


def test_exfil_port():
    data = load_report()
    port = data.get("exfil_port")
    assert int(port) == 8443, \
        f"Wrong exfil_port: expected 8443, got {port}"


def test_persistence_path():
    data = load_report()
    assert data.get("persistence_path") == "/etc/cron.d/system-update", \
        f"Wrong persistence_path: {data.get('persistence_path')}"


# --- Config evaluation tests ---

def test_real_config_id():
    """Verify the solver correctly identified config A as the real operational config."""
    data = load_report()
    assert data.get("real_config_id") == "A", \
        f"Wrong real_config_id: expected 'A', got {data.get('real_config_id')!r}"


def test_not_decoy_c2():
    """Verify the solver didn't report plaintext decoy C2 as primary."""
    data = load_report()
    assert data.get("c2_primary") != "telemetry.windowsupdate.com", \
        "Reported plaintext decoy C2 domain as primary"


def test_not_trap_config_c2():
    """Verify the solver didn't report trap config B's C2 as primary."""
    data = load_report()
    assert data.get("c2_primary") != "api-gateway.stormfront.xyz", \
        "Reported trap config C2 domain as primary - must evaluate which config is operational"


def test_not_trap_config_campaign():
    """Verify the solver didn't report trap config B's campaign ID."""
    data = load_report()
    assert data.get("campaign_id") != "PHANTOM-2048-SIGMA", \
        "Reported trap config campaign ID - must evaluate which config is operational"


# --- YARA rule tests ---

def test_yara_rule_exists():
    assert os.path.exists("/app/detection.yar"), \
        "YARA detection rule not found at /app/detection.yar"


def test_yara_valid_syntax():
    """Verify the YARA rule has valid syntax by scanning a dummy target."""
    result = subprocess.run(
        ["yara", "/app/detection.yar", "/dev/null"],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        f"YARA syntax error: {result.stderr}"


def test_yara_detects_malware():
    """Verify the YARA rule matches the malware sample."""
    result = subprocess.run(
        ["yara", "/app/detection.yar", "/app/malware_sample"],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        f"YARA execution error: {result.stderr}"
    assert result.stdout.strip() != "", \
        "YARA rule did not match the malware sample"


def test_yara_no_false_positive():
    """Verify the YARA rule does NOT match the benign sample."""
    result = subprocess.run(
        ["yara", "/app/detection.yar", "/app/benign_sample"],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        f"YARA execution error: {result.stderr}"
    assert result.stdout.strip() == "", \
        f"YARA rule falsely matched benign sample: {result.stdout.strip()}"
