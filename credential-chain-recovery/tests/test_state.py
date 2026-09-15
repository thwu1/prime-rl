
"""Verify adversarial incident forensics: flag recovery, artifact
classification, threat evaluation, and firewall countermeasure design."""

import hashlib
import json
import os
import re
import stat

import pytest

# SHA-256 hashes of expected values (prevents answer leakage in test code)
EXPECTED_FLAG_HASH = \
    "f5e341b4013f068d9696a16063642689441b9dd7402b1bbe686d5cb76a07383a"
EXPECTED_GENUINE_PCAP_HASH = \
    "b0c73a5b18a6a88e1d8df933de2bcff582028aff951764a82894bc044c2d2747"
EXPECTED_GENUINE_DB_HASH = \
    "889a28af5c3537e2c0ec4d540835355bc69a6c7614453802fbb66b0ae99f9c13"
EXPECTED_GENUINE_SHADOW_HASH = \
    "09a5e82a18c7119b687d0b78ac157bc2fa4a34e758cd218d5b80ed6d5d739d63"
EXPECTED_GENUINE_REPORT_HASH = \
    "75e20b7d50c8ade9c39cf22367144f247a48510cbe510e889244ec785efe97f9"
EXPECTED_HONEYPOT_PCAP_HASH = \
    "9cbf4259498c7db0b6693795b97dbf7c711a7fe64c147b17294f8e8c9ed9cc78"
EXPECTED_HONEYPOT_DB_HASH = \
    "7dfb4cf67742cb0660305e56ef816c53fcec892cae7f6ee39b75f34e659d672c"
EXPECTED_HONEYPOT_SHADOW_HASH = \
    "934bb5585c504adcbd8a5abc60d52a3f0fb738df44e783cd98575c03e6318b6f"
EXPECTED_HONEYPOT_REPORT_HASH = \
    "042dfc72b39b49b894ed0ca51bf7e4f363ea4b84fe38dc34a67d645be5c59343"
EXPECTED_CRITICAL_CRED_HASH = \
    "06e55b633481f7bb072957eabcf110c972e86691c3cfedabe088024bffe42f23"
EXPECTED_INDICATOR_HASH = \
    "2a1073a6e67f0e5f09a5957c659503c690efe7272be8313df872556a9a684d8c"

ANSWER_PATH = "/app/answer.txt"
CLASSIFICATION_PATH = "/app/classification.json"
THREAT_ASSESSMENT_PATH = "/app/threat_assessment.json"
FIREWALL_PATH = "/app/firewall_rules.sh"


# ── Flag verification ──────────────────────────────────────────────────────

class TestFlag:
    """Verify the recovered proof flag is from the genuine report."""

    def test_answer_file_exists(self):
        assert os.path.isfile(ANSWER_PATH), \
            f"{ANSWER_PATH} does not exist."

    def test_answer_format(self):
        with open(ANSWER_PATH) as f:
            content = f.read().strip()
        assert len(content) > 0, f"{ANSWER_PATH} is empty."
        assert content.startswith("ACME-REDTEAM-FLAG{"), \
            "Flag does not start with expected prefix."
        assert content.endswith("}"), \
            "Flag does not end with expected suffix."

    def test_answer_correct(self):
        """Flag must match expected hash — honeypot decoy flag will fail."""
        with open(ANSWER_PATH) as f:
            content = f.read().strip()
        actual_hash = hashlib.sha256(content.encode()).hexdigest()
        assert actual_hash == EXPECTED_FLAG_HASH, (
            "Proof flag is incorrect. If you recovered a flag but it "
            "does not match, you may have decrypted the honeypot decoy "
            "report instead of the genuine one."
        )


# ── Artifact classification verification ───────────────────────────────────

