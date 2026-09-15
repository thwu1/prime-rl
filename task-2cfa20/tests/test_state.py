"""
WCAG 2.0 / Section 508 Conformance Audit Verification Tests
"""

import json
import os
import pytest

REPORT_PATH = "/app/audit_report.json"

EXPECTED_VIOLATIONS = [
    ("index.html", "11.A"),
    ("index.html", "12.A"),
    ("index.html", "7.A"),
    ("index.html", "14.B"),
    ("index.html", "13.A"),
    ("index.html", "13.C"),
    ("form.html", "5.C"),
    ("form.html", "11.B"),
    ("form.html", "6.A"),
    ("form.html", "13.B"),
    ("report.html", "10.B"),
    ("report.html", "14.C"),
    ("report.html", "12.D"),
    ("report.html", "7.B"),
    ("report.html", "15.A"),
]

FALSE_POSITIVES = [
    ("form.html", "11.A"),
    ("form.html", "12.A"),
    ("report.html", "7.A"),
    ("report.html", "14.B"),
]

WCAG_SC_MAP = {
    "11.A": "3.1.1",
    "12.A": "2.4.2",
    "7.A": "1.1.1",
    "7.B": "1.1.1",
    "14.B": "1.3.1",
    "14.C": "1.3.1",
    "13.A": "1.4.1",
    "13.B": "1.3.3",
    "13.C": "1.4.3",
    "5.C": "1.3.1",
    "11.B": "3.1.2",
    "6.A": "2.4.4",
    "10.B": "1.3.1",
    "12.D": "4.1.2",
    "15.A": "1.3.1",
}


@pytest.fixture(scope="session")
def report_data():
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="session")
def violations(report_data):
    assert "violations" in report_data, "Report missing 'violations' key"
    assert isinstance(report_data["violations"], list), "'violations' must be a list"
    return report_data["violations"]


@pytest.fixture(scope="session")
def violation_pairs(violations):
    return {(v["file"], v["test_id"]) for v in violations}


class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH)

    def test_valid_json(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        assert "violations" in data

    def test_violation_entries_have_required_fields(self, violations):
        required_keys = {"file", "test_id", "wcag_sc", "element", "description"}
        for v in violations:
            missing = required_keys - set(v.keys())
            assert not missing, f"Violation missing keys {missing}: {v}"


class TestExpectedViolations:
    @pytest.mark.parametrize("file,test_id", EXPECTED_VIOLATIONS)
    def test_violation_detected(self, file, test_id, violation_pairs):
        assert (file, test_id) in violation_pairs, \
            f"Expected violation not found: {file} / Test {test_id}"


class TestFalsePositives:
    @pytest.mark.parametrize("file,test_id", FALSE_POSITIVES)
    def test_no_false_positive(self, file, test_id, violation_pairs):
        assert (file, test_id) not in violation_pairs, \
            f"False positive detected: {file} / Test {test_id} should not be flagged"


class TestWCAGMapping:
    @pytest.mark.parametrize("file,test_id", EXPECTED_VIOLATIONS)
    def test_wcag_sc_correct(self, file, test_id, violations):
        matching = [v for v in violations
                    if v["file"] == file and v["test_id"] == test_id]
        if not matching:
            pytest.skip(f"Violation ({file}, {test_id}) not found")
        expected_sc = WCAG_SC_MAP[test_id]
        actual_sc = matching[0].get("wcag_sc", "")
        assert expected_sc in actual_sc, \
            f"Wrong WCAG SC for {file}/{test_id}: expected '{expected_sc}', got '{actual_sc}'"
