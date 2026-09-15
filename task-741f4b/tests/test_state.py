"""
Test suite for SysY LLVM compiler pipeline.
Verifies the pipeline at /app/sysy_run against 15 test programs.

Each test compiles SysY source to LLVM IR, links with the runtime library
using llvm-link, and executes via lli. stdout and exit code are verified.

"""
import subprocess
import os
import pytest

PIPELINE = "/app/sysy_run"
TESTS_DIR = "/app/tests"

EXPECTATIONS = {
    "test_01": {
        "stdout": "42 26 63\n",
        "returncode": 3,
    },
    "test_02": {
        "stdout": "14 20 3 2 -3 -2 12 1 0\n",
        "returncode": 0,
    },
    "test_03": {
        "stdout": "1 0 2 1 0 1 0 1 0\n",
        "returncode": 0,
    },
    "test_04": {
        "stdout": "23 8\n",
        "returncode": 0,
    },
    "test_05": {
        "stdout": "3628800 6 1 +-0\n",
        "returncode": 0,
    },
    "test_06": {
        "stdout": "10 0 0 0 20 30 20 10 2\n",
        "returncode": 0,
    },
    "test_07": {
        "stdout": "150 21 1 2 0\n",
        "returncode": 0,
    },
    "test_08": {
        "stdout": "0 0 1 2\n",
        "returncode": 0,
    },
    "test_09": {
        "stdout": "30 60 150\n",
        "returncode": 0,
    },
    "test_10": {
        "stdout": "7 3 18 28\n",
        "returncode": 7,
    },
    "test_11": {
        "stdout": "5 1 4 1 3\n",
        "returncode": 5,
    },
    "test_12": {
        "stdout": "1 2 3 4 5 7 8 9\n",
        "returncode": 0,
    },
    "test_13": {
        "stdout": "0 1 55 6765 832040\n",
        "returncode": 0,
    },
    "test_14": {
        "stdout": "50 16 1\n",
        "returncode": 0,
    },
    "test_15": {
        "stdout": "1 1 0 2 1 1\n",
        "returncode": 0,
    },
}


def test_pipeline_exists():
    """The pipeline executable must exist and be runnable."""
    assert os.path.exists(PIPELINE), (
        f"Pipeline not found at {PIPELINE}. "
        "You must create an executable at this path."
    )
    assert os.access(PIPELINE, os.X_OK), (
        f"{PIPELINE} exists but is not executable. Run: chmod +x {PIPELINE}"
    )


def test_llvm_tools_available():
    """Verify that required LLVM tools are available."""
    for tool in ['clang', 'lli', 'llvm-link']:
        result = subprocess.run(
            ['which', tool], capture_output=True, text=True)
        assert result.returncode == 0, (
            f"Required tool '{tool}' not found in PATH. "
            "Install it with: apt install clang llvm"
        )


def test_runtime_library_exists():
    """The SysY runtime library C source must be present."""
    assert os.path.exists("/app/runtime/sylib.c"), (
        "Runtime library not found at /app/runtime/sylib.c"
    )


@pytest.mark.parametrize("test_name", sorted(EXPECTATIONS.keys()))
def test_sysy_program(test_name):
    """Run a SysY test program through the LLVM pipeline and verify output."""
    spec = EXPECTATIONS[test_name]
    sy_file = os.path.join(TESTS_DIR, f"{test_name}.sy")
    in_file = os.path.join(TESTS_DIR, f"{test_name}.in")

    assert os.path.exists(sy_file), f"Test source file not found: {sy_file}"
    assert os.path.exists(PIPELINE), f"Pipeline not found at {PIPELINE}"

    stdin_data = None
    if os.path.exists(in_file):
        with open(in_file) as f:
            stdin_data = f.read()

    try:
        result = subprocess.run(
            [PIPELINE, sy_file],
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"Pipeline timed out (60s) on {test_name}")
    except PermissionError:
        pytest.fail(
            f"Permission denied running {PIPELINE}. Run: chmod +x {PIPELINE}"
        )

    expected_stdout = spec["stdout"]
    expected_ret = spec["returncode"] % 256
    actual_ret = result.returncode % 256

    if result.stdout != expected_stdout:
        pytest.fail(
            f"stdout mismatch for {test_name}:\n"
            f"  expected: {expected_stdout!r}\n"
            f"  actual:   {result.stdout!r}\n"
            f"  stderr:   {result.stderr[:500]!r}"
        )

    if actual_ret != expected_ret:
        pytest.fail(
            f"return code mismatch for {test_name}: "
            f"expected {expected_ret}, got {actual_ret}\n"
            f"  stderr: {result.stderr[:500]!r}"
        )
