"""
Tests for the protothread-based cooperative fan-out/fan-in pipeline.

Generates binary input, runs the pipeline, and verifies output
against independently computed expected results.
"""


import subprocess
import struct
import os
import pytest

INPUT_PATH = "/app/input.dat"
OUTPUT_PATH = "/app/output.dat"
BINARY_PATH = "/app/pipeline"
SOURCE_PATH = "/app/pipeline.c"


def compute_expected(values):
    """Reproduce the pipeline transformation in Python.

    For each input value v:
      1. Transformer: t = ((v & 0xFF) * 7 + 13) & 0xFF
      2. Splitter routes by t & 1:
         even (t & 1 == 0) -> EvenProc: t * 2
         odd  (t & 1 == 1) -> OddProc:  t + 50
    """
    results = []
    for v in values:
        t = ((v & 0xFF) * 7 + 13) & 0xFF
        if (t & 1) == 0:
            results.append(t * 2)
        else:
            results.append(t + 50)
    return results


def generate_input(values, path):
    """Write values as binary little-endian int32."""
    with open(path, 'wb') as f:
        for v in values:
            f.write(struct.pack('<i', v))


def build_pipeline():
    """Compile pipeline.c and return the subprocess result."""
    return subprocess.run(
        ["gcc", "-O2", "-o", BINARY_PATH, SOURCE_PATH, "-I/app/include"],
        capture_output=True, text=True
    )


