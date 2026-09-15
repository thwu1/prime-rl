"""
Tests for the edge detection pipeline optimization task.
Verifies correctness against baseline and measures speedup.

The pipeline has three stages (Gaussian smooth, gradient, NMS) with
multiple bottleneck types. The optimized version must produce output
matching the baseline within tolerance and achieve >= 3x speedup.
"""

import os
import struct
import subprocess

import numpy as np
import pytest

INPUT = "/app/input.bin"
NUM_ITERS = "8"


def _build(target):
    r = subprocess.run(
        ["make", "-C", "/app", target],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"Build '{target}' failed:\n{r.stderr}"


def _run(binary, output_path):
    """Run an edge_detect binary and return its reported wall-clock time."""
    r = subprocess.run(
        [binary, INPUT, output_path, NUM_ITERS],
        capture_output=True, text=True, timeout=300,
    )
    assert r.returncode == 0, (
        f"{binary} exited with code {r.returncode}:\n{r.stderr}"
    )
    for line in r.stderr.strip().splitlines():
        if line.startswith("TIME:"):
            return float(line.split(":")[1].strip())
    pytest.fail(f"No TIME line in stderr of {binary}:\n{r.stderr}")


def _read_output(path):
    with open(path, "rb") as f:
        w, h = struct.unpack("ii", f.read(8))
        data = np.frombuffer(f.read(), dtype=np.float32)
        assert data.size == w * h, f"Expected {w*h} pixels, got {data.size}"
        return data.reshape(h, w)


# ------------------------------------------------------------------
#  Tests
# ------------------------------------------------------------------


def test_01_build_optimized():
    """The optimized edge_detect.c must compile without errors."""
    _build("edge_detect")
    assert os.path.isfile("/app/edge_detect"), "Binary not produced"


def test_02_correctness():
    """
    The optimized version must produce output matching the baseline
    within floating-point tolerance across the full NMS result.
    """
    _build("edge_detect")
    _build("edge_detect_ref")

    _run("/app/edge_detect_ref", "/tmp/out_ref.bin")
    _run("/app/edge_detect", "/tmp/out_opt.bin")

    ref = _read_output("/tmp/out_ref.bin")
    opt = _read_output("/tmp/out_opt.bin")
    assert ref.shape == opt.shape, (
        f"Shape mismatch: ref {ref.shape} vs opt {opt.shape}"
    )

    diff = np.abs(ref.astype(np.float64) - opt.astype(np.float64))
    max_err = float(np.max(diff))
    mean_err = float(np.mean(diff))

    assert max_err < 50.0, (
        f"Max pixel error {max_err:.4f} exceeds tolerance 50.0"
    )
    assert mean_err < 1.0, (
        f"Mean pixel error {mean_err:.6f} exceeds tolerance 1.0"
    )


def test_03_speedup():
    """
    The optimized version must run at least 3x faster than baseline.
    Both binaries must already exist from prior tests.
    """
    _build("edge_detect")
    _build("edge_detect_ref")

    ref_time = _run("/app/edge_detect_ref", "/tmp/out_ref2.bin")
    opt_time = _run("/app/edge_detect", "/tmp/out_opt2.bin")

    speedup = ref_time / opt_time if opt_time > 0 else 0.0
    print(
        f"\nBaseline: {ref_time:.3f}s  |  "
        f"Optimized: {opt_time:.3f}s  |  "
        f"Speedup: {speedup:.2f}x"
    )
    assert speedup >= 3.0, (
        f"Insufficient speedup: {speedup:.2f}x (need >= 3.0x). "
        f"Baseline={ref_time:.3f}s, Optimized={opt_time:.3f}s"
    )
