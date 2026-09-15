"""
Tests for malware PCAP forensic analysis, YARA detection engineering, and threat assessment.
Verifies evidence integrity, artifact extraction, forensic report accuracy,
YARA rule quality and match results, and threat assessment completeness.
"""

import pytest
import json
import hashlib
import os
import re
import subprocess


PCAP_PATH = "/app/evidence/infected.pcap"
PACKED_PATH = "/app/artifacts/malware_packed.exe"
UNPACKED_PATH = "/app/artifacts/malware_unpacked.exe"
REPORT_PATH = "/app/report.json"
YARA_RULES_PATH = "/app/detection/malware.yar"
VALIDATION_PATH = "/app/detection/validation.json"
ASSESSMENT_PATH = "/app/assessment.json"

EXPECTED_PCAP_MD5 = "c09a3019ada7ab17a44537b069480312"
EXPECTED_PACKED_MD5 = "5942ba36cf732097479c51986eee91ed"
EXPECTED_UNPACKED_MD5 = "ca21cefdd297152f6226e1c2d767cb96"


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# --- Evidence integrity ---

class TestEvidenceIntegrity:
    def test_pcap_exists(self):
        assert os.path.isfile(PCAP_PATH), f"PCAP not found at {PCAP_PATH}"

    def test_pcap_md5(self):
        actual = md5_file(PCAP_PATH)
        assert actual == EXPECTED_PCAP_MD5, (
            f"PCAP MD5 mismatch: got {actual}, expected {EXPECTED_PCAP_MD5}"
        )


# --- Artifact extraction ---

class TestArtifactExtraction:
    def test_packed_malware_exists(self):
        assert os.path.isfile(PACKED_PATH), (
            f"Packed malware not found at {PACKED_PATH}"
        )

    def test_packed_malware_md5(self):
        actual = md5_file(PACKED_PATH)
        assert actual == EXPECTED_PACKED_MD5, (
            f"Packed malware MD5 mismatch: got {actual}, expected {EXPECTED_PACKED_MD5}"
        )

    def test_unpacked_malware_exists(self):
        assert os.path.isfile(UNPACKED_PATH), (
            f"Unpacked malware not found at {UNPACKED_PATH}"
        )

    def test_unpacked_malware_md5(self):
        actual = md5_file(UNPACKED_PATH)
        assert actual == EXPECTED_UNPACKED_MD5, (
            f"Unpacked malware MD5 mismatch: got {actual}, expected {EXPECTED_UNPACKED_MD5}"
        )


# --- Forensic report ---

