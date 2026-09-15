"""
Tests for NAAQS compliance audit: corrected report and error analysis.

"""
import json
import os
import pytest

REPORT_PATH = "/app/output/compliance_report.json"
ERRORS_PATH = "/app/output/error_analysis.json"

# Expected correct results: (site_id, param_code, pollutant_standard, design_value, naaqs_level, status)
EXPECTED = [
    ("04-013-3002", 44201, "Ozone 8-hour 2015",     0.070,  0.070, "Meeting"),
    ("04-013-3002", 81102, "PM10 24-hour 2006",      1.0,    1.0,   "Meeting"),
    ("06-025-0005", 81102, "PM10 24-hour 2006",      3.0,    1.0,   "Exceeding"),
    ("06-037-1103", 88101, "PM25 24-hour 2006",      37.0,   35.0,  "Exceeding"),
    ("06-037-1103", 88101, "PM25 Annual 2024",       9.8,    9.0,   "Exceeding"),
    ("06-071-0306", 44201, "Ozone 8-hour 2015",      0.078,  0.070, "Exceeding"),
    ("29-099-0019", 42401, "SO2 1-hour 2010",        75.0,   75.0,  "Meeting"),
    ("36-061-0056", 88101, "PM25 24-hour 2006",      None,   35.0,  "Insufficient Data"),
    ("36-061-0056", 88101, "PM25 Annual 2024",       None,   9.0,   "Insufficient Data"),
    ("39-035-0060", 88101, "PM25 24-hour 2006",      36.0,   35.0,  "Exceeding"),
    ("39-035-0060", 88101, "PM25 Annual 2024",       8.7,    9.0,   "Meeting"),
    ("42-003-0008", 44201, "Ozone 8-hour 2015",      0.068,  0.070, "Meeting"),
    ("42-003-0008", 88101, "PM25 24-hour 2006",      34.0,   35.0,  "Meeting"),
    ("42-003-0008", 88101, "PM25 Annual 2024",       9.0,    9.0,   "Meeting"),
    ("48-201-1039", 42602, "NO2 1-hour 2010",        98.0,   100.0, "Meeting"),
]

# Monitors that have errors in the previous report
KNOWN_ERROR_MONITORS = {
    ("06-071-0306", 44201),   # Error A: O3 truncation vs rounding
    ("06-037-1103", 88101),   # Error B: PM2.5 annual wrong standard
    ("42-003-0008", 88101),   # Error B: PM2.5 annual wrong standard
    ("39-035-0060", 88101),   # Error B: PM2.5 annual wrong standard
    ("36-061-0056", 88101),   # Error B+D: wrong standard + no completeness check
    ("29-099-0019", 42401),   # Error C: SO2 wrong percentile
    ("06-025-0005", 81102),   # Error E: PM10 threshold wrong
    ("04-013-3002", 81102),   # Error E: PM10 naaqs_level wrong
}


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), f"Report file not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    assert "monitors" in data, "Report must have a 'monitors' key"
    return data["monitors"]


@pytest.fixture
def error_analysis():
    assert os.path.exists(ERRORS_PATH), f"Error analysis not found at {ERRORS_PATH}"
    with open(ERRORS_PATH) as f:
        data = json.load(f)
    assert "errors" in data, "Error analysis must have an 'errors' key"
    return data["errors"]


def _find_entry(report, site_id, param_code, pollutant_standard):
    matches = [
        m for m in report
        if m.get("site_id") == site_id
        and m.get("parameter_code") == param_code
        and m.get("pollutant_standard") == pollutant_standard
    ]
    return matches[0] if matches else None


# ═══════════════════════════════════════════════════════════════
# COMPLIANCE REPORT TESTS
# ═══════════════════════════════════════════════════════════════

def test_report_exists():
    assert os.path.exists(REPORT_PATH)
    with open(REPORT_PATH) as f:
        data = json.load(f)
    assert "monitors" in data


def test_report_count(report):
    assert len(report) == len(EXPECTED), (
        f"Expected {len(EXPECTED)} monitor entries, got {len(report)}. "
        f"Ensure non-regulatory monitors (ARM designation) are excluded "
        f"and only current standards are included."
    )


def test_report_sorted(report):
    keys = [
        (m["site_id"], m["parameter_code"], m["pollutant_standard"])
        for m in report
    ]
    assert keys == sorted(keys), "Report must be sorted by site_id, parameter_code, pollutant_standard"


def test_no_old_standards(report):
    old_standards = {"Ozone 8-hour 2008", "PM25 Annual 2012"}
    for m in report:
        assert m["pollutant_standard"] not in old_standards, (
            f"Old standard {m['pollutant_standard']} should not appear in corrected report"
        )


