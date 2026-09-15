"""
Test suite for cross-language COBS-postcard forensics and schema migration.

Verifies:
1. Bug report correctly identifies all 3 bugs
2. Decoded output matches independent reference decoder
3. C decoder was built and conformance report is correct
4. Migration analysis frame counts are accurate

"""
import json
import csv
import os
import struct
import subprocess
import pytest
from collections import defaultdict


# ────────────────────────────────────────────────────────
# Reference COBS decoder
# ────────────────────────────────────────────────────────

def cobs_decode(data):
    """Decode COBS-encoded bytes. Raises ValueError on invalid data."""
    output = bytearray()
    idx = 0
    while idx < len(data):
        code = data[idx]
        idx += 1
        if code == 0:
            raise ValueError("unexpected zero in COBS data")
        for _ in range(code - 1):
            if idx >= len(data):
                raise ValueError("truncated COBS block")
            output.append(data[idx])
            idx += 1
        if code < 0xFF and idx < len(data):
            output.append(0x00)
    return bytes(output)


# ────────────────────────────────────────────────────────
# Reference postcard varint / zigzag decoder
# ────────────────────────────────────────────────────────

def varint_decode(data, offset, max_bytes):
    """Decode a LEB128 varint. Returns (value, new_offset)."""
    result = 0
    shift = 0
    for _ in range(max_bytes):
        if offset >= len(data):
            raise ValueError("varint: unexpected end of data")
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if (byte & 0x80) == 0:
            return result, offset
    raise ValueError("varint: exceeds max encoded length")


def zigzag_decode(n):
    """Decode zigzag-encoded unsigned to signed."""
    return (n >> 1) ^ -(n & 1)


def decode_reading(data):
    """Decode a SensorReading from postcard wire format bytes."""
    off = 0

    sensor_id, off = varint_decode(data, off, 3)
    if sensor_id > 0xFFFF:
        raise ValueError("sensor_id exceeds u16")

    timestamp_ms, off = varint_decode(data, off, 10)

    temp_zz, off = varint_decode(data, off, 5)
    temperature_cdeg = zigzag_decode(temp_zz)

    humidity, off = varint_decode(data, off, 3)
    if humidity > 0xFFFF:
        raise ValueError("humidity exceeds u16")

    pressure, off = varint_decode(data, off, 5)
    if pressure > 0xFFFFFFFF:
        raise ValueError("pressure exceeds u32")

    battery, off = varint_decode(data, off, 3)
    if battery > 0xFFFF:
        raise ValueError("battery exceeds u16")

    status_disc, off = varint_decode(data, off, 5)
    status_names = ["Ok", "Warning", "Error", "Calibrating"]
    if status_disc >= len(status_names):
        raise ValueError("unknown status variant")
    status = status_names[status_disc]

    seq_len, off = varint_decode(data, off, 10)
    sub_readings = []
    for _ in range(seq_len):
        v_zz, off = varint_decode(data, off, 3)
        sub_readings.append(zigzag_decode(v_zz))

    return {
        "sensor_id": sensor_id,
        "timestamp_ms": timestamp_ms,
        "temperature_cdeg": temperature_cdeg,
        "humidity_pct_x10": humidity,
        "pressure_pa": pressure,
        "battery_mv": battery,
        "status": status,
        "sub_readings": sub_readings,
    }


# ────────────────────────────────────────────────────────
# Fixture: independently decode capture.bin
# ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ref():
    """Decode capture.bin using the reference decoder to get ground truth."""
    with open("/app/capture.bin", "rb") as f:
        raw = f.read()

    assert raw[:4] == b"PCOB", "Bad magic in capture.bin"
    stream = raw[8:]

    frames = [f for f in stream.split(b'\x00') if f]

    valid = []
    corrupted = 0
    for idx, frame in enumerate(frames):
        try:
            reading = decode_reading(cobs_decode(frame))
            reading["frame_idx"] = idx
            valid.append(reading)
        except (ValueError, IndexError):
            corrupted += 1

    return {"total": len(frames), "valid": valid, "corrupted": corrupted}


