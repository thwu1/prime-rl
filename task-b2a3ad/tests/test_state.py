"""
Tests for the 3D FDTD stencil benchmark.

"""

import subprocess
import os
import json
import pytest
import numpy as np

# Parameters must match /app/fdtd3d.h exactly
DIMX, DIMY, DIMZ = 48, 32, 16
RADIUS = 4
TIMESTEPS = 10
COEFF_VAL = 0.1

OUTER_DIMX = DIMX + 2 * RADIUS   # 56
OUTER_DIMY = DIMY + 2 * RADIUS   # 40
OUTER_DIMZ = DIMZ + 2 * RADIUS   # 24
VOLUME_SIZE = OUTER_DIMX * OUTER_DIMY * OUTER_DIMZ  # 53760


def generate_input():
    """Generate deterministic input data matching the C implementation."""
    data = np.zeros((OUTER_DIMZ, OUTER_DIMY, OUTER_DIMX), dtype=np.float64)
    for iz in range(OUTER_DIMZ):
        for iy in range(OUTER_DIMY):
            for ix in range(OUTER_DIMX):
                val = ((ix * 7 + iy * 13 + iz * 29 + 5) % 256)
                data[iz, iy, ix] = val / 256.0
    return data


def reference_stencil(input_data, timesteps):
    """Compute the correct FDTD stencil result using float64 arithmetic."""
    coeff = [COEFF_VAL] * (RADIUS + 1)
    r = RADIUS
    src = input_data.copy()

    for _ in range(timesteps):
        dst = src.copy()
        result = src[r:r+DIMZ, r:r+DIMY, r:r+DIMX] * coeff[0]
        for ir in range(1, RADIUS + 1):
            c = coeff[ir]
            result = result + c * (
                src[r:r+DIMZ, r:r+DIMY, r+ir:r+DIMX+ir] +
                src[r:r+DIMZ, r:r+DIMY, r-ir:r+DIMX-ir])
            result = result + c * (
                src[r:r+DIMZ, r+ir:r+DIMY+ir, r:r+DIMX] +
                src[r:r+DIMZ, r-ir:r+DIMY-ir, r:r+DIMX])
            result = result + c * (
                src[r+ir:r+DIMZ+ir, r:r+DIMY, r:r+DIMX] +
                src[r-ir:r+DIMZ-ir, r:r+DIMY, r:r+DIMX])
        dst[r:r+DIMZ, r:r+DIMY, r:r+DIMX] = result
        src = dst

    return src


@pytest.fixture(scope="module")
def build_result():
    """Build the project."""
    subprocess.run(["make", "-C", "/app", "clean"],
                   capture_output=True)
    result = subprocess.run(["make", "-C", "/app"],
                            capture_output=True, text=True)
    return result


@pytest.fixture(scope="module")
def run_result(build_result):
    """Run the program after building."""
    assert build_result.returncode == 0, (
        f"Build failed:\nstdout:\n{build_result.stdout}\n"
        f"stderr:\n{build_result.stderr}")
    result = subprocess.run(
        ["/app/fdtd3d"],
        capture_output=True, text=True, cwd="/app", timeout=120)
    return result


@pytest.fixture(scope="module")
def reference():
    """Compute the reference solution."""
    return reference_stencil(generate_input(), TIMESTEPS)


def test_build_succeeds(build_result):
    """Project must compile with make."""
    assert build_result.returncode == 0, (
        f"Build failed with exit code {build_result.returncode}:\n"
        f"stdout:\n{build_result.stdout}\nstderr:\n{build_result.stderr}")


def test_program_runs(run_result):
    """Program must execute without errors."""
    assert run_result.returncode == 0, (
        f"Program failed (exit code {run_result.returncode}):\n"
        f"stdout:\n{run_result.stdout}\nstderr:\n{run_result.stderr}")


def test_naive_output_exists(run_result):
    """output_naive.bin must exist with correct size."""
    assert run_result.returncode == 0
    path = "/app/output_naive.bin"
    assert os.path.exists(path), "output_naive.bin not found"
    expected = VOLUME_SIZE * 4
    actual = os.path.getsize(path)
    assert actual == expected, (
        f"output_naive.bin: {actual} bytes (expected {expected})")


def test_tiled_output_exists(run_result):
    """output_tiled.bin must exist with correct size."""
    assert run_result.returncode == 0
    path = "/app/output_tiled.bin"
    assert os.path.exists(path), "output_tiled.bin not found"
    expected = VOLUME_SIZE * 4
    actual = os.path.getsize(path)
    assert actual == expected, (
        f"output_tiled.bin: {actual} bytes (expected {expected})")


def test_naive_correctness(run_result, reference):
    """Naive solver output must match Python reference."""
    assert run_result.returncode == 0
    with open("/app/output_naive.bin", "rb") as f:
        naive = np.frombuffer(f.read(), dtype=np.float32).reshape(
            OUTER_DIMZ, OUTER_DIMY, OUTER_DIMX)
    r = RADIUS
    out_interior = naive[r:r+DIMZ, r:r+DIMY, r:r+DIMX].astype(np.float64)
    ref_interior = reference[r:r+DIMZ, r:r+DIMY, r:r+DIMX]
    max_diff = np.max(np.abs(ref_interior - out_interior))
    assert np.allclose(out_interior, ref_interior, rtol=1e-2, atol=1e-2), (
        f"Naive output does not match reference.\n"
        f"Max absolute diff: {max_diff:.6e}\n"
        f"Sample ref [0,0,:5]: {ref_interior[0, 0, :5]}\n"
        f"Sample out [0,0,:5]: {out_interior[0, 0, :5]}")