def test_no_poc2(report):
    """POC 2 monitors should not appear in the report."""
    pa_o3 = [m for m in report if m["site_id"] == "42-003-0008" and m["parameter_code"] == 44201]
    assert len(pa_o3) == 1, "Should have exactly one O3 entry for PA (POC 1 only)"


def test_no_arm_monitors(report):
    """ARM-designated monitors must not appear in regulatory compliance report."""
    arm_sites = {"48-113-0069"}
    for m in report:
        assert m["site_id"] not in arm_sites, (
            f"Monitor {m['site_id']} uses ARM method designation and must be "
            f"excluded from regulatory compliance assessment per 40 CFR Part 53"
        )


def test_no_events_excluded_contamination(report):
    """Verify O3 CA design value reflects Events Included data, not Events Excluded."""
    entry = _find_entry(report, "06-071-0306", 44201, "Ozone 8-hour 2015")
    assert entry is not None
    # Events Excluded would give DV=0.075; Events Included gives 0.078
    assert abs(entry["design_value"] - 0.078) < 1e-6, (
        f"O3 CA DV should be 0.078 (from Events Included data), got {entry['design_value']}. "
        f"Events Excluded records must not be used for compliance determination."
    )


class TestOzone:
    def test_o3_az_meeting(self, report):
        entry = _find_entry(report, "04-013-3002", 44201, "Ozone 8-hour 2015")
        assert entry is not None, "Missing O3 entry for 04-013-3002"
        assert entry["status"] == "Meeting"
        assert abs(entry["design_value"] - 0.070) < 1e-6

    def test_o3_ca_exceeding(self, report):
        """Truncation must produce 0.078, not 0.079 (rounded)."""
        entry = _find_entry(report, "06-071-0306", 44201, "Ozone 8-hour 2015")
        assert entry is not None, "Missing O3 entry for 06-071-0306"
        assert entry["status"] == "Exceeding"
        assert abs(entry["design_value"] - 0.078) < 1e-6

    def test_o3_pa_meeting(self, report):
        entry = _find_entry(report, "42-003-0008", 44201, "Ozone 8-hour 2015")
        assert entry is not None, "Missing O3 entry for 42-003-0008"
        assert entry["status"] == "Meeting"
        assert abs(entry["design_value"] - 0.068) < 1e-6


class TestPM25Annual:
    def test_pm25_annual_la_exceeding(self, report):
        entry = _find_entry(report, "06-037-1103", 88101, "PM25 Annual 2024")
        assert entry is not None, "Missing PM2.5 Annual entry for 06-037-1103"
        assert entry["status"] == "Exceeding"
        assert abs(entry["design_value"] - 9.8) < 0.05

    def test_pm25_annual_pa_meeting_edge(self, report):
        """Edge case: DV rounds to exactly 9.0, which equals the standard."""
        entry = _find_entry(report, "42-003-0008", 88101, "PM25 Annual 2024")
        assert entry is not None, "Missing PM2.5 Annual entry for 42-003-0008"
        assert entry["status"] == "Meeting"
        assert abs(entry["design_value"] - 9.0) < 0.05

    def test_pm25_annual_oh_meeting(self, report):
        entry = _find_entry(report, "39-035-0060", 88101, "PM25 Annual 2024")
        assert entry is not None, "Missing PM2.5 Annual entry for 39-035-0060"
        assert entry["status"] == "Meeting"
        assert abs(entry["design_value"] - 8.7) < 0.05


class TestPM25_24hr:
    def test_pm25_24hr_la_exceeding(self, report):
        entry = _find_entry(report, "06-037-1103", 88101, "PM25 24-hour 2006")
        assert entry is not None
        assert entry["status"] == "Exceeding"
        assert abs(entry["design_value"] - 37.0) < 0.5

    def test_pm25_24hr_oh_exceeding_rounding(self, report):
        """Rounding edge case: 35.5 rounds up to 36 (half-up convention)."""
        entry = _find_entry(report, "39-035-0060", 88101, "PM25 24-hour 2006")
        assert entry is not None
        assert entry["status"] == "Exceeding"
        assert abs(entry["design_value"] - 36.0) < 0.5

    def test_pm25_24hr_pa_meeting(self, report):
        entry = _find_entry(report, "42-003-0008", 88101, "PM25 24-hour 2006")
        assert entry is not None
        assert entry["status"] == "Meeting"
        assert abs(entry["design_value"] - 34.0) < 0.5


class TestNO2:
    def test_no2_tx_meeting(self, report):
        entry = _find_entry(report, "48-201-1039", 42602, "NO2 1-hour 2010")
        assert entry is not None
        assert entry["status"] == "Meeting"
        assert abs(entry["design_value"] - 98.0) < 0.5


