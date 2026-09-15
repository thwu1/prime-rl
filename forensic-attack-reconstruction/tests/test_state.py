"""
Verification tests for the forensic incident response and security assessment task.
Tests validate three deliverables:
  1. /app/incident_report.json — attack chain findings and false positive classification
  2. /app/detection.yar — YARA rules that detect threat actor artifacts
  3. /app/security_assessment.json — security posture evaluation with MITRE mapping,
     Sigma rules, architecture critique, and maturity rating
"""
import json
import os
import re
import hashlib
import struct
import subprocess
import tarfile
import io
import pytest
import yaml


REPORT_PATH = "/app/incident_report.json"
YARA_PATH = "/app/detection.yar"
ASSESSMENT_PATH = "/app/security_assessment.json"

# Ground-truth values (derived from evidence, not exposed in instruction)
ATTACKER_IP = "198.51.100.47"
SCANNER_IP = "203.0.113.50"
C2_SERVER = "203.0.113.89"
C2_PORT = 4444
ENCRYPTION_SEED = "pr0j3ct_m4yh3m_2024"
EXPECTED_EXFIL_FILES = {
    "customer_db.csv",
    "api_credentials.txt",
    "ssh_private_keys.txt",
    "internal_network_map.txt",
}


def report_str(report):
    """Serialize report to lowercase string for keyword search."""
    return json.dumps(report).lower()


def get_false_positives(report):
    """Extract false positives section from report, case-insensitive key search."""
    for key in report:
        if "false" in key.lower() and "positive" in key.lower():
            return report[key]
    return None


@pytest.fixture(scope="module")
def report():
    assert os.path.exists(REPORT_PATH), f"Incident report not found at {REPORT_PATH}"
    with open(REPORT_PATH, "r") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def assessment():
    assert os.path.exists(ASSESSMENT_PATH), (
        f"Security assessment not found at {ASSESSMENT_PATH}"
    )
    with open(ASSESSMENT_PATH, "r") as f:
        return json.load(f)


# ── Incident Report: Attack Identification ──────────────────────────────────


class TestAttackIdentification:
    def test_attacker_ip(self, report):
        """Verify the correct attacker IP was identified from web logs."""
        assert ATTACKER_IP in report_str(report), (
            f"Report must identify attacker IP {ATTACKER_IP}"
        )

    def test_vulnerability_type(self, report):
        """Verify the initial access vulnerability class was identified."""
        rstr = report_str(report)
        assert any(
            kw in rstr
            for kw in ["ssti", "template injection", "server-side template", "server side template"]
        ), "Report must identify the vulnerability as SSTI / template injection"

    def test_vulnerable_endpoint(self, report):
        """Verify the exploited endpoint was identified."""
        assert "/search" in report_str(report), (
            "Report must identify /search as the vulnerable endpoint"
        )

    def test_vulnerable_parameter(self, report):
        """Verify the exploited parameter was identified."""
        rstr = report_str(report)
        assert any(
            kw in rstr for kw in ['"q"', "'q'", "parameter q", "param q", "=q"]
        ) or re.search(r'\bq\b', rstr), (
            "Report must identify 'q' as the vulnerable parameter"
        )


# ── Incident Report: Privilege Escalation ────────────────────────────────────


class TestPrivilegeEscalation:
    def test_wwwdata_user(self, report):
        """Verify www-data is documented in the escalation chain."""
        assert "www-data" in report_str(report), (
            "Report must reference www-data in the escalation chain"
        )

    def test_devops_user(self, report):
        """Verify devops is documented in the escalation chain."""
        assert "devops" in report_str(report), (
            "Report must reference devops in the escalation chain"
        )

    def test_root_reached(self, report):
        """Verify escalation to root is documented."""
        assert "root" in report_str(report), (
            "Report must document escalation to root"
        )

    def test_password_reuse_method(self, report):
        """Verify the password reuse technique was identified."""
        rstr = report_str(report)
        assert any(
            kw in rstr
            for kw in ["password", "credential", "config.py", "service_password", "reuse"]
        ), "Report must describe the credential reuse from config.py"

    def test_sudo_script_method(self, report):
        """Verify the writable sudo script technique was identified."""
        rstr = report_str(report)
        assert any(
            kw in rstr
            for kw in ["sudo", "writable", "run-diagnostics", "diagnostics.sh"]
        ), "Report must describe the sudo script privilege escalation"