class TestClassification:
    """Verify correct discrimination of genuine vs. honeypot artifacts."""

    def test_classification_exists(self):
        assert os.path.isfile(CLASSIFICATION_PATH), \
            f"{CLASSIFICATION_PATH} does not exist."

    def test_classification_structure(self):
        with open(CLASSIFICATION_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)
        for category in ["genuine", "honeypot"]:
            assert category in data, f"Missing '{category}' key."
            for field in ["pcap_session", "database_table",
                          "shadow_host", "encrypted_report"]:
                assert field in data[category], \
                    f"Missing '{field}' in '{category}'."

    def test_genuine_pcap_session(self):
        with open(CLASSIFICATION_PATH) as f:
            data = json.load(f)
        actual = hashlib.sha256(
            data["genuine"]["pcap_session"].encode()).hexdigest()
        assert actual == EXPECTED_GENUINE_PCAP_HASH, \
            "Incorrect genuine PCAP session source IP."

    def test_genuine_database_table(self):
        with open(CLASSIFICATION_PATH) as f:
            data = json.load(f)
        actual = hashlib.sha256(
            data["genuine"]["database_table"].encode()).hexdigest()
        assert actual == EXPECTED_GENUINE_DB_HASH, \
            "Incorrect genuine database table."

    def test_genuine_shadow_host(self):
        with open(CLASSIFICATION_PATH) as f:
            data = json.load(f)
        actual = hashlib.sha256(
            data["genuine"]["shadow_host"].encode()).hexdigest()
        assert actual == EXPECTED_GENUINE_SHADOW_HASH, \
            "Incorrect genuine shadow host."

    def test_genuine_report(self):
        with open(CLASSIFICATION_PATH) as f:
            data = json.load(f)
        actual = hashlib.sha256(
            data["genuine"]["encrypted_report"].encode()).hexdigest()
        assert actual == EXPECTED_GENUINE_REPORT_HASH, \
            "Incorrect genuine report file."

    def test_honeypot_pcap_session(self):
        with open(CLASSIFICATION_PATH) as f:
            data = json.load(f)
        actual = hashlib.sha256(
            data["honeypot"]["pcap_session"].encode()).hexdigest()
        assert actual == EXPECTED_HONEYPOT_PCAP_HASH, \
            "Incorrect honeypot PCAP session source IP."

    def test_honeypot_database_table(self):
        with open(CLASSIFICATION_PATH) as f:
            data = json.load(f)
        actual = hashlib.sha256(
            data["honeypot"]["database_table"].encode()).hexdigest()
        assert actual == EXPECTED_HONEYPOT_DB_HASH, \
            "Incorrect honeypot database table."

    def test_honeypot_shadow_host(self):
        with open(CLASSIFICATION_PATH) as f:
            data = json.load(f)
        actual = hashlib.sha256(
            data["honeypot"]["shadow_host"].encode()).hexdigest()
        assert actual == EXPECTED_HONEYPOT_SHADOW_HASH, \
            "Incorrect honeypot shadow host."

    def test_honeypot_report(self):
        with open(CLASSIFICATION_PATH) as f:
            data = json.load(f)
        actual = hashlib.sha256(
            data["honeypot"]["encrypted_report"].encode()).hexdigest()
        assert actual == EXPECTED_HONEYPOT_REPORT_HASH, \
            "Incorrect honeypot report file."


# ── Threat assessment verification ───────────────────────────────────────

