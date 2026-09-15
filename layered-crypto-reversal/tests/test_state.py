import os
import json
import hashlib
import pytest

EXPECTED_FLAG = "TBENCH{xtea_pcbc_raw_rsa3_spec_mismatch}"
EXPECTED_FORGED_HASH = "854cdaba4060a88fe4886cb720ecfe239a69efa381a55be1e64beca6bfeda643"


# ============================================================
# Flag decryption tests
# ============================================================

def test_flag_file_exists():
    assert os.path.exists("/app/flag.txt"), "/app/flag.txt does not exist"


def test_flag_not_empty():
    with open("/app/flag.txt") as f:
        content = f.read().strip()
    assert len(content) > 0, "flag.txt is empty"


def test_flag_correct():
    with open("/app/flag.txt") as f:
        flag = f.read().strip()
    assert flag == EXPECTED_FLAG, f"Flag mismatch: got '{flag}'"


# ============================================================
# Vulnerability assessment tests
# ============================================================

def test_vuln_assessment_exists():
    assert os.path.exists("/app/vuln_assessment.json"), (
        "/app/vuln_assessment.json does not exist"
    )


def test_vuln_assessment_valid_json():
    with open("/app/vuln_assessment.json") as f:
        data = json.load(f)
    assert isinstance(data, dict), "Root must be a JSON object"
    assert "discrepancies" in data, "Missing 'discrepancies' key"
    assert isinstance(data["discrepancies"], list), "'discrepancies' must be an array"


def test_vuln_assessment_minimum_count():
    with open("/app/vuln_assessment.json") as f:
        data = json.load(f)
    assert len(data["discrepancies"]) >= 6, (
        f"Expected at least 6 discrepancies, got {len(data['discrepancies'])}"
    )


def test_vuln_assessment_entry_structure():
    with open("/app/vuln_assessment.json") as f:
        data = json.load(f)
    required_fields = {"id", "spec_claim", "actual_behavior",
                       "exploitable", "severity", "impact"}
    valid_severities = {"critical", "high", "medium", "low"}
    for i, d in enumerate(data["discrepancies"]):
        missing = required_fields - set(d.keys())
        assert not missing, f"Discrepancy {i} missing fields: {missing}"
        assert isinstance(d["exploitable"], bool), (
            f"Discrepancy {i} 'exploitable' must be boolean, got {type(d['exploitable'])}"
        )
        assert d["severity"] in valid_severities, (
            f"Discrepancy {i} severity '{d['severity']}' not in {valid_severities}"
        )


def test_vuln_assessment_cipher_discrepancy():
    """The cipher identity mismatch (AES vs XTEA) must be identified as critical/exploitable."""
    with open("/app/vuln_assessment.json") as f:
        data = json.load(f)
    cipher_matches = [
        d for d in data["discrepancies"]
        if ("xtea" in d["actual_behavior"].lower()
            or "tea" in d["actual_behavior"].lower())
        and ("aes" in d["spec_claim"].lower()
             or "cipher" in d["id"].lower()
             or "algorithm" in d["id"].lower())
    ]
    assert len(cipher_matches) >= 1, (
        "Must identify cipher algorithm discrepancy (AES-256 vs XTEA)"
    )
    cd = cipher_matches[0]
    assert cd["exploitable"] is True, (
        "Cipher algorithm discrepancy must be marked exploitable"
    )
    assert cd["severity"] == "critical", (
        f"Cipher algorithm discrepancy must be critical, got '{cd['severity']}'"
    )


def test_vuln_assessment_rsa_padding_discrepancy():
    """The RSA padding mismatch (OAEP vs textbook) must be identified as critical/exploitable."""
    with open("/app/vuln_assessment.json") as f:
        data = json.load(f)
    rsa_matches = [
        d for d in data["discrepancies"]
        if any(kw in d["actual_behavior"].lower()
               for kw in ["textbook", "raw", "no padding", "no oaep", "pow("])
        or any(kw in d["spec_claim"].lower()
               for kw in ["oaep", "pkcs"])
        or any(kw in d["id"].lower()
               for kw in ["rsa_padding", "padding", "oaep"])
    ]
    assert len(rsa_matches) >= 1, (
        "Must identify RSA padding discrepancy (OAEP vs textbook RSA)"
    )
    rd = rsa_matches[0]
    assert rd["exploitable"] is True, (
        "RSA padding discrepancy must be marked exploitable"
    )
    assert rd["severity"] == "critical", (
        f"RSA padding discrepancy must be critical, got '{rd['severity']}'"
    )


def test_vuln_assessment_has_non_exploitable():
    """At least 2 discrepancies must be evaluated as non-exploitable."""
    with open("/app/vuln_assessment.json") as f:
        data = json.load(f)
    non_exploitable = [d for d in data["discrepancies"] if d["exploitable"] is False]
    assert len(non_exploitable) >= 2, (
        f"Expected at least 2 non-exploitable discrepancies, got {len(non_exploitable)}. "
        "Not all discrepancies directly enabled this specific attack."
    )


def test_vuln_assessment_severity_coherence():
    """The highest-severity exploitable finding must be rated at least as high as
    the highest non-exploitable finding. Exploitable flaws that directly enabled
    the attack should not be rated below cosmetic differences."""
    with open("/app/vuln_assessment.json") as f:
        data = json.load(f)
    severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    exploitable = [d for d in data["discrepancies"] if d["exploitable"] is True]
    non_exploitable = [d for d in data["discrepancies"] if d["exploitable"] is False]
    if exploitable and non_exploitable:
        max_exploit = max(severity_rank[d["severity"]] for d in exploitable)
        max_non_exploit = max(severity_rank[d["severity"]] for d in non_exploitable)
        assert max_exploit >= max_non_exploit, (
            "Exploitable discrepancies should be rated at least as severely "
            "as non-exploitable ones"
        )


# ============================================================
# Forged payload tests
# ============================================================

def test_forged_payload_exists():
    assert os.path.exists("/app/forged_payload.bin"), (
        "/app/forged_payload.bin does not exist"
    )


def test_forged_payload_size():
    """'FORGED_BY_ANALYST' is 17 bytes, PKCS#7 padded to 24 bytes (3 XTEA blocks)."""
    with open("/app/forged_payload.bin", "rb") as f:
        data = f.read()
    assert len(data) == 24, (
        f"Forged payload must be 24 bytes (3 XTEA blocks), got {len(data)}"
    )


def test_forged_payload_correct():
    """Verify the forged ciphertext via SHA-256 hash. This confirms correct XTEA-PCBC
    encryption of 'FORGED_BY_ANALYST' with the recovered key and zero IV."""
    with open("/app/forged_payload.bin", "rb") as f:
        data = f.read()
    h = hashlib.sha256(data).hexdigest()
    assert h == EXPECTED_FORGED_HASH, (
        f"Forged payload SHA-256 mismatch.\n"
        f"  Expected: {EXPECTED_FORGED_HASH}\n"
        f"  Got:      {h}\n"
        "This means the XTEA-PCBC encryption of 'FORGED_BY_ANALYST' with "
        "the recovered key and 8 zero-byte IV is incorrect."
    )
