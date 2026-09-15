
import json
import os
import subprocess
import pytest


OUTPUT_PATH = "/app/output.json"
VALIDATION_PATH = "/app/validation.json"
MESSAGES_PATH = "/app/messages.txt"
MSGCHECK_BIN = "/app/msgcheck"


@pytest.fixture(scope="module")
def decoder_output():
    assert os.path.exists(OUTPUT_PATH), f"{OUTPUT_PATH} does not exist"
    with open(OUTPUT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def validation():
    assert os.path.exists(VALIDATION_PATH), f"{VALIDATION_PATH} does not exist"
    with open(VALIDATION_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def msgcheck_output():
    assert os.path.exists(MSGCHECK_BIN), f"{MSGCHECK_BIN} does not exist"
    result = subprocess.run(
        [MSGCHECK_BIN, "-j", "-v", MESSAGES_PATH],
        capture_output=True, text=True
    )
    assert result.returncode == 0, (
        f"msgcheck failed with exit code {result.returncode}: {result.stderr}"
    )
    return json.loads(result.stdout)


# ---- Encoded message format tests ----

class TestEncodedMessages:
    def test_messages_file_exists(self):
        assert os.path.exists(MESSAGES_PATH), "encoded messages file missing"

    def test_message_count(self):
        with open(MESSAGES_PATH) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 24, f"Expected 24 messages (6 aircraft x 4), got {len(lines)}"

    def test_message_format(self):
        with open(MESSAGES_PATH) as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                assert line.startswith("*"), f"Line {i}: must start with *"
                assert line.endswith(";"), f"Line {i}: must end with ;"
                hex_part = line[1:-1]
                assert len(hex_part) == 28, f"Line {i}: must be 28 hex chars, got {len(hex_part)}"
                int(hex_part, 16)  # validates hex

    def test_df17_format(self):
        """All messages should have DF=17."""
        with open(MESSAGES_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                hex_part = line[1:-1].upper()
                first_byte = int(hex_part[:2], 16)
                df = (first_byte >> 3) & 0x1F
                assert df == 17, f"Expected DF=17, got DF={df} in {hex_part}"


# ---- Compiled integrity validator tests ----

class TestMessageIntegrity:
    def test_msgcheck_total(self, msgcheck_output):
        assert msgcheck_output["total_messages"] == 24

    def test_msgcheck_crc_valid(self, msgcheck_output):
        assert msgcheck_output["crc_valid"] == 22

    def test_msgcheck_crc_corrected(self, msgcheck_output):
        assert msgcheck_output["crc_corrected"] == 2

    def test_msgcheck_no_invalid(self, msgcheck_output):
        assert msgcheck_output["crc_invalid"] == 0

    def test_msgcheck_all_df17(self, msgcheck_output):
        assert msgcheck_output["df17_messages"] == 24

    def test_msgcheck_type_distribution(self, msgcheck_output):
        """Verify correct distribution of message types via TC values."""
        tcs = [m["tc"] for m in msgcheck_output["messages"]]
        ident_count = sum(1 for tc in tcs if 1 <= tc <= 4)
        pos_count = sum(1 for tc in tcs if 9 <= tc <= 18)
        vel_count = sum(1 for tc in tcs if tc == 19)
        assert ident_count == 6, f"Expected 6 identification msgs, got {ident_count}"
        assert pos_count == 12, f"Expected 12 position msgs, got {pos_count}"
        assert vel_count == 6, f"Expected 6 velocity msgs, got {vel_count}"


# ---- Decoder output structure ----

class TestDecoderStructure:
    def test_output_exists(self, decoder_output):
        assert decoder_output is not None

    def test_has_aircraft(self, decoder_output):
        assert "aircraft" in decoder_output

    def test_has_statistics(self, decoder_output):
        assert "statistics" in decoder_output

    def test_aircraft_count(self, decoder_output):
        assert len(decoder_output["aircraft"]) == 6

    def test_expected_icaos(self, decoder_output):
        expected = {"A1B2C3", "D4E5F6", "789ABC", "1A2B3C", "FE9876", "C0FFEE"}
        assert set(decoder_output["aircraft"].keys()) == expected


# ---- Callsign round-trip ----

class TestCallsigns:
    @pytest.mark.parametrize("icao,expected_cs", [
        ("A1B2C3", "TEST01"),
        ("D4E5F6", "BENCH2"),
        ("789ABC", "EVAL03"),
        ("1A2B3C", "QUIZ4X"),
        ("FE9876", "HARD05"),
        ("C0FFEE", "EDGE06"),
    ])
    def test_callsign(self, decoder_output, icao, expected_cs):
        decoded_cs = decoder_output["aircraft"][icao]["callsign"].strip()
        assert decoded_cs == expected_cs, f"Expected '{expected_cs}', got '{decoded_cs}'"


# ---- Altitude round-trip (must be exact) ----

class TestAltitudes:
    @pytest.mark.parametrize("icao,expected_alt", [
        ("A1B2C3", 35000),
        ("D4E5F6", 28000),
        ("789ABC", 41000),
        ("1A2B3C", 15000),
        ("FE9876", 42000),
        ("C0FFEE", 1000),
    ])
    def test_altitude(self, decoder_output, icao, expected_alt):
        assert decoder_output["aircraft"][icao]["altitude"] == expected_alt


# ---- Position round-trip (CPR quantization tolerance) ----

class TestPositions:
    POS_TOL = 0.05  # degrees

    @pytest.mark.parametrize("icao,expected_lat,expected_lon", [
        ("A1B2C3", 40.0, -74.0),
        ("D4E5F6", 51.5, -0.1),
        ("789ABC", -33.9, 151.2),
        ("1A2B3C", 35.7, 139.7),
        ("FE9876", 82.0, 10.0),
        ("C0FFEE", -0.5, -179.9),
    ])
    def test_position(self, decoder_output, icao, expected_lat, expected_lon):
        pos = decoder_output["aircraft"][icao]["position"]
        assert pos["lat"] is not None, f"{icao}: lat is None"
        assert pos["lon"] is not None, f"{icao}: lon is None"
        assert abs(pos["lat"] - expected_lat) < self.POS_TOL, \
            f"{icao}: lat {pos['lat']} not within {self.POS_TOL} of {expected_lat}"
        assert abs(pos["lon"] - expected_lon) < self.POS_TOL, \
            f"{icao}: lon {pos['lon']} not within {self.POS_TOL} of {expected_lon}"


# ---- Position edge case tests ----

class TestPositionEdgeCases:
    def test_southern_hemisphere(self, decoder_output):
        lat = decoder_output["aircraft"]["789ABC"]["position"]["lat"]
        assert lat < 0, f"789ABC should have negative lat (Sydney), got {lat}"

    def test_near_equator(self, decoder_output):
        lat = decoder_output["aircraft"]["C0FFEE"]["position"]["lat"]
        assert -1.0 < lat < 0.0, f"C0FFEE should have lat near -0.5, got {lat}"

    def test_near_antimeridian(self, decoder_output):
        lon = decoder_output["aircraft"]["C0FFEE"]["position"]["lon"]
        assert lon < -179.0, f"C0FFEE should have lon near -180, got {lon}"

    def test_high_latitude(self, decoder_output):
        lat = decoder_output["aircraft"]["FE9876"]["position"]["lat"]
        assert lat > 80.0, f"FE9876 should have lat > 80 (polar), got {lat}"


# ---- Velocity round-trip ----

class TestVelocities:
    GS_TOL = 2.0  # knots (quantization)
    HDG_TOL = 1.5  # degrees
    VR_TOL = 64    # ft/min (one quantization step)

    @pytest.mark.parametrize("icao,expected_gs,expected_hdg,expected_vr", [
        ("A1B2C3", 450.0, 90.0, 0),
        ("D4E5F6", 380.0, 270.0, -512),
        ("789ABC", 510.0, 180.0, 0),
        ("1A2B3C", 249.0, 45.0, 2048),
        ("FE9876", 300.0, 0.0, 0),
        ("C0FFEE", 150.0, 315.0, -1024),
    ])
    def test_velocity(self, decoder_output, icao, expected_gs, expected_hdg, expected_vr):
        vel = decoder_output["aircraft"][icao]["velocity"]
        assert vel is not None, f"{icao}: velocity is None"

        assert abs(vel["ground_speed"] - expected_gs) < self.GS_TOL, \
            f"{icao}: gs {vel['ground_speed']} not near {expected_gs}"

        hdg_diff = abs(vel["heading"] - expected_hdg)
        if hdg_diff > 180:
            hdg_diff = 360 - hdg_diff
        assert hdg_diff < self.HDG_TOL, \
            f"{icao}: heading {vel['heading']} not near {expected_hdg}"

        assert abs(vel["vertical_rate"] - expected_vr) < self.VR_TOL, \
            f"{icao}: vrate {vel['vertical_rate']} not near {expected_vr}"

    def test_heading_north(self, decoder_output):
        hdg = decoder_output["aircraft"]["FE9876"]["velocity"]["heading"]
        assert hdg < 1.0 or hdg > 359.0, f"FE9876 heading should be ~0, got {hdg}"


# ---- Statistics (error correction) ----

class TestStatistics:
    def test_total_messages(self, decoder_output):
        assert decoder_output["statistics"]["total_messages"] == 24

    def test_valid_messages(self, decoder_output):
        assert decoder_output["statistics"]["valid_messages"] == 22

    def test_corrected_messages(self, decoder_output):
        assert decoder_output["statistics"]["corrected_messages"] == 2

    def test_unique_aircraft(self, decoder_output):
        assert decoder_output["statistics"]["unique_aircraft"] == 6


# ---- Validation report ----

class TestValidationReport:
    def test_validation_exists(self, validation):
        assert validation is not None

    def test_has_round_trip_results(self, validation):
        assert "round_trip_results" in validation

    def test_has_summary(self, validation):
        assert "summary" in validation

    def test_all_aircraft_in_results(self, validation):
        expected = {"A1B2C3", "D4E5F6", "789ABC", "1A2B3C", "FE9876", "C0FFEE"}
        assert set(validation["round_trip_results"].keys()) == expected

    def test_position_errors_small(self, validation):
        for icao, result in validation["round_trip_results"].items():
            assert result["position_error_deg"] < 0.05, \
                f"{icao}: position error {result['position_error_deg']} >= 0.05"

    def test_callsigns_match(self, validation):
        for icao, result in validation["round_trip_results"].items():
            assert result["callsign_match"] is True, f"{icao}: callsign mismatch"

    def test_altitudes_match(self, validation):
        for icao, result in validation["round_trip_results"].items():
            assert result["altitude_match"] is True, f"{icao}: altitude mismatch"

    def test_heading_errors_small(self, validation):
        for icao, result in validation["round_trip_results"].items():
            assert result["heading_error_deg"] < 1.0, \
                f"{icao}: heading error {result['heading_error_deg']} >= 1.0"

    def test_summary_total_aircraft(self, validation):
        assert validation["summary"]["total_aircraft"] == 6

    def test_summary_total_messages(self, validation):
        assert validation["summary"]["total_messages"] == 24

    def test_summary_successful_round_trips(self, validation):
        assert validation["summary"]["successful_round_trips"] == 6

    def test_summary_error_injected(self, validation):
        assert validation["summary"]["error_injected_messages"] == 2

    def test_summary_error_corrected(self, validation):
        assert validation["summary"]["error_corrected_messages"] == 2
