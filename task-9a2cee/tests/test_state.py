"""
Tests for npm supply chain security audit — verifies /app/audit_report.json.

"""
import json
import os
import pytest


REPORT_PATH = "/app/audit_report.json"

ALL_PACKAGES = [
    "config-utils",
    "log-helper",
    "string-tools",
    "data-store",
    "path-resolver",
    "build-runner",
]

EXPECTED_COMPROMISED = {"log-helper", "data-store", "build-runner"}
EXPECTED_CLEAN = {"config-utils", "string-tools", "path-resolver"}

VALID_CWES = {"CWE-506", "CWE-912", "CWE-94"}

# Critical advisory IDs that must NOT appear on clean packages
CRITICAL_ADVISORIES = {"ADV-2024-0117", "ADV-2024-0223", "ADV-2024-0341"}


@pytest.fixture(scope="module")
def report():
    assert os.path.exists(REPORT_PATH), f"{REPORT_PATH} does not exist"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def audit_by_pkg(report):
    """Index audit entries by package name."""
    assert "audit" in report, "Top-level 'audit' key missing"
    mapping = {}
    for entry in report["audit"]:
        assert "package" in entry, f"Entry missing 'package' key: {entry}"
        mapping[entry["package"]] = entry
    return mapping


# ============================================================
# Structure tests
# ============================================================

class TestStructure:
    def test_report_file_exists(self):
        assert os.path.exists(REPORT_PATH)

    def test_valid_json(self, report):
        assert isinstance(report, dict)
        assert "audit" in report

    def test_audit_is_list(self, report):
        assert isinstance(report["audit"], list)

    def test_correct_count(self, report):
        assert len(report["audit"]) == 6, (
            f"Expected 6 audit entries, got {len(report['audit'])}"
        )

    def test_all_packages_present(self, audit_by_pkg):
        found = set(audit_by_pkg.keys())
        expected = set(ALL_PACKAGES)
        assert found == expected, (
            f"Missing: {expected - found}, Extra: {found - expected}"
        )

    def test_required_fields(self, audit_by_pkg):
        for name, entry in audit_by_pkg.items():
            assert "version" in entry, f"{name}: missing 'version'"
            assert "integrity_match" in entry, f"{name}: missing 'integrity_match'"
            assert "compromised" in entry, f"{name}: missing 'compromised'"


# ============================================================
# Integrity verification tests
# ============================================================

class TestIntegrityVerification:
    """Verify that the agent correctly computed SRI hashes."""

    def test_log_helper_integrity_mismatch(self, audit_by_pkg):
        assert audit_by_pkg["log-helper"]["integrity_match"] is False, (
            "log-helper tarball was tampered — integrity_match should be False"
        )

    def test_config_utils_integrity_ok(self, audit_by_pkg):
        assert audit_by_pkg["config-utils"]["integrity_match"] is True

    def test_string_tools_integrity_ok(self, audit_by_pkg):
        assert audit_by_pkg["string-tools"]["integrity_match"] is True

    def test_data_store_integrity_ok(self, audit_by_pkg):
        assert audit_by_pkg["data-store"]["integrity_match"] is True

    def test_path_resolver_integrity_ok(self, audit_by_pkg):
        assert audit_by_pkg["path-resolver"]["integrity_match"] is True

    def test_build_runner_integrity_ok(self, audit_by_pkg):
        assert audit_by_pkg["build-runner"]["integrity_match"] is True


# ============================================================
# Compromised detection tests
# ============================================================

class TestCompromisedDetection:
    """Verify correct identification of compromised vs clean packages."""

    def test_log_helper_flagged(self, audit_by_pkg):
        assert audit_by_pkg["log-helper"]["compromised"] is True

    def test_data_store_flagged(self, audit_by_pkg):
        assert audit_by_pkg["data-store"]["compromised"] is True

    def test_build_runner_flagged(self, audit_by_pkg):
        assert audit_by_pkg["build-runner"]["compromised"] is True

    def test_config_utils_clean(self, audit_by_pkg):
        assert audit_by_pkg["config-utils"]["compromised"] is False

    def test_string_tools_clean(self, audit_by_pkg):
        assert audit_by_pkg["string-tools"]["compromised"] is False

    def test_path_resolver_clean(self, audit_by_pkg):
        assert audit_by_pkg["path-resolver"]["compromised"] is False


# ============================================================
# log-helper analysis
# ============================================================

