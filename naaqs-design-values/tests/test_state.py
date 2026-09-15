
import json
import os
import pytest

OUTPUT_FILE = "/app/output/naaqs_compliance.json"


@pytest.fixture
def compliance_data():
    assert os.path.exists(OUTPUT_FILE), f"Output file {OUTPUT_FILE} does not exist"
    with open(OUTPUT_FILE) as f:
        data = json.load(f)
    assert "monitors" in data
    assert "site_level" in data
    assert "summary" in data
    return data


def find_monitor(data, site_id, param_code, poc, standard):
    for m in data["monitors"]:
        if (m["site_id"] == site_id and m["parameter_code"] == param_code
                and m["poc"] == poc and m["standard"] == standard):
            return m
    return None


def find_site_level(data, site_id, param_code, standard):
    for s in data["site_level"]:
        if (s["site_id"] == site_id and s["parameter_code"] == param_code
                and s["standard"] == standard):
            return s
    return None


class TestOutputStructure:
    def test_assessment_period(self, compliance_data):
        assert compliance_data["assessment_period"] == "2021-2023"

    def test_monitor_count(self, compliance_data):
        assert len(compliance_data["monitors"]) == 14

    def test_summary_total(self, compliance_data):
        assert compliance_data["summary"]["total_monitor_assessments"] == 14

    def test_summary_exceeding(self, compliance_data):
        assert compliance_data["summary"]["exceeding"] == 8

    def test_summary_meeting(self, compliance_data):
        assert compliance_data["summary"]["meeting"] == 6

    def test_summary_incomplete(self, compliance_data):
        assert compliance_data["summary"]["incomplete_data"] == 1


class TestOzoneDesignValues:
    """O3 8-hour 2015: 4th-highest daily max 8-hr avg, averaged over 3 years,
    TRUNCATED to 3 decimal places. NAAQS level = 0.070 ppm."""

    def test_o3_la_design_value(self, compliance_data):
        """(0.079+0.073+0.069)/3 = 0.07367 truncated to 0.073"""
        m = find_monitor(compliance_data, "06-037-0002", 44201, 1, "Ozone 8-hour 2015")
        assert m is not None, "O3 monitor at LA (06-037-0002) not found"
        assert m["design_value"] == 0.073
        assert m["exceeds_standard"] is True
        assert m["data_complete"] is True

    def test_o3_nyc_design_value(self, compliance_data):
        """(0.068+0.071+0.065)/3 = 0.068 truncated to 0.068"""
        m = find_monitor(compliance_data, "36-061-0056", 44201, 1, "Ozone 8-hour 2015")
        assert m is not None, "O3 monitor at NYC (36-061-0056) not found"
        assert m["design_value"] == 0.068
        assert m["exceeds_standard"] is False

    def test_o3_phoenix_incomplete(self, compliance_data):
        """(0.082+0.075+0.071)/3 = 0.076. Year 2021 has Completeness=N."""
        m = find_monitor(compliance_data, "04-013-0019", 44201, 1, "Ozone 8-hour 2015")
        assert m is not None, "O3 monitor at Phoenix (04-013-0019) not found"
        assert m["design_value"] == 0.076
        assert m["exceeds_standard"] is True
        assert m["data_complete"] is False

    def test_o3_truncation_not_rounding(self, compliance_data):
        """O3 LA average is 0.07367 — rounding would give 0.074, truncation gives 0.073.
        This test ensures the agent uses truncation (EPA O3 convention)."""
        m = find_monitor(compliance_data, "06-037-0002", 44201, 1, "Ozone 8-hour 2015")
        assert m is not None
        # If the agent rounded instead of truncated, DV would be 0.074
        assert m["design_value"] != 0.074, "Agent appears to be rounding O3 instead of truncating"
        assert m["design_value"] == 0.073


class TestPM25AnnualDesignValues:
    """PM25 Annual 2024: arithmetic mean averaged over 3 years,
    ROUNDED to 1 decimal place. NAAQS level = 9.0 ug/m3."""

    def test_pm25_annual_chicago(self, compliance_data):
        """(10.2+9.8+8.5)/3 = 9.5"""
        m = find_monitor(compliance_data, "17-031-4201", 88101, 1, "PM25 Annual 2024")
        assert m is not None, "PM2.5 annual monitor at Chicago not found"
        assert m["design_value"] == 9.5
        assert m["exceeds_standard"] is True

    def test_pm25_annual_houston(self, compliance_data):
        """(8.7+9.1+8.6)/3 = 8.8"""
        m = find_monitor(compliance_data, "48-201-1039", 88101, 1, "PM25 Annual 2024")
        assert m is not None
        assert m["design_value"] == 8.8
        assert m["exceeds_standard"] is False

    def test_pm25_annual_la2_poc1(self, compliance_data):
        """(11.3+10.8+10.1)/3 = 10.7"""
        m = find_monitor(compliance_data, "06-037-1103", 88101, 1, "PM25 Annual 2024")
        assert m is not None
        assert m["design_value"] == 10.7
        assert m["exceeds_standard"] is True

    def test_pm25_annual_la2_poc2(self, compliance_data):
        """(11.0+10.5+9.8)/3 = 10.4"""
        m = find_monitor(compliance_data, "06-037-1103", 88101, 2, "PM25 Annual 2024")
        assert m is not None
        assert m["design_value"] == 10.4
        assert m["exceeds_standard"] is True


