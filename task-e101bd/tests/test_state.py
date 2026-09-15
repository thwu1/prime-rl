
"""Tests for ground station binary log decoder and ADS-B report."""

import json
import os
import math
import pytest


REPORT_PATH = "/app/aircraft_report.json"

# Expected aircraft data (computed from verified Mode S message encoder)
EXPECTED = {
    "A1B2C3": {
        "callsign": "UAL1234",
        "lat": 40.641,
        "lon": -73.778,
        "altitude_ft": 35000,
        "ground_speed_kts": 450.0,
        "heading_deg": 90.0,
        "vertical_rate_fpm": -512,
        "num_valid_messages": 4,
        "registration": "N14001",
        "operator": "United Airlines",
    },
    "D4E5F6": {
        "callsign": "BAW789",
        "lat": 51.470,
        "lon": -0.454,
        "altitude_ft": 28000,
        "ground_speed_kts": 380.0,
        "heading_deg": 270.0,
        "vertical_rate_fpm": 0,
        "num_valid_messages": 4,
        "registration": "G-EUPT",
        "operator": "British Airways",
    },
    "789ABC": {
        "callsign": "DLH42",
        "lat": 48.354,
        "lon": 11.786,
        "altitude_ft": 41000,
        "ground_speed_kts": 489.3,
        "heading_deg": 45.0,
        "vertical_rate_fpm": 1280,
        "num_valid_messages": 4,
        "registration": "D-AIMA",
        "operator": "Lufthansa",
    },
}

# ICAOs that must NOT appear (corrupted CRC, noise, or non-DF17)
REJECTED_ICAOS = ["DEADBE", "000000", "FFFFFF"]


@pytest.fixture(scope="module")
def report():
    """Load the aircraft report JSON."""
    assert os.path.isfile(REPORT_PATH), (
        f"Aircraft report not found at {REPORT_PATH}. "
        "Ensure the decoder was run and produced the output."
    )
    with open(REPORT_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict), "Report must be a JSON object keyed by ICAO address"
    return data


class TestReportStructure:
    """Verify the report has the expected aircraft entries."""

    def test_all_aircraft_present(self, report):
        for icao in EXPECTED:
            assert icao in report, f"Missing aircraft {icao} in report"

    def test_no_invalid_aircraft(self, report):
        for icao in REJECTED_ICAOS:
            assert icao not in report, (
                f"Aircraft {icao} should have been rejected"
            )

    def test_report_keys(self, report):
        required_fields = [
            "callsign", "lat", "lon", "altitude_ft",
            "ground_speed_kts", "heading_deg", "vertical_rate_fpm",
            "num_valid_messages", "registration", "operator",
        ]
        for icao, entry in report.items():
            if icao not in EXPECTED:
                continue
            for field in required_fields:
                assert field in entry, (
                    f"Aircraft {icao} missing field '{field}'"
                )


class TestCallsignDecoding:

    @pytest.mark.parametrize("icao", list(EXPECTED.keys()))
    def test_callsign(self, report, icao):
        expected_cs = EXPECTED[icao]["callsign"]
        actual_cs = report[icao]["callsign"]
        assert actual_cs.strip() == expected_cs.strip(), (
            f"Aircraft {icao}: expected callsign '{expected_cs}', got '{actual_cs}'"
        )


class TestPositionDecoding:

    @pytest.mark.parametrize("icao", list(EXPECTED.keys()))
    def test_latitude(self, report, icao):
        expected_lat = EXPECTED[icao]["lat"]
        actual_lat = report[icao]["lat"]
        assert actual_lat is not None, f"Aircraft {icao}: latitude is null"
        assert abs(actual_lat - expected_lat) < 0.01, (
            f"Aircraft {icao}: expected lat ~{expected_lat}, got {actual_lat} "
            f"(error: {abs(actual_lat - expected_lat):.6f} degrees)"
        )

    @pytest.mark.parametrize("icao", list(EXPECTED.keys()))
    def test_longitude(self, report, icao):
        expected_lon = EXPECTED[icao]["lon"]
        actual_lon = report[icao]["lon"]
        assert actual_lon is not None, f"Aircraft {icao}: longitude is null"
        assert abs(actual_lon - expected_lon) < 0.01, (
            f"Aircraft {icao}: expected lon ~{expected_lon}, got {actual_lon} "
            f"(error: {abs(actual_lon - expected_lon):.6f} degrees)"
        )

    @pytest.mark.parametrize("icao", list(EXPECTED.keys()))
    def test_altitude(self, report, icao):
        expected_alt = EXPECTED[icao]["altitude_ft"]
        actual_alt = report[icao]["altitude_ft"]
        assert actual_alt is not None, f"Aircraft {icao}: altitude is null"
        assert actual_alt == expected_alt, (
            f"Aircraft {icao}: expected altitude {expected_alt} ft, got {actual_alt} ft"
        )