@pytest.fixture
def report():
    assert os.path.isfile(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        return json.load(f)


class TestForensicReport:
    def test_victim_username(self, report):
        val = report.get("victim_username", "").strip()
        assert val.upper() == "ADMINISTRATOR", (
            f"victim_username mismatch: got '{val}'"
        )

    def test_initial_url(self, report):
        val = report.get("initial_url", "").strip().rstrip("/")
        assert val == "http://nrtjo.eu/true.php", (
            f"initial_url mismatch: got '{val}'"
        )

    def test_java_applets(self, report):
        raw = report.get("java_applets", [])
        applets = sorted([a.strip() for a in raw])
        assert applets == ["q.jar", "sdfg.jar"], (
            f"java_applets mismatch: got {applets}"
        )

    def test_packed_malware_md5_in_report(self, report):
        val = report.get("packed_malware_md5", "").strip().lower()
        assert val == EXPECTED_PACKED_MD5, (
            f"packed_malware_md5 in report mismatch: got '{val}'"
        )

    def test_packer_name(self, report):
        val = report.get("packer_name", "").strip()
        assert val.upper() == "UPX", f"packer_name mismatch: got '{val}'"

    def test_unpacked_malware_md5_in_report(self, report):
        val = report.get("unpacked_malware_md5", "").strip().lower()
        assert val == EXPECTED_UNPACKED_MD5, (
            f"unpacked_malware_md5 in report mismatch: got '{val}'"
        )

    def test_c2_ip(self, report):
        val = report.get("c2_ip", "").strip()
        assert val == "213.155.29.144", f"c2_ip mismatch: got '{val}'"


# --- YARA detection rules ---

class TestYaraRules:
    def test_rules_file_exists(self):
        assert os.path.isfile(YARA_RULES_PATH), (
            f"YARA rules not found at {YARA_RULES_PATH}"
        )

    def test_rules_syntax_valid(self):
        """YARA rules must compile without errors."""
        result = subprocess.run(
            ["yara", YARA_RULES_PATH, "/dev/null"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"YARA compilation failed: {result.stderr}"
        )

    def test_at_least_two_rules(self):
        """Must contain at least 2 distinct YARA rules."""
        with open(YARA_RULES_PATH) as f:
            content = f.read()
        rule_count = len(re.findall(r'^\s*rule\s+\w+', content, re.MULTILINE))
        assert rule_count >= 2, (
            f"Expected at least 2 YARA rules, found {rule_count}"
        )

    def test_rules_have_metadata(self):
        """Rules must include meta sections with required fields."""
        with open(YARA_RULES_PATH) as f:
            content = f.read()
        assert "meta:" in content, "YARA rules must contain meta: sections"
        assert re.search(r'description\s*=', content), (
            "YARA rules must have description metadata"
        )
        assert re.search(r'author\s*=', content), (
            "YARA rules must have author metadata"
        )
        assert re.search(r'date\s*=', content), (
            "YARA rules must have date metadata"
        )

    def test_rules_use_meaningful_patterns(self):
        """Rules must use hex patterns or string definitions, not just hashes."""
        with open(YARA_RULES_PATH) as f:
            content = f.read()
        assert "strings:" in content, (
            "YARA rules must contain strings: sections"
        )
        has_hex = bool(re.search(r'\$\w+\s*=\s*\{[^}]+\}', content))
        has_string = bool(re.search(r'\$\w+\s*=\s*"[^"]+"', content))
        assert has_hex or has_string, (
            "Rules must contain hex byte patterns ({ ... }) or "
            "string definitions (\"...\") — not just file hashes"
        )

    def test_rules_match_packed_malware(self):
        """At least one YARA rule must match the packed malware artifact."""
        result = subprocess.run(
            ["yara", YARA_RULES_PATH, PACKED_PATH],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"YARA error scanning packed malware: {result.stderr}"
        )
        assert result.stdout.strip(), (
            "No YARA rules matched the packed malware — "
            "rules must detect the packed variant"
        )

    def test_rules_match_unpacked_malware(self):
        """At least one YARA rule must match the unpacked malware artifact."""
        result = subprocess.run(
            ["yara", YARA_RULES_PATH, UNPACKED_PATH],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"YARA error scanning unpacked malware: {result.stderr}"
        )
        assert result.stdout.strip(), (
            "No YARA rules matched the unpacked malware — "
            "rules must detect the unpacked variant"
        )


# --- YARA validation results ---

class TestValidation:
    def test_validation_exists(self):
        assert os.path.isfile(VALIDATION_PATH), (
            f"Validation report not found at {VALIDATION_PATH}"
        )

    def test_validation_documents_matches(self):
        """Validation must document rule scanning results."""
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        content_str = json.dumps(data).lower()
        assert "match" in content_str or "rule" in content_str or "hit" in content_str, (
            "Validation report must document match/rule/hit results"
        )


# --- Threat assessment ---

@pytest.fixture
def assessment():
    assert os.path.isfile(ASSESSMENT_PATH), (
        f"Assessment not found at {ASSESSMENT_PATH}"
    )
    with open(ASSESSMENT_PATH) as f:
        return json.load(f)


class TestThreatAssessment:
    def test_attack_stages_present(self, assessment):
        stages = assessment.get("attack_stages", [])
        assert len(stages) >= 3, (
            f"Expected at least 3 attack stages, found {len(stages)}"
        )

    def test_attack_stages_structure(self, assessment):
        """Each attack stage must have all required fields."""
        required = {
            "stage_name", "protocol", "src_ip", "dst_ip",
            "description", "attck_technique_id"
        }
        for stage in assessment.get("attack_stages", []):
            missing = required - set(stage.keys())
            assert not missing, (
                f"Stage '{stage.get('stage_name', '?')}' missing fields: {missing}"
            )

    def test_attck_technique_id_format(self, assessment):
        """ATT&CK technique IDs must follow TXXXx format."""
        for stage in assessment.get("attack_stages", []):
            tid = stage.get("attck_technique_id", "")
            assert re.match(r'^T\d{4}', tid), (
                f"Invalid ATT&CK technique ID format '{tid}' in stage "
                f"'{stage.get('stage_name', '?')}'"
            )

    def test_attck_techniques_list(self, assessment):
        techniques = set(assessment.get("attck_techniques", []))
        assert len(techniques) >= 3, (
            f"Expected at least 3 distinct ATT&CK techniques, found {len(techniques)}"
        )

    def test_attck_core_techniques(self, assessment):
        """Must include techniques for drive-by compromise, tool transfer, and obfuscation."""
        techniques = set(assessment.get("attck_techniques", []))
        required = {"T1189", "T1105", "T1027"}
        missing = required - techniques
        assert not missing, (
            f"Missing required ATT&CK technique IDs: {missing}. "
            f"T1189=Drive-by Compromise, T1105=Ingress Tool Transfer, "
            f"T1027=Obfuscated Files or Information"
        )

    def test_detection_gaps(self, assessment):
        gaps = assessment.get("detection_gaps", [])
        assert len(gaps) >= 2, (
            f"Expected at least 2 detection gap analyses, found {len(gaps)}"
        )
        for gap in gaps:
            assert "stage_name" in gap, (
                "Each detection gap must have 'stage_name'"
            )
            assert "gap_description" in gap, (
                "Each detection gap must have 'gap_description'"
            )
            assert len(gap.get("gap_description", "")) > 20, (
                f"Gap description for '{gap.get('stage_name', '?')}' "
                f"is too brief — provide substantive analysis"
            )

    def test_defense_recommendations(self, assessment):
        recs = assessment.get("defense_recommendations", [])
        assert len(recs) >= 3, (
            f"Expected at least 3 defense recommendations, found {len(recs)}"
        )
        for rec in recs:
            assert "recommendation" in rec, (
                "Each recommendation must have 'recommendation'"
            )
            assert "addresses_stage" in rec, (
                "Each recommendation must have 'addresses_stage'"
            )
            assert "effectiveness_rationale" in rec, (
                "Each recommendation must have 'effectiveness_rationale'"
            )
            assert len(rec.get("effectiveness_rationale", "")) > 20, (
                f"Rationale for '{rec.get('recommendation', '?')[:40]}...' "
                f"is too brief — justify the priority ranking"
            )
