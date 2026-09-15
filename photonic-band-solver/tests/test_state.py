#!/usr/bin/env python3
"""Tests for 2D Photonic Crystal Band Structure Solver with material resolution
and convergence analysis."""


import json
import os
import subprocess
import pytest


SOLVER = "/app/solve_bands.py"
OPTIMIZER = "/app/optimize_gap.py"
CONVERGENCE = "/app/convergence.py"
MATERIALS_DB = "/app/data/materials.json"


def write_config(config, path="/tmp/test_config.json"):
    with open(path, "w") as f:
        json.dump(config, f)
    return path


def run_solver(config, timeout=120):
    config_path = write_config(config, f"/tmp/config_{id(config)}.json")
    result = subprocess.run(
        ["python3", SOLVER, config_path],
        capture_output=True, text=True, timeout=timeout, cwd="/app"
    )
    assert result.returncode == 0, (
        f"Solver failed.\nstderr: {result.stderr[:500]}\nstdout: {result.stdout[:500]}"
    )
    with open("/app/results.json") as f:
        return json.load(f)


def run_optimizer(config, timeout=300):
    config_path = write_config(config, "/tmp/opt_config.json")
    result = subprocess.run(
        ["python3", OPTIMIZER, config_path],
        capture_output=True, text=True, timeout=timeout, cwd="/app"
    )
    assert result.returncode == 0, (
        f"Optimizer failed.\nstderr: {result.stderr[:500]}\nstdout: {result.stdout[:500]}"
    )
    with open("/app/opt_result.json") as f:
        return json.load(f)


def run_convergence(config, timeout=300):
    config_path = write_config(config, "/tmp/conv_config.json")
    result = subprocess.run(
        ["python3", CONVERGENCE, config_path],
        capture_output=True, text=True, timeout=timeout, cwd="/app"
    )
    assert result.returncode == 0, (
        f"Convergence script failed.\nstderr: {result.stderr[:500]}\nstdout: {result.stdout[:500]}"
    )
    with open("/app/convergence_result.json") as f:
        return json.load(f)


def find_gap(gaps, from_band, to_band):
    for g in gaps:
        if g["from_band"] == from_band and g["to_band"] == to_band:
            return g
    return None


# ---------------------------------------------------------------------------
# Fixtures: each computation runs once per session
# ---------------------------------------------------------------------------

SQUARE_CONFIG = {
    "lattice_type": "square",
    "rod_material": "high-eps-rod",
    "background_material": "air",
    "radius": 0.2,
    "num_bands": 8,
    "resolution": 20,
    "k_interp": 4,
}

TRIANGULAR_CONFIG = {
    "lattice_type": "triangular",
    "rod_material": "high-eps-rod",
    "background_material": "air",
    "radius": 0.2,
    "num_bands": 8,
    "resolution": 20,
    "k_interp": 4,
}

OPT_CONFIG = {
    "lattice_type": "triangular",
    "rod_material": "high-eps-rod",
    "background_material": "air",
    "resolution": 20,
    "k_interp": 4,
    "radius_min": 0.1,
    "radius_max": 0.3,
}

CONVERGENCE_CONFIG = {
    "lattice_type": "square",
    "rod_material": "high-eps-rod",
    "background_material": "air",
    "radius": 0.2,
    "num_bands": 8,
    "k_interp": 4,
    "target_accuracy": 0.05,
    "reference_file": "/app/data/reference/square_tm.ref",
}


@pytest.fixture(scope="session")
def square_results():
    return run_solver(SQUARE_CONFIG)


@pytest.fixture(scope="session")
def triangular_results():
    return run_solver(TRIANGULAR_CONFIG)


@pytest.fixture(scope="session")
def opt_results():
    return run_optimizer(OPT_CONFIG)


@pytest.fixture(scope="session")
def convergence_results():
    return run_convergence(CONVERGENCE_CONFIG)


# ---------------------------------------------------------------------------
# Material database tests
# ---------------------------------------------------------------------------

class TestMaterialResolution:
    """Verify the solver resolves material names from the database."""

    def test_materials_db_exists(self):
        assert os.path.isfile(MATERIALS_DB), f"{MATERIALS_DB} not found"

    def test_solver_uses_material_names(self, square_results):
        """If solver ran successfully with material names, resolution worked."""
        assert "bands" in square_results
        assert len(square_results["bands"]) >= 15

    def test_invalid_material_fails(self):
        """Solver should fail on unknown material names."""
        config = {
            "lattice_type": "square",
            "rod_material": "nonexistent_material_xyz",
            "background_material": "air",
            "radius": 0.2,
            "num_bands": 4,
            "resolution": 8,
            "k_interp": 4,
        }
        config_path = write_config(config, "/tmp/invalid_mat_config.json")
        result = subprocess.run(
            ["python3", SOLVER, config_path],
            capture_output=True, text=True, timeout=30, cwd="/app"
        )
        assert result.returncode != 0, "Solver should fail on invalid material"