class TestVelocityDecoding:

    @pytest.mark.parametrize("icao", list(EXPECTED.keys()))
    def test_ground_speed(self, report, icao):
        expected_spd = EXPECTED[icao]["ground_speed_kts"]
        actual_spd = report[icao]["ground_speed_kts"]
        assert actual_spd is not None, f"Aircraft {icao}: ground speed is null"
        assert abs(actual_spd - expected_spd) < 1.5, (
            f"Aircraft {icao}: expected speed ~{expected_spd} kts, got {actual_spd} kts"
        )

    @pytest.mark.parametrize("icao", list(EXPECTED.keys()))
    def test_heading(self, report, icao):
        expected_hdg = EXPECTED[icao]["heading_deg"]
        actual_hdg = report[icao]["heading_deg"]
        assert actual_hdg is not None, f"Aircraft {icao}: heading is null"
        diff = abs(actual_hdg - expected_hdg)
        if diff > 180:
            diff = 360 - diff
        assert diff < 1.5, (
            f"Aircraft {icao}: expected heading ~{expected_hdg}, got {actual_hdg}"
        )

    @pytest.mark.parametrize("icao", list(EXPECTED.keys()))
    def test_vertical_rate(self, report, icao):
        expected_vr = EXPECTED[icao]["vertical_rate_fpm"]
        actual_vr = report[icao]["vertical_rate_fpm"]
        assert actual_vr is not None, f"Aircraft {icao}: vertical rate is null"
        assert abs(actual_vr - expected_vr) <= 64, (
            f"Aircraft {icao}: expected VR ~{expected_vr} fpm, got {actual_vr} fpm"
        )


class TestMessageCounting:

    @pytest.mark.parametrize("icao", list(EXPECTED.keys()))
    def test_valid_message_count(self, report, icao):
        expected_count = EXPECTED[icao]["num_valid_messages"]
        actual_count = report[icao]["num_valid_messages"]
        assert actual_count == expected_count, (
            f"Aircraft {icao}: expected {expected_count} valid messages, got {actual_count}"
        )


class TestRegistryCrossReference:
    """Verify registry data is correctly joined."""

    @pytest.mark.parametrize("icao", list(EXPECTED.keys()))
    def test_registration(self, report, icao):
        expected_reg = EXPECTED[icao]["registration"]
        actual_reg = report[icao]["registration"]
        assert actual_reg == expected_reg, (
            f"Aircraft {icao}: expected registration '{expected_reg}', got '{actual_reg}'"
        )

    @pytest.mark.parametrize("icao", list(EXPECTED.keys()))
    def test_operator(self, report, icao):
        expected_op = EXPECTED[icao]["operator"]
        actual_op = report[icao]["operator"]
        assert actual_op == expected_op, (
            f"Aircraft {icao}: expected operator '{expected_op}', got '{actual_op}'"
        )


class TestCRCIntegrity:

    def test_valid_messages_accepted(self, report):
        assert len([k for k in report if k in EXPECTED]) == 3

    def test_corrupted_message_rejected(self, report):
        assert "DEADBE" not in report

    def test_non_df17_ignored(self, report):
        if "A1B2C3" in report:
            assert report["A1B2C3"]["num_valid_messages"] == 4, (
                "Non-DF17 messages should not be counted"
            )


class TestPositionConsistency:

    def test_latitudes_in_range(self, report):
        for icao, entry in report.items():
            if icao not in EXPECTED:
                continue
            lat = entry.get("lat")
            if lat is not None:
                assert -90 <= lat <= 90, (
                    f"Aircraft {icao}: latitude {lat} out of range"
                )

    def test_longitudes_in_range(self, report):
        for icao, entry in report.items():
            if icao not in EXPECTED:
                continue
            lon = entry.get("lon")
            if lon is not None:
                assert -180 <= lon <= 180, (
                    f"Aircraft {icao}: longitude {lon} out of range"
                )

    def test_speeds_positive(self, report):
        for icao, entry in report.items():
            if icao not in EXPECTED:
                continue
            spd = entry.get("ground_speed_kts")
            if spd is not None:
                assert spd >= 0, (
                    f"Aircraft {icao}: negative ground speed {spd}"
                )

    def test_headings_in_range(self, report):
        for icao, entry in report.items():
            if icao not in EXPECTED:
                continue
            hdg = entry.get("heading_deg")
            if hdg is not None:
                assert 0 <= hdg < 360, (
                    f"Aircraft {icao}: heading {hdg} out of range"
                )