class TestPM25_24hrDesignValues:
    """PM25 24-hour 2024: 98th percentile averaged over 3 years,
    ROUNDED to integer. NAAQS level = 35 ug/m3."""

    def test_pm25_24hr_chicago(self, compliance_data):
        """(38.2+35.6+33.1)/3 = 35.633 rounded to 36"""
        m = find_monitor(compliance_data, "17-031-4201", 88101, 1, "PM25 24-hour 2024")
        assert m is not None, "PM2.5 24-hr monitor at Chicago not found"
        assert m["design_value"] == 36
        assert m["exceeds_standard"] is True

    def test_pm25_24hr_houston(self, compliance_data):
        """(32.4+34.8+30.2)/3 = 32.467 rounded to 32"""
        m = find_monitor(compliance_data, "48-201-1039", 88101, 1, "PM25 24-hour 2024")
        assert m is not None
        assert m["design_value"] == 32
        assert m["exceeds_standard"] is False


class TestEventFiltering:
    """Chicago PM2.5 has a decoy 'Events Included' row for 2022 with mean=11.2.
    The correct row has Event Type='No Events' and mean=9.8."""

    def test_event_filtering_correct_dv(self, compliance_data):
        m = find_monitor(compliance_data, "17-031-4201", 88101, 1, "PM25 Annual 2024")
        assert m is not None
        # Correct: (10.2 + 9.8 + 8.5)/3 = 9.5
        # Wrong (Events Included): (10.2 + 11.2 + 8.5)/3 = 9.97 -> 10.0
        # Wrong (both rows for 2022): (10.2 + 9.8 + 11.2 + 8.5)/4 = 9.925 -> 9.9
        assert m["design_value"] == 9.5, (
            "Design value should be 9.5 (using No Events mean=9.8), "
            "not 10.0 (Events Included mean=11.2)"
        )


class TestNO2DesignValues:
    """NO2 1-hour: 98th percentile of daily max 1-hr values,
    averaged over 3 years, rounded to integer. NAAQS level = 100 ppb."""

    def test_no2_la(self, compliance_data):
        """(105+98+102)/3 = 101.67 -> 102"""
        m = find_monitor(compliance_data, "06-037-0002", 42602, 1, "NO2 1-hour")
        assert m is not None, "NO2 monitor at LA not found"
        assert m["design_value"] == 102
        assert m["exceeds_standard"] is True

    def test_no2_nyc(self, compliance_data):
        """(89+95+92)/3 = 92"""
        m = find_monitor(compliance_data, "36-061-0056", 42602, 1, "NO2 1-hour")
        assert m is not None
        assert m["design_value"] == 92
        assert m["exceeds_standard"] is False


class TestSO2DesignValues:
    """SO2 1-hour 2010: 99th percentile of daily max 1-hr values,
    averaged over 3 years, rounded to integer. NAAQS level = 75 ppb.
    Note: SO2 uses 99th percentile (NOT 98th like NO2)."""

    def test_so2_pittsburgh(self, compliance_data):
        """(82+76+71)/3 = 76.33 -> 76"""
        m = find_monitor(compliance_data, "42-003-0008", 42401, 1, "SO2 1-hour 2010")
        assert m is not None, "SO2 monitor at Pittsburgh not found"
        assert m["design_value"] == 76
        assert m["exceeds_standard"] is True

    def test_so2_stlouis(self, compliance_data):
        """(68+72+65)/3 = 68.33 -> 68"""
        m = find_monitor(compliance_data, "29-510-0085", 42401, 1, "SO2 1-hour 2010")
        assert m is not None
        assert m["design_value"] == 68
        assert m["exceeds_standard"] is False


class TestCODesignValues:
    """CO 8-hour 1971: highest 2nd-max non-overlapping 8-hr value
    across the 3-year period. NAAQS level = 9.0 ppm."""

    def test_co_la(self, compliance_data):
        """max(3.2, 2.8, 3.5) = 3.5"""
        m = find_monitor(compliance_data, "06-037-0002", 42101, 1, "CO 8-hour 1971")
        assert m is not None, "CO monitor at LA not found"
        assert m["design_value"] == 3.5
        assert m["exceeds_standard"] is False


class TestMultiPOCSiteLevelDesignValues:
    """Site 06-037-1103 has two POCs for PM2.5 annual.
    POC 1 DV=10.7, POC 2 DV=10.4. Site-level DV should be 10.7 (worst case)."""

    def test_site_level_la2_worst_poc(self, compliance_data):
        s = find_site_level(compliance_data, "06-037-1103", 88101, "PM25 Annual 2024")
        assert s is not None, "Site-level entry for 06-037-1103 PM2.5 annual not found"
        assert s["design_value"] == 10.7
        assert s["worst_poc"] == 1
        assert s["exceeds_standard"] is True


class TestDataCompleteness:
    """Only Phoenix O3 (04-013-0019) should have data_complete=False."""

    def test_complete_monitors(self, compliance_data):
        incomplete = [m for m in compliance_data["monitors"] if not m["data_complete"]]
        assert len(incomplete) == 1
        assert incomplete[0]["site_id"] == "04-013-0019"

    def test_all_others_complete(self, compliance_data):
        complete = [m for m in compliance_data["monitors"] if m["data_complete"]]
        assert len(complete) == 13
