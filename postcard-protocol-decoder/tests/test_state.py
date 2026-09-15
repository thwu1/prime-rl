#!/usr/bin/env python3
"""Verification tests for postcard decoder, frame analysis, and schema compatibility."""

import json
import os
import pytest


def load_messages():
    with open('/app/decoded_messages.json') as f:
        return json.load(f)


def load_report():
    with open('/app/compatibility_report.json') as f:
        return json.load(f)


def load_frame_analysis():
    with open('/app/frame_analysis.json') as f:
        return json.load(f)


def find_message(output, session, seq_no):
    for msg in output:
        if msg["session"] == session and msg["seq_no"] == seq_no:
            return msg
    return None


def find_migration(report, migration_id):
    for entry in report:
        if entry["migration_id"] == migration_id:
            return entry
    return None


# ===========================================================================
# Frame analysis tests
# ===========================================================================

class TestFrameAnalysis:
    def test_frame_analysis_exists(self):
        assert os.path.exists('/app/frame_analysis.json'), \
            "frame_analysis.json not found"

    def test_total_frame_count(self):
        analysis = load_frame_analysis()
        assert len(analysis) == 12, f"Expected 12 frames, got {len(analysis)}"

    def test_valid_frame_count(self):
        analysis = load_frame_analysis()
        valid = [f for f in analysis if f["crc_valid"] is True]
        assert len(valid) == 9, f"Expected 9 valid frames, got {len(valid)}"

    def test_corrupt_frame_count(self):
        analysis = load_frame_analysis()
        corrupt = [f for f in analysis if f["crc_valid"] is False]
        assert len(corrupt) == 3, f"Expected 3 corrupt frames, got {len(corrupt)}"

    def test_alpha_has_four_frames(self):
        analysis = load_frame_analysis()
        alpha = [f for f in analysis if f["session"] == "session_alpha"]
        assert len(alpha) == 4

    def test_beta_has_four_frames(self):
        analysis = load_frame_analysis()
        beta = [f for f in analysis if f["session"] == "session_beta"]
        assert len(beta) == 4

    def test_gamma_has_four_frames(self):
        analysis = load_frame_analysis()
        gamma = [f for f in analysis if f["session"] == "session_gamma"]
        assert len(gamma) == 4

    def test_alpha_frame2_is_corrupt(self):
        analysis = load_frame_analysis()
        alpha = [f for f in analysis if f["session"] == "session_alpha"]
        alpha.sort(key=lambda x: x["frame_index"])
        assert alpha[2]["crc_valid"] is False

    def test_beta_frame3_is_corrupt(self):
        analysis = load_frame_analysis()
        beta = [f for f in analysis if f["session"] == "session_beta"]
        beta.sort(key=lambda x: x["frame_index"])
        assert beta[3]["crc_valid"] is False

    def test_gamma_frame0_is_corrupt(self):
        analysis = load_frame_analysis()
        gamma = [f for f in analysis if f["session"] == "session_gamma"]
        gamma.sort(key=lambda x: x["frame_index"])
        assert gamma[0]["crc_valid"] is False

    def test_alpha_valid_keys(self):
        analysis = load_frame_analysis()
        alpha = [f for f in analysis if f["session"] == "session_alpha"]
        alpha.sort(key=lambda x: x["frame_index"])
        assert alpha[0]["key_hex"] == "a1b2c3d4e5f60718"
        assert alpha[1]["key_hex"] == "1234567890abcdef"
        assert alpha[3]["key_hex"] == "a1b2c3d4e5f60718"

    def test_beta_valid_keys(self):
        analysis = load_frame_analysis()
        beta = [f for f in analysis if f["session"] == "session_beta"]
        beta.sort(key=lambda x: x["frame_index"])
        assert beta[0]["key_hex"] == "fedcba9876543210"
        assert beta[1]["key_hex"] == "55aa55aa55aa55aa"
        assert beta[2]["key_hex"] == "1234567890abcdef"

    def test_gamma_valid_keys(self):
        analysis = load_frame_analysis()
        gamma = [f for f in analysis if f["session"] == "session_gamma"]
        gamma.sort(key=lambda x: x["frame_index"])
        assert gamma[1]["key_hex"] == "55aa55aa55aa55aa"
        assert gamma[2]["key_hex"] == "fedcba9876543210"
        assert gamma[3]["key_hex"] == "55aa55aa55aa55aa"

    def test_session_ordering(self):
        analysis = load_frame_analysis()
        sessions = [f["session"] for f in analysis]
        first_alpha = sessions.index("session_alpha")
        first_beta = sessions.index("session_beta")
        first_gamma = sessions.index("session_gamma")
        assert first_alpha < first_beta < first_gamma


# ===========================================================================
# Decoded messages tests
# ===========================================================================