# ────────────────────────────────────────────────────────
# Tests: bug_report.json
# ────────────────────────────────────────────────────────

class TestBugReport:
    def test_file_exists(self):
        assert os.path.isfile("/app/results/bug_report.json"), \
            "/app/results/bug_report.json not found"

    def test_has_three_bugs(self):
        bugs = json.load(open("/app/results/bug_report.json"))
        assert isinstance(bugs, list), "bug_report.json must be a JSON array"
        assert len(bugs) == 3, f"Expected 3 bugs, found {len(bugs)}"

    def test_each_bug_has_required_keys(self):
        bugs = json.load(open("/app/results/bug_report.json"))
        for i, bug in enumerate(bugs):
            assert "component" in bug, f"Bug {i}: missing 'component' key"
            assert "bug_description" in bug, f"Bug {i}: missing 'bug_description' key"
            assert "fix_description" in bug, f"Bug {i}: missing 'fix_description' key"

    def test_zigzag_bug_identified(self):
        """At least one bug report entry must identify the zigzag decode error."""
        bugs = json.load(open("/app/results/bug_report.json"))
        found = False
        for bug in bugs:
            text = (bug.get("component", "") + " " +
                    bug.get("bug_description", "") + " " +
                    bug.get("fix_description", "")).lower()
            if "zigzag" in text or ("sign" in text and "decode" in text):
                found = True
                break
        assert found, "No bug entry identifies the zigzag decode error"

    def test_enum_bug_identified(self):
        """At least one bug report entry must identify the enum mapping error."""
        bugs = json.load(open("/app/results/bug_report.json"))
        found = False
        for bug in bugs:
            text = (bug.get("component", "") + " " +
                    bug.get("bug_description", "") + " " +
                    bug.get("fix_description", "")).lower()
            if (("enum" in text or "status" in text or "variant" in text) and
                    ("swap" in text or "order" in text or "error" in text or
                     "warning" in text or "map" in text or "wrong" in text)):
                found = True
                break
        assert found, "No bug entry identifies the enum variant mapping error"

    def test_field_swap_bug_identified(self):
        """At least one bug report entry must identify the field order swap."""
        bugs = json.load(open("/app/results/bug_report.json"))
        found = False
        for bug in bugs:
            text = (bug.get("component", "") + " " +
                    bug.get("bug_description", "") + " " +
                    bug.get("fix_description", "")).lower()
            if (("field" in text or "order" in text or "swap" in text) and
                    ("humidity" in text or "battery" in text)):
                found = True
                break
        assert found, "No bug entry identifies the humidity/battery field swap"


# ────────────────────────────────────────────────────────
# Tests: summary.json
# ────────────────────────────────────────────────────────

class TestSummary:
    def test_file_exists(self):
        assert os.path.isfile("/app/results/summary.json"), \
            "/app/results/summary.json not found"

    def test_total_frames(self, ref):
        s = json.load(open("/app/results/summary.json"))
        assert s["total_frames"] == ref["total"], \
            f"total_frames: got {s['total_frames']}, expected {ref['total']}"

    def test_valid_frames(self, ref):
        s = json.load(open("/app/results/summary.json"))
        assert s["valid_frames"] == len(ref["valid"]), \
            f"valid_frames: got {s['valid_frames']}, expected {len(ref['valid'])}"

    def test_corrupted_frames(self, ref):
        s = json.load(open("/app/results/summary.json"))
        assert s["corrupted_frames"] == ref["corrupted"], \
            f"corrupted_frames: got {s['corrupted_frames']}, expected {ref['corrupted']}"

    def test_unique_sensors(self, ref):
        s = json.load(open("/app/results/summary.json"))
        expected = sorted(set(r["sensor_id"] for r in ref["valid"]))
        assert sorted(s["unique_sensors"]) == expected


# ────────────────────────────────────────────────────────
# Tests: decoded.csv
# ────────────────────────────────────────────────────────

