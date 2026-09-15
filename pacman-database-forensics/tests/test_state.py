"""Verify pacman database forensics report, strategy, and repair script.

"""
import json
import os
import re

import pytest


REPORT_PATH = "/app/report.json"
STRATEGY_PATH = "/app/strategy.json"
REPAIR_PATH = "/app/repair.sh"


def load_report():
    with open(REPORT_PATH) as f:
        return json.load(f)


def load_strategy():
    with open(STRATEGY_PATH) as f:
        return json.load(f)


def issues_by_type(report, issue_type):
    return [i for i in report["issues"] if i.get("type") == issue_type]


# ── Report structure ──────────────────────────────────────────────────────

class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH), "report.json not found at /app/report.json"

    def test_report_is_valid_json(self):
        report = load_report()
        assert "issues" in report, "report.json must have an 'issues' key"
        assert isinstance(report["issues"], list), "'issues' must be a list"

    def test_all_issues_have_required_fields(self):
        report = load_report()
        for i, issue in enumerate(report["issues"]):
            assert "type" in issue, "Issue %d missing 'type'" % i
            assert "package" in issue, "Issue %d missing 'package'" % i
            assert "details" in issue, "Issue %d missing 'details'" % i


# ── MISSING_DESC ──────────────────────────────────────────────────────────

class TestMissingDesc:
    def test_readline_detected(self):
        report = load_report()
        issues = issues_by_type(report, "MISSING_DESC")
        packages = [i["package"] for i in issues]
        assert any("readline" in p for p in packages), (
            "readline MISSING_DESC not detected. Found packages: %s" % packages
        )


# ── CORRUPTED_DESC ────────────────────────────────────────────────────────

class TestCorruptedDesc:
    def test_expat_detected(self):
        report = load_report()
        issues = issues_by_type(report, "CORRUPTED_DESC")
        packages = [i["package"] for i in issues]
        assert any("expat" in p for p in packages), (
            "expat CORRUPTED_DESC not detected. Found packages: %s" % packages
        )


# ── PARTIAL_UPGRADE ──────────────────────────────────────────────────────

class TestPartialUpgrade:
    def test_openssl_detected(self):
        report = load_report()
        issues = issues_by_type(report, "PARTIAL_UPGRADE")
        openssl_issues = [i for i in issues if "openssl" in i["package"]]
        assert len(openssl_issues) > 0, "openssl PARTIAL_UPGRADE not detected"

    def test_openssl_versions(self):
        report = load_report()
        issues = issues_by_type(report, "PARTIAL_UPGRADE")
        openssl_issues = [i for i in issues if "openssl" in i["package"]]
        details = openssl_issues[0]["details"]
        assert details.get("local_version", "").startswith("3.2"), (
            "openssl local_version wrong: %s" % details.get("local_version")
        )
        assert details.get("sync_version", "").startswith("3.3"), (
            "openssl sync_version wrong: %s" % details.get("sync_version")
        )

    def test_openssl_affected_dependents(self):
        report = load_report()
        issues = issues_by_type(report, "PARTIAL_UPGRADE")
        openssl_issues = [i for i in issues if "openssl" in i["package"]]
        details = openssl_issues[0]["details"]
        dependents = details.get("affected_dependents", [])
        assert any("curl" in d for d in dependents), (
            "curl not in openssl affected_dependents: %s" % dependents
        )

    def test_ncurses_detected(self):
        report = load_report()
        issues = issues_by_type(report, "PARTIAL_UPGRADE")
        ncurses_issues = [i for i in issues if "ncurses" in i["package"]]
        assert len(ncurses_issues) > 0, "ncurses PARTIAL_UPGRADE not detected"

    def test_ncurses_versions(self):
        report = load_report()
        issues = issues_by_type(report, "PARTIAL_UPGRADE")
        ncurses_issues = [i for i in issues if "ncurses" in i["package"]]
        details = ncurses_issues[0]["details"]
        assert details.get("local_version", "").startswith("6.3"), (
            "ncurses local_version wrong: %s" % details.get("local_version")
        )
        assert details.get("sync_version", "").startswith("6.4"), (
            "ncurses sync_version wrong: %s" % details.get("sync_version")
        )

    def test_ncurses_affected_dependents(self):
        report = load_report()
        issues = issues_by_type(report, "PARTIAL_UPGRADE")
        ncurses_issues = [i for i in issues if "ncurses" in i["package"]]
        details = ncurses_issues[0]["details"]
        dependents = details.get("affected_dependents", [])
        assert any("bash" in d for d in dependents), (
            "bash not in ncurses affected_dependents: %s" % dependents
        )

    # ── ICU with epoch-based versioning ──

    def test_icu_detected(self):
        report = load_report()
        issues = issues_by_type(report, "PARTIAL_UPGRADE")
        icu_issues = [i for i in issues if i["package"] == "icu"]
        assert len(icu_issues) > 0, (
            "icu PARTIAL_UPGRADE not detected — requires epoch-aware vercmp "
            "(local 1:74.2-1 vs sync 1:75.1-1)"
        )

    def test_icu_versions_include_epoch(self):
        report = load_report()
        issues = issues_by_type(report, "PARTIAL_UPGRADE")
        icu_issues = [i for i in issues if i["package"] == "icu"]
        details = icu_issues[0]["details"]
        assert "1:74.2" in details.get("local_version", ""), (
            "icu local_version must include epoch: %s" % details.get("local_version")
        )
        assert "1:75.1" in details.get("sync_version", ""), (
            "icu sync_version must include epoch: %s" % details.get("sync_version")
        )

    def test_icu_affected_dependents(self):
        report = load_report()
        issues = issues_by_type(report, "PARTIAL_UPGRADE")
        icu_issues = [i for i in issues if i["package"] == "icu"]
        details = icu_issues[0]["details"]
        dependents = details.get("affected_dependents", [])
        assert any("libxml2" in d for d in dependents), (
            "libxml2 not in icu affected_dependents: %s" % dependents
        )


