
import os
import pytest
import xml.etree.ElementTree as ET

REPORT_NS = "http://hl7.org/fhirpath/tests/report"

# Expected computed values for each test by name
EXPECTED = {
    # Add group (CqlDateTimeArithmeticTest.xml)
    "DateTimeAdd5Years": "@2010-10-10T",
    "DateTimeAddMonthsOverflow": "@2006-03-10T",
    "DateTimeAddDaysOverflow": "@2016-07-01T",
    "DateTimeAddHoursOverflow": "@2016-06-11T00",
    "DateTimeAddMinutesOverflow": "@2016-06-10T06:00",
    "DateTimeAddSecondsOverflow": "@2016-06-10T05:06:00",
    "DateTimeAdd5Milliseconds": "@2005-05-10T05:05:05.010",
    "DateTimeAddMillisecondsOverflow": "@2016-06-10T05:05:06.000",
    "DateTimeAddLeapYear": "@2013-02-28T",
    "DateTimeAdd2YearsByMonths": "@2016T",
    "DateTimeAdd2YearsByDaysRem5": "@2016T",
    "DateTimeAddHoursPreservedSec": "@2005-05-10T10:20:30",
    "DateTimeAddWeeksEquality": "true",
    "DateTimeAddSubPrecPreserved": "true",
    "DateTimeAddSubPrecOverflow": "true",
    "DateAdd1Year": "@2015-06",
    "DateAdd33Days": "@2014-07",
    # DurationBetween group
    "DurationYears": "4",
    "DurationMonths": "0",
    "DurationDays": "-788",
    "DurationWeeks1": "1",
    "DurationWeeks2": "2",
    "DurationHoursTime": "2",
    "DurationMinutesTime": "4",
    "DurationSecondsTime": "4",
    "DurationMillisecondsTime": "5",
    "DurationHoursTimezone": "1",
    "DurationMinutesTimezone": "45",
    "DurationDaysTimezone": "0",
    # DifferenceIn group
    "DiffYears": "5",
    "DiffMonths": "8",
    "DiffDays": "10",
    "DiffHours": "8",
    "DiffWeeks1": "1",
    "DiffWeeks2": "2",
    "DiffYearsNegative": "-18",
    "DiffMillisecondsTz": "3600400",
    "DiffDaysTz": "1",
    "DiffHoursTz": "1",
    "DiffMinutesTz": "45",
    # SameAs group (CqlDateTimePrecisionTest.xml)
    "SameYearTrue": "true",
    "SameYearFalse": "false",
    "SameDayTrue": "true",
    "SameDayFalse": "false",
    "SameDayInsufficientPrec": "null",
    "SameHourTzTrue": "true",
    "SameHourTzFalse": "false",
    # AfterBefore group
    "AfterYearTrue": "true",
    "AfterYearFalse": "false",
    "AfterDayUncertain": "true",
    "BeforeHourTz": "true",
    # UncertaintyIntervals group
    "UncertaintyYears": "Interval[ 4, 5 ]",
    "UncertaintyDays": "Interval[ 17, 44 ]",
    "UncertaintyMonths": "Interval[ 4, 16 ]",
    # UncertainComparison group
    "UncertainCompGt5True": "true",
    "UncertainCompGt5Null": "null",
    "UncertainCompGt25False": "false",
    "UncertainCompLt24True": "true",
    "UncertainCompEq24False": "false",
    # TimeOperations group
    "TimeAdd5Hours": "@T20:59:59.999",
    "TimeAdd1Minute": "@T16:00:59.999",
    "TimeAdd1Millisecond": "@T16:00:00.000",
    "TimeDurationHours": "1",
    "TimeDiffHours": "3",
    "TimeDiffMilliseconds": "-5",
    # Blind group (no expected output in XML)
    "BlindSubtractLeapYear": "@2011-02-28T",
    "BlindMonthsBetween": "14",
    "BlindSameDayTz": "true",
    "BlindTimeWrap": "@T01:00",
}

SKIPPED_TESTS = {"DateTimeAddInvalidYears", "DateTimeInvalidConstruct"}


