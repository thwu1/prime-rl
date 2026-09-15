
"""
Tests for performance incident forensics task.

Verifies the agent correctly:
  - Identified the inverted difffolded.pl arguments
  - Classified each code change as bug or intentional
  - Recognized the off-CPU nature of the sync-io bug
  - Evaluated hotfix effectiveness
  - Produced a corrected differential flame graph
  - Found errors in the junior engineer's report
"""

import json
import os
import pytest

REPORT_PATH = "/app/forensic_report.json"
BASELINE_PATH = "/app/profiles/baseline.folded"
INCIDENT_PATH = "/app/profiles/incident.folded"
AFTER_HOTFIX_PATH = "/app/profiles/after_hotfix.folded"


def parse_folded(path):
    """Parse folded stack format into dict of stack -> sample_count."""
    stacks = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                stacks[parts[0]] = int(parts[1])
    return stacks


def leaf_samples(stacks):
    """Sum samples per leaf (last) function in each stack."""
    totals = {}
    for stack, count in stacks.items():
        leaf = stack.split(";")[-1]
        totals[leaf] = totals.get(leaf, 0) + count
    return totals


@pytest.fixture(scope="session")
def baseline():
    return parse_folded(BASELINE_PATH)


@pytest.fixture(scope="session")
def incident():
    return parse_folded(INCIDENT_PATH)


@pytest.fixture(scope="session")
def after_hotfix():
    return parse_folded(AFTER_HOTFIX_PATH)


@pytest.fixture(scope="session")
def report():
    with open(REPORT_PATH) as f:
        return json.load(f)


def find_issue(report, func_name):
    """Find an issue entry by function name."""
    for item in report.get("issues", []):
        if item.get("function") == func_name:
            return item
    return None


