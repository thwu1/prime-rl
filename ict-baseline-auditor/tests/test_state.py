
"""
Verification tests for the ICT Testing Baseline v3.1 Conformance Auditor.

Tests verify that /app/report.json contains correct FAIL findings for
known accessibility violations and no false positives for compliant elements.
"""

import json
import re
import os
import pytest

REPORT_PATH = "/app/report.json"


@pytest.fixture(scope="session")
def report():
    assert os.path.exists(REPORT_PATH), f"Report file not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict), "Report must be a JSON object"
    return data


def get_findings(report, page):
    """Get the findings list for a specific page."""
    pages = report.get("pages", {})
    return pages.get(page, {}).get("findings", [])


def has_fail_finding(findings, element_id, baseline_prefix=None):
    """Check if there is a FAIL finding for the given element_id."""
    for f in findings:
        if f.get("element_id") == element_id and f.get("result") == "FAIL":
            if baseline_prefix is None:
                return True
            if f.get("baseline_test_id", "").startswith(baseline_prefix):
                return True
    return False


def has_any_fail(findings, element_id):
    """Check if any FAIL finding exists for the given element_id."""
    return any(
        f.get("element_id") == element_id and f.get("result") == "FAIL"
        for f in findings
    )


# =====================================================================
# Report Structure and Format
# =====================================================================


class TestReportStructure:
    """Validate the overall report structure and format."""

    def test_report_has_required_keys(self, report):
        assert "pages" in report, "Report must contain 'pages' key"
        assert "baseline_version" in report, "Report must contain 'baseline_version'"
        assert report["baseline_version"] == "3.1", \
            f"baseline_version must be '3.1', got '{report['baseline_version']}'"

    def test_all_pages_audited(self, report):
        pages = set(report.get("pages", {}).keys())
        expected = {
            "page_images.html",
            "page_forms.html",
            "page_tables.html",
            "page_structure.html",
        }
        assert expected.issubset(pages), \
            f"Missing pages in report: {expected - pages}"

    def test_findings_have_required_fields(self, report):
        required = {"element_id", "baseline_test_id", "result", "wcag_sc"}
        for page, data in report.get("pages", {}).items():
            for finding in data.get("findings", []):
                missing = required - set(finding.keys())
                assert not missing, \
                    f"Finding in {page} missing fields: {missing}. Finding: {finding}"

    def test_all_results_are_fail(self, report):
        """Report should contain only FAIL findings (passing elements omitted)."""
        for page, data in report.get("pages", {}).items():
            for finding in data.get("findings", []):
                assert finding["result"] == "FAIL", \
                    f"Non-FAIL result in {page}: {finding}"

    def test_wcag_sc_format_valid(self, report):
        for page, data in report.get("pages", {}).items():
            for finding in data.get("findings", []):
                sc = finding.get("wcag_sc", "")
                assert re.match(r'^\d+\.\d+\.\d+$', sc), \
                    f"Invalid WCAG SC format '{sc}' in {page}"

    def test_baseline_test_ids_valid(self, report):
        valid_ids = {"6.A", "6.B", "10.A", "11.A", "12.A", "12.B", "13.A", "15.A"}
        for page, data in report.get("pages", {}).items():
            for finding in data.get("findings", []):
                tid = finding.get("baseline_test_id", "")
                assert tid in valid_ids, \
                    f"Invalid baseline_test_id '{tid}' in {page}. Valid: {valid_ids}"

    def test_minimum_total_fail_count(self, report):
        """There must be at least 12 FAIL findings across all pages."""
        total = sum(
            len(data.get("findings", []))
            for data in report.get("pages", {}).values()
        )
        assert total >= 12, \
            f"Expected >= 12 FAIL findings across all pages, got {total}"


# =====================================================================
# page_images.html — Baseline 6 (Images)
# =====================================================================