class TestConformanceReport:
    """Verify CQL conformance test runner output against HL7 reference values."""

    @pytest.fixture(autouse=True, scope="class")
    def load_report(self, request):
        report_path = "/app/report.xml"
        assert os.path.exists(report_path), (
            f"Report file not found at {report_path}. "
            "Run 'bash /app/cql_runner.sh' first."
        )
        tree = ET.parse(report_path)
        root = tree.getroot()
        request.cls.root = root

        # Build results dict by test name
        results = {}
        ns = REPORT_NS
        for suite in root.findall(f"{{{ns}}}suite"):
            for tr in suite.findall(f"{{{ns}}}test-result"):
                name = tr.get("name")
                status = tr.get("status")
                computed_el = tr.find(f"{{{ns}}}computed")
                expected_el = tr.find(f"{{{ns}}}expected")
                computed = (computed_el.text or "") if computed_el is not None else ""
                expected = (expected_el.text or "") if expected_el is not None else ""
                group = tr.get("group", "")
                results[name] = {
                    "status": status,
                    "computed": computed,
                    "expected": expected,
                    "group": group,
                }
        request.cls.results = results

    def test_input_validation_log_exists(self):
        """Input XML validation log must exist."""
        assert os.path.exists("/app/input_validation.log"), "input_validation.log not found"

    def test_input_validation_passed(self):
        """All input XML files must validate against testSchema.xsd."""
        content = open("/app/input_validation.log").read()
        assert "validates" in content, (
            f"Input validation log does not indicate success. Content:\n{content[:500]}"
        )

    def test_output_validation_log_exists(self):
        """Output XML validation log must exist."""
        assert os.path.exists("/app/output_validation.log"), "output_validation.log not found"

    def test_output_validation_passed(self):
        """report.xml must validate against reportSchema.xsd."""
        content = open("/app/output_validation.log").read()
        assert "validates" in content, (
            f"Output validation log does not indicate success. Content:\n{content[:500]}"
        )

    def test_report_has_generated_attr(self):
        """conformance-report root must have a 'generated' attribute."""
        assert self.root.get("generated") is not None, "Missing 'generated' attribute on root"

    def test_report_has_two_suites(self):
        """Report must contain exactly two suite elements."""
        ns = REPORT_NS
        suites = self.root.findall(f"{{{ns}}}suite")
        assert len(suites) == 2, f"Expected 2 suites, found {len(suites)}"

    def test_suite_sources(self):
        """Each suite must have a valid source attribute matching input files."""
        ns = REPORT_NS
        expected_sources = {"CqlDateTimeArithmeticTest.xml", "CqlDateTimePrecisionTest.xml"}
        actual_sources = {s.get("source") for s in self.root.findall(f"{{{ns}}}suite")}
        assert actual_sources == expected_sources, (
            f"Suite sources: expected {expected_sources}, got {actual_sources}"
        )

    def test_all_expected_tests_present(self):
        """All 69 expected test results must be present in the report."""
        missing = set(EXPECTED.keys()) - set(self.results.keys())
        assert not missing, f"Missing results for tests: {sorted(missing)}"

    @pytest.mark.parametrize("test_name", sorted(EXPECTED.keys()))
    def test_expression_result(self, test_name):
        """Each expression must produce the correct computed value."""
        assert test_name in self.results, f"Test '{test_name}' not found in report"
        result = self.results[test_name]
        assert result["status"] == "pass", (
            f"Test '{test_name}': status is '{result['status']}', expected 'pass'"
        )
        assert result["computed"] == EXPECTED[test_name], (
            f"Test '{test_name}': expected '{EXPECTED[test_name]}', got '{result['computed']}'"
        )

    def test_skipped_tests_present(self):
        """Invalid-expression tests must appear with status='skip'."""
        for test_name in SKIPPED_TESTS:
            assert test_name in self.results, f"Skipped test '{test_name}' not in report"
            assert self.results[test_name]["status"] == "skip", (
                f"Test '{test_name}' should be skipped, got '{self.results[test_name]['status']}'"
            )

    def test_summary_total(self):
        """Summary @total must match total number of tests."""
        ns = REPORT_NS
        summary = self.root.find(f"{{{ns}}}summary")
        assert summary is not None, "Summary element not found"
        total = int(summary.get("total"))
        expected_total = len(EXPECTED) + len(SKIPPED_TESTS)
        assert total == expected_total, (
            f"Summary total: expected {expected_total}, got {total}"
        )

    def test_summary_passed(self):
        """Summary @passed must equal number of passing tests."""
        ns = REPORT_NS
        summary = self.root.find(f"{{{ns}}}summary")
        assert summary is not None, "Summary element not found"
        passed = int(summary.get("passed"))
        assert passed == len(EXPECTED), (
            f"Summary passed: expected {len(EXPECTED)}, got {passed}"
        )

    def test_summary_skipped(self):
        """Summary @skipped must equal number of skipped tests."""
        ns = REPORT_NS
        summary = self.root.find(f"{{{ns}}}summary")
        assert summary is not None, "Summary element not found"
        skipped = int(summary.get("skipped"))
        assert skipped == len(SKIPPED_TESTS), (
            f"Summary skipped: expected {len(SKIPPED_TESTS)}, got {skipped}"
        )

    def test_no_error_results(self):
        """No tests should have error status."""
        errors = {name: r for name, r in self.results.items() if r["status"] == "error"}
        assert not errors, f"Tests with error status: {list(errors.keys())}"
