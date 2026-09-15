
import json
import os
import pytest


OUTPUT_PATH = "/app/recovered.json"


@pytest.fixture
def recovered():
    """Load the recovered telemetry output."""
    assert os.path.exists(OUTPUT_PATH), f"{OUTPUT_PATH} does not exist"
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    assert isinstance(data, list), "recovered.json must be a JSON array"
    return data


def test_valid_message_count(recovered):
    """Exactly 10 messages should survive CRC32 verification."""
    assert len(recovered) == 10, f"Expected 10 valid messages, got {len(recovered)}"


def test_message_order_types(recovered):
    """Messages must appear in correct buffer-read order (Region A then B)."""
    expected = [
        "Heartbeat", "SensorData", "DiagnosticLog", "Heartbeat", "SensorData",
        "ConfigAck", "DiagnosticLog", "Heartbeat", "SensorData", "ConfigAck",
    ]
    actual = [m["type"] for m in recovered]
    assert actual == expected, f"Type order mismatch:\n  expected: {expected}\n  actual:   {actual}"


def test_heartbeat_seq1(recovered):
    msg = recovered[0]
    assert msg["type"] == "Heartbeat"
    assert msg["sequence"] == 1
    assert msg["uptime_ms"] == 60000
    assert msg["cpu_temp_c"] == 23


def test_sensor_data_ch0(recovered):
    msg = recovered[1]
    assert msg["type"] == "SensorData"
    assert msg["channel"] == 0
    assert msg["timestamp_us"] == 90000
    assert msg["samples"] == [100, -50, 200, -300, 150]


def test_diagnostic_log_info(recovered):
    msg = recovered[2]
    assert msg["type"] == "DiagnosticLog"
    assert msg["level"] == "Info"
    assert msg["module_path"] == "sensor_drv"
    assert msg["message"] == "all channels initialized"
    assert msg["error_code"] is None


def test_heartbeat_seq2(recovered):
    msg = recovered[3]
    assert msg["type"] == "Heartbeat"
    assert msg["sequence"] == 2
    assert msg["uptime_ms"] == 120000
    assert msg["cpu_temp_c"] == 25


def test_sensor_data_ch1(recovered):
    msg = recovered[4]
    assert msg["type"] == "SensorData"
    assert msg["channel"] == 1
    assert msg["timestamp_us"] == 180000
    assert msg["samples"] == [-1000, 500]


def test_config_ack_req42(recovered):
    msg = recovered[5]
    assert msg["type"] == "ConfigAck"
    assert msg["request_id"] == 42
    assert msg["accepted"] is True
    assert abs(msg["effective_rate_hz"] - 100.0) < 0.01
    assert msg["active_channels"] == [0, 1, 2]


def test_diagnostic_log_warn(recovered):
    msg = recovered[6]
    assert msg["type"] == "DiagnosticLog"
    assert msg["level"] == "Warn"
    assert msg["module_path"] == "power_mgmt"
    assert msg["message"] == "battery below threshold"
    assert msg["error_code"] == 1024


def test_heartbeat_seq3(recovered):
    msg = recovered[7]
    assert msg["type"] == "Heartbeat"
    assert msg["sequence"] == 3
    assert msg["uptime_ms"] == 180000
    assert msg["cpu_temp_c"] == 28


def test_sensor_data_ch2(recovered):
    msg = recovered[8]
    assert msg["type"] == "SensorData"
    assert msg["channel"] == 2
    assert msg["timestamp_us"] == 300000
    assert msg["samples"] == [0, 0, 0, -1, 1]


def test_config_ack_req43(recovered):
    msg = recovered[9]
    assert msg["type"] == "ConfigAck"
    assert msg["request_id"] == 43
    assert msg["accepted"] is False
    assert abs(msg["effective_rate_hz"] - 50.0) < 0.01
    assert msg["active_channels"] == [0]


def test_corrupted_frames_excluded(recovered):
    """Corrupted frames (seq=99, req_id=99) must not appear."""
    for msg in recovered:
        if msg["type"] == "Heartbeat":
            assert msg["sequence"] != 99, "Corrupted heartbeat (seq=99) should be excluded"
        if msg["type"] == "ConfigAck":
            assert msg["request_id"] != 99, "Corrupted ConfigAck (req=99) should be excluded"


def test_all_variant_types_present(recovered):
    """All four TelemetryMessage variants must appear."""
    types = {m["type"] for m in recovered}
    assert types == {"Heartbeat", "SensorData", "DiagnosticLog", "ConfigAck"}


def test_fixint_le_not_varint(recovered):
    """SensorData.timestamp_us must be decoded as fixed-width LE u32,
    not as a varint. If varint-decoded, 90000 would give a wrong value
    because the raw LE bytes contain 0x00 which terminates varint early."""
    for msg in recovered:
        if msg["type"] == "SensorData":
            assert msg["timestamp_us"] in (90000, 180000, 300000), \
                f"timestamp_us={msg['timestamp_us']} looks wrong — was it decoded as varint instead of fixed-width LE?"
