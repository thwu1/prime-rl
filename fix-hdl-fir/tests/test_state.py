
import subprocess
import os
import pytest


def read_values(filename):
    """Read integer values from a simulation output file."""
    path = f"/app/{filename}"
    assert os.path.exists(path), f"{filename} not found — simulation may not have run"
    with open(path) as f:
        return [int(line.strip()) for line in f if line.strip()]


@pytest.fixture(scope="session", autouse=True)
def build_and_run_simulation():
    """Build with Verilator and run the simulation once for all tests."""
    # Clean previous artifacts
    subprocess.run(["rm", "-rf", "obj_dir"], cwd="/app")
    for fname in ["response_a.txt", "response_b.txt", "response_atomic.txt",
                   "response_switch.txt", "latency.txt"]:
        p = f"/app/{fname}"
        if os.path.exists(p):
            os.remove(p)

    result = subprocess.run(
        ["make", "run"],
        cwd="/app",
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"Verilator build or simulation failed:\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )


def test_impulse_response_lowpass():
    """Impulse response with symmetric low-pass coefficients [3,11,25,32,32,25,11,3]."""
    values = read_values("response_a.txt")
    coeffs = [3, 11, 25, 32, 32, 25, 11, 3]
    expected = [1000 * c for c in coeffs]

    assert len(values) >= len(expected), (
        f"Expected at least {len(expected)} output samples, got {len(values)}"
    )
    for i, exp in enumerate(expected):
        assert values[i] == exp, (
            f"response_a[{i}] = {values[i]}, expected {exp}"
        )
    # Remaining samples must be zero (impulse response tail)
    for i in range(len(expected), len(values)):
        assert values[i] == 0, (
            f"response_a[{i}] = {values[i]}, expected 0"
        )


def test_impulse_response_signed():
    """Impulse response with antisymmetric signed coefficients [-1,-4,-6,0,0,6,4,1]."""
    values = read_values("response_b.txt")
    coeffs = [-1, -4, -6, 0, 0, 6, 4, 1]
    expected = [500 * c for c in coeffs]

    assert len(values) >= len(expected), (
        f"Expected at least {len(expected)} output samples, got {len(values)}"
    )
    for i, exp in enumerate(expected):
        assert values[i] == exp, (
            f"response_b[{i}] = {values[i]}, expected {exp}"
        )
    for i in range(len(expected), len(values)):
        assert values[i] == 0, (
            f"response_b[{i}] = {values[i]}, expected 0"
        )


def test_atomic_coefficient_switch():
    """After loading A (committed) then B (NOT committed), impulse must use A."""
    values = read_values("response_atomic.txt")
    coeffs_a = [3, 11, 25, 32, 32, 25, 11, 3]
    expected = [1000 * c for c in coeffs_a]

    assert len(values) >= len(expected), (
        f"Expected at least {len(expected)} output samples, got {len(values)}"
    )
    for i, exp in enumerate(expected):
        assert values[i] == exp, (
            f"atomic[{i}] = {values[i]}, expected {exp} (should still be coeff set A)"
        )


def test_coefficient_reload_after_commit():
    """After committing B via cfg_done, impulse must use B."""
    values = read_values("response_switch.txt")
    coeffs_b = [-1, -4, -6, 0, 0, 6, 4, 1]
    expected = [500 * c for c in coeffs_b]

    assert len(values) >= len(expected), (
        f"Expected at least {len(expected)} output samples, got {len(values)}"
    )
    for i, exp in enumerate(expected):
        assert values[i] == exp, (
            f"switch[{i}] = {values[i]}, expected {exp} (should be coeff set B after commit)"
        )
    for i in range(len(expected), len(values)):
        assert values[i] == 0, (
            f"switch[{i}] = {values[i]}, expected 0"
        )


def test_output_latency():
    """dout_valid must assert exactly 1 clock cycle after din_valid."""
    values = read_values("latency.txt")
    assert len(values) >= 1, "latency.txt is empty"
    assert values[0] == 1, (
        f"Measured latency = {values[0]} cycles, expected exactly 1"
    )