def run_pipeline(timeout=10):
    """Run the compiled pipeline. Returns None on timeout."""
    try:
        return subprocess.run(
            [BINARY_PATH], capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return None


def read_output():
    """Read output file and return list of integers, or None."""
    if not os.path.exists(OUTPUT_PATH):
        return None
    with open(OUTPUT_PATH, 'r') as f:
        lines = [line.strip() for line in f if line.strip()]
    return [int(x) for x in lines]


class TestPipelineBuild:
    def test_compiles(self):
        """Pipeline must compile without errors."""
        r = build_pipeline()
        assert r.returncode == 0, f"Compilation failed:\n{r.stderr}"


class TestPipelineCorrectness:
    @pytest.fixture(autouse=True)
    def setup(self):
        """Build pipeline before each test."""
        r = build_pipeline()
        assert r.returncode == 0, f"Compilation failed:\n{r.stderr}"
        if os.path.exists(OUTPUT_PATH):
            os.remove(OUTPUT_PATH)

    def test_basic_50_values(self):
        """50 sequential values processed correctly."""
        values = list(range(50))
        generate_input(values, INPUT_PATH)
        expected = compute_expected(values)

        r = run_pipeline()
        assert r is not None, "Pipeline timed out (possible deadlock)"
        assert r.returncode == 0, \
            f"Pipeline exited with code {r.returncode}\nstderr: {r.stderr}"

        actual = read_output()
        assert actual is not None, "Output file was not created"
        assert len(actual) == len(expected), \
            f"Expected {len(expected)} output values, got {len(actual)}"
        assert sorted(actual) == sorted(expected), \
            f"Output mismatch.\nExpected (sorted): {sorted(expected)[:15]}...\nGot (sorted):      {sorted(actual)[:15]}..."

    def test_empty_input(self):
        """Empty input produces empty output file."""
        generate_input([], INPUT_PATH)

        r = run_pipeline()
        assert r is not None, "Pipeline timed out on empty input"
        assert r.returncode == 0

        assert os.path.exists(OUTPUT_PATH), "Output file not created for empty input"
        with open(OUTPUT_PATH, 'r') as f:
            content = f.read().strip()
        assert content == "", f"Expected empty output, got: '{content}'"

    def test_single_value(self):
        """Single input value processed correctly."""
        values = [42]
        generate_input(values, INPUT_PATH)
        expected = compute_expected(values)

        r = run_pipeline()
        assert r is not None, "Pipeline timed out"
        assert r.returncode == 0

        actual = read_output()
        assert actual is not None, "Output file not created"
        assert sorted(actual) == sorted(expected), f"Expected {expected}, got {actual}"

    def test_large_input_200(self):
        """200 values processed without deadlock."""
        values = list(range(200))
        generate_input(values, INPUT_PATH)
        expected = compute_expected(values)

        r = run_pipeline()
        assert r is not None, "Pipeline timed out on 200 values (possible deadlock)"
        assert r.returncode == 0

        actual = read_output()
        assert actual is not None
        assert len(actual) == len(expected), \
            f"Expected {len(expected)} values, got {len(actual)}"
        assert sorted(actual) == sorted(expected)

    def test_negative_values(self):
        """Negative input values handled correctly."""
        values = [-100, -50, -1, 0, 1, 50, 100]
        generate_input(values, INPUT_PATH)
        expected = compute_expected(values)

        r = run_pipeline()
        assert r is not None, "Pipeline timed out"
        assert r.returncode == 0

        actual = read_output()
        assert actual is not None
        assert sorted(actual) == sorted(expected), \
            f"Expected {sorted(expected)}, got {sorted(actual)}"

    def test_stress_1000_values(self):
        """1000 values: stress test for channel synchronization."""
        values = list(range(1000))
        generate_input(values, INPUT_PATH)
        expected = compute_expected(values)

        r = run_pipeline(timeout=15)
        assert r is not None, "Pipeline timed out on 1000 values"
        assert r.returncode == 0

        actual = read_output()
        assert actual is not None
        assert len(actual) == len(expected), \
            f"Expected {len(expected)} values, got {len(actual)}"
        assert sorted(actual) == sorted(expected)

    def test_all_even_path(self):
        """All values route through EvenProc (none through OddProc).

        Odd input values produce even transformed values:
        t = ((v & 0xFF) * 7 + 13) & 0xFF is even when v is odd.
        """
        values = [1, 3, 5, 7, 9, 11, 13, 15]
        generate_input(values, INPUT_PATH)
        expected = compute_expected(values)
        # Verify all go through even path
        for v in values:
            t = ((v & 0xFF) * 7 + 13) & 0xFF
            assert (t & 1) == 0, f"v={v} gives t={t} which is odd"

        r = run_pipeline()
        assert r is not None, "Pipeline timed out"
        assert r.returncode == 0

        actual = read_output()
        assert actual is not None
        assert len(actual) == len(expected), \
            f"Expected {len(expected)} values, got {len(actual)}"
        assert sorted(actual) == sorted(expected)

    def test_all_odd_path(self):
        """All values route through OddProc (none through EvenProc).

        Even input values produce odd transformed values:
        t = ((v & 0xFF) * 7 + 13) & 0xFF is odd when v is even.
        """
        values = [0, 2, 4, 6, 8, 10, 12, 14]
        generate_input(values, INPUT_PATH)
        expected = compute_expected(values)
        # Verify all go through odd path
        for v in values:
            t = ((v & 0xFF) * 7 + 13) & 0xFF
            assert (t & 1) == 1, f"v={v} gives t={t} which is even"

        r = run_pipeline()
        assert r is not None, "Pipeline timed out"
        assert r.returncode == 0

        actual = read_output()
        assert actual is not None
        assert len(actual) == len(expected), \
            f"Expected {len(expected)} values, got {len(actual)}"
        assert sorted(actual) == sorted(expected)

    def test_mixed_large_range(self):
        """Large range with negative and positive values."""
        values = list(range(-200, 200))
        generate_input(values, INPUT_PATH)
        expected = compute_expected(values)

        r = run_pipeline(timeout=15)
        assert r is not None, "Pipeline timed out on 400 mixed values"
        assert r.returncode == 0

        actual = read_output()
        assert actual is not None
        assert len(actual) == len(expected), \
            f"Expected {len(expected)} values, got {len(actual)}"
        assert sorted(actual) == sorted(expected)