class TestThreatAssessment:
    """Verify evaluative judgments about the attack chain and deception."""

    def test_threat_assessment_exists(self):
        assert os.path.isfile(THREAT_ASSESSMENT_PATH), \
            f"{THREAT_ASSESSMENT_PATH} does not exist."

    def test_threat_assessment_structure(self):
        with open(THREAT_ASSESSMENT_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)
        for field in ["critical_entry_credential",
                      "honeypot_primary_indicator",
                      "deception_rating",
                      "recommended_priority_fix"]:
            assert field in data, f"Missing '{field}' in threat assessment."

    def test_critical_entry_credential(self):
        """The 'operator' credential is reused in two downstream steps
        (XOR key derivation AND GPG passphrase construction), making it
        the single most critical link. All other credentials affect only
        one step."""
        with open(THREAT_ASSESSMENT_PATH) as f:
            data = json.load(f)
        actual = hashlib.sha256(
            data["critical_entry_credential"].encode()).hexdigest()
        assert actual == EXPECTED_CRITICAL_CRED_HASH, \
            "Incorrect critical entry credential evaluation."

    def test_honeypot_primary_indicator(self):
        """The 'tag' field in server_access.log directly labels sessions
        as THPot (honeypot) vs prod-api (genuine)."""
        with open(THREAT_ASSESSMENT_PATH) as f:
            data = json.load(f)
        actual = hashlib.sha256(
            data["honeypot_primary_indicator"].encode()).hexdigest()
        assert actual == EXPECTED_INDICATOR_HASH, \
            "Incorrect honeypot primary indicator field."

    def test_deception_rating_valid(self):
        """Rating must be an integer between 1 and 10."""
        with open(THREAT_ASSESSMENT_PATH) as f:
            data = json.load(f)
        rating = data["deception_rating"]
        assert isinstance(rating, int), \
            "deception_rating must be an integer."
        assert 1 <= rating <= 10, \
            "deception_rating must be between 1 and 10."

    def test_recommended_priority_fix(self):
        """Must provide a substantive remediation recommendation."""
        with open(THREAT_ASSESSMENT_PATH) as f:
            data = json.load(f)
        fix = data["recommended_priority_fix"]
        assert isinstance(fix, str), \
            "recommended_priority_fix must be a string."
        assert len(fix.strip()) >= 15, \
            "recommended_priority_fix must be substantive (>=15 chars)."


# ── Firewall countermeasure verification ───────────────────────────────────

class TestFirewall:
    """Verify designed firewall rules block attacks, allow legit services."""

    def test_firewall_exists_and_executable(self):
        assert os.path.isfile(FIREWALL_PATH), \
            f"{FIREWALL_PATH} does not exist."
        st = os.stat(FIREWALL_PATH)
        assert st.st_mode & stat.S_IXUSR, \
            f"{FIREWALL_PATH} is not executable."

    def test_firewall_contains_iptables(self):
        with open(FIREWALL_PATH) as f:
            content = f.read()
        assert "iptables" in content, \
            "Firewall script does not contain iptables commands."

    def test_firewall_blocks_attacker(self):
        """Script must DROP/REJECT the identified attacker source IP."""
        with open(FIREWALL_PATH) as f:
            content = f.read()
        drop_lines = [
            line for line in content.split('\n')
            if 'DROP' in line or 'REJECT' in line
        ]
        found_ips = set()
        for line in drop_lines:
            for ip_match in re.finditer(r'\d+\.\d+\.\d+\.\d+', line):
                found_ips.add(ip_match.group())
        attacker_blocked = any(
            hashlib.sha256(ip.encode()).hexdigest()
            == EXPECTED_GENUINE_PCAP_HASH
            for ip in found_ips
        )
        assert attacker_blocked, \
            "Firewall does not block the identified attacker IP."

    def test_firewall_allows_legitimate_services(self):
        """Rules must ACCEPT traffic on ports 22, 80, 443."""
        with open(FIREWALL_PATH) as f:
            content = f.read()
        accept_lines = [
            line for line in content.split('\n')
            if 'ACCEPT' in line
        ]
        accept_text = '\n'.join(accept_lines)
        for port in [22, 80, 443]:
            assert str(port) in accept_text, \
                f"Firewall does not allow port {port}."

    def test_firewall_has_rate_limiting(self):
        """Rules must include rate limiting for service protection."""
        with open(FIREWALL_PATH) as f:
            content = f.read().lower()
        has_limiting = (
            "limit" in content
            or "connlimit" in content
            or "hashlimit" in content
        )
        assert has_limiting, \
            "Firewall does not include rate limiting."
