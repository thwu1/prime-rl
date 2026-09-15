"""Tests for quickcalc supply chain forensic analysis.

"""
import json
import os
import re
import subprocess

import pytest


REPORT_PATH = "/app/report/analysis.json"
SEMGREP_RULE_PATH = "/app/report/detect_malware.yaml"


@pytest.fixture
def report():
    """Load the analysis report."""
    assert os.path.isfile(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        return json.load(f)


class TestVersionClassification:
    """Test correct classification of package versions."""

    def test_malicious_versions_identified(self, report):
        mal = set(report.get("malicious_versions", []))
        assert "1.2.0" in mal, "v1.2.0 should be classified as malicious"
        assert "1.2.1" in mal, "v1.2.1 should be classified as malicious"
        assert "1.2.2" in mal, "v1.2.2 should be classified as malicious"

    def test_clean_versions_identified(self, report):
        clean = set(report.get("clean_versions", []))
        assert "1.0.0" in clean, "v1.0.0 should be classified as clean"
        assert "1.0.1" in clean, "v1.0.1 should be classified as clean"
        assert "1.1.0" in clean, "v1.1.0 should be classified as clean"

    def test_no_version_overlap(self, report):
        mal = set(report.get("malicious_versions", []))
        clean = set(report.get("clean_versions", []))
        assert len(mal & clean) == 0, "No version should appear in both malicious and clean lists"

    def test_all_versions_classified(self, report):
        mal = set(report.get("malicious_versions", []))
        clean = set(report.get("clean_versions", []))
        all_versions = mal | clean
        assert len(all_versions) == 6, f"All 6 versions must be classified, got {len(all_versions)}"


class TestIOCExtraction:
    """Test extraction of indicators of compromise from decoded payloads."""

    def test_c2_domain(self, report):
        c2 = report.get("c2_domains", [])
        assert any("quickcalc-cdn.freeddns.org" in d for d in c2), \
            "Must identify updates.quickcalc-cdn.freeddns.org as C2 domain"

    def test_exfil_domain(self, report):
        exfil = report.get("exfil_domains", [])
        assert any("quickcalc.cloud" in d for d in exfil), \
            "Must identify api-cdn.quickcalc.cloud as exfil domain"

    def test_exfil_endpoint(self, report):
        endpoints = report.get("exfil_endpoints", [])
        assert any("api-cdn.quickcalc.cloud" in e and "telemetry" in e for e in endpoints), \
            "Must identify the /v2/telemetry exfil endpoint"

    def test_beacon_interval(self, report):
        interval = report.get("beacon_interval_seconds")
        assert interval == 300, f"Beacon interval should be 300 seconds, got {interval}"

    def test_targeted_credentials_core(self, report):
        creds = set(report.get("targeted_credentials", []))
        required = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "PYPI_TOKEN"}
        missing = required - creds
        assert len(missing) == 0, f"Missing targeted credentials: {missing}"

    def test_targeted_files_ssh(self, report):
        files = report.get("targeted_files", [])
        files_str = " ".join(files)
        assert ("id_rsa" in files_str or "id_ed25519" in files_str), \
            "Must identify SSH key files as targets"

    def test_targeted_files_aws(self, report):
        files = report.get("targeted_files", [])
        assert any("aws" in f.lower() and "credentials" in f.lower() for f in files), \
            "Must identify AWS credentials file as target"

    def test_targeted_files_k8s(self, report):
        files = report.get("targeted_files", [])
        assert any("kubernetes" in f.lower() or "serviceaccount" in f.lower() for f in files), \
            "Must identify Kubernetes service account token as target"

    def test_persistence_mechanism(self, report):
        mech = report.get("persistence_mechanism", "").lower()
        assert "pth" in mech, f"Must identify .pth file as persistence mechanism, got: {mech}"