class TestOutputStructure:
    def test_output_exists(self):
        assert os.path.exists('/app/decoded_messages.json'), \
            "decoded_messages.json not found at /app/decoded_messages.json"

    def test_message_count(self):
        output = load_messages()
        assert len(output) == 9, f"Expected 9 messages, got {len(output)}"

    def test_session_alpha_count(self):
        output = load_messages()
        alpha = [m for m in output if m["session"] == "session_alpha"]
        assert len(alpha) == 3

    def test_session_beta_count(self):
        output = load_messages()
        beta = [m for m in output if m["session"] == "session_beta"]
        assert len(beta) == 3

    def test_session_gamma_count(self):
        output = load_messages()
        gamma = [m for m in output if m["session"] == "session_gamma"]
        assert len(gamma) == 3

    def test_wire_order_alpha(self):
        output = load_messages()
        alpha = [m for m in output if m["session"] == "session_alpha"]
        seq_nos = [m["seq_no"] for m in alpha]
        assert seq_nos == [1, 42, 2]

    def test_wire_order_beta(self):
        output = load_messages()
        beta = [m for m in output if m["session"] == "session_beta"]
        seq_nos = [m["seq_no"] for m in beta]
        assert seq_nos == [100, 11, 5]

    def test_wire_order_gamma(self):
        output = load_messages()
        gamma = [m for m in output if m["session"] == "session_gamma"]
        seq_nos = [m["seq_no"] for m in gamma]
        assert seq_nos == [12, 0, 20]

    def test_session_ordering(self):
        output = load_messages()
        sessions = [m["session"] for m in output]
        alpha_idx = sessions.index("session_alpha")
        beta_idx = sessions.index("session_beta")
        gamma_idx = sessions.index("session_gamma")
        assert alpha_idx < beta_idx < gamma_idx


class TestSensorReading:
    def test_sensor_reading_normal(self):
        output = load_messages()
        msg = find_message(output, "session_alpha", 1)
        assert msg is not None
        assert msg["message_type"] == "SensorReading"
        body = msg["body"]
        assert body["sensor_id"] == 1023
        assert body["temperature"] == -15
        assert abs(body["humidity"] - 65.5) < 0.01
        assert body["label"] == "temp_a"

    def test_sensor_reading_zeros(self):
        output = load_messages()
        msg = find_message(output, "session_alpha", 2)
        assert msg is not None
        assert msg["message_type"] == "SensorReading"
        body = msg["body"]
        assert body["sensor_id"] == 0
        assert body["temperature"] == 0
        assert abs(body["humidity"] - 0.0) < 0.01
        assert body["label"] == ""


class TestMotorCommand:
    def test_motor_reverse_with_duration(self):
        output = load_messages()
        msg = find_message(output, "session_alpha", 42)
        assert msg is not None
        assert msg["message_type"] == "MotorCommand"
        body = msg["body"]
        assert body["motor_idx"] == 3
        assert body["speed"] == -500
        assert body["direction"] == "Reverse"
        assert body["duration_ms"] == 2000

    def test_motor_forward_none_duration(self):
        output = load_messages()
        msg = find_message(output, "session_beta", 5)
        assert msg is not None
        assert msg["message_type"] == "MotorCommand"
        body = msg["body"]
        assert body["motor_idx"] == 0
        assert body["speed"] == 0
        assert body["direction"] == "Forward"
        assert body["duration_ms"] is None


class TestDeviceStatus:
    def test_device_status_populated(self):
        output = load_messages()
        msg = find_message(output, "session_beta", 100)
        assert msg is not None
        assert msg["message_type"] == "DeviceStatus"
        body = msg["body"]
        assert body["uptime_secs"] == 86400
        assert body["errors"] == [1, 257]
        assert body["firmware_version"] == [1, 4, 2]
        config = body["config"]
        assert isinstance(config, dict)
        assert config["gain"] == 100
        assert config["offset"] == -5

    def test_device_status_empty(self):
        output = load_messages()
        msg = find_message(output, "session_gamma", 0)
        assert msg is not None
        assert msg["message_type"] == "DeviceStatus"
        body = msg["body"]
        assert body["uptime_secs"] == 0
        assert body["errors"] == []
        assert body["firmware_version"] == [0, 0, 1]
        assert body["config"] == {}