class TestDecodedCSV:
    def test_file_exists(self):
        assert os.path.isfile("/app/results/decoded.csv"), \
            "/app/results/decoded.csv not found"

    def test_headers(self):
        with open("/app/results/decoded.csv") as f:
            headers = csv.DictReader(f).fieldnames
        assert headers == [
            "frame_idx", "sensor_id", "timestamp_ms", "temperature_cdeg",
            "humidity_pct_x10", "pressure_pa", "battery_mv", "status",
            "num_sub_readings"
        ]

    def test_row_count(self, ref):
        with open("/app/results/decoded.csv") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == len(ref["valid"]), \
            f"CSV row count: got {len(rows)}, expected {len(ref['valid'])}"

    def test_first_frame(self, ref):
        with open("/app/results/decoded.csv") as f:
            rows = list(csv.DictReader(f))
        exp = ref["valid"][0]
        row = rows[0]
        assert int(row["frame_idx"]) == exp["frame_idx"]
        assert int(row["sensor_id"]) == exp["sensor_id"]
        assert int(row["timestamp_ms"]) == exp["timestamp_ms"]
        assert int(row["temperature_cdeg"]) == exp["temperature_cdeg"]
        assert int(row["pressure_pa"]) == exp["pressure_pa"]

    def test_all_values(self, ref):
        """Exhaustive check: every field of every row must match."""
        with open("/app/results/decoded.csv") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == len(ref["valid"])
        for i, (row, exp) in enumerate(zip(rows, ref["valid"])):
            assert int(row["frame_idx"]) == exp["frame_idx"], \
                f"row {i}: frame_idx mismatch"
            assert int(row["sensor_id"]) == exp["sensor_id"], \
                f"row {i}: sensor_id mismatch"
            assert int(row["timestamp_ms"]) == exp["timestamp_ms"], \
                f"row {i}: timestamp_ms mismatch"
            assert int(row["temperature_cdeg"]) == exp["temperature_cdeg"], \
                f"row {i}: temperature_cdeg mismatch"
            assert int(row["humidity_pct_x10"]) == exp["humidity_pct_x10"], \
                f"row {i}: humidity_pct_x10 mismatch"
            assert int(row["pressure_pa"]) == exp["pressure_pa"], \
                f"row {i}: pressure_pa mismatch"
            assert int(row["battery_mv"]) == exp["battery_mv"], \
                f"row {i}: battery_mv mismatch"
            assert row["status"] == exp["status"], \
                f"row {i}: status mismatch: {row['status']} != {exp['status']}"
            assert int(row["num_sub_readings"]) == len(exp["sub_readings"]), \
                f"row {i}: num_sub_readings mismatch"


# ────────────────────────────────────────────────────────
# Tests: per_sensor.json
# ────────────────────────────────────────────────────────