# ── Epoch false-positive trap ─────────────────────────────────────────────

class TestEpochHandling:
    def test_libtasn1_not_partial_upgrade(self):
        """libtasn1 local 1:4.19.0-1 is NEWER than sync 4.20.0-1 due to
        epoch 1 > implicit epoch 0.  Must NOT be flagged as PARTIAL_UPGRADE."""
        report = load_report()
        issues = issues_by_type(report, "PARTIAL_UPGRADE")
        libtasn1_issues = [i for i in issues if "libtasn1" in i["package"]]
        assert len(libtasn1_issues) == 0, (
            "libtasn1 incorrectly flagged as PARTIAL_UPGRADE — "
            "epoch 1 makes local (1:4.19.0-1) newer than sync (4.20.0-1)"
        )


# ── MISSING_DEPENDENCY ───────────────────────────────────────────────────

class TestMissingDependency:
    def test_libgcrypt_detected(self):
        report = load_report()
        issues = issues_by_type(report, "MISSING_DEPENDENCY")
        assert len(issues) > 0, "No MISSING_DEPENDENCY issues found"
        found = False
        for issue in issues:
            pkg = issue.get("package", "")
            details = issue.get("details", {})
            missing = details.get("missing_dependency", "")
            if "libssh2" in pkg and "libgcrypt" in missing:
                found = True
        assert found, (
            "libssh2->libgcrypt MISSING_DEPENDENCY not found. Issues: %s" % issues
        )


# ── FILE_CONFLICT ────────────────────────────────────────────────────────

class TestFileConflict:
    def test_ca_certificates_conflict(self):
        report = load_report()
        issues = issues_by_type(report, "FILE_CONFLICT")
        assert len(issues) > 0, "No FILE_CONFLICT issues found"
        found = False
        for issue in issues:
            details = issue.get("details", {})
            file_path = details.get("file", "")
            pkgs = details.get("packages", [])
            if "ca-certificates.crt" in file_path:
                has_ca = any("ca-certificates" in p for p in pkgs)
                has_utils = any("ca-certificates-utils" in p for p in pkgs)
                if has_ca and has_utils:
                    found = True
        assert found, (
            "ca-certificates file conflict not found. Issues: %s" % issues
        )


# ── ORPHANED_PACKAGE ─────────────────────────────────────────────────────

class TestOrphanedPackage:
    def test_mpdecimal_orphan(self):
        report = load_report()
        issues = issues_by_type(report, "ORPHANED_PACKAGE")
        packages = [i.get("package", "") for i in issues]
        assert any("mpdecimal" in p for p in packages), (
            "mpdecimal orphan not found. Found: %s" % packages
        )

    def test_gdbm_orphan(self):
        report = load_report()
        issues = issues_by_type(report, "ORPHANED_PACKAGE")
        packages = [i.get("package", "") for i in issues]
        assert any("gdbm" in p for p in packages), (
            "gdbm orphan not found. Found: %s" % packages
        )


# ── Strategy evaluation ─────────────────────────────────────────────────