# ── Incident Report: Persistence / Backdoors ─────────────────────────────────


class TestPersistence:
    def test_crontab_backdoor(self, report):
        """Verify the base64-encoded crontab reverse shell was identified."""
        rstr = report_str(report)
        assert any(
            kw in rstr for kw in ["crontab", "cron"]
        ), "Report must identify the crontab backdoor"

    def test_systemd_backdoor(self, report):
        """Verify the disguised systemd service was identified."""
        rstr = report_str(report)
        assert any(
            kw in rstr for kw in ["systemd", "reverse-proxy-cache"]
        ), "Report must identify the systemd service backdoor"

    def test_ssh_key_backdoor(self, report):
        """Verify the planted SSH key was identified."""
        rstr = report_str(report)
        assert any(
            kw in rstr for kw in ["ssh", "authorized_key", "backup-automation"]
        ), "Report must identify the SSH key backdoor"


# ── Incident Report: C2 Infrastructure ───────────────────────────────────────


class TestC2Infrastructure:
    def test_c2_server(self, report):
        """Verify C2 server IP was identified."""
        assert C2_SERVER in report_str(report), (
            f"Report must identify C2 server {C2_SERVER}"
        )

    def test_c2_port(self, report):
        """Verify C2 port was identified."""
        assert str(C2_PORT) in report_str(report), (
            f"Report must identify C2 port {C2_PORT}"
        )


# ── Incident Report: Data Exfiltration ───────────────────────────────────────


class TestDataExfiltration:
    def test_encryption_seed(self, report):
        """Verify the encryption seed was recovered."""
        assert ENCRYPTION_SEED in report_str(report), (
            f"Report must contain the recovered encryption seed '{ENCRYPTION_SEED}'"
        )

    def test_exfiltrated_files(self, report):
        """Verify all exfiltrated files were identified (requires decryption)."""
        rstr = report_str(report)
        for fname in EXPECTED_EXFIL_FILES:
            assert fname.lower() in rstr, (
                f"Report must list exfiltrated file: {fname}"
            )


# ── Incident Report: False Positive Classification ──────────────────────────


class TestFalsePositives:
    def test_false_positives_section_exists(self, report):
        """Report must contain a false_positives section."""
        fp = get_false_positives(report)
        assert fp is not None, (
            "Report must have a 'false_positives' key documenting benign indicators"
        )

    def test_scanner_classified_as_false_positive(self, report):
        """The Nikto vulnerability scanner must be classified as a false positive."""
        fp = get_false_positives(report)
        assert fp is not None, "Report must have a false_positives section"
        fp_str = json.dumps(fp).lower()
        assert any(
            kw in fp_str
            for kw in [SCANNER_IP, "nikto", "vulnerability scan", "scanner"]
        ), (
            f"The vulnerability scanner ({SCANNER_IP} / Nikto) must appear "
            f"in the false_positives section"
        )

    def test_attacker_ip_not_confused_with_scanner(self, report):
        """The real attacker IP must be identified, not the scanner."""
        rstr = report_str(report)
        assert ATTACKER_IP in rstr, (
            f"Report must identify the real attacker IP {ATTACKER_IP}"
        )


# ── YARA Detection Rules ────────────────────────────────────────────────────