def get_expected_leaf_samples(stacks, func_name):
    """Get expected sample count for a leaf function from parsed stacks."""
    total = 0
    for stack, count in stacks.items():
        if stack.split(";")[-1] == func_name:
            total += count
    return total


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_file_exists(self):
        assert os.path.exists(REPORT_PATH), \
            f"Expected forensic report at {REPORT_PATH}"

    def test_valid_json(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_required_top_level_keys(self, report):
        required = ["flamegraph_correction", "issues",
                     "engineer_report_errors", "hotfix_evaluation",
                     "remediation_priority"]
        for key in required:
            assert key in report, f"Missing required key: {key}"

    def test_at_least_four_issues(self, report):
        assert len(report["issues"]) >= 4, \
            "Must identify at least 4 significant code changes"


# ---------------------------------------------------------------------------
# Flamegraph correction tests
# ---------------------------------------------------------------------------

class TestFlamegraphCorrection:
    """Verify agent discovered the inverted difffolded.pl arguments."""

    def test_identifies_argument_swap(self, report):
        desc = report["flamegraph_correction"]["error_description"].lower()
        swap_indicators = [
            "swap", "invert", "reverse", "wrong order", "backward",
            "reversed", "flipped", "incorrect order", "opposite"
        ]
        assert any(w in desc for w in swap_indicators), \
            "Must identify that difffolded.pl arguments were swapped/inverted"

    def test_corrected_svg_exists(self, report):
        path = report["flamegraph_correction"]["corrected_diff_path"]
        assert os.path.exists(path), \
            f"Corrected SVG not found at {path}"
        assert os.path.getsize(path) > 500, \
            "Corrected SVG file is too small to be valid"

    def test_corrected_svg_is_svg(self, report):
        path = report["flamegraph_correction"]["corrected_diff_path"]
        with open(path) as f:
            header = f.read(500)
        header_lower = header.lower()
        assert "<svg" in header_lower or "<?xml" in header_lower, \
            "Corrected file does not appear to be valid SVG"


# ---------------------------------------------------------------------------
# Issue classification tests
# ---------------------------------------------------------------------------

class TestIssueClassification:
    """Verify correct classification of each code change."""

    def test_copy_to_buffer_is_bug(self, report):
        issue = find_issue(report, "copy_to_buffer")
        assert issue is not None, "Must identify copy_to_buffer"
        assert issue["classification"] == "bug"
        assert issue["bug_type"] == "zero-byte-read"

    def test_flush_to_disk_is_bug(self, report):
        issue = find_issue(report, "flush_to_disk")
        assert issue is not None, "Must identify flush_to_disk"
        assert issue["classification"] == "bug"
        assert issue["bug_type"] == "sync-io"

    def test_recompute_hash_is_bug(self, report):
        issue = find_issue(report, "recompute_hash")
        assert issue is not None, "Must identify recompute_hash"
        assert issue["classification"] == "bug"
        assert issue["bug_type"] == "redundant-computation"

    def test_verify_hmac_is_intentional(self, report):
        issue = find_issue(report, "verify_hmac")
        assert issue is not None, "Must identify verify_hmac"
        assert issue["classification"] == "intentional", \
            f"verify_hmac is an intentional SHA256 upgrade, got {issue['classification']}"

    def test_copy_to_buffer_source_file(self, report):
        issue = find_issue(report, "copy_to_buffer")
        assert issue is not None
        assert issue["source_file"] == "data_loader.c"

    def test_flush_to_disk_source_file(self, report):
        issue = find_issue(report, "flush_to_disk")
        assert issue is not None
        assert issue["source_file"] == "logger.c"

    def test_recompute_hash_source_file(self, report):
        issue = find_issue(report, "recompute_hash")
        assert issue is not None
        assert issue["source_file"] == "validator.c"


# ---------------------------------------------------------------------------
# Off-CPU analysis tests (key expert insight)
# ---------------------------------------------------------------------------

class TestOffCPUAnalysis:
    """Verify the critical expert insight: flush_to_disk is hidden in CPU profiles."""

    def test_flush_to_disk_hidden_in_cpu_profile(self, report):
        """The sync-io bug causes off-CPU blocking, invisible to CPU sampling."""
        issue = find_issue(report, "flush_to_disk")
        assert issue is not None
        vis = issue.get("cpu_profile_visibility", "").lower()
        assert vis == "hidden", \
            f"flush_to_disk should be 'hidden' in CPU profiles (off-CPU issue), got '{vis}'"

    def test_flush_to_disk_samples_decreased(self, report, baseline, incident):
        """Expert insight: sync-io causes FEWER CPU samples, not more."""
        issue = find_issue(report, "flush_to_disk")
        assert issue is not None
        baseline_expected = get_expected_leaf_samples(baseline, "flush_to_disk")
        incident_expected = get_expected_leaf_samples(incident, "flush_to_disk")
        assert issue["incident_cpu_samples"] < issue["baseline_cpu_samples"], \
            "flush_to_disk CPU samples should DECREASE (it went off-CPU)"
        assert incident_expected < baseline_expected, \
            "Profile data confirms flush_to_disk decreased from baseline to incident"

    def test_copy_to_buffer_visible(self, report):
        issue = find_issue(report, "copy_to_buffer")
        assert issue is not None
        vis = issue.get("cpu_profile_visibility", "").lower()
        assert vis == "visible", \
            "copy_to_buffer's CPU spin should be visible in CPU profiles"

    def test_recompute_hash_visible(self, report):
        issue = find_issue(report, "recompute_hash")
        assert issue is not None
        vis = issue.get("cpu_profile_visibility", "").lower()
        assert vis == "visible", \
            "recompute_hash's redundant computation should be visible in CPU profiles"


# ---------------------------------------------------------------------------
# Sample count accuracy
# ---------------------------------------------------------------------------

class TestSampleAccuracy:
    """Verify reported sample counts match actual profile data."""

    def test_copy_to_buffer_baseline(self, report, baseline):
        issue = find_issue(report, "copy_to_buffer")
        assert issue is not None
        expected = get_expected_leaf_samples(baseline, "copy_to_buffer")
        assert issue["baseline_cpu_samples"] == expected, \
            f"copy_to_buffer baseline should be {expected}"

    def test_copy_to_buffer_incident(self, report, incident):
        issue = find_issue(report, "copy_to_buffer")
        assert issue is not None
        expected = get_expected_leaf_samples(incident, "copy_to_buffer")
        assert issue["incident_cpu_samples"] == expected, \
            f"copy_to_buffer incident should be {expected}"

    def test_flush_to_disk_baseline(self, report, baseline):
        issue = find_issue(report, "flush_to_disk")
        assert issue is not None
        expected = get_expected_leaf_samples(baseline, "flush_to_disk")
        assert issue["baseline_cpu_samples"] == expected, \
            f"flush_to_disk baseline should be {expected}"

    def test_flush_to_disk_incident(self, report, incident):
        issue = find_issue(report, "flush_to_disk")
        assert issue is not None
        expected = get_expected_leaf_samples(incident, "flush_to_disk")
        assert issue["incident_cpu_samples"] == expected, \
            f"flush_to_disk incident should be {expected}"

    def test_recompute_hash_baseline(self, report, baseline):
        issue = find_issue(report, "recompute_hash")
        assert issue is not None
        expected = get_expected_leaf_samples(baseline, "recompute_hash")
        assert issue["baseline_cpu_samples"] == expected, \
            f"recompute_hash baseline should be {expected} (not in baseline)"

    def test_recompute_hash_incident(self, report, incident):
        issue = find_issue(report, "recompute_hash")
        assert issue is not None
        expected = get_expected_leaf_samples(incident, "recompute_hash")
        assert issue["incident_cpu_samples"] == expected, \
            f"recompute_hash incident should be {expected}"

    def test_verify_hmac_baseline(self, report, baseline):
        issue = find_issue(report, "verify_hmac")
        assert issue is not None
        expected = get_expected_leaf_samples(baseline, "verify_hmac")
        assert issue["baseline_cpu_samples"] == expected, \
            f"verify_hmac baseline should be {expected}"

    def test_verify_hmac_incident(self, report, incident):
        issue = find_issue(report, "verify_hmac")
        assert issue is not None
        expected = get_expected_leaf_samples(incident, "verify_hmac")
        assert issue["incident_cpu_samples"] == expected, \
            f"verify_hmac incident should be {expected}"


# ---------------------------------------------------------------------------
# Engineer report error identification
# ---------------------------------------------------------------------------

class TestEngineerReportErrors:
    """Verify agent found errors in the junior engineer's report."""

    def test_at_least_three_errors(self, report):
        errors = report.get("engineer_report_errors", [])
        assert len(errors) >= 3, \
            f"Must identify at least 3 errors in engineer's report, found {len(errors)}"

    def test_identifies_flush_disk_error(self, report):
        """Must identify that flush_to_disk was misdiagnosed."""
        errors = report.get("engineer_report_errors", [])
        all_text = " ".join(
            str(e.get("error_description", "")).lower()
            for e in errors
        )
        assert any(term in all_text for term in [
            "flush", "off-cpu", "offcpu", "dsync", "sync",
            "block", "hidden", "invisible"
        ]), "Must identify the flush_to_disk / off-CPU misdiagnosis"

    def test_identifies_inversion_error(self, report):
        """Must identify that the differential analysis was inverted."""
        errors = report.get("engineer_report_errors", [])
        all_text = " ".join(
            str(e.get("error_description", "")).lower()
            for e in errors
        )
        correction_desc = report.get("flamegraph_correction", {}).get(
            "error_description", ""
        ).lower()
        combined = all_text + " " + correction_desc
        assert any(term in combined for term in [
            "swap", "invert", "reverse", "wrong order", "backward",
            "flipped", "opposite"
        ]), "Must identify the difffolded.pl argument inversion"


# ---------------------------------------------------------------------------
# Hotfix evaluation
# ---------------------------------------------------------------------------

class TestHotfixEvaluation:
    """Verify correct assessment of hotfix effectiveness."""

    def test_hotfix_a_effective(self, report):
        hf_a = report["hotfix_evaluation"]["hotfix_a"]
        assert hf_a["effective"] is True, \
            "Hotfix A correctly fixes the zero-byte read and should be effective"

    def test_hotfix_b_ineffective(self, report):
        hf_b = report["hotfix_evaluation"]["hotfix_b"]
        assert hf_b["effective"] is False, \
            "Hotfix B modifies the wrong file and should be ineffective"

    def test_hotfix_b_explains_wrong_target(self, report):
        hf_b = report["hotfix_evaluation"]["hotfix_b"]
        explanation = hf_b.get("explanation", "").lower()
        assert any(term in explanation for term in [
            "wrong file", "data_loader", "logger",
            "wrong function", "wrong target", "no-op",
            "nonblock", "misapplied", "incorrect"
        ]), "Must explain why hotfix B is ineffective (wrong file/target)"


# ---------------------------------------------------------------------------
# Remediation priority
# ---------------------------------------------------------------------------

class TestRemediationPriority:
    """Verify the remediation ordering reflects expert judgment."""

    def test_contains_flush_to_disk(self, report):
        priority = report.get("remediation_priority", [])
        assert "flush_to_disk" in priority, \
            "flush_to_disk must be in remediation priority (still unfixed)"

    def test_contains_recompute_hash(self, report):
        priority = report.get("remediation_priority", [])
        assert "recompute_hash" in priority, \
            "recompute_hash must be in remediation priority (still unfixed)"

    def test_flush_before_recompute(self, report):
        priority = report.get("remediation_priority", [])
        idx_flush = priority.index("flush_to_disk")
        idx_recomp = priority.index("recompute_hash")
        assert idx_flush < idx_recomp, \
            "flush_to_disk (hidden off-CPU bottleneck) should be prioritized " \
            "over recompute_hash (visible CPU waste)"

    def test_verify_hmac_not_in_priority(self, report):
        priority = report.get("remediation_priority", [])
        assert "verify_hmac" not in priority, \
            "verify_hmac is intentional and should NOT be in remediation list"
