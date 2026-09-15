
"""
Verification tests for the KernelCI Pipeline Configuration Auditor.
Tests are category-agnostic: findings are verified by searching the
entire report for evidence of each specific defect, regardless of how
the auditor chose to categorize them.
"""

import json
import os
import subprocess
import pytest


REPORT_PATH = "/app/audit_report.json"


def setup_module(module):
    """Ensure audit.py has been run and report exists."""
    if os.path.exists("/app/audit.py"):
        subprocess.run(
            ["python3", "/app/audit.py"],
            cwd="/app",
            capture_output=True,
            timeout=60,
        )


def load_report():
    with open(REPORT_PATH) as f:
        return json.load(f)


def all_findings(report=None):
    """Extract all finding objects from every list-valued key in the report."""
    if report is None:
        report = load_report()
    findings = []
    for key, val in report.items():
        if isinstance(val, list):
            findings.extend(val)
    return findings


def report_json_text(report=None):
    """Full report as lowercased JSON string for broad text searches."""
    if report is None:
        report = load_report()
    return json.dumps(report).lower()


# ── Tool execution ──────────────────────────────────────────────────


class TestToolExecution:
    def test_audit_tool_exists(self):
        assert os.path.exists("/app/audit.py"), "audit.py must exist at /app/audit.py"

    def test_audit_tool_runs_successfully(self):
        result = subprocess.run(
            ["python3", "/app/audit.py"],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"audit.py failed: {result.stderr}"

    def test_report_created(self):
        assert os.path.exists(REPORT_PATH), "audit_report.json must be created"

    def test_report_is_valid_json_object(self):
        report = load_report()
        assert isinstance(report, dict)


# ── Report structure ────────────────────────────────────────────────


class TestReportStructure:
    def test_has_multiple_defect_categories(self):
        report = load_report()
        categories = [k for k, v in report.items() if isinstance(v, list) and len(v) > 0]
        assert len(categories) >= 4, (
            f"Report should have at least 4 non-empty defect categories, "
            f"found {len(categories)}: {categories}"
        )

    def test_findings_are_objects(self):
        findings = all_findings()
        assert len(findings) > 0, "Report must contain at least one finding"
        for f in findings:
            assert isinstance(f, dict), (
                f"Each finding must be a JSON object, got {type(f)}"
            )

    def test_findings_have_severity(self):
        findings = all_findings()
        for f in findings:
            has_sev = any(k in f for k in ["severity", "level", "criticality"])
            assert has_sev, f"Finding missing severity field: {list(f.keys())}"

    def test_findings_have_description(self):
        findings = all_findings()
        for f in findings:
            has_desc = any(
                k in f
                for k in ["message", "description", "detail", "issue", "summary"]
            )
            assert has_desc, f"Finding missing description field: {list(f.keys())}"


# ── Priority range overlaps ─────────────────────────────────────────


class TestPriorityOverlaps:
    """LAVA labs alpha[10,50], beta[30,70], gamma[45,55], zeta[20,45]
    have multiple pairwise priority range overlaps."""

    def test_alpha_beta_overlap(self):
        findings = all_findings()
        found = any(
            "alpha" in json.dumps(f).lower() and "beta" in json.dumps(f).lower()
            for f in findings
        )
        assert found, "Should detect priority overlap between alpha and beta"

    def test_alpha_gamma_overlap(self):
        findings = all_findings()
        found = any(
            "alpha" in json.dumps(f).lower() and "gamma" in json.dumps(f).lower()
            for f in findings
        )
        assert found, "Should detect priority overlap between alpha and gamma"

    def test_beta_gamma_overlap(self):
        findings = all_findings()
        found = any(
            "beta" in json.dumps(f).lower() and "gamma" in json.dumps(f).lower()
            for f in findings
        )
        assert found, "Should detect priority overlap between beta and gamma"

    def test_sufficient_overlap_pairs(self):
        """At least 4 pairwise overlaps exist among alpha, beta, gamma, zeta."""
        findings = all_findings()
        labs = ["alpha", "beta", "gamma", "zeta"]
        pairs_found = set()
        for f in findings:
            ft = json.dumps(f).lower()
            for i, a in enumerate(labs):
                for b in labs[i + 1 :]:
                    if a in ft and b in ft:
                        pairs_found.add((a, b))
        assert len(pairs_found) >= 4, (
            f"Expected >=4 priority overlap pairs, found {len(pairs_found)}: "
            f"{pairs_found}"
        )


# ── Invalid priority ranges ────────────────────────────────────────


class TestInvalidRanges:
    """lava-delta has priority_min=80 > priority_max=60."""

    def test_delta_inverted_range(self):
        findings = all_findings()
        found = any(
            "delta" in json.dumps(f).lower()
            and any(
                kw in json.dumps(f).lower()
                for kw in ["invert", "invalid", "range", "exceed", "greater", "min", "80"]
            )
            for f in findings
        )
        assert found, "Should detect lava-delta's inverted priority range (min=80 > max=60)"


# ── Tree rule conflicts ────────────────────────────────────────────


class TestTreeRuleConflicts:
    """lava-delta has contradictory android/!android rules.
    alpha allows 'next' while beta denies it at overlapping priorities.
    alpha allows 'stable' while zeta denies it at overlapping priorities."""

    def test_delta_internal_contradiction(self):
        findings = all_findings()
        found = any(
            "delta" in json.dumps(f).lower() and "android" in json.dumps(f).lower()
            for f in findings
        )
        assert found, "Should detect delta's android/!android tree rule contradiction"

    def test_cross_lab_next_conflict(self):
        findings = all_findings()
        found = any(
            "next" in json.dumps(f).lower()
            and ("alpha" in json.dumps(f).lower() or "beta" in json.dumps(f).lower())
            for f in findings
        )
        assert found, "Should detect cross-lab tree conflict for 'next' (alpha vs beta)"

    def test_cross_lab_stable_conflict(self):
        findings = all_findings()
        found = any(
            "stable" in json.dumps(f).lower() and "zeta" in json.dumps(f).lower()
            for f in findings
        )
        assert found, "Should detect cross-lab tree conflict for 'stable' involving zeta"


# ── Token issues ────────────────────────────────────────────────────


class TestTokenIssues:
    """lava-delta uses placeholder token REPLACE-ME-WITH-REAL-TOKEN.
    lava-gamma and lava-zeta each inherit alpha's token via YAML merge key
    (diamond inheritance pattern)."""

    def test_placeholder_token_detected(self):
        findings = all_findings()
        found = any(
            "delta" in json.dumps(f).lower()
            and any(
                kw in json.dumps(f).lower()
                for kw in ["placeholder", "replace", "token"]
            )
            for f in findings
        )
        assert found, "Should detect delta's placeholder callback token"

    def test_gamma_inherited_token(self):
        findings = all_findings()
        found = any(
            "gamma" in json.dumps(f).lower()
            and any(
                kw in json.dumps(f).lower()
                for kw in ["inherit", "merge", "shared", "anchor", "alpha"]
            )
            for f in findings
        )
        assert found, (
            "Should detect gamma's callback token inherited from alpha "
            "via YAML merge key"
        )

    def test_zeta_inherited_token(self):
        findings = all_findings()
        found = any(
            "zeta" in json.dumps(f).lower()
            and any(
                kw in json.dumps(f).lower()
                for kw in ["inherit", "merge", "shared", "anchor", "alpha"]
            )
            for f in findings
        )
        assert found, (
            "Should detect zeta's callback token inherited from alpha "
            "via YAML merge key (diamond inheritance)"
        )


# ── Missing fields ──────────────────────────────────────────────────


class TestMissingFields:
    """backup-ssh is missing 'host'. lava-epsilon is missing 'url'."""

    def test_backup_ssh_missing_host(self):
        findings = all_findings()
        found = any(
            "backup" in json.dumps(f).lower()
            and any(
                kw in json.dumps(f).lower()
                for kw in ["host", "missing", "required"]
            )
            for f in findings
        )
        assert found, "Should detect backup-ssh's missing required 'host' field"

    def test_epsilon_missing_url(self):
        findings = all_findings()
        found = any(
            "epsilon" in json.dumps(f).lower()
            and any(
                kw in json.dumps(f).lower()
                for kw in ["url", "missing", "required"]
            )
            for f in findings
        )
        assert found, "Should detect lava-epsilon's missing required 'url' field"


# ── Storage issues ──────────────────────────────────────────────────


class TestStorageIssues:
    """s3-artifacts has base_url (production) vs api_url (staging) mismatch."""

    def test_s3_environment_mismatch(self):
        findings = all_findings()
        found = any(
            any(kw in json.dumps(f).lower() for kw in ["s3", "artifact"])
            and any(
                kw in json.dumps(f).lower()
                for kw in ["mismatch", "staging", "production", "inconsist", "environment"]
            )
            for f in findings
        )
        assert found, (
            "Should detect s3-artifacts environment mismatch "
            "(prod base_url vs staging api_url)"
        )


# ── Security warnings ──────────────────────────────────────────────


class TestSecurityWarnings:
    """lava-delta has disable_queue_limit: true."""

    def test_delta_queue_limit_disabled(self):
        findings = all_findings()
        found = any(
            "delta" in json.dumps(f).lower()
            and "queue" in json.dumps(f).lower()
            for f in findings
        )
        assert found, "Should flag lava-delta's disabled queue depth limiting"


# ── Completeness ────────────────────────────────────────────────────


class TestCompleteness:
    """Verify the audit is comprehensive."""

    def test_minimum_total_findings(self):
        findings = all_findings()
        assert len(findings) >= 13, (
            f"Expected at least 13 total findings across all categories, "
            f"got {len(findings)}"
        )

    def test_multiple_labs_covered(self):
        """At least 5 of the 6 LAVA labs should appear in findings."""
        text = report_json_text()
        labs = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]
        found = [lab for lab in labs if lab in text]
        assert len(found) >= 5, (
            f"At least 5 LAVA labs should appear in findings, "
            f"found {len(found)}: {found}"
        )

    def test_gamma_mentioned(self):
        """Gamma has inherited token and priority overlaps -- must appear."""
        text = report_json_text()
        assert "gamma" in text, "lava-gamma should appear in audit findings"

    def test_zeta_mentioned(self):
        """Zeta has inherited token, tree conflicts, and priority overlaps."""
        text = report_json_text()
        assert "zeta" in text, "lava-zeta should appear in audit findings"
