
import hashlib
import json
import os
import re
import subprocess
import pytest


def test_recovered_data_file_exists():
    """Verify the recovered data file was created."""
    assert os.path.exists('/app/recovered_data.txt'), \
        "Recovered data file not found at /app/recovered_data.txt"


def test_recovered_data_matches_hash():
    """Verify the recovered data matches the expected SHA-256 hash."""
    with open('/app/.verification', 'r') as f:
        expected_hash = f.read().strip()
    with open('/app/recovered_data.txt', 'r') as f:
        data = f.read().strip()
    actual_hash = hashlib.sha256(data.encode('utf-8')).hexdigest()
    assert actual_hash == expected_hash, \
        "Recovered data does not match expected content"


def test_recovered_data_is_valid_json():
    """Verify the recovered data is well-formed JSON with expected fields."""
    with open('/app/recovered_data.txt', 'r') as f:
        data = json.load(f)
    assert 'host' in data, "Missing 'host' field in recovered data"
    assert 'user' in data, "Missing 'user' field in recovered data"
    assert 'token' in data, "Missing 'token' field in recovered data"
    assert isinstance(data['token'], str), "Token should be a string"
    assert len(data['token']) > 32, "Token appears too short"


def test_recovered_data_nonempty():
    """Verify the recovered data has substantial content."""
    with open('/app/recovered_data.txt', 'r') as f:
        data = f.read().strip()
    assert len(data) > 50, "Recovered data appears too short"
    assert data.startswith('{'), "Data should be JSON (starts with {)"
    assert data.endswith('}'), "Data should be JSON (ends with })"


def test_analysis_report_exists():
    """Verify the analysis report was created."""
    assert os.path.exists('/app/analysis_report.json'), \
        "Analysis report not found at /app/analysis_report.json"


def test_analysis_report_correct_exfil_channel():
    """Verify the analyst correctly identified the exfiltration channel."""
    with open('/app/analysis_report.json', 'r') as f:
        report = json.load(f)
    exfil = report.get('exfil_domain', '').lower()
    assert 'cdn-telemetry.example.com' in exfil, \
        "Incorrect exfiltration domain identification"


def test_analysis_report_correct_other_channel():
    """Verify the analyst correctly identified the other channel."""
    with open('/app/analysis_report.json', 'r') as f:
        report = json.load(f)
    other = report.get('other_domain', '').lower()
    assert 'api-metrics.example.com' in other, \
        "Incorrect other/secondary domain identification"


def test_analysis_report_correct_ciphers():
    """Verify the analyst correctly identified the ciphers used."""
    with open('/app/analysis_report.json', 'r') as f:
        report = json.load(f)
    exfil_cipher = report.get('exfil_cipher', '').lower()
    other_cipher = report.get('other_cipher', '').lower()
    assert 'tea' in exfil_cipher or 'xtea' in exfil_cipher, \
        "Exfiltration cipher should be identified as XTEA variant"
    assert 'feistel' in other_cipher, \
        "Other channel cipher should be identified as Feistel"


def test_analysis_report_cipher_param():
    """Verify the analyst identified the non-standard cipher parameter."""
    with open('/app/analysis_report.json', 'r') as f:
        report = json.load(f)
    param_hex = report.get('exfil_cipher_param_hex', '').lower().strip()
    assert param_hex.startswith('0x'), \
        "Cipher parameter should be in hex format (0x...)"
    assert param_hex != '0x9e3779b9', \
        "Parameter should be the modified value, not the standard constant"
    val = int(param_hex, 16)
    assert val & 0x80000001 == 0x80000001, \
        "Cipher parameter must have bits 31 and 0 set (OR'd with 0x80000001)"


def test_detection_assessment_exists():
    """Verify the detection assessment was created."""
    assert os.path.exists('/app/detection_assessment.json'), \
        "Detection assessment not found at /app/detection_assessment.json"