# ---------------------------------------------------------------------------
# Square lattice tests
# ---------------------------------------------------------------------------

class TestSquareLattice:
    """TM band structure of square lattice rods (eps=12, r=0.2)."""

    def test_output_has_bands(self, square_results):
        assert "bands" in square_results, "Missing 'bands' key"
        assert len(square_results["bands"]) >= 15, (
            f"Expected >=15 k-points, got {len(square_results['bands'])}"
        )

    def test_output_has_gaps(self, square_results):
        assert "gaps" in square_results, "Missing 'gaps' key"

    def test_band_count(self, square_results):
        for i, row in enumerate(square_results["bands"]):
            assert len(row) == 8, f"Expected 8 bands at k-point {i}, got {len(row)}"

    def test_frequencies_non_negative(self, square_results):
        for i, row in enumerate(square_results["bands"]):
            for j, f in enumerate(row):
                assert f >= -1e-6, f"Negative freq {f} at k={i}, band={j}"

    def test_gap_exists(self, square_results):
        gap = find_gap(square_results["gaps"], 1, 2)
        assert gap is not None, "No TM gap between bands 1 and 2"

    def test_gap_percent(self, square_results):
        gap = find_gap(square_results["gaps"], 1, 2)
        assert gap is not None, "No gap found"
        assert 35.0 <= gap["gap_percent"] <= 43.0, (
            f"Gap {gap['gap_percent']:.2f}% outside [35,43] (ref: 38.95%)"
        )

    def test_lower_band_edge(self, square_results):
        gap = find_gap(square_results["gaps"], 1, 2)
        assert gap is not None
        ref = 0.2826
        err = abs(gap["gap_min"] - ref) / ref
        assert err < 0.05, (
            f"Lower edge {gap['gap_min']:.6f} has {err*100:.1f}% error vs ref {ref}"
        )

    def test_upper_band_edge(self, square_results):
        gap = find_gap(square_results["gaps"], 1, 2)
        assert gap is not None
        ref = 0.4193
        err = abs(gap["gap_max"] - ref) / ref
        assert err < 0.05, (
            f"Upper edge {gap['gap_max']:.6f} has {err*100:.1f}% error vs ref {ref}"
        )


# ---------------------------------------------------------------------------
# Triangular lattice tests
# ---------------------------------------------------------------------------

class TestTriangularLattice:
    """TM band structure of triangular lattice rods (eps=12, r=0.2)."""

    def test_gap_exists(self, triangular_results):
        gap = find_gap(triangular_results["gaps"], 1, 2)
        assert gap is not None, "No TM gap between bands 1 and 2"

    def test_gap_percent(self, triangular_results):
        gap = find_gap(triangular_results["gaps"], 1, 2)
        assert gap is not None
        assert 43.0 <= gap["gap_percent"] <= 52.0, (
            f"Gap {gap['gap_percent']:.2f}% outside [43,52] (ref: 47.47%)"
        )

    def test_lower_band_edge(self, triangular_results):
        gap = find_gap(triangular_results["gaps"], 1, 2)
        assert gap is not None
        ref = 0.2751
        err = abs(gap["gap_min"] - ref) / ref
        assert err < 0.05, (
            f"Lower edge {gap['gap_min']:.6f} has {err*100:.1f}% error vs ref {ref}"
        )

    def test_upper_band_edge(self, triangular_results):
        gap = find_gap(triangular_results["gaps"], 1, 2)
        assert gap is not None
        ref = 0.4463
        err = abs(gap["gap_max"] - ref) / ref
        assert err < 0.05, (
            f"Upper edge {gap['gap_max']:.6f} has {err*100:.1f}% error vs ref {ref}"
        )


# ---------------------------------------------------------------------------
# Optimization tests
# ---------------------------------------------------------------------------

class TestOptimization:
    """Gap optimization for triangular lattice."""

    def test_optimal_radius(self, opt_results):
        ref = 0.176
        assert abs(opt_results["optimal_radius"] - ref) < 0.02, (
            f"Optimal radius {opt_results['optimal_radius']:.6f} "
            f"not within 0.02 of {ref}"
        )

    def test_max_gap_percent(self, opt_results):
        assert 44.0 <= opt_results["max_gap_percent"] <= 53.0, (
            f"Max gap {opt_results['max_gap_percent']:.2f}% "
            f"outside [44,53] (ref: 48.6%)"
        )