def test_tiled_correctness(run_result, reference):
    """Tiled solver output must match Python reference."""
    assert run_result.returncode == 0
    with open("/app/output_tiled.bin", "rb") as f:
        tiled = np.frombuffer(f.read(), dtype=np.float32).reshape(
            OUTER_DIMZ, OUTER_DIMY, OUTER_DIMX)
    r = RADIUS
    out_interior = tiled[r:r+DIMZ, r:r+DIMY, r:r+DIMX].astype(np.float64)
    ref_interior = reference[r:r+DIMZ, r:r+DIMY, r:r+DIMX]
    max_diff = np.max(np.abs(ref_interior - out_interior))
    assert np.allclose(out_interior, ref_interior, rtol=1e-2, atol=1e-2), (
        f"Tiled output does not match reference.\n"
        f"Max absolute diff: {max_diff:.6e}\n"
        f"Sample ref [0,0,:5]: {ref_interior[0, 0, :5]}\n"
        f"Sample out [0,0,:5]: {out_interior[0, 0, :5]}")


def test_outputs_match(run_result):
    """Naive and tiled outputs must match each other within float32 tolerance."""
    assert run_result.returncode == 0
    with open("/app/output_naive.bin", "rb") as f:
        naive = np.frombuffer(f.read(), dtype=np.float32)
    with open("/app/output_tiled.bin", "rb") as f:
        tiled = np.frombuffer(f.read(), dtype=np.float32)
    max_diff = np.max(np.abs(
        naive.astype(np.float64) - tiled.astype(np.float64)))
    assert np.allclose(naive, tiled, rtol=1e-5, atol=1e-5), (
        f"Naive and tiled outputs differ.\n"
        f"Max absolute diff: {max_diff:.6e}")


def test_results_json_exists(run_result):
    """results.json must exist."""
    assert run_result.returncode == 0
    assert os.path.exists("/app/results.json"), "results.json not found"


def test_results_json_structure(run_result):
    """results.json must have the required structure."""
    assert run_result.returncode == 0
    with open("/app/results.json") as f:
        data = json.load(f)
    assert "grid" in data, "Missing 'grid' key"
    assert "stencil" in data, "Missing 'stencil' key"
    assert "comparison" in data, "Missing 'comparison' key"
    assert "naive_checksum" in data, "Missing 'naive_checksum'"
    assert "tiled_checksum" in data, "Missing 'tiled_checksum'"
    assert data["grid"]["dimx"] == DIMX
    assert data["grid"]["dimy"] == DIMY
    assert data["grid"]["dimz"] == DIMZ
    assert data["stencil"]["radius"] == RADIUS
    assert data["stencil"]["timesteps"] == TIMESTEPS
    comp = data["comparison"]
    for key in ["max_absolute_error", "mean_absolute_error",
                "relative_l2_error", "max_error_location",
                "interior_elements_compared", "match"]:
        assert key in comp, f"Missing comparison.{key}"
    assert comp["interior_elements_compared"] == DIMX * DIMY * DIMZ


def test_results_json_match(run_result):
    """results.json must report that outputs match."""
    assert run_result.returncode == 0
    with open("/app/results.json") as f:
        data = json.load(f)
    assert data["comparison"]["match"] is True, (
        f"results.json reports match=false, "
        f"max_absolute_error={data['comparison']['max_absolute_error']}")


def test_results_json_checksums(run_result, reference):
    """Checksums in results.json must be plausible."""
    assert run_result.returncode == 0
    with open("/app/results.json") as f:
        data = json.load(f)
    ref_sum = float(np.sum(reference))
    naive_sum = data["naive_checksum"]
    tiled_sum = data["tiled_checksum"]
    assert abs(naive_sum - tiled_sum) / (abs(naive_sum) + 1e-10) < 0.01, (
        f"Checksums diverge: naive={naive_sum}, tiled={tiled_sum}")
    assert abs(naive_sum - ref_sum) / (abs(ref_sum) + 1e-10) < 0.05, (
        f"Naive checksum {naive_sum} far from reference {ref_sum}")


def test_halo_preserved(run_result):
    """Halo boundary values must be preserved in both outputs."""
    assert run_result.returncode == 0
    inp = generate_input().astype(np.float32)
    r = RADIUS
    for fname in ["output_naive.bin", "output_tiled.bin"]:
        with open(f"/app/{fname}", "rb") as f:
            out = np.frombuffer(f.read(), dtype=np.float32).reshape(
                OUTER_DIMZ, OUTER_DIMY, OUTER_DIMX)
        np.testing.assert_allclose(
            out[:r, :, :], inp[:r, :, :], rtol=1e-6,
            err_msg=f"{fname}: top z-halo modified")
        np.testing.assert_allclose(
            out[r+DIMZ:, :, :], inp[r+DIMZ:, :, :], rtol=1e-6,
            err_msg=f"{fname}: bottom z-halo modified")
        np.testing.assert_allclose(
            out[r:r+DIMZ, r:r+DIMY, :r],
            inp[r:r+DIMZ, r:r+DIMY, :r], rtol=1e-6,
            err_msg=f"{fname}: left x-halo modified")
