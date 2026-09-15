
"""
Tests for QEC code distance calculator.

Tests generate fresh detector error models (from Stim-generated QEC codes and
hand-crafted examples) and verify that /app/compute_distance.py outputs the
correct code distance for each.
"""

import subprocess
import tempfile
import os

import stim
import pytest


def run_distance(dem_path: str) -> int:
    """Run the agent's compute_distance.py and return the parsed integer result."""
    result = subprocess.run(
        ["python3", "/app/compute_distance.py", dem_path],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"compute_distance.py failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    output = result.stdout.strip()
    assert output.lstrip("-").isdigit(), (
        f"Expected integer output, got: {output!r}"
    )
    return int(output)


def write_dem(content: str) -> str:
    """Write a DEM string to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(
        suffix=".dem", mode="w", delete=False, dir="/tmp"
    )
    f.write(content)
    f.close()
    return f.name


def stim_dem_path(code_task: str, distance: int, rounds: int, noise: float) -> str:
    """Generate a DEM from a Stim circuit and return the temp file path."""
    c = stim.Circuit.generated(
        code_task,
        rounds=rounds,
        distance=distance,
        after_clifford_depolarization=noise,
    )
    dem = c.detector_error_model(decompose_errors=True)
    return write_dem(str(dem))


# ---------------------------------------------------------------------------
# Test: script exists
# ---------------------------------------------------------------------------


class TestScriptExists:
    def test_file_exists(self):
        assert os.path.isfile("/app/compute_distance.py"), (
            "/app/compute_distance.py not found"
        )


# ---------------------------------------------------------------------------
# Tests on Stim-generated repetition codes
# ---------------------------------------------------------------------------


class TestRepetitionCode:
    def test_distance_3(self):
        path = stim_dem_path(
            "repetition_code:memory", distance=3, rounds=3, noise=0.01
        )
        assert run_distance(path) == 3
        os.unlink(path)

    def test_distance_5(self):
        path = stim_dem_path(
            "repetition_code:memory", distance=5, rounds=5, noise=0.01
        )
        assert run_distance(path) == 5
        os.unlink(path)

    def test_distance_7(self):
        path = stim_dem_path(
            "repetition_code:memory", distance=7, rounds=7, noise=0.01
        )
        assert run_distance(path) == 7
        os.unlink(path)


# ---------------------------------------------------------------------------
# Tests on Stim-generated rotated surface codes
# ---------------------------------------------------------------------------


class TestSurfaceCode:
    def test_distance_3(self):
        path = stim_dem_path(
            "surface_code:rotated_memory_z", distance=3, rounds=3, noise=0.001
        )
        assert run_distance(path) == 3
        os.unlink(path)

    def test_distance_5(self):
        path = stim_dem_path(
            "surface_code:rotated_memory_z", distance=5, rounds=5, noise=0.001
        )
        assert run_distance(path) == 5
        os.unlink(path)


# ---------------------------------------------------------------------------
# Tests on hand-crafted DEMs with known distances
# ---------------------------------------------------------------------------


class TestCustomDEM:
    def test_distance_1_bare_observable(self):
        """Single error flipping observable with no detectors => distance 1."""
        path = write_dem("error(0.1) L0\n")
        assert run_distance(path) == 1
        os.unlink(path)

    def test_distance_2_boundary_pair(self):
        """Two boundary-connected errors needed to cancel the detector."""
        dem = (
            "error(0.1) D0 L0\n"
            "error(0.1) D0\n"
        )
        path = write_dem(dem)
        assert run_distance(path) == 2
        os.unlink(path)

    def test_distance_3_chain(self):
        """Linear chain of 3 errors."""
        dem = (
            "error(0.1) D0 L0\n"
            "error(0.1) D0 D1\n"
            "error(0.1) D1\n"
        )
        path = write_dem(dem)
        assert run_distance(path) == 3
        os.unlink(path)

    def test_distance_4_chain(self):
        """Linear chain of 4 errors."""
        dem = (
            "error(0.1) D0 L0\n"
            "error(0.1) D0 D1\n"
            "error(0.1) D1 D2\n"
            "error(0.1) D2\n"
        )
        path = write_dem(dem)
        assert run_distance(path) == 4
        os.unlink(path)

    def test_distance_3_branching(self):
        """Branching graph where shortest path has length 3 (via short branch)."""
        dem = (
            "error(0.1) D0 L0\n"   # boundary -> D0, flips L0
            "error(0.1) D0 D1\n"   # D0 -> D1
            "error(0.1) D1 D2\n"   # D1 -> D2
            "error(0.1) D2\n"      # D2 -> boundary  (long path: 4)
            "error(0.1) D0 D3\n"   # D0 -> D3
            "error(0.1) D3\n"      # D3 -> boundary  (short path: 3)
        )
        path = write_dem(dem)
        assert run_distance(path) == 3
        os.unlink(path)


# ---------------------------------------------------------------------------
# Edge-case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_parallel_edges_different_observables(self):
        """Two edges between same detector pair, one flipping observable.
        Combined, they cancel detectors and flip observable => distance 2."""
        dem = (
            "error(0.1) D0 D1 L0\n"
            "error(0.1) D0 D1\n"
        )
        path = write_dem(dem)
        assert run_distance(path) == 2
        os.unlink(path)

    def test_multiple_observables_min(self):
        """Two observables with different distances; result is the minimum.
        L0 has distance 3, L1 has distance 2 => overall distance 2."""
        dem = (
            "error(0.1) D0 L0\n"   # boundary -> D0, flips L0
            "error(0.1) D0 D1\n"   # D0 -> D1
            "error(0.1) D1 L1\n"   # boundary -> D1, flips L1
            "error(0.1) D1\n"      # boundary -> D1
        )
        path = write_dem(dem)
        assert run_distance(path) == 2
        os.unlink(path)