class TestPerSensor:
    def test_file_exists(self):
        assert os.path.isfile("/app/results/per_sensor.json"), \
            "/app/results/per_sensor.json not found"

    def test_sensor_keys(self, ref):
        ps = json.load(open("/app/results/per_sensor.json"))
        expected_keys = sorted(str(s) for s in set(r["sensor_id"] for r in ref["valid"]))
        assert sorted(ps.keys()) == expected_keys

    def test_counts(self, ref):
        ps = json.load(open("/app/results/per_sensor.json"))
        by_sid = defaultdict(int)
        for r in ref["valid"]:
            by_sid[r["sensor_id"]] += 1
        for sid, cnt in by_sid.items():
            assert ps[str(sid)]["count"] == cnt, \
                f"sensor {sid}: count {ps[str(sid)]['count']} != {cnt}"

    def test_avg_temperature(self, ref):
        ps = json.load(open("/app/results/per_sensor.json"))
        by_sid = defaultdict(list)
        for r in ref["valid"]:
            by_sid[r["sensor_id"]].append(r["temperature_cdeg"])
        for sid, temps in by_sid.items():
            expected = sum(temps) / len(temps)
            actual = ps[str(sid)]["avg_temperature_cdeg"]
            assert abs(actual - expected) < 0.1, \
                f"sensor {sid}: avg_temp {actual} != {expected}"

    def test_min_max_temperature(self, ref):
        ps = json.load(open("/app/results/per_sensor.json"))
        by_sid = defaultdict(list)
        for r in ref["valid"]:
            by_sid[r["sensor_id"]].append(r["temperature_cdeg"])
        for sid, temps in by_sid.items():
            assert ps[str(sid)]["min_temperature_cdeg"] == min(temps), \
                f"sensor {sid}: min_temp mismatch"
            assert ps[str(sid)]["max_temperature_cdeg"] == max(temps), \
                f"sensor {sid}: max_temp mismatch"

    def test_error_count(self, ref):
        ps = json.load(open("/app/results/per_sensor.json"))
        errs = defaultdict(int)
        for r in ref["valid"]:
            if r["status"] == "Error":
                errs[r["sensor_id"]] += 1
        for sid in set(r["sensor_id"] for r in ref["valid"]):
            expected = errs.get(sid, 0)
            actual = ps[str(sid)]["error_count"]
            assert actual == expected, \
                f"sensor {sid}: error_count {actual} != {expected}"

    def test_total_sub_readings(self, ref):
        ps = json.load(open("/app/results/per_sensor.json"))
        subs = defaultdict(int)
        for r in ref["valid"]:
            subs[r["sensor_id"]] += len(r["sub_readings"])
        for sid in set(r["sensor_id"] for r in ref["valid"]):
            expected = subs.get(sid, 0)
            actual = ps[str(sid)]["total_sub_readings"]
            assert actual == expected, \
                f"sensor {sid}: total_sub_readings {actual} != {expected}"


# ────────────────────────────────────────────────────────
# Tests: anomalies.json
# ────────────────────────────────────────────────────────

class TestAnomalies:
    def test_file_exists(self):
        assert os.path.isfile("/app/results/anomalies.json"), \
            "/app/results/anomalies.json not found"

    def test_anomaly_count(self, ref):
        anomalies = json.load(open("/app/results/anomalies.json"))
        expected_count = 0
        for r in ref["valid"]:
            if r["status"] == "Error" or r["temperature_cdeg"] > 450 or \
               r["temperature_cdeg"] < -350:
                expected_count += 1
        assert len(anomalies) == expected_count, \
            f"anomaly count: got {len(anomalies)}, expected {expected_count}"

    def test_anomaly_content(self, ref):
        anomalies = json.load(open("/app/results/anomalies.json"))
        expected = []
        for r in ref["valid"]:
            reasons = []
            if r["status"] == "Error":
                reasons.append("error_status")
            if r["temperature_cdeg"] > 450:
                reasons.append("high_temperature")
            if r["temperature_cdeg"] < -350:
                reasons.append("low_temperature")
            if reasons:
                expected.append({
                    "frame_idx": r["frame_idx"],
                    "sensor_id": r["sensor_id"],
                    "reasons": sorted(reasons),
                })

        a_sorted = sorted(anomalies, key=lambda x: x["frame_idx"])
        e_sorted = sorted(expected, key=lambda x: x["frame_idx"])

        assert len(a_sorted) == len(e_sorted)
        for a, e in zip(a_sorted, e_sorted):
            assert a["frame_idx"] == e["frame_idx"], \
                f"anomaly frame_idx mismatch: {a['frame_idx']} != {e['frame_idx']}"
            assert a["sensor_id"] == e["sensor_id"], \
                f"anomaly sensor_id mismatch at frame {e['frame_idx']}"
            assert sorted(a["reasons"]) == e["reasons"], \
                f"anomaly reasons mismatch at frame {e['frame_idx']}: " \
                f"{sorted(a['reasons'])} != {e['reasons']}"


# ────────────────────────────────────────────────────────
# Tests: conformance.json (C decoder cross-validation)
# ────────────────────────────────────────────────────────