class TestSO2:
    def test_so2_mo_meeting_edge(self, report):
        """Must use 99th percentile (not 98th). DV=75, exactly at standard."""
        entry = _find_entry(report, "29-099-0019", 42401, "SO2 1-hour 2010")
        assert entry is not None
        assert entry["status"] == "Meeting"
        assert abs(entry["design_value"] - 75.0) < 0.5


class TestPM10:
    def test_pm10_az_meeting(self, report):
        """Exceedance count avg = 1.0, threshold = 1."""
        entry = _find_entry(report, "04-013-3002", 81102, "PM10 24-hour 2006")
        assert entry is not None
        assert entry["status"] == "Meeting"
        assert abs(entry["design_value"] - 1.0) < 0.01

    def test_pm10_ca_exceeding(self, report):
        """Exceedance count avg = 3.0, exceeds threshold of 1."""
        entry = _find_entry(report, "06-025-0005", 81102, "PM10 24-hour 2006")
        assert entry is not None
        assert entry["status"] == "Exceeding"
        assert abs(entry["design_value"] - 3.0) < 0.01

    def test_pm10_naaqs_level(self, report):
        """PM10 naaqs_level should be 1.0 (exceedance threshold), not 150."""
        entry = _find_entry(report, "04-013-3002", 81102, "PM10 24-hour 2006")
        assert entry is not None
        assert abs(entry["naaqs_level"] - 1.0) < 0.01, (
            f"PM10 naaqs_level should be 1.0 (exceedance threshold), got {entry['naaqs_level']}"
        )


class TestInsufficientData:
    def test_ny_annual_insufficient(self, report):
        entry = _find_entry(report, "36-061-0056", 88101, "PM25 Annual 2024")
        assert entry is not None
        assert entry["status"] == "Insufficient Data"
        assert entry["design_value"] is None

    def test_ny_24hr_insufficient(self, report):
        entry = _find_entry(report, "36-061-0056", 88101, "PM25 24-hour 2006")
        assert entry is not None
        assert entry["status"] == "Insufficient Data"
        assert entry["design_value"] is None


class TestNAAQSLevels:
    def test_o3_naaqs_level(self, report):
        entry = _find_entry(report, "04-013-3002", 44201, "Ozone 8-hour 2015")
        assert entry is not None
        assert abs(entry["naaqs_level"] - 0.070) < 1e-6

    def test_pm25_annual_naaqs_level(self, report):
        entry = _find_entry(report, "06-037-1103", 88101, "PM25 Annual 2024")
        assert entry is not None
        assert abs(entry["naaqs_level"] - 9.0) < 0.01

    def test_pm25_24hr_naaqs_level(self, report):
        entry = _find_entry(report, "06-037-1103", 88101, "PM25 24-hour 2006")
        assert entry is not None
        assert abs(entry["naaqs_level"] - 35.0) < 0.01

    def test_no2_naaqs_level(self, report):
        entry = _find_entry(report, "48-201-1039", 42602, "NO2 1-hour 2010")
        assert entry is not None
        assert abs(entry["naaqs_level"] - 100.0) < 0.01

    def test_so2_naaqs_level(self, report):
        entry = _find_entry(report, "29-099-0019", 42401, "SO2 1-hour 2010")
        assert entry is not None
        assert abs(entry["naaqs_level"] - 75.0) < 0.01


# ═══════════════════════════════════════════════════════════════
# ERROR ANALYSIS TESTS
# ═══════════════════════════════════════════════════════════════

def test_error_analysis_exists():
    assert os.path.exists(ERRORS_PATH)
    with open(ERRORS_PATH) as f:
        data = json.load(f)
    assert "errors" in data


def test_error_analysis_minimum_count(error_analysis):
    """Must identify at least 4 distinct errors."""
    assert len(error_analysis) >= 4, (
        f"Expected at least 4 errors identified, got {len(error_analysis)}"
    )


def test_error_analysis_has_required_fields(error_analysis):
    """Each error entry must have required fields."""
    required = {"affected_monitor", "parameter_code", "explanation"}
    for i, e in enumerate(error_analysis):
        for field in required:
            assert field in e, f"Error entry {i} missing required field '{field}'"


def test_error_analysis_cites_real_errors(error_analysis):
    """At least 4 cited errors must reference monitors that actually had errors."""
    cited = set()
    for e in error_analysis:
        monitor = str(e.get("affected_monitor", ""))
        param = int(e.get("parameter_code", 0))
        cited.add((monitor, param))
    valid = cited & KNOWN_ERROR_MONITORS
    assert len(valid) >= 4, (
        f"Expected at least 4 correctly identified error monitors, got {len(valid)}: {valid}"
    )


def test_error_analysis_covers_multiple_pollutants(error_analysis):
    """Errors should span at least 3 different parameter codes."""
    params = {int(e.get("parameter_code", 0)) for e in error_analysis}
    assert len(params) >= 3, (
        f"Expected errors spanning at least 3 parameter codes, got {params}"
    )
