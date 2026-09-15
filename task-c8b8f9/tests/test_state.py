
"""
Tests for the postcard wire format decoder.
Verifies the decoder correctly processes COBS-framed postcard messages,
including valid decoding and error classification.
"""
import json
import os
import subprocess
import math
import pytest


@pytest.fixture(scope="session", autouse=True)
def run_decoder():
    """Run the decoder to generate report.json before tests."""
    decoder_path = "/app/decoder.py"
    assert os.path.isfile(decoder_path), "decoder.py not found at /app/decoder.py"
    result = subprocess.run(
        ["python3", decoder_path],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"decoder.py failed with exit code {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


@pytest.fixture(scope="session")
def report():
    """Load the generated report."""
    report_path = "/app/report.json"
    assert os.path.isfile(report_path), "report.json not found at /app/report.json"
    with open(report_path, "r") as f:
        return json.load(f)


class TestReportStructure:
    """Verify report has the expected top-level structure."""

    def test_has_required_fields(self, report):
        for field in ["total_messages", "valid_count", "invalid_count",
                       "type_counts", "messages"]:
            assert field in report, f"Missing required field: {field}"

    def test_total_messages(self, report):
        assert report["total_messages"] == 25

    def test_valid_count(self, report):
        assert report["valid_count"] == 18

    def test_invalid_count(self, report):
        assert report["invalid_count"] == 7

    def test_messages_length(self, report):
        assert len(report["messages"]) == 25


class TestTypeDistribution:
    """Verify the per-type counts of valid messages."""

    def test_sensor_reading_count(self, report):
        assert report["type_counts"].get("SensorReading") == 5

    def test_config_update_count(self, report):
        assert report["type_counts"].get("ConfigUpdate") == 7

    def test_heartbeat_count(self, report):
        assert report["type_counts"].get("Heartbeat") == 3

    def test_alert_count(self, report):
        assert report["type_counts"].get("Alert") == 3


def _get_msg(report, idx):
    """Get message at given index."""
    for m in report["messages"]:
        if m.get("index") == idx:
            return m
    pytest.fail(f"Message with index {idx} not found")


def _approx(a, b, tol=1e-4):
    """Check float approximate equality."""
    return abs(a - b) < tol


def _find_nested_value(obj, key):
    """Recursively find a value by key in a nested dict."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            result = _find_nested_value(v, key)
            if result is not None:
                return result
    if isinstance(obj, list):
        for item in obj:
            result = _find_nested_value(item, key)
            if result is not None:
                return result
    return None


class TestValidMessages:
    """Verify specific decoded values for valid messages."""

    def test_msg0_sensor_reading_basic(self, report):
        """SensorReading(sensor_id=42, timestamp=1000000, values=[23.5, 24.125], status=None)"""
        m = _get_msg(report, 0)
        assert m["valid"] is True
        assert m["type"] == "SensorReading"
        data = m["data"]
        assert data["sensor_id"] == 42
        assert data["timestamp"] == 1000000
        assert len(data["values"]) == 2
        assert _approx(data["values"][0], 23.5)
        assert _approx(data["values"][1], 24.125)
        assert data["status"] is None

    def test_msg1_sensor_with_status_ok(self, report):
        """SensorReading with status=Some(Ok)"""
        m = _get_msg(report, 1)
        assert m["valid"] is True
        assert m["type"] == "SensorReading"
        data = m["data"]
        assert data["sensor_id"] == 7
        assert data["timestamp"] == 2000000
        assert len(data["values"]) == 1
        assert _approx(data["values"][0], 18.25)
        # status should be Some(Ok) -- represented as a dict with _variant="Ok"
        status = data["status"]
        assert status is not None
        assert isinstance(status, dict)
        assert status.get("_variant") == "Ok"

    def test_msg2_config_int_negative(self, report):
        """ConfigUpdate(param_id=100, value=Int(-15))"""
        m = _get_msg(report, 2)
        assert m["valid"] is True
        assert m["type"] == "ConfigUpdate"
        data = m["data"]
        assert data["param_id"] == 100
        value = data["value"]
        assert isinstance(value, dict)
        assert value.get("_variant") == "Int"
        assert value.get("value") == -15

    def test_msg3_config_float(self, report):
        """ConfigUpdate(param_id=200, value=Float(3.140625))"""
        m = _get_msg(report, 3)
        assert m["valid"] is True
        data = m["data"]
        assert data["param_id"] == 200
        value = data["value"]
        assert value.get("_variant") == "Float"
        assert _approx(value.get("value"), 3.140625)

    def test_msg4_config_string(self, report):
        """ConfigUpdate(param_id=300, value=Str("hello"))"""
        m = _get_msg(report, 4)
        assert m["valid"] is True
        data = m["data"]
        assert data["param_id"] == 300
        value = data["value"]
        assert value.get("_variant") == "Str"
        assert value.get("value") == "hello"

    def test_msg5_config_bool_true(self, report):
        """ConfigUpdate(param_id=400, value=Bool(true))"""
        m = _get_msg(report, 5)
        assert m["valid"] is True
        data = m["data"]
        assert data["param_id"] == 400
        value = data["value"]
        assert value.get("_variant") == "Bool"
        assert value.get("value") is True

    def test_msg6_heartbeat(self, report):
        """Heartbeat(uptime_ms=86400000, free_mem=65536)"""
        m = _get_msg(report, 6)
        assert m["valid"] is True
        assert m["type"] == "Heartbeat"
        data = m["data"]
        assert data["uptime_ms"] == 86400000
        assert data["free_mem"] == 65536

    def test_msg7_heartbeat2(self, report):
        """Heartbeat(uptime_ms=172800000, free_mem=32768)"""
        m = _get_msg(report, 7)
        assert m["valid"] is True
        data = m["data"]
        assert data["uptime_ms"] == 172800000
        assert data["free_mem"] == 32768

    def test_msg8_alert_info(self, report):
        """Alert(level=Info, source="temp", code=100)"""
        m = _get_msg(report, 8)
        assert m["valid"] is True
        assert m["type"] == "Alert"
        data = m["data"]
        assert data["level"]["_variant"] == "Info"
        assert data["source"] == "temp"
        assert data["code"] == 100

    def test_msg9_alert_critical(self, report):
        """Alert(level=Critical, source="pressure", code=500)"""
        m = _get_msg(report, 9)
        assert m["valid"] is True
        data = m["data"]
        assert data["level"]["_variant"] == "Critical"
        assert data["source"] == "pressure"
        assert data["code"] == 500

    def test_msg10_status_warning(self, report):
        """SensorReading with status=Some(Warning(5))"""
        m = _get_msg(report, 10)
        assert m["valid"] is True
        data = m["data"]
        assert data["sensor_id"] == 1
        assert data["timestamp"] == 0
        assert data["values"] == []
        status = data["status"]
        assert status is not None
        assert status.get("_variant") == "Warning"
        assert status.get("code") == 5

    def test_msg11_max_values(self, report):
        """SensorReading with u32_max timestamp and Error status"""
        m = _get_msg(report, 11)
        assert m["valid"] is True
        data = m["data"]
        assert data["sensor_id"] == 255
        assert data["timestamp"] == 4294967295
        assert len(data["values"]) == 3
        assert _approx(data["values"][0], 0.0)
        assert _approx(data["values"][1], -1.0)
        assert _approx(data["values"][2], 100.5)
        status = data["status"]
        assert status.get("_variant") == "Error"
        assert status.get("code") == 1024

    def test_msg12_empty_string(self, report):
        """ConfigUpdate with empty string value"""
        m = _get_msg(report, 12)
        assert m["valid"] is True
        data = m["data"]
        assert data["param_id"] == 0
        assert data["value"]["_variant"] == "Str"
        assert data["value"]["value"] == ""

    def test_msg13_all_zeros(self, report):
        """Heartbeat with all zero values"""
        m = _get_msg(report, 13)
        assert m["valid"] is True
        data = m["data"]
        assert data["uptime_ms"] == 0
        assert data["free_mem"] == 0

    def test_msg14_alert_warn(self, report):
        """Alert(level=Warn, source="battery", code=42)"""
        m = _get_msg(report, 14)
        assert m["valid"] is True
        data = m["data"]
        assert data["level"]["_variant"] == "Warn"
        assert data["source"] == "battery"
        assert data["code"] == 42

    def test_msg15_five_floats(self, report):
        """SensorReading with 5 float values"""
        m = _get_msg(report, 15)
        assert m["valid"] is True
        data = m["data"]
        assert data["sensor_id"] == 1000
        assert data["timestamp"] == 500000
        assert len(data["values"]) == 5
        for i, expected in enumerate([1.0, 2.0, 3.0, 4.0, 5.0]):
            assert _approx(data["values"][i], expected), \
                f"values[{i}] = {data['values'][i]}, expected {expected}"
        assert data["status"] is None

    def test_msg16_int_zero(self, report):
        """ConfigUpdate Int(0) with zigzag encoding"""
        m = _get_msg(report, 16)
        assert m["valid"] is True
        data = m["data"]
        assert data["param_id"] == 50
        assert data["value"]["_variant"] == "Int"
        assert data["value"]["value"] == 0

    def test_msg17_bool_false(self, report):
        """ConfigUpdate Bool(false)"""
        m = _get_msg(report, 17)
        assert m["valid"] is True
        data = m["data"]
        assert data["param_id"] == 60
        assert data["value"]["_variant"] == "Bool"
        assert data["value"]["value"] is False


class TestInvalidMessages:
    """Verify that invalid messages are correctly identified."""

    @pytest.mark.parametrize("idx", [18, 19, 20, 21, 22, 23, 24])
    def test_invalid_message_detected(self, report, idx):
        """Each invalid message index must be marked as invalid."""
        m = _get_msg(report, idx)
        assert m["valid"] is False, \
            f"Message {idx} should be invalid but was marked valid"

    def test_all_valid_messages_marked_valid(self, report):
        """Messages 0-17 should all be valid."""
        for idx in range(18):
            m = _get_msg(report, idx)
            assert m["valid"] is True, \
                f"Message {idx} should be valid but was marked invalid"

    def test_invalid_has_error_info(self, report):
        """All invalid messages should have error_type field."""
        for idx in [18, 19, 20, 21, 22, 23, 24]:
            m = _get_msg(report, idx)
            assert "error_type" in m, \
                f"Invalid message {idx} missing error_type field"
            assert isinstance(m["error_type"], str) and len(m["error_type"]) > 0, \
                f"Invalid message {idx} has empty error_type"