class TestConformance:
    def test_file_exists(self):
        assert os.path.isfile("/app/results/conformance.json"), \
            "/app/results/conformance.json not found"

    def test_c_decoder_binary_exists(self):
        """The C decoder must have been built."""
        assert os.path.isfile("/app/libcobs/decode_capture"), \
            "C decoder binary /app/libcobs/decode_capture not found — " \
            "must be built with make -C /app/libcobs/"

    def test_c_decoder_runs(self):
        """The C decoder must execute successfully on capture.bin."""
        result = subprocess.run(
            ["/app/libcobs/decode_capture", "/app/capture.bin"],
            capture_output=True, timeout=30
        )
        assert result.returncode == 0, \
            f"C decoder exited with code {result.returncode}: {result.stderr.decode()}"

    def test_c_decoder_output_matches_reference(self, ref):
        """C decoder JSON output must match the Python reference decoder."""
        result = subprocess.run(
            ["/app/libcobs/decode_capture", "/app/capture.bin"],
            capture_output=True, timeout=30
        )
        c_output = json.loads(result.stdout.decode())
        assert len(c_output) == len(ref["valid"]), \
            f"C decoder frame count {len(c_output)} != reference {len(ref['valid'])}"
        for i, (c_frame, ref_frame) in enumerate(zip(c_output, ref["valid"])):
            assert c_frame["frame_idx"] == ref_frame["frame_idx"], \
                f"C frame {i}: frame_idx mismatch"
            assert c_frame["sensor_id"] == ref_frame["sensor_id"], \
                f"C frame {i}: sensor_id mismatch"
            assert c_frame["temperature_cdeg"] == ref_frame["temperature_cdeg"], \
                f"C frame {i}: temperature_cdeg mismatch"
            assert c_frame["humidity_pct_x10"] == ref_frame["humidity_pct_x10"], \
                f"C frame {i}: humidity_pct_x10 mismatch"
            assert c_frame["pressure_pa"] == ref_frame["pressure_pa"], \
                f"C frame {i}: pressure_pa mismatch"
            assert c_frame["battery_mv"] == ref_frame["battery_mv"], \
                f"C frame {i}: battery_mv mismatch"
            assert c_frame["status"] == ref_frame["status"], \
                f"C frame {i}: status mismatch"

    def test_conformance_frame_counts(self, ref):
        conf = json.load(open("/app/results/conformance.json"))
        expected_valid = len(ref["valid"])
        assert conf["c_decoder_valid_frames"] == expected_valid, \
            f"c_decoder_valid_frames: {conf['c_decoder_valid_frames']} != {expected_valid}"
        assert conf["python_decoder_valid_frames"] == expected_valid, \
            f"python_decoder_valid_frames: {conf['python_decoder_valid_frames']} != {expected_valid}"

    def test_zero_discrepancies(self):
        conf = json.load(open("/app/results/conformance.json"))
        assert conf["frames_matching"] == conf["frames_compared"], \
            f"frames_matching ({conf['frames_matching']}) != frames_compared ({conf['frames_compared']})"
        discrepancies = conf.get("discrepancies", [])
        assert len(discrepancies) == 0, \
            f"Expected 0 discrepancies, found {len(discrepancies)}"


# ────────────────────────────────────────────────────────
# Tests: migration_analysis.json (v2 schema evaluation)
# ────────────────────────────────────────────────────────

