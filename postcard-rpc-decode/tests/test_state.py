
import json
import pytest


@pytest.fixture(scope="module")
def analysis():
    with open("/app/analysis.json", "r") as f:
        return json.load(f)


# --- Frame counts ---

def test_total_frames(analysis):
    assert analysis["total_frames"] == 79


def test_valid_frames(analysis):
    assert analysis["valid_frames"] == 74


def test_invalid_frames(analysis):
    assert analysis["invalid_frames"] == 5


# --- Key derivation ---

def test_derived_key_status_report(analysis):
    assert analysis["derived_keys"]["StatusReport"] == "62deca8bf1f1e450"


def test_derived_key_batch_samples(analysis):
    assert analysis["derived_keys"]["BatchSamples"] == "71d7f23709ed09bb"


def test_derived_key_config_entry(analysis):
    assert analysis["derived_keys"]["ConfigEntry"] == "231a20881c3edc90"


def test_derived_key_system_event(analysis):
    assert analysis["derived_keys"]["SystemEvent"] == "0fc4510d7aae496e"


# --- Round-trip encoding verification ---

def test_round_trip_success(analysis):
    assert analysis["round_trip_success"] == 74


# --- Per-type message counts ---

def test_temp_reading_count(analysis):
    assert analysis["message_counts"]["TempReading"] == 20


def test_motor_command_count(analysis):
    assert analysis["message_counts"]["MotorCommand"] == 10


def test_status_report_count(analysis):
    assert analysis["message_counts"]["StatusReport"] == 18


def test_batch_samples_count(analysis):
    assert analysis["message_counts"]["BatchSamples"] == 10


def test_config_entry_count(analysis):
    assert analysis["message_counts"]["ConfigEntry"] == 8


def test_system_event_count(analysis):
    assert analysis["message_counts"]["SystemEvent"] == 8


# --- Invalid frame forensics ---

def test_invalid_frame_details_length(analysis):
    assert len(analysis["invalid_frame_details"]) == 5


def test_invalid_frame_indices(analysis):
    indices = [d["frame_index"] for d in analysis["invalid_frame_details"]]
    assert sorted(indices) == [30, 49, 76, 77, 78]


def test_invalid_frame_categories(analysis):
    details = {d["frame_index"]: d["error_category"]
               for d in analysis["invalid_frame_details"]}
    assert details[30] == "header_too_short"
    assert details[49] == "unknown_key"
    assert details[76] == "unknown_key"
    assert details[77] == "cobs_error"
    assert details[78] == "cobs_error"


def test_invalid_frame_hex_prefixes(analysis):
    details = {d["frame_index"]: d["raw_hex_prefix"]
               for d in analysis["invalid_frame_details"]}
    assert details[30] == "02aa"
    assert details[49] == "0b01020304050607"
    assert details[76] == "100fc4510d3aae49"
    assert details[77] == "0b71d7f23709ed09"
    assert details[78] == "1d231a20881c3edc"


# --- Temperature analysis ---

def test_temp_min(analysis):
    assert analysis["temp_analysis"]["min_celsius_x100"] == -1500


def test_temp_max(analysis):
    assert analysis["temp_analysis"]["max_celsius_x100"] == 6000


def test_temp_mean(analysis):
    assert abs(analysis["temp_analysis"]["mean_celsius_x100"] - 1830.0) < 0.01


def test_temp_sensor_ids(analysis):
    assert analysis["temp_analysis"]["unique_sensor_ids"] == [1, 2, 3, 4, 5]


def test_temp_invalid_count(analysis):
    assert analysis["temp_analysis"]["invalid_count"] == 2


# --- Motor analysis ---

def test_motor_max_abs_speed(analysis):
    assert analysis["motor_analysis"]["max_abs_speed_rpm"] == 6000


def test_motor_total_duration(analysis):
    assert analysis["motor_analysis"]["total_duration_ms"] == 48000


# --- StatusReport analysis ---

def test_fault_sequence_numbers(analysis):
    assert analysis["fault_sequence_numbers"] == [35, 39, 43, 48]


def test_calibration_offset_sums(analysis):
    assert analysis["calibration_offset_sums"] == [40, -80, 310]


def test_recovery_gaps(analysis):
    assert analysis["recovery_gaps"] == [2, 3, 3]


def test_unrecovered_faults(analysis):
    assert analysis["unrecovered_faults"] == 1


# --- Batch analysis ---

def test_batch_total_samples(analysis):
    assert analysis["batch_total_samples"] == 237


def test_batch_channel_counts(analysis):
    expected = {"0": 4, "1": 3, "2": 2, "3": 1}
    assert analysis["batch_channel_counts"] == expected


# --- Config analysis ---

def test_config_none_count(analysis):
    assert analysis["config_none_count"] == 3


# --- SystemEvent summary ---

def test_system_boot_count(analysis):
    assert analysis["system_event_summary"]["boot_count"] == 3


def test_system_watchdog_total(analysis):
    assert analysis["system_event_summary"]["watchdog_reset_total"] == 10


def test_system_memory_warning_count(analysis):
    assert analysis["system_event_summary"]["memory_warning_count"] == 2


def test_system_shutdown_count(analysis):
    assert analysis["system_event_summary"]["shutdown_count"] == 1


def test_system_firmware_versions(analysis):
    assert analysis["system_event_summary"]["firmware_versions"] == ["2.1.0", "2.2.0-rc1"]


def test_system_unique_sources(analysis):
    assert analysis["system_event_summary"]["unique_source_ids"] == [1, 2, 3]


def test_system_peak_memory(analysis):
    assert analysis["system_event_summary"]["peak_memory_used_kb"] == 500


# --- Thermal correlation ---

def test_thermal_correlation_length(analysis):
    assert len(analysis["thermal_correlation"]) == 2


def test_thermal_correlation_first(analysis):
    entry = analysis["thermal_correlation"][0]
    assert entry["event_timestamp_ms"] == 5000
    assert entry["nearby_temp_count"] == 5
    assert abs(entry["nearby_temp_mean_x100"] - 2446.0) < 0.01


def test_thermal_correlation_second(analysis):
    entry = analysis["thermal_correlation"][1]
    assert entry["event_timestamp_ms"] == 20000
    assert entry["nearby_temp_count"] == 3
    assert abs(entry["nearby_temp_mean_x100"] - 1300.0) < 0.01