def test_detection_assessment_structure():
    """Verify the detection assessment has correct structure and substance."""
    with open('/app/detection_assessment.json', 'r') as f:
        data = json.load(f)
    assert 'resilient_indicators' in data, "Missing resilient_indicators"
    assert 'brittle_indicators' in data, "Missing brittle_indicators"
    assert isinstance(data['resilient_indicators'], list)
    assert isinstance(data['brittle_indicators'], list)
    assert len(data['resilient_indicators']) >= 3, \
        f"Need >= 3 resilient indicators, found {len(data['resilient_indicators'])}"
    assert len(data['brittle_indicators']) >= 2, \
        f"Need >= 2 brittle indicators, found {len(data['brittle_indicators'])}"
    for item in data['resilient_indicators']:
        assert 'feature' in item and isinstance(item['feature'], str), \
            "Each resilient indicator must have a 'feature' string"
        assert 'reason' in item and isinstance(item['reason'], str), \
            "Each resilient indicator must have a 'reason' string"
        assert len(item['reason']) >= 10, \
            "Reasons should be substantive explanations"
    for item in data['brittle_indicators']:
        assert 'feature' in item and isinstance(item['feature'], str), \
            "Each brittle indicator must have a 'feature' string"
        assert 'reason' in item and isinstance(item['reason'], str), \
            "Each brittle indicator must have a 'reason' string"
        assert len(item['reason']) >= 10, \
            "Reasons should be substantive explanations"


def test_detection_assessment_resilient_quality():
    """Resilient indicators should NOT include domain names (which vary between samples)."""
    with open('/app/detection_assessment.json', 'r') as f:
        data = json.load(f)
    for item in data['resilient_indicators']:
        feat_lower = item['feature'].lower()
        assert 'domain' not in feat_lower, \
            f"C2 domain names are operationally variable (brittle), not resilient: '{item['feature']}'"


def test_detection_assessment_brittle_quality():
    """Brittle indicators should recognize that C2 infrastructure varies between samples."""
    with open('/app/detection_assessment.json', 'r') as f:
        data = json.load(f)
    brittle_text = ' '.join(
        item['feature'].lower() + ' ' + item['reason'].lower()
        for item in data['brittle_indicators']
    )
    keywords = ['domain', 'c2', 'infrastructure', 'url', 'server', 'host']
    assert any(kw in brittle_text for kw in keywords), \
        "Brittle indicators should recognize that C2 domains/infrastructure vary between samples"


def test_yara_rule_exists():
    """Verify the YARA detection rule was created."""
    assert os.path.exists('/app/implant.yar'), \
        "YARA rule not found at /app/implant.yar"


def test_yara_rule_has_indicators():
    """Verify the YARA rule defines sufficient indicator strings."""
    with open('/app/implant.yar', 'r') as f:
        content = f.read()
    string_defs = re.findall(r'\$\w+\s*=', content)
    assert len(string_defs) >= 3, \
        f"YARA rule must define at least 3 indicator strings, found {len(string_defs)}"


def test_yara_rule_matches_alpha():
    """Verify the YARA rule matches the first implant sample."""
    result = subprocess.run(
        ['yara', '/app/implant.yar', '/app/sample_alpha'],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        f"YARA rule failed to compile or run: {result.stderr}"
    assert result.stdout.strip(), \
        "YARA rule should match sample_alpha but produced no output"


def test_yara_rule_matches_beta():
    """Verify the YARA rule matches the variant sample (family-level detection)."""
    result = subprocess.run(
        ['yara', '/app/implant.yar', '/app/sample_beta'],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        f"YARA rule failed to compile or run: {result.stderr}"
    assert result.stdout.strip(), \
        "YARA rule should match sample_beta (family-level detection) but produced no output"


def test_yara_rule_no_false_positive():
    """Verify the YARA rule does not match clean system binaries."""
    clean_binary = '/usr/bin/ls'
    if not os.path.exists(clean_binary):
        pytest.skip("Clean binary /usr/bin/ls not available")
    result = subprocess.run(
        ['yara', '/app/implant.yar', clean_binary],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        f"YARA rule failed to compile: {result.stderr}"
    assert not result.stdout.strip(), \
        "YARA rule should NOT match clean system binaries (false positive on /usr/bin/ls)"