class TestLogHelperAnalysis:
    """Verify analysis of log-helper postinstall exfiltration."""

    def test_cwe(self, audit_by_pkg):
        cwe = audit_by_pkg["log-helper"].get("cwe", "")
        assert any(cwe.startswith(c) for c in VALID_CWES), (
            f"Expected one of {VALID_CWES}, got '{cwe}'"
        )

    def test_attack_type(self, audit_by_pkg):
        at = audit_by_pkg["log-helper"].get("attack_type", "").lower()
        assert at in ("postinstall", "install", "lifecycle"), (
            f"Expected postinstall/install/lifecycle, got '{at}'"
        )

    def test_malicious_file(self, audit_by_pkg):
        mf = audit_by_pkg["log-helper"].get("malicious_file", "").lower()
        assert "postinstall" in mf, (
            f"Expected malicious_file to reference 'postinstall', got '{mf}'"
        )

    def test_behavior_keywords(self, audit_by_pkg):
        behavior = audit_by_pkg["log-helper"].get("behavior_summary", "").lower()
        keywords = [
            "environment", "variable", "env", "exfiltrat", "send",
            "credential", "steal", "leak", "collect", "harvest",
            "base64", "https", "post",
        ]
        matches = [kw for kw in keywords if kw in behavior]
        assert len(matches) >= 2, (
            f"Expected >=2 behavior keywords, matched: {matches}"
        )


# ============================================================
# data-store analysis
# ============================================================

class TestDataStoreAnalysis:
    """Verify analysis of data-store credential theft via DNS."""

    def test_cwe(self, audit_by_pkg):
        cwe = audit_by_pkg["data-store"].get("cwe", "")
        assert any(cwe.startswith(c) for c in VALID_CWES), (
            f"Expected one of {VALID_CWES}, got '{cwe}'"
        )

    def test_attack_type(self, audit_by_pkg):
        at = audit_by_pkg["data-store"].get("attack_type", "").lower()
        assert at in ("runtime", "import", "require", "constructor"), (
            f"Expected runtime/import/require/constructor, got '{at}'"
        )

    def test_malicious_file(self, audit_by_pkg):
        mf = audit_by_pkg["data-store"].get("malicious_file", "").lower()
        assert "persistence" in mf, (
            f"Expected malicious_file to reference 'persistence', got '{mf}'"
        )

    def test_behavior_keywords(self, audit_by_pkg):
        behavior = audit_by_pkg["data-store"].get("behavior_summary", "").lower()
        keywords = [
            "wallet", "credential", "key", "crypto", "bitcoin",
            "ssh", "aws", "exfiltrat", "dns", "steal", "read",
            "sensitive", "private", "secret", "subdomain",
        ]
        matches = [kw for kw in keywords if kw in behavior]
        assert len(matches) >= 2, (
            f"Expected >=2 behavior keywords, matched: {matches}"
        )


# ============================================================
# build-runner analysis
# ============================================================

class TestBuildRunnerAnalysis:
    """Verify analysis of build-runner destructive wiper payload."""

    def test_cwe(self, audit_by_pkg):
        cwe = audit_by_pkg["build-runner"].get("cwe", "")
        valid = VALID_CWES | {"CWE-400"}
        assert any(cwe.startswith(c) for c in valid), (
            f"Expected one of {valid}, got '{cwe}'"
        )

    def test_attack_type(self, audit_by_pkg):
        at = audit_by_pkg["build-runner"].get("attack_type", "").lower()
        assert at in ("runtime", "method_call", "import", "require"), (
            f"Expected runtime/method_call, got '{at}'"
        )

    def test_malicious_file(self, audit_by_pkg):
        mf = audit_by_pkg["build-runner"].get("malicious_file", "").lower()
        assert "cache" in mf, (
            f"Expected malicious_file to reference 'cache', got '{mf}'"
        )

    def test_behavior_keywords(self, audit_by_pkg):
        behavior = audit_by_pkg["build-runner"].get("behavior_summary", "").lower()
        keywords = [
            "overwrite", "destruct", "delet", "wipe", "empty",
            "replac", "erase", "truncat", "zero", "blank",
            "write", "remove", "corrupt",
        ]
        matches = [kw for kw in keywords if kw in behavior]
        assert len(matches) >= 1, (
            f"Expected >=1 behavior keywords, matched: {matches}"
        )


# ============================================================
# Evidence quality — semgrep usage required
# ============================================================

