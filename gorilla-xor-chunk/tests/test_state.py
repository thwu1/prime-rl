
import subprocess
import pytest


@pytest.fixture(scope="session")
def go_test_output():
    """Run go test once and cache the output for all test functions."""
    result = subprocess.run(
        ["go", "test", "-v", "-count=1", "-timeout=120s", "./..."],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=180,
    )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }


def test_go_tests_compile_and_pass(go_test_output):
    """All Go tests must compile and pass."""
    combined = go_test_output["stdout"] + "\n" + go_test_output["stderr"]
    assert go_test_output["returncode"] == 0, (
        f"Go tests failed (exit code {go_test_output['returncode']}):\n{combined}"
    )


def test_xor_basic_roundtrip(go_test_output):
    assert "--- PASS: TestXORBasicRoundTrip" in go_test_output["stdout"]


def test_xor_leading_zero_clamp(go_test_output):
    assert "--- PASS: TestXORLeadingZeroClamp" in go_test_output["stdout"]


def test_xor_significant_bits_overflow(go_test_output):
    assert "--- PASS: TestXORSignificantBitsOverflow" in go_test_output["stdout"]


def test_xor_dod_boundary_value(go_test_output):
    assert "--- PASS: TestXORDodBoundaryValue" in go_test_output["stdout"]


def test_xor_seeking(go_test_output):
    assert "--- PASS: TestXORSeeking" in go_test_output["stdout"]


def test_xor_special_values(go_test_output):
    assert "--- PASS: TestXORSpecialValues" in go_test_output["stdout"]


def test_xor_appender_resume(go_test_output):
    assert "--- PASS: TestXORAppenderResume" in go_test_output["stdout"]


def test_xor_negative_timestamps(go_test_output):
    assert "--- PASS: TestXORNegativeTimestamps" in go_test_output["stdout"]


def test_varbit_int_roundtrip(go_test_output):
    assert "--- PASS: TestVarbitIntRoundTrip" in go_test_output["stdout"]


def test_varbit_uint_roundtrip(go_test_output):
    assert "--- PASS: TestVarbitUintRoundTrip" in go_test_output["stdout"]


def test_varbit_boundary_values(go_test_output):
    assert "--- PASS: TestVarbitBoundaryValues" in go_test_output["stdout"]


def test_merge_basic(go_test_output):
    assert "--- PASS: TestMergeBasic" in go_test_output["stdout"]


def test_merge_overlapping(go_test_output):
    assert "--- PASS: TestMergeOverlapping" in go_test_output["stdout"]


def test_merge_empty(go_test_output):
    assert "--- PASS: TestMergeEmpty" in go_test_output["stdout"]


def test_merge_dedup(go_test_output):
    assert "--- PASS: TestMergeDedup" in go_test_output["stdout"]