# ---------------------------------------------------------------------------
# Convergence analysis tests
# ---------------------------------------------------------------------------

class TestConvergence:
    """Convergence analysis for square lattice TM bands."""

    def test_convergence_script_exists(self):
        assert os.path.isfile(CONVERGENCE), f"{CONVERGENCE} not found"

    def test_output_structure(self, convergence_results):
        required = ["min_resolution", "converged_gap_percent",
                     "reference_gap_percent", "relative_error",
                     "resolution_series"]
        for key in required:
            assert key in convergence_results, f"Missing key: {key}"

    def test_reference_gap_parsed(self, convergence_results):
        """Verify the script correctly parsed the MPB reference value."""
        ref = 38.9514660888911
        parsed = convergence_results["reference_gap_percent"]
        assert abs(parsed - ref) / ref < 0.001, (
            f"Parsed reference gap {parsed:.4f}% doesn't match "
            f"expected {ref:.4f}% from square_tm.ref"
        )

    def test_resolution_series_length(self, convergence_results):
        series = convergence_results["resolution_series"]
        assert len(series) >= 5, (
            f"Expected >=5 resolution entries, got {len(series)}"
        )

    def test_resolution_series_starts_low(self, convergence_results):
        series = convergence_results["resolution_series"]
        resolutions = [e["resolution"] for e in series]
        assert min(resolutions) <= 8, (
            f"Resolution series should start from low values, min is {min(resolutions)}"
        )

    def test_resolution_series_fields(self, convergence_results):
        series = convergence_results["resolution_series"]
        for entry in series:
            assert "resolution" in entry, "Missing 'resolution' in series entry"
            assert "gap_percent" in entry, "Missing 'gap_percent' in series entry"
            assert "error" in entry, "Missing 'error' in series entry"

    def test_min_resolution_reasonable(self, convergence_results):
        mr = convergence_results["min_resolution"]
        assert 4 <= mr <= 32, (
            f"min_resolution {mr} outside reasonable range [4, 32]"
        )

    def test_converged_within_target(self, convergence_results):
        err = convergence_results["relative_error"]
        assert err <= 0.05, (
            f"Converged relative error {err:.4f} exceeds target accuracy 0.05"
        )

    def test_errors_generally_decrease(self, convergence_results):
        """Higher resolutions should generally produce smaller errors."""
        series = convergence_results["resolution_series"]
        sorted_series = sorted(series, key=lambda e: e["resolution"])
        if len(sorted_series) >= 3:
            first_err = sorted_series[0]["error"]
            last_err = sorted_series[-1]["error"]
            assert last_err < first_err, (
                f"Error at highest resolution ({last_err:.4f}) should be less "
                f"than error at lowest resolution ({first_err:.4f})"
            )


# ---------------------------------------------------------------------------
# Structural / sanity tests
# ---------------------------------------------------------------------------

class TestSolverBasics:
    """Verify solver scripts exist and produce valid JSON."""

    def test_solver_exists(self):
        assert os.path.isfile(SOLVER), f"{SOLVER} not found"

    def test_optimizer_exists(self):
        assert os.path.isfile(OPTIMIZER), f"{OPTIMIZER} not found"

    def test_bands_monotonic_at_each_k(self, square_results):
        """Bands should be sorted in ascending order at each k-point."""
        for i, row in enumerate(square_results["bands"]):
            for j in range(len(row) - 1):
                assert row[j] <= row[j + 1] + 1e-6, (
                    f"Bands not sorted at k={i}: band {j}={row[j]} > "
                    f"band {j+1}={row[j+1]}"
                )

    def test_gap_min_less_than_gap_max(self, square_results):
        for g in square_results["gaps"]:
            assert g["gap_min"] < g["gap_max"], (
                f"gap_min {g['gap_min']} >= gap_max {g['gap_max']}"
            )

    def test_no_meep_installed(self):
        """External EM packages should not be available."""
        r = subprocess.run(
            ["python3", "-c", "import meep"],
            capture_output=True, text=True
        )
        assert r.returncode != 0, "meep should not be importable"

    def test_reference_files_exist(self):
        """Reference data files must be present in the environment."""
        for ref_file in ["square_tm.ref", "triangular_tm.ref",
                         "triangular_optimal.ref"]:
            path = f"/app/data/reference/{ref_file}"
            assert os.path.isfile(path), f"Reference file {path} not found"