class TestImageFindings:
    """Verify image accessibility findings."""

    PAGE = "page_images.html"

    def test_img1_presentational_role_conflict(self, report):
        """img with role='none' and non-empty alt must FAIL baseline 6
        (presentational role conflict per WAI-ARIA conflict resolution)."""
        findings = get_findings(report, self.PAGE)
        assert has_fail_finding(findings, "img1", "6"), \
            "img1 (role='none' + alt='Acme Corporation Logo') must FAIL Baseline 6"

    def test_img2_decorative_but_focusable(self, report):
        """img with alt='' but tabindex=0 must FAIL baseline 6
        (decorative image should not be keyboard focusable)."""
        findings = get_findings(report, self.PAGE)
        assert has_fail_finding(findings, "img2", "6"), \
            "img2 (alt='' + tabindex=0) must FAIL Baseline 6"

    def test_img3_correct_meaningful_no_fail(self, report):
        """img with proper descriptive alt text must NOT have any FAIL finding."""
        findings = get_findings(report, self.PAGE)
        assert not has_any_fail(findings, "img3"), \
            "img3 (correct meaningful image with descriptive alt) must not FAIL"

    def test_img4_missing_alt_attribute(self, report):
        """img with no alt attribute at all must FAIL baseline 6
        (F65: no text alternative technique used)."""
        findings = get_findings(report, self.PAGE)
        assert has_fail_finding(findings, "img4", "6"), \
            "img4 (no alt attribute) must FAIL Baseline 6"

    def test_img5_role_img_no_accessible_name(self, report):
        """div[role=img] with no accessible name must FAIL baseline 6."""
        findings = get_findings(report, self.PAGE)
        assert has_fail_finding(findings, "img5", "6"), \
            "img5 (role='img' with no accessible name) must FAIL Baseline 6"

    def test_img6_correct_decorative_no_fail(self, report):
        """img with alt='' and role='presentation' must NOT have any FAIL."""
        findings = get_findings(report, self.PAGE)
        assert not has_any_fail(findings, "img6"), \
            "img6 (correct decorative: alt='' + role=presentation) must not FAIL"

    def test_img7_aria_labelledby_no_fail(self, report):
        """img with valid aria-labelledby providing accessible name must NOT FAIL."""
        findings = get_findings(report, self.PAGE)
        assert not has_any_fail(findings, "img7"), \
            "img7 (valid aria-labelledby) must not FAIL"


# =====================================================================
# page_forms.html — Baseline 10 (Forms)
# =====================================================================


class TestFormFindings:
    """Verify form accessibility findings."""

    PAGE = "page_forms.html"

    def test_f1_no_accessible_name(self, report):
        """Input with no label, aria-label, aria-labelledby, or title must FAIL 10.A."""
        findings = get_findings(report, self.PAGE)
        assert has_fail_finding(findings, "f1", "10"), \
            "f1 (no accessible name) must FAIL Baseline 10.A"

    def test_f2_invalid_aria_labelledby(self, report):
        """Input with aria-labelledby referencing nonexistent element must FAIL 10.A."""
        findings = get_findings(report, self.PAGE)
        assert has_fail_finding(findings, "f2", "10"), \
            "f2 (aria-labelledby references nonexistent ID) must FAIL Baseline 10.A"

    def test_f3_title_provides_name_no_fail(self, report):
        """Input with title='Phone Number' must NOT FAIL
        (title provides accessible name)."""
        findings = get_findings(report, self.PAGE)
        assert not has_any_fail(findings, "f3"), \
            "f3 (title attribute providing accessible name) must not FAIL"

    def test_f4_label_for_no_fail(self, report):
        """Input with proper <label for=...> association must NOT FAIL."""
        findings = get_findings(report, self.PAGE)
        assert not has_any_fail(findings, "f4"), \
            "f4 (proper label-for association) must not FAIL"

    def test_f5_empty_aria_label(self, report):
        """Input with aria-label='' (empty string) must FAIL 10.A."""
        findings = get_findings(report, self.PAGE)
        assert has_fail_finding(findings, "f5", "10"), \
            "f5 (empty aria-label) must FAIL Baseline 10.A"

    def test_f6_partial_aria_labelledby_no_fail(self, report):
        """Input with aria-labelledby where one ref is valid and one is invalid
        must NOT FAIL (the resolved name 'First' is non-empty)."""
        findings = get_findings(report, self.PAGE)
        assert not has_any_fail(findings, "f6"), \
            "f6 (partial aria-labelledby resolving to non-empty name) must not FAIL"

    def test_f7_empty_button(self, report):
        """Button with no text content and no label must FAIL 10.A."""
        findings = get_findings(report, self.PAGE)
        assert has_fail_finding(findings, "f7", "10"), \
            "f7 (empty button, no accessible name) must FAIL Baseline 10.A"