class TestMigrationAnalysis:
    def test_file_exists(self):
        assert os.path.isfile("/app/results/migration_analysis.json"), \
            "/app/results/migration_analysis.json not found"

    def test_total_valid_frames(self, ref):
        ma = json.load(open("/app/results/migration_analysis.json"))
        assert ma["total_valid_frames"] == len(ref["valid"]), \
            f"total_valid_frames: {ma['total_valid_frames']} != {len(ref['valid'])}"

    def test_has_schema_changes(self):
        ma = json.load(open("/app/results/migration_analysis.json"))
        assert "schema_changes" in ma, "Missing schema_changes key"
        assert isinstance(ma["schema_changes"], list), "schema_changes must be a list"
        assert len(ma["schema_changes"]) >= 5, \
            f"Expected at least 5 schema changes, found {len(ma['schema_changes'])}"

    def test_pressure_lossy_count(self, ref):
        """Frames where pressure_pa % 100 != 0 are lossy due to u32→u16 truncation."""
        ma = json.load(open("/app/results/migration_analysis.json"))
        expected_lossy = sum(1 for r in ref["valid"] if r["pressure_pa"] % 100 != 0)
        pressure_change = None
        for change in ma["schema_changes"]:
            field = change.get("field", "").lower()
            if "pressure" in field:
                pressure_change = change
                break
        assert pressure_change is not None, "No schema change entry for pressure field"
        assert pressure_change["compatibility"] == "lossy", \
            f"pressure change should be lossy, got {pressure_change['compatibility']}"
        assert pressure_change["affected_frame_count"] == expected_lossy, \
            f"pressure affected_frame_count: {pressure_change['affected_frame_count']} != {expected_lossy}"

    def test_location_zone_lossy_count(self, ref):
        """Frames from sensors 5 and 8 have no zone mapping → lossy."""
        ma = json.load(open("/app/results/migration_analysis.json"))
        expected_lossy = sum(1 for r in ref["valid"] if r["sensor_id"] in (5, 8))
        location_change = None
        for change in ma["schema_changes"]:
            field = change.get("field", "").lower()
            if "location" in field or "zone" in field:
                location_change = change
                break
        assert location_change is not None, "No schema change entry for location_zone"
        assert location_change["compatibility"] == "lossy", \
            f"location_zone should be lossy, got {location_change['compatibility']}"
        assert location_change["affected_frame_count"] == expected_lossy, \
            f"location affected_frame_count: {location_change['affected_frame_count']} != {expected_lossy}"

    def test_temperature_lossless(self):
        """Temperature cdeg→mdeg scaling (×10) is lossless for i32."""
        ma = json.load(open("/app/results/migration_analysis.json"))
        temp_change = None
        for change in ma["schema_changes"]:
            field = change.get("field", "").lower()
            if "temperature" in field or "temp" in field:
                temp_change = change
                break
        assert temp_change is not None, "No schema change entry for temperature"
        assert temp_change["compatibility"] == "lossless", \
            f"temperature change should be lossless, got {temp_change['compatibility']}"

    def test_sub_readings_lossless(self):
        """sub_readings i16→i32 widening is lossless."""
        ma = json.load(open("/app/results/migration_analysis.json"))
        sr_change = None
        for change in ma["schema_changes"]:
            field = change.get("field", "").lower()
            if "sub_reading" in field or "sub_read" in field:
                sr_change = change
                break
        assert sr_change is not None, "No schema change entry for sub_readings"
        assert sr_change["compatibility"] == "lossless", \
            f"sub_readings change should be lossless, got {sr_change['compatibility']}"

    def test_status_lossless(self):
        """Enum reordering is semantically lossless (unambiguous remapping)."""
        ma = json.load(open("/app/results/migration_analysis.json"))
        status_change = None
        for change in ma["schema_changes"]:
            field = change.get("field", "").lower()
            if "status" in field or "enum" in field:
                status_change = change
                break
        assert status_change is not None, "No schema change entry for status enum"
        assert status_change["compatibility"] == "lossless", \
            f"status enum change should be lossless, got {status_change['compatibility']}"

    def test_overall_lossless_count(self, ref):
        """A frame is fully lossless iff sensor has known zone AND pressure_pa % 100 == 0."""
        ma = json.load(open("/app/results/migration_analysis.json"))
        known_zone_sensors = {1, 2, 3}
        lossless = sum(
            1 for r in ref["valid"]
            if r["sensor_id"] in known_zone_sensors and r["pressure_pa"] % 100 == 0
        )
        lossy = len(ref["valid"]) - lossless
        assert ma["fully_lossless_frames"] == lossless, \
            f"fully_lossless_frames: {ma['fully_lossless_frames']} != {lossless}"
        assert ma["lossy_frames"] == lossy, \
            f"lossy_frames: {ma['lossy_frames']} != {lossy}"