class TestEvidenceQuality:
    """Verify that compromised packages have semgrep-based evidence."""

    def test_log_helper_has_semgrep_evidence(self, audit_by_pkg):
        evidence = audit_by_pkg["log-helper"].get("evidence", [])
        semgrep_entries = [e for e in evidence if e.startswith("semgrep:")]
        assert len(semgrep_entries) >= 1, (
            f"log-helper must have >=1 semgrep: evidence entry, got {evidence}"
        )

    def test_data_store_has_semgrep_evidence(self, audit_by_pkg):
        evidence = audit_by_pkg["data-store"].get("evidence", [])
        semgrep_entries = [e for e in evidence if e.startswith("semgrep:")]
        assert len(semgrep_entries) >= 1, (
            f"data-store must have >=1 semgrep: evidence entry, got {evidence}"
        )

    def test_build_runner_has_semgrep_evidence(self, audit_by_pkg):
        evidence = audit_by_pkg["build-runner"].get("evidence", [])
        semgrep_entries = [e for e in evidence if e.startswith("semgrep:")]
        assert len(semgrep_entries) >= 1, (
            f"build-runner must have >=1 semgrep: evidence entry, got {evidence}"
        )

    def test_log_helper_has_integrity_evidence(self, audit_by_pkg):
        evidence = audit_by_pkg["log-helper"].get("evidence", [])
        has_integrity = any("integrity" in e.lower() for e in evidence)
        assert has_integrity, (
            f"log-helper should have integrity-related evidence, got {evidence}"
        )


# ============================================================
# Advisory cross-reference
# ============================================================

class TestAdvisoryCorrelation:
    """Verify correct advisory cross-referencing."""

    def test_log_helper_has_required_advisory(self, audit_by_pkg):
        advisories = audit_by_pkg["log-helper"].get("related_advisories", [])
        assert "ADV-2024-0117" in advisories, (
            f"log-helper must include ADV-2024-0117, got {advisories}"
        )

    def test_data_store_has_required_advisory(self, audit_by_pkg):
        advisories = audit_by_pkg["data-store"].get("related_advisories", [])
        assert "ADV-2024-0223" in advisories, (
            f"data-store must include ADV-2024-0223, got {advisories}"
        )

    def test_build_runner_has_required_advisory(self, audit_by_pkg):
        advisories = audit_by_pkg["build-runner"].get("related_advisories", [])
        assert "ADV-2024-0341" in advisories, (
            f"build-runner must include ADV-2024-0341, got {advisories}"
        )

    def test_config_utils_no_critical_advisory(self, audit_by_pkg):
        advisories = set(audit_by_pkg["config-utils"].get("related_advisories", []))
        overlap = advisories & CRITICAL_ADVISORIES
        assert len(overlap) == 0, (
            f"config-utils should not have critical advisories: {overlap}"
        )

    def test_string_tools_no_critical_advisory(self, audit_by_pkg):
        advisories = set(audit_by_pkg["string-tools"].get("related_advisories", []))
        overlap = advisories & CRITICAL_ADVISORIES
        assert len(overlap) == 0, (
            f"string-tools should not have critical advisories: {overlap}"
        )

    def test_path_resolver_no_critical_advisory(self, audit_by_pkg):
        advisories = set(audit_by_pkg["path-resolver"].get("related_advisories", []))
        overlap = advisories & CRITICAL_ADVISORIES
        assert len(overlap) == 0, (
            f"path-resolver should not have critical advisories: {overlap}"
        )

    def test_config_utils_no_prototype_pollution_advisory(self, audit_by_pkg):
        """ADV-2024-0512 matches config-* by pattern but only 1/3 indicators present."""
        advisories = audit_by_pkg["config-utils"].get("related_advisories", [])
        assert "ADV-2024-0512" not in advisories, (
            f"config-utils should NOT include ADV-2024-0512 (indicators not substantiated)"
        )


# ============================================================
# Clean packages — no false positives
# ============================================================

class TestCleanPackagesNotOverFlagged:
    """Ensure clean packages don't have malicious metadata."""

    def test_config_utils_no_malicious_details(self, audit_by_pkg):
        entry = audit_by_pkg["config-utils"]
        assert entry["compromised"] is False
        if "malicious_file" in entry:
            val = entry["malicious_file"]
            assert val is None or val == "", (
                "Clean package config-utils should not have malicious_file"
            )

    def test_string_tools_no_malicious_details(self, audit_by_pkg):
        entry = audit_by_pkg["string-tools"]
        assert entry["compromised"] is False

    def test_path_resolver_no_malicious_details(self, audit_by_pkg):
        entry = audit_by_pkg["path-resolver"]
        assert entry["compromised"] is False
