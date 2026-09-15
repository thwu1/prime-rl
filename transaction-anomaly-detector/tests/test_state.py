
import json
import pytest

EXPECTED = {
    "h_serializable": {
        "anomalies": [],
        "strongest_level": "PL-3"
    },
    "h_g0": {
        "anomalies": ["G0"],
        "strongest_level": "PL-0"
    },
    "h_g1a": {
        "anomalies": ["G1a"],
        "strongest_level": "PL-1"
    },
    "h_g1b": {
        "anomalies": ["G-single", "G1b"],
        "strongest_level": "PL-1"
    },
    "h_g1c": {
        "anomalies": ["G1c"],
        "strongest_level": "PL-1"
    },
    "h_g_single": {
        "anomalies": ["G-single"],
        "strongest_level": "PL-2"
    },
    "h_g2_item": {
        "anomalies": ["G2-item"],
        "strongest_level": "PL-2"
    },
    "h_complex": {
        "anomalies": ["G-single", "G1a", "G2-item"],
        "strongest_level": "PL-1"
    }
}


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


def test_results_file_exists(results):
    """results.json must exist and be valid JSON."""
    assert isinstance(results, dict)


def test_all_histories_present(results):
    """Every expected history must have an entry."""
    for name in EXPECTED:
        assert name in results, f"Missing result for history: {name}"


@pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
def test_anomalies_correct(results, history_name):
    """Detected anomalies must match expected set exactly."""
    expected_anomalies = sorted(EXPECTED[history_name]["anomalies"])
    actual_anomalies = sorted(results[history_name]["anomalies"])
    assert actual_anomalies == expected_anomalies, (
        f"{history_name}: expected anomalies {expected_anomalies}, got {actual_anomalies}"
    )


@pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
def test_strongest_level_correct(results, history_name):
    """Strongest isolation level must match expected value."""
    expected_level = EXPECTED[history_name]["strongest_level"]
    actual_level = results[history_name]["strongest_level"]
    assert actual_level == expected_level, (
        f"{history_name}: expected level {expected_level}, got {actual_level}"
    )


@pytest.mark.parametrize("history_name", sorted(EXPECTED.keys()))
def test_result_structure(results, history_name):
    """Each result must have 'anomalies' (list) and 'strongest_level' (string)."""
    entry = results[history_name]
    assert "anomalies" in entry, f"{history_name}: missing 'anomalies' key"
    assert "strongest_level" in entry, f"{history_name}: missing 'strongest_level' key"
    assert isinstance(entry["anomalies"], list), f"{history_name}: 'anomalies' must be a list"
    assert isinstance(entry["strongest_level"], str), f"{history_name}: 'strongest_level' must be a string"


def test_anomaly_names_valid(results):
    """All reported anomaly names must be from the valid set."""
    valid = {"G0", "G1a", "G1b", "G1c", "G-single", "G2-item"}
    for name, entry in results.items():
        for anomaly in entry.get("anomalies", []):
            assert anomaly in valid, (
                f"{name}: invalid anomaly name '{anomaly}', valid: {valid}"
            )


def test_level_names_valid(results):
    """All reported levels must be from the valid set."""
    valid = {"PL-0", "PL-1", "PL-2", "PL-3"}
    for name, entry in results.items():
        level = entry.get("strongest_level", "")
        assert level in valid, (
            f"{name}: invalid level '{level}', valid: {valid}"
        )


def test_no_extra_histories(results):
    """Results should not contain entries for non-existent histories."""
    for name in results:
        assert name in EXPECTED, f"Unexpected history in results: {name}"