# =====================================================================
# page_tables.html — Baseline 12 (Tables)
# =====================================================================


class TestTableFindings:
    """Verify table accessibility findings."""

    PAGE = "page_tables.html"

    def test_t1_correct_data_table_no_fail(self, report):
        """Properly structured data table with scope-based headers must NOT FAIL."""
        findings = get_findings(report, self.PAGE)
        assert not has_any_fail(findings, "t1"), \
            "t1 (correct data table with scope headers) must not FAIL"

    def test_t2_invalid_headers_reference(self, report):
        """Table cell whose headers attribute references a nonexistent ID
        must produce a FAIL for Baseline 12."""
        findings = get_findings(report, self.PAGE)
        t2_fail = any(
            f.get("result") == "FAIL"
            and f.get("baseline_test_id", "").startswith("12")
            for f in findings
            if f.get("element_id", "").startswith("t2")
        )
        assert t2_fail, \
            "t2 (headers referencing nonexistent 't2_h3_missing') must FAIL Baseline 12"

    def test_t3_aria_table_missing_cell_roles(self, report):
        """ARIA table (role=table) with data cells missing role=cell must FAIL 12.A."""
        findings = get_findings(report, self.PAGE)
        assert has_fail_finding(findings, "t3", "12"), \
            "t3 (ARIA table with cells missing role='cell') must FAIL Baseline 12"


# =====================================================================
# page_structure.html — Baselines 11, 13, 15
# =====================================================================


class TestStructureFindings:
    """Verify structure, language, and page title findings."""

    PAGE = "page_structure.html"

    def test_missing_lang_attribute(self, report):
        """html element without lang attribute must produce a FAIL for 15.A."""
        findings = get_findings(report, self.PAGE)
        lang_fail = any(
            f.get("result") == "FAIL"
            and f.get("baseline_test_id") == "15.A"
            for f in findings
        )
        assert lang_fail, \
            "Missing lang attribute on <html> must FAIL Baseline 15.A"

    def test_empty_page_title(self, report):
        """Empty <title></title> must produce a FAIL for 11.A."""
        findings = get_findings(report, self.PAGE)
        title_fail = any(
            f.get("result") == "FAIL"
            and f.get("baseline_test_id") == "11.A"
            for f in findings
        )
        assert title_fail, \
            "Empty page title must FAIL Baseline 11.A"

    def test_empty_heading_fails(self, report):
        """Empty h2 heading must FAIL 13.A (heading does not describe topic)."""
        findings = get_findings(report, self.PAGE)
        assert has_fail_finding(findings, "h_empty", "13"), \
            "h_empty (empty <h2>) must FAIL Baseline 13.A"

    def test_good_heading_no_fail(self, report):
        """Heading with descriptive content must NOT FAIL."""
        findings = get_findings(report, self.PAGE)
        assert not has_any_fail(findings, "h_good"), \
            "h_good (descriptive heading) must not FAIL"

    def test_valid_heading_no_fail(self, report):
        """Another heading with descriptive content must NOT FAIL."""
        findings = get_findings(report, self.PAGE)
        assert not has_any_fail(findings, "h_valid"), \
            "h_valid (descriptive heading) must not FAIL"