class TestStrategy:
    def test_strategy_exists(self):
        assert os.path.exists(STRATEGY_PATH), (
            "strategy.json not found at /app/strategy.json"
        )

    def test_strategy_valid_json(self):
        strategy = load_strategy()
        assert "recommended_strategy" in strategy
        assert "minimum_repair_set" in strategy
        assert "independent_repair_groups" in strategy

    def test_recommended_targeted(self):
        strategy = load_strategy()
        assert strategy["recommended_strategy"] == "targeted", (
            "Expected 'targeted' strategy, got '%s'" % strategy["recommended_strategy"]
        )

    def test_minimum_repair_set_includes_partial_upgrades(self):
        strategy = load_strategy()
        repair_set = set(strategy.get("minimum_repair_set", []))
        for pkg in ["openssl", "ncurses", "icu"]:
            assert pkg in repair_set, (
                "%s missing from minimum_repair_set: %s" % (pkg, sorted(repair_set))
            )

    def test_minimum_repair_set_includes_libgcrypt(self):
        """libgcrypt must be installed to satisfy libssh2's dependency."""
        strategy = load_strategy()
        repair_set = set(strategy.get("minimum_repair_set", []))
        assert "libgcrypt" in repair_set, (
            "libgcrypt missing from minimum_repair_set: %s" % sorted(repair_set)
        )

    def test_independent_groups_count(self):
        strategy = load_strategy()
        groups = strategy.get("independent_repair_groups", [])
        assert len(groups) >= 3, (
            "Expected at least 3 independent repair groups, got %d" % len(groups)
        )

    def test_groups_partition_repair_set(self):
        """Every package in minimum_repair_set must appear in exactly one group."""
        strategy = load_strategy()
        groups = strategy.get("independent_repair_groups", [])
        repair_set = set(strategy.get("minimum_repair_set", []))

        all_in_groups = set()
        for group in groups:
            pkgs = group if isinstance(group, list) else group.get("packages", [])
            for pkg in pkgs:
                assert pkg not in all_in_groups, (
                    "%s appears in multiple groups" % pkg
                )
                all_in_groups.add(pkg)

        for pkg in repair_set:
            assert pkg in all_in_groups, (
                "%s from minimum_repair_set not found in any group" % pkg
            )

    def test_no_circular_dependencies(self):
        strategy = load_strategy()
        assert strategy.get("has_circular_dependencies") is False, (
            "Expected no circular dependencies in repair graph"
        )

    def test_rationale_present(self):
        strategy = load_strategy()
        rationale = strategy.get("recommendation_rationale", "")
        assert len(rationale) > 20, (
            "Recommendation rationale too short or missing"
        )


# ── Repair script ────────────────────────────────────────────────────────

class TestRepairScript:
    def test_repair_script_exists(self):
        assert os.path.exists(REPAIR_PATH), "repair.sh not found at /app/repair.sh"

    def _non_comment_lines(self):
        with open(REPAIR_PATH) as f:
            content = f.read()
        lines = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                lines.append(stripped)
        return lines

    def _first_mention(self, lines, keyword):
        """Return index of first line mentioning keyword, or -1."""
        for i, line in enumerate(lines):
            if re.search(r'\b' + re.escape(keyword) + r'\b', line):
                return i
        return -1

    def test_openssl_before_curl(self):
        lines = self._non_comment_lines()
        os_pos = self._first_mention(lines, "openssl")
        curl_pos = self._first_mention(lines, "curl")
        if os_pos >= 0 and curl_pos >= 0:
            assert os_pos <= curl_pos, (
                "openssl (line %d) must appear before or with "
                "curl (line %d) in repair.sh" % (os_pos, curl_pos)
            )

    def test_ncurses_before_bash(self):
        lines = self._non_comment_lines()
        nc_pos = self._first_mention(lines, "ncurses")
        bash_pos = self._first_mention(lines, "bash")
        if nc_pos >= 0 and bash_pos >= 0:
            assert nc_pos <= bash_pos, (
                "ncurses (line %d) must appear before or with "
                "bash (line %d) in repair.sh" % (nc_pos, bash_pos)
            )

    def test_libgcrypt_before_libssh2(self):
        lines = self._non_comment_lines()
        gc_pos = self._first_mention(lines, "libgcrypt")
        ssh_pos = self._first_mention(lines, "libssh2")
        if gc_pos >= 0 and ssh_pos >= 0:
            assert gc_pos <= ssh_pos, (
                "libgcrypt (line %d) must appear before or with "
                "libssh2 (line %d) in repair.sh" % (gc_pos, ssh_pos)
            )

    def test_icu_before_libxml2(self):
        lines = self._non_comment_lines()
        icu_pos = self._first_mention(lines, "icu")
        xml_pos = self._first_mention(lines, "libxml2")
        if icu_pos >= 0 and xml_pos >= 0:
            assert icu_pos <= xml_pos, (
                "icu (line %d) must appear before or with "
                "libxml2 (line %d) in repair.sh" % (icu_pos, xml_pos)
            )

    def test_repair_addresses_partial_upgrades(self):
        lines = self._non_comment_lines()
        combined = " ".join(lines).lower()
        assert "openssl" in combined, "repair.sh must address openssl"
        assert "ncurses" in combined, "repair.sh must address ncurses"
        assert "icu" in combined, "repair.sh must address icu"

    def test_repair_addresses_missing_dep(self):
        lines = self._non_comment_lines()
        combined = " ".join(lines).lower()
        assert "libgcrypt" in combined, "repair.sh must address libgcrypt"

    def test_repair_addresses_readline(self):
        lines = self._non_comment_lines()
        combined = " ".join(lines).lower()
        assert "readline" in combined, "repair.sh must address readline"

    def test_repair_addresses_orphans(self):
        lines = self._non_comment_lines()
        combined = " ".join(lines).lower()
        assert "mpdecimal" in combined or "orphan" in combined, (
            "repair.sh must address orphaned packages"
        )


# ── False-positive ceiling ───────────────────────────────────────────────

class TestPrecision:
    def test_no_excessive_false_positives(self):
        report = load_report()
        total = len(report["issues"])
        # We planted 9 issues; allow tolerance for valid extra findings
        assert total <= 18, (
            "Too many issues (%d). Expected ~9, max 18. "
            "Analyzer may be producing false positives." % total
        )