class TestAlert:
    def test_alert_warning_variant(self):
        output = load_messages()
        msg = find_message(output, "session_beta", 11)
        assert msg is not None
        assert msg["message_type"] == "Alert"
        body = msg["body"]
        assert body["timestamp"] == 5000
        assert body["acknowledged"] is False
        severity = body["severity"]
        assert isinstance(severity, dict)
        assert "Warning" in severity
        assert severity["Warning"] == "temperature rising"

    def test_alert_critical_variant(self):
        output = load_messages()
        msg = find_message(output, "session_gamma", 12)
        assert msg is not None
        assert msg["message_type"] == "Alert"
        body = msg["body"]
        assert body["timestamp"] == 5002
        assert body["acknowledged"] is False
        severity = body["severity"]
        assert isinstance(severity, dict)
        assert "Critical" in severity
        crit = severity["Critical"]
        assert isinstance(crit, dict)
        assert crit["code"] == 1001
        assert crit["detail"] == "motor stall"
        assert crit["recoverable"] is False

    def test_alert_info_variant(self):
        output = load_messages()
        msg = find_message(output, "session_gamma", 20)
        assert msg is not None
        assert msg["message_type"] == "Alert"
        body = msg["body"]
        assert body["timestamp"] == 6000
        assert body["severity"] == "Info"
        assert body["acknowledged"] is True


class TestEdgeCases:
    def test_varint_large_value(self):
        output = load_messages()
        msg = find_message(output, "session_beta", 100)
        assert msg is not None
        assert msg["body"]["uptime_secs"] == 86400

    def test_zigzag_negative(self):
        output = load_messages()
        msg = find_message(output, "session_alpha", 42)
        assert msg is not None
        assert msg["body"]["speed"] == -500

    def test_zigzag_in_map(self):
        output = load_messages()
        msg = find_message(output, "session_beta", 100)
        assert msg is not None
        assert msg["body"]["config"]["offset"] == -5

    def test_cobs_with_many_zeros(self):
        output = load_messages()
        msg = find_message(output, "session_alpha", 2)
        assert msg is not None
        assert msg["body"]["sensor_id"] == 0
        assert msg["body"]["humidity"] == 0.0

    def test_required_fields_present(self):
        output = load_messages()
        for i, msg in enumerate(output):
            assert "session" in msg, f"Message {i} missing 'session'"
            assert "seq_no" in msg, f"Message {i} missing 'seq_no'"
            assert "message_type" in msg, f"Message {i} missing 'message_type'"
            assert "body" in msg, f"Message {i} missing 'body'"


# ===========================================================================
# Compatibility report tests
# ===========================================================================

class TestCompatibilityReport:
    def test_report_exists(self):
        assert os.path.exists('/app/compatibility_report.json'), \
            "compatibility_report.json not found"

    def test_report_has_ten_entries(self):
        report = load_report()
        assert len(report) == 10, f"Expected 10 migration entries, got {len(report)}"

    def test_all_migration_ids_present(self):
        report = load_report()
        ids = {entry["migration_id"] for entry in report}
        expected = {"M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10"}
        assert ids == expected, f"Missing migration IDs: {expected - ids}"

    def test_m1_widen_signed_int(self):
        report = load_report()
        m = find_migration(report, "M1")
        assert m is not None
        assert m["compatible"] is True

    def test_m2_append_optional_field(self):
        report = load_report()
        m = find_migration(report, "M2")
        assert m is not None
        assert m["compatible"] is False

    def test_m3_signed_to_unsigned(self):
        report = load_report()
        m = find_migration(report, "M3")
        assert m is not None
        assert m["compatible"] is False

    def test_m4_tuple_to_seq(self):
        report = load_report()
        m = find_migration(report, "M4")
        assert m is not None
        assert m["compatible"] is False

    def test_m5_enum_reorder(self):
        report = load_report()
        m = find_migration(report, "M5")
        assert m is not None
        assert m["compatible"] is False

    def test_m6_widen_unsigned_in_seq(self):
        report = load_report()
        m = find_migration(report, "M6")
        assert m is not None
        assert m["compatible"] is True

    def test_m7_widen_float(self):
        report = load_report()
        m = find_migration(report, "M7")
        assert m is not None
        assert m["compatible"] is False

    def test_m8_map_to_seq_tuple(self):
        report = load_report()
        m = find_migration(report, "M8")
        assert m is not None
        assert m["compatible"] is True

    def test_m9_unsigned_to_signed_in_seq(self):
        """seq<u16> -> seq<i16>: incompatible because unsigned varint vs
        zigzag+varint encoding differ even for the same numeric values."""
        report = load_report()
        m = find_migration(report, "M9")
        assert m is not None
        assert m["compatible"] is False

    def test_m10_append_enum_variant(self):
        """Adding a new variant at the end of a unit_variant enum preserves
        forward compatibility: existing discriminant indices are unchanged."""
        report = load_report()
        m = find_migration(report, "M10")
        assert m is not None
        assert m["compatible"] is True

    def test_report_entries_have_required_keys(self):
        report = load_report()
        for entry in report:
            assert "migration_id" in entry
            assert "compatible" in entry
            assert isinstance(entry["compatible"], bool)