class TestAttackChainReconstruction:
    """Test reconstruction of the attack chain from log correlation."""

    def test_initial_access_vector(self, report):
        vector = report.get("initial_access_vector", "").lower()
        assert "trivy" in vector, "Must identify compromised trivy action as initial access vector"

    def test_compromised_tool_name(self, report):
        tool = report.get("compromised_tool_name", "").lower()
        assert "trivy" in tool, f"Must identify trivy as the compromised tool, got: {tool}"

    def test_compromised_tool_version(self, report):
        version = report.get("compromised_tool_version", "")
        assert "0.69.4" in version, \
            f"Must identify v0.69.4 as compromised version, got: {version}"

    def test_credential_exfil_destination(self, report):
        dest = report.get("credential_exfil_destination", "").lower()
        assert "checkmarx.zone" in dest, \
            "Must identify checkmarx.zone as where trivy exfiltrated credentials"

    def test_registrar(self, report):
        registrar = report.get("attacker_infrastructure_domain_registrar", "").lower()
        assert "namecheap" in registrar, \
            f"Must identify Namecheap as registrar, got: {registrar}"

    def test_c2_decoy_ip(self, report):
        ip = report.get("attacker_c2_decoy_ip", "")
        assert ip == "8.8.8.8", f"Must identify 8.8.8.8 as C2 decoy IP, got: {ip}"

    def test_timeline_has_minimum_events(self, report):
        timeline = report.get("attack_timeline", [])
        assert len(timeline) >= 4, \
            f"Timeline must have at least 4 events, got {len(timeline)}"

    def test_timeline_chronological_order(self, report):
        timeline = report.get("attack_timeline", [])
        timestamps = [e.get("timestamp", "") for e in timeline]
        assert timestamps == sorted(timestamps), \
            "Timeline events must be in chronological order"

    def test_timeline_includes_trivy_compromise(self, report):
        timeline = report.get("attack_timeline", [])
        events_str = " ".join(e.get("event", "").lower() for e in timeline)
        assert "trivy" in events_str, "Timeline must include trivy compromise event"

    def test_timeline_includes_package_publication(self, report):
        timeline = report.get("attack_timeline", [])
        events_str = " ".join(e.get("event", "").lower() for e in timeline)
        has_publication = (
            "1.2.0" in events_str
            or "publish" in events_str
            or "upload" in events_str
        )
        assert has_publication, "Timeline must include malicious package publication"


class TestMitreAttackMapping:
    """Test MITRE ATT&CK technique mapping requires evaluative judgment."""

    def test_has_minimum_techniques(self, report):
        techniques = report.get("mitre_attack_techniques", [])
        assert len(techniques) >= 4, \
            f"Must map at least 4 MITRE ATT&CK techniques, got {len(techniques)}"

    def test_technique_id_format(self, report):
        techniques = report.get("mitre_attack_techniques", [])
        for t in techniques:
            assert "technique_id" in t, "Each technique must have a technique_id field"
            assert re.match(r"T\d{4}", t["technique_id"]), \
                f"Technique ID must match T#### format, got: {t['technique_id']}"

    def test_technique_has_name(self, report):
        techniques = report.get("mitre_attack_techniques", [])
        for t in techniques:
            assert "technique_name" in t and len(t["technique_name"]) > 3, \
                "Each technique must have a meaningful technique_name"

    def test_includes_supply_chain_technique(self, report):
        ids = [t["technique_id"] for t in report.get("mitre_attack_techniques", [])]
        assert any("T1195" in tid for tid in ids), \
            "Must identify supply chain compromise technique (T1195)"

    def test_includes_obfuscation_technique(self, report):
        ids = [t["technique_id"] for t in report.get("mitre_attack_techniques", [])]
        assert any("T1027" in tid for tid in ids), \
            "Must identify obfuscated files/information technique (T1027)"

    def test_includes_c2_protocol_technique(self, report):
        ids = [t["technique_id"] for t in report.get("mitre_attack_techniques", [])]
        assert any("T1071" in tid for tid in ids), \
            "Must identify application layer C2 protocol technique (T1071)"

    def test_includes_exfiltration_technique(self, report):
        ids = [t["technique_id"] for t in report.get("mitre_attack_techniques", [])]
        has_exfil = any("T1041" in tid or "T1567" in tid for tid in ids)
        assert has_exfil, \
            "Must identify exfiltration technique (T1041 or T1567)"


