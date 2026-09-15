
import json
import os
import pytest

OUTPUT_PATH = "/app/recovery_output.json"


def _normalize(obj):
    """Recursively convert all dict keys to strings for comparison."""
    if isinstance(obj, dict):
        return {str(k): _normalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    return obj


@pytest.fixture
def output():
    assert os.path.exists(OUTPUT_PATH), (
        f"Output file {OUTPUT_PATH} not found. "
        "Ensure recovery.py was created and produces this file."
    )
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    return data


def test_output_structure(output):
    """Verify the output contains all required fields."""
    required = [
        "analysis_dpt",
        "analysis_txn_table",
        "redo_lsns",
        "undo_lsns",
        "final_page_states",
        "committed_txns",
        "aborted_txns",
        "nta_protected_pages",
    ]
    for key in required:
        assert key in output, f"Missing required key in output: {key}"


def test_analysis_dpt(output):
    """Verify the dirty page table after analysis."""
    expected = {
        "1": 30, "2": 50, "3": 150, "5": 40, "6": 60,
        "7": 110, "8": 160, "9": 170, "10": 70,
        "11": 210, "12": 220, "13": 240, "14": 250,
    }
    actual = _normalize(output["analysis_dpt"])
    assert actual == expected, (
        f"Analysis DPT mismatch.\nExpected: {expected}\nActual:   {actual}"
    )


def test_analysis_txn_table(output):
    """Verify the transaction table after analysis."""
    expected = {
        "2": {"status": "RECOVERY_ABORTING", "last_lsn": 310},
    }
    actual = _normalize(output["analysis_txn_table"])
    assert actual == expected, (
        f"Analysis txn table mismatch.\n"
        f"Expected: {expected}\nActual:   {actual}"
    )


def test_redo_lsns(output):
    """Verify the exact ordered list of LSNs that were re-applied."""
    expected = [60, 110, 160, 220, 240, 310]
    actual = output["redo_lsns"]
    assert actual == expected, (
        f"Redo LSNs mismatch.\nExpected: {expected}\nActual:   {actual}"
    )


def test_undo_lsns(output):
    """Verify the exact ordered list of LSNs that were reversed."""
    expected = [160, 60, 50]
    actual = output["undo_lsns"]
    assert actual == expected, (
        f"Undo LSNs mismatch.\nExpected: {expected}\nActual:   {actual}"
    )


def test_final_page_states(output):
    """Verify final recovered page values."""
    expected = {
        "1": 101, "2": 0, "3": 301, "5": 95, "6": 200,
        "7": 701, "8": 0, "9": 55, "10": 1090, "11": 300,
        "12": 2290, "13": 500, "14": 400,
    }
    actual = _normalize(output["final_page_states"])
    assert actual == expected, (
        f"Final page states mismatch.\nExpected: {expected}\nActual:   {actual}"
    )


def test_committed_txns(output):
    """Verify committed transactions."""
    expected = [1, 3]
    actual = sorted(output["committed_txns"])
    assert actual == expected, (
        f"Committed txns mismatch.\nExpected: {expected}\nActual:   {actual}"
    )


def test_aborted_txns(output):
    """Verify aborted transactions."""
    expected = [2, 4]
    actual = sorted(output["aborted_txns"])
    assert actual == expected, (
        f"Aborted txns mismatch.\nExpected: {expected}\nActual:   {actual}"
    )


def test_nta_protected_pages(output):
    """Verify NTA-protected pages whose modifications persisted despite parent txn abort."""
    expected = [10, 12]
    actual = sorted(output["nta_protected_pages"])
    assert actual == expected, (
        f"NTA-protected pages mismatch.\n"
        f"Expected: {expected}\nActual:   {actual}"
    )