class TestYaraRules:
    def test_yara_file_exists(self):
        """YARA rules file must exist."""
        assert os.path.exists(YARA_PATH), f"YARA rules not found at {YARA_PATH}"

    def test_yara_has_multiple_rules(self):
        """YARA file must contain at least 2 detection rules."""
        with open(YARA_PATH) as f:
            content = f.read()
        rules = re.findall(r'rule\s+\w+', content)
        assert len(rules) >= 2, f"Expected at least 2 YARA rules, found {len(rules)}"

    def test_yara_rules_have_descriptions(self):
        """Every YARA rule must have a description in its meta section."""
        with open(YARA_PATH) as f:
            content = f.read()
        rules = re.findall(r'rule\s+\w+', content)
        descriptions = re.findall(r'description\s*=', content)
        assert len(descriptions) >= len(rules), (
            f"Found {len(rules)} rules but only {len(descriptions)} descriptions; "
            f"each rule must have a description in meta"
        )

    def test_yara_detects_encryption_tool(self):
        """YARA rules must match the threat actor's custom encryption tool."""
        result = subprocess.run(
            ["yara", YARA_PATH, "/app/evidence/encryption_tool.py"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"YARA scan error: {result.stderr}"
        assert result.stdout.strip(), (
            "YARA rules must detect the encryption tool in "
            "/app/evidence/encryption_tool.py"
        )

    def test_yara_detects_reverse_shell_service(self):
        """YARA rules must match the malicious systemd service."""
        result = subprocess.run(
            ["yara", YARA_PATH,
             "/app/evidence/systemd/reverse-proxy-cache.service"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"YARA scan error: {result.stderr}"
        assert result.stdout.strip(), (
            "YARA rules must detect the malicious systemd service"
        )

    def test_yara_detects_crontab_persistence(self):
        """YARA rules must match the malicious crontab entries."""
        result = subprocess.run(
            ["yara", YARA_PATH, "/app/evidence/crontabs/root"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"YARA scan error: {result.stderr}"
        assert result.stdout.strip(), (
            "YARA rules must detect backdoor patterns in root crontab"
        )


# ── Security Assessment: Structure ─────────────────────────────────────────


class TestAssessmentStructure:
    def test_assessment_file_exists(self):
        """Security assessment file must exist."""
        assert os.path.exists(ASSESSMENT_PATH), (
            f"Security assessment not found at {ASSESSMENT_PATH}"
        )

    def test_has_all_required_sections(self, assessment):
        """Assessment must contain all five required top-level sections."""
        required = [
            "control_failure_analysis",
            "detection_coverage_matrix",
            "sigma_rules",
            "architecture_weaknesses",
            "overall_maturity",
        ]
        for key in required:
            assert key in assessment, (
                f"Security assessment missing required section: '{key}'"
            )


# ── Security Assessment: Control Failure Analysis ──────────────────────────


class TestControlFailureAnalysis:
    def test_minimum_entries(self, assessment):
        """At least 4 control failure entries covering different attack stages."""
        cfa = assessment["control_failure_analysis"]
        assert isinstance(cfa, list), "control_failure_analysis must be an array"
        assert len(cfa) >= 4, (
            f"Expected at least 4 control failure entries, found {len(cfa)}"
        )

    def test_entries_have_required_fields(self, assessment):
        """Each control failure entry must have the specified fields."""
        cfa = assessment["control_failure_analysis"]
        required_fields = [
            "attack_stage", "mitre_technique_id", "mitre_technique_name",
            "existing_control", "failure_reason", "recommended_control",
        ]
        for i, entry in enumerate(cfa):
            for field in required_fields:
                assert field in entry, (
                    f"Control failure entry {i} missing field '{field}'"
                )

    def test_covers_initial_access(self, assessment):
        """Control failure analysis must cover the initial access stage."""
        cfa_str = json.dumps(assessment["control_failure_analysis"]).lower()
        assert any(
            kw in cfa_str
            for kw in ["t1190", "initial access", "exploit public"]
        ), "Control failure analysis must cover initial access (T1190)"

    def test_covers_privilege_escalation(self, assessment):
        """Control failure analysis must cover privilege escalation."""
        cfa_str = json.dumps(assessment["control_failure_analysis"]).lower()
        assert any(
            kw in cfa_str
            for kw in ["t1078", "t1548", "privilege escalat", "valid account",
                        "abuse elevation"]
        ), "Control failure analysis must cover privilege escalation"

    def test_covers_persistence(self, assessment):
        """Control failure analysis must cover persistence mechanisms."""
        cfa_str = json.dumps(assessment["control_failure_analysis"]).lower()
        assert any(
            kw in cfa_str
            for kw in ["t1053", "t1543", "t1098", "scheduled task", "cron",
                        "systemd", "ssh authorized"]
        ), "Control failure analysis must cover persistence"

    def test_covers_exfiltration(self, assessment):
        """Control failure analysis must cover data exfiltration."""
        cfa_str = json.dumps(assessment["control_failure_analysis"]).lower()
        assert any(
            kw in cfa_str
            for kw in ["t1048", "t1041", "exfiltrat", "alternative protocol"]
        ), "Control failure analysis must cover exfiltration"

    def test_mitre_ids_are_valid_format(self, assessment):
        """MITRE technique IDs must follow the TXXXXx pattern."""
        cfa = assessment["control_failure_analysis"]
        for entry in cfa:
            tid = entry["mitre_technique_id"]
            assert re.match(r'^T\d{4}(\.\d{3})?$', tid), (
                f"Invalid MITRE technique ID format: '{tid}'"
            )

    def test_recommended_controls_are_substantive(self, assessment):
        """Recommended controls must be substantive, not generic."""
        cfa = assessment["control_failure_analysis"]
        for i, entry in enumerate(cfa):
            rc = entry["recommended_control"]
            assert len(str(rc)) >= 20, (
                f"Recommended control in entry {i} too short — must be specific"
            )


# ── Security Assessment: Detection Coverage Matrix ─────────────────────────


class TestDetectionCoverageMatrix:
    def test_minimum_entries(self, assessment):
        """At least 4 detection coverage entries."""
        dcm = assessment["detection_coverage_matrix"]
        assert isinstance(dcm, list), "detection_coverage_matrix must be an array"
        assert len(dcm) >= 4, (
            f"Expected at least 4 detection matrix entries, found {len(dcm)}"
        )

    def test_entries_have_required_fields(self, assessment):
        """Each detection matrix entry must have the specified fields."""
        dcm = assessment["detection_coverage_matrix"]
        required_fields = [
            "mitre_id", "technique_name", "current_status",
            "required_data_source", "proposed_detection",
        ]
        for i, entry in enumerate(dcm):
            for field in required_fields:
                assert field in entry, (
                    f"Detection matrix entry {i} missing field '{field}'"
                )

    def test_status_values_valid(self, assessment):
        """Detection status must be one of: detected, partial, undetected."""
        dcm = assessment["detection_coverage_matrix"]
        valid_statuses = {"detected", "partial", "undetected"}
        for i, entry in enumerate(dcm):
            status = entry["current_status"].lower()
            assert status in valid_statuses, (
                f"Entry {i} has invalid status '{status}'; "
                f"must be one of {valid_statuses}"
            )

    def test_identifies_detection_gaps(self, assessment):
        """Matrix must identify at least one undetected technique."""
        dcm = assessment["detection_coverage_matrix"]
        statuses = [e["current_status"].lower() for e in dcm]
        assert "undetected" in statuses or "partial" in statuses, (
            "Detection matrix must identify gaps (undetected/partial techniques)"
        )

    def test_proposed_detections_are_substantive(self, assessment):
        """Proposed detection approaches must be substantive."""
        dcm = assessment["detection_coverage_matrix"]
        for i, entry in enumerate(dcm):
            pd = entry["proposed_detection"]
            assert len(str(pd)) >= 20, (
                f"Proposed detection in entry {i} too short — must be specific"
            )


# ── Security Assessment: Sigma Rules ──────────────────────────────────────


class TestSigmaRules:
    def test_minimum_count(self, assessment):
        """At least 3 Sigma detection rules must be provided."""
        rules = assessment["sigma_rules"]
        assert isinstance(rules, list), "sigma_rules must be an array"
        assert len(rules) >= 3, (
            f"Expected at least 3 Sigma rules, found {len(rules)}"
        )

    def test_rules_are_valid_yaml(self, assessment):
        """Each Sigma rule must be a valid YAML string."""
        rules = assessment["sigma_rules"]
        for i, rule_str in enumerate(rules):
            assert isinstance(rule_str, str), (
                f"Sigma rule {i} must be a YAML string, got {type(rule_str)}"
            )
            parsed = yaml.safe_load(rule_str)
            assert isinstance(parsed, dict), (
                f"Sigma rule {i} YAML does not parse to a dict"
            )

    def test_rules_have_required_sigma_fields(self, assessment):
        """Each Sigma rule must have title, logsource, and detection sections."""
        rules = assessment["sigma_rules"]
        for i, rule_str in enumerate(rules):
            parsed = yaml.safe_load(rule_str)
            assert "title" in parsed, f"Sigma rule {i} missing 'title'"
            assert "logsource" in parsed, f"Sigma rule {i} missing 'logsource'"
            assert "detection" in parsed, f"Sigma rule {i} missing 'detection'"

    def test_logsource_has_structure(self, assessment):
        """Each Sigma rule logsource must specify category or product."""
        rules = assessment["sigma_rules"]
        for i, rule_str in enumerate(rules):
            parsed = yaml.safe_load(rule_str)
            ls = parsed["logsource"]
            assert isinstance(ls, dict), (
                f"Sigma rule {i} logsource must be a dict"
            )
            assert any(
                k in ls for k in ["category", "product", "service"]
            ), f"Sigma rule {i} logsource must have category, product, or service"

    def test_detection_has_condition(self, assessment):
        """Each Sigma rule detection section must have a condition."""
        rules = assessment["sigma_rules"]
        for i, rule_str in enumerate(rules):
            parsed = yaml.safe_load(rule_str)
            det = parsed["detection"]
            assert isinstance(det, dict), (
                f"Sigma rule {i} detection must be a dict"
            )
            assert "condition" in det, (
                f"Sigma rule {i} detection must have a 'condition'"
            )

    def test_rules_cover_initial_access(self, assessment):
        """At least one Sigma rule must address initial access detection."""
        rules_combined = " ".join(assessment["sigma_rules"]).lower()
        assert any(
            kw in rules_combined
            for kw in ["ssti", "template injection", "initial access",
                        "t1190", "exploit", "injection"]
        ), "Sigma rules must include detection for the initial access technique"

    def test_rules_cover_privilege_escalation(self, assessment):
        """At least one Sigma rule must address privilege escalation detection."""
        rules_combined = " ".join(assessment["sigma_rules"]).lower()
        assert any(
            kw in rules_combined
            for kw in ["privilege escalation", "sudo", "su ",
                        "t1078", "t1548", "elevation"]
        ), "Sigma rules must include detection for privilege escalation"

    def test_rules_cover_persistence(self, assessment):
        """At least one Sigma rule must address persistence detection."""
        rules_combined = " ".join(assessment["sigma_rules"]).lower()
        assert any(
            kw in rules_combined
            for kw in ["persistence", "cron", "systemd", "base64",
                        "t1053", "t1543", "scheduled"]
        ), "Sigma rules must include detection for persistence mechanisms"


# ── Security Assessment: Architecture Weaknesses ──────────────────────────


class TestArchitectureWeaknesses:
    def test_minimum_count(self, assessment):
        """At least 5 architecture weaknesses must be identified."""
        aw = assessment["architecture_weaknesses"]
        assert isinstance(aw, list), "architecture_weaknesses must be an array"
        assert len(aw) >= 5, (
            f"Expected at least 5 architecture weaknesses, found {len(aw)}"
        )

    def test_entries_have_required_fields(self, assessment):
        """Each weakness entry must have the specified fields."""
        aw = assessment["architecture_weaknesses"]
        required_fields = [
            "rank", "weakness", "impact_assessment",
            "evidence_from_incident", "remediation",
        ]
        for i, entry in enumerate(aw):
            for field in required_fields:
                assert field in entry, (
                    f"Architecture weakness {i} missing field '{field}'"
                )

    def test_weaknesses_are_ranked(self, assessment):
        """Weaknesses must be numbered/ranked in order."""
        aw = assessment["architecture_weaknesses"]
        ranks = [int(entry["rank"]) for entry in aw]
        assert ranks == sorted(ranks), (
            "Architecture weaknesses must be ranked in ascending order"
        )

    def test_evidence_is_substantive(self, assessment):
        """Each weakness must cite evidence from the investigation."""
        aw = assessment["architecture_weaknesses"]
        for i, entry in enumerate(aw):
            evidence = entry["evidence_from_incident"]
            assert len(str(evidence)) >= 20, (
                f"Weakness {i} evidence too short — must reference specific findings"
            )

    def test_weaknesses_cover_credential_management(self, assessment):
        """Weaknesses must address credential management failures."""
        aw_str = json.dumps(assessment["architecture_weaknesses"]).lower()
        assert any(
            kw in aw_str
            for kw in ["credential", "password", "plaintext", "config.py",
                        "secret", "hardcoded"]
        ), "Architecture weaknesses must address credential management"

    def test_weaknesses_cover_access_control(self, assessment):
        """Weaknesses must address access control / permission failures."""
        aw_str = json.dumps(assessment["architecture_weaknesses"]).lower()
        assert any(
            kw in aw_str
            for kw in ["permission", "access control", "writable", "sudo",
                        "privilege", "least privilege"]
        ), "Architecture weaknesses must address access control failures"


# ── Security Assessment: Overall Maturity ──────────────────────────────────


class TestOverallMaturity:
    def test_has_score(self, assessment):
        """Overall maturity must include a numeric score."""
        om = assessment["overall_maturity"]
        assert "score" in om, "overall_maturity must have a 'score'"
        score = om["score"]
        assert isinstance(score, (int, float)), "Maturity score must be numeric"
        assert 1 <= int(score) <= 5, "Maturity score must be between 1 and 5"

    def test_score_reflects_severe_failures(self, assessment):
        """Given pervasive control failures, maturity score should be low."""
        score = int(assessment["overall_maturity"]["score"])
        assert score <= 3, (
            f"Maturity score {score} too high — the organization had plaintext "
            f"credentials, no WAF, writable sudo scripts, no egress filtering, "
            f"and multiple undetected persistence mechanisms"
        )

    def test_has_substantive_justification(self, assessment):
        """Maturity justification must be evidence-based and substantive."""
        om = assessment["overall_maturity"]
        assert "justification" in om, (
            "overall_maturity must have a 'justification'"
        )
        justification = str(om["justification"])
        assert len(justification) >= 100, (
            "Maturity justification must be substantive (100+ characters) "
            "with evidence-based reasoning"
        )


# ── Independent Decryption Verification ──────────────────────────────────────


class TestDecryptionVerification:
    def test_encrypted_archive_integrity(self):
        """Independently verify the encrypted archive decrypts correctly
        with the known seed and contains the expected files."""
        enc_path = "/app/evidence/encrypted_exfil.bin"
        assert os.path.exists(enc_path), "Encrypted exfil file not found"

        with open(enc_path, "rb") as f:
            data = f.read()

        # Reproduce key derivation
        dk = hashlib.sha512(ENCRYPTION_SEED.encode("utf-8")).digest()
        for _ in range(50000):
            dk = hashlib.sha512(dk).digest()
        key = dk[:32]

        # Decrypt (CTR mode)
        nonce = data[:12]
        ciphertext = data[12:]
        result = bytearray()
        for i in range(0, len(ciphertext), 32):
            counter_block = nonce + struct.pack(">I", i // 32)
            keystream = hashlib.sha256(key + counter_block).digest()
            chunk = ciphertext[i : i + 32]
            result.extend(b ^ k for b, k in zip(chunk, keystream[: len(chunk)]))

        # Verify it's a valid gzip tar with expected contents
        tar_buffer = io.BytesIO(bytes(result))
        with tarfile.open(fileobj=tar_buffer, mode="r:gz") as tar:
            members = {m.name for m in tar.getmembers()}

        assert members == EXPECTED_EXFIL_FILES, (
            f"Decrypted archive contains {members}, expected {EXPECTED_EXFIL_FILES}"
        )