class TestSeverityAssessment:
    """Test severity assessment requires evaluative judgment about threat levels."""

    SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    def test_all_malicious_versions_assessed(self, report):
        assessments = report.get("severity_assessment", [])
        versions = {a.get("version") for a in assessments}
        assert "1.2.0" in versions, "Must assess v1.2.0 severity"
        assert "1.2.1" in versions, "Must assess v1.2.1 severity"
        assert "1.2.2" in versions, "Must assess v1.2.2 severity"

    def test_valid_severity_levels(self, report):
        assessments = report.get("severity_assessment", [])
        for a in assessments:
            assert a.get("severity") in self.SEVERITY_ORDER, \
                f"Invalid severity level '{a.get('severity')}' for v{a.get('version')}. " \
                f"Must be one of: low, medium, high, critical"

    def test_v122_is_critical(self, report):
        assessments = report.get("severity_assessment", [])
        severity_map = {a["version"]: a["severity"] for a in assessments}
        assert severity_map.get("1.2.2") == "critical", \
            "v1.2.2 (with lateral movement, encrypted exfil, system credential theft) " \
            "should be rated critical"

    def test_severity_ordering(self, report):
        assessments = report.get("severity_assessment", [])
        severity_map = {a["version"]: a["severity"] for a in assessments}
        s_120 = self.SEVERITY_ORDER.get(severity_map.get("1.2.0", "low"), -1)
        s_121 = self.SEVERITY_ORDER.get(severity_map.get("1.2.1", "low"), -1)
        s_122 = self.SEVERITY_ORDER.get(severity_map.get("1.2.2", "low"), -1)
        assert s_122 >= s_121 >= s_120, \
            "Severity must increase monotonically: v1.2.0 <= v1.2.1 <= v1.2.2"

    def test_has_justification(self, report):
        assessments = report.get("severity_assessment", [])
        for a in assessments:
            justification = a.get("justification", "")
            assert len(justification) >= 20, \
                f"Severity assessment for v{a.get('version')} needs substantive justification " \
                f"(got {len(justification)} chars)"


class TestSemgrepRule:
    """Test the Semgrep detection rule catches malicious patterns."""

    def test_semgrep_rule_exists(self):
        assert os.path.isfile(SEMGREP_RULE_PATH), \
            f"Semgrep rule not found at {SEMGREP_RULE_PATH}"

    def test_semgrep_rule_valid_yaml(self):
        import yaml
        with open(SEMGREP_RULE_PATH) as f:
            data = yaml.safe_load(f)
        assert "rules" in data, "Semgrep rule file must contain 'rules' key"
        assert len(data["rules"]) > 0, "Must contain at least one rule"

    def test_detects_malicious_setup_py(self):
        """Semgrep rule must flag v1.2.0 setup.py (base64 exec pattern)."""
        result = subprocess.run(
            ["semgrep", "--config", SEMGREP_RULE_PATH,
             "/app/packages/quickcalc-1.2.0/setup.py",
             "--json", "--quiet"],
            capture_output=True, text=True, timeout=120
        )
        output = json.loads(result.stdout) if result.stdout.strip() else {"results": []}
        assert len(output.get("results", [])) > 0, \
            "Semgrep rule must detect malicious pattern in v1.2.0 setup.py"

    def test_detects_malicious_utils(self):
        """Semgrep rule must flag v1.2.2 utils.py (zlib+base64 exec pattern)."""
        result = subprocess.run(
            ["semgrep", "--config", SEMGREP_RULE_PATH,
             "/app/packages/quickcalc-1.2.2/quickcalc/utils.py",
             "--json", "--quiet"],
            capture_output=True, text=True, timeout=120
        )
        output = json.loads(result.stdout) if result.stdout.strip() else {"results": []}
        assert len(output.get("results", [])) > 0, \
            "Semgrep rule must detect malicious pattern in v1.2.2 utils.py"

    def test_no_false_positives_clean_v100(self):
        """Semgrep rule must NOT flag clean v1.0.0."""
        result = subprocess.run(
            ["semgrep", "--config", SEMGREP_RULE_PATH,
             "/app/packages/quickcalc-1.0.0/",
             "--json", "--quiet"],
            capture_output=True, text=True, timeout=120
        )
        output = json.loads(result.stdout) if result.stdout.strip() else {"results": []}
        assert len(output.get("results", [])) == 0, \
            "Semgrep rule must not false-positive on clean v1.0.0"

    def test_no_false_positives_clean_v110(self):
        """Semgrep rule must NOT flag clean v1.1.0."""
        result = subprocess.run(
            ["semgrep", "--config", SEMGREP_RULE_PATH,
             "/app/packages/quickcalc-1.1.0/",
             "--json", "--quiet"],
            capture_output=True, text=True, timeout=120
        )
        output = json.loads(result.stdout) if result.stdout.strip() else {"results": []}
        assert len(output.get("results", [])) == 0, \
            "Semgrep rule must not false-positive on clean v1.1.0"
