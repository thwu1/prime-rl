"""
Tests for the bathymetric gridding optimization pipeline.

"""

import json
import os
import subprocess

import numpy as np
import pandas as pd
import pytest

RESULTS_DIR = "/app/results"
TENSIONS = [0.0, 0.1, 0.25, 0.35, 0.5, 0.75, 1.0]


class TestCrossValidation:
    """Verify cross-validation results."""

    def test_cv_results_exist(self):
        path = os.path.join(RESULTS_DIR, "cv_results.csv")
        assert os.path.exists(path), f"Missing {path}"

    def test_cv_results_format(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "cv_results.csv"))
        assert list(df.columns) == ["tension", "mean_rmse"], (
            f"Expected columns [tension, mean_rmse], got {list(df.columns)}"
        )
        assert len(df) == 7, f"Expected 7 rows (one per tension), got {len(df)}"

    def test_cv_tensions_valid(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "cv_results.csv"))
        for t in df["tension"]:
            assert t in TENSIONS, f"Unexpected tension value: {t}"
        assert set(df["tension"].tolist()) == set(TENSIONS)

    def test_cv_rmse_positive_finite(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "cv_results.csv"))
        for _, row in df.iterrows():
            rmse = row["mean_rmse"]
            assert np.isfinite(rmse), (
                f"Non-finite RMSE for tension={row['tension']}: {rmse}"
            )
            assert rmse > 0, (
                f"Non-positive RMSE for tension={row['tension']}: {rmse}"
            )

    def test_cv_rmse_reasonable_range(self):
        """RMSE for bathymetry (meters) should be in a reasonable range."""
        df = pd.read_csv(os.path.join(RESULTS_DIR, "cv_results.csv"))
        for _, row in df.iterrows():
            assert 1 < row["mean_rmse"] < 10000, (
                f"RMSE {row['mean_rmse']} for tension={row['tension']} "
                f"is outside reasonable range for bathymetry data"
            )

    def test_cv_rmse_variation(self):
        """Different tensions should produce different RMSE values."""
        df = pd.read_csv(os.path.join(RESULTS_DIR, "cv_results.csv"))
        assert df["mean_rmse"].std() > 0, (
            "All RMSE values are identical -- cross-validation may not be working"
        )


class TestOptimalTension:
    """Verify optimal tension selection."""

    def test_optimal_tension_exists(self):
        path = os.path.join(RESULTS_DIR, "optimal_tension.txt")
        assert os.path.exists(path), f"Missing {path}"

    def test_optimal_tension_valid(self):
        with open(os.path.join(RESULTS_DIR, "optimal_tension.txt")) as f:
            tension = float(f.read().strip())
        assert tension in TENSIONS, (
            f"Optimal tension {tension} is not in the candidate list {TENSIONS}"
        )

    def test_optimal_tension_matches_cv_minimum(self):
        with open(os.path.join(RESULTS_DIR, "optimal_tension.txt")) as f:
            optimal = float(f.read().strip())
        df = pd.read_csv(os.path.join(RESULTS_DIR, "cv_results.csv"))
        best_idx = df["mean_rmse"].idxmin()
        expected = df.loc[best_idx, "tension"]
        assert optimal == expected, (
            f"Optimal tension {optimal} does not match CV minimum "
            f"(tension={expected}, RMSE={df.loc[best_idx, 'mean_rmse']:.2f})"
        )


class TestFinalGrid:
    """Verify the final grid file properties."""

    def test_grid_file_exists(self):
        path = os.path.join(RESULTS_DIR, "final_grid.nc")
        assert os.path.exists(path), f"Missing {path}"
        assert os.path.getsize(path) > 0, "Grid file is empty"

    def test_grid_properties(self):
        """Verify grid dimensions and region using GMT grdinfo."""
        result = subprocess.run(
            ["gmt", "grdinfo", "-Cn", os.path.join(RESULTS_DIR, "final_grid.nc")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"gmt grdinfo failed: {result.stderr}"
        )
        values = result.stdout.strip().split()
        assert len(values) >= 10, (
            f"grdinfo output has fewer than 10 fields: {result.stdout}"
        )
        w, e, s, n = (
            float(values[0]),
            float(values[1]),
            float(values[2]),
            float(values[3]),
        )
        dx, dy = float(values[6]), float(values[7])
        nx, ny = int(float(values[8])), int(float(values[9]))

        # Check region
        assert abs(w - 245.0) < 0.01, f"West boundary wrong: {w}"
        assert abs(e - 255.0) < 0.01, f"East boundary wrong: {e}"
        assert abs(s - 20.0) < 0.01, f"South boundary wrong: {s}"
        assert abs(n - 30.0) < 0.01, f"North boundary wrong: {n}"

        # Check spacing (10 arc-minutes = 1/6 degree)
        expected_dx = 1.0 / 6.0
        assert abs(dx - expected_dx) < 0.001, (
            f"X-spacing wrong: {dx} (expected ~{expected_dx:.6f})"
        )
        assert abs(dy - expected_dx) < 0.001, (
            f"Y-spacing wrong: {dy} (expected ~{expected_dx:.6f})"
        )

        # Check dimensions (gridline registration: 61x61)
        assert nx == 61, f"Expected nx=61, got {nx}"
        assert ny == 61, f"Expected ny=61, got {ny}"

    def test_grid_info_file(self):
        path = os.path.join(RESULTS_DIR, "grid_info.txt")
        assert os.path.exists(path), f"Missing {path}"
        with open(path) as f:
            info = f.read()
        assert len(info) > 10, "grid_info.txt is too short"
        assert "245" in info, "grid_info.txt should mention region boundary 245"
        assert "255" in info, "grid_info.txt should mention region boundary 255"


class TestResidualStats:
    """Verify residual statistics."""

    def test_residual_stats_exists(self):
        path = os.path.join(RESULTS_DIR, "residual_stats.json")
        assert os.path.exists(path), f"Missing {path}"

    def test_residual_stats_keys(self):
        with open(os.path.join(RESULTS_DIR, "residual_stats.json")) as f:
            stats = json.load(f)
        required = [
            "mean", "std", "min", "max",
            "min_lon", "min_lat", "max_lon", "max_lat",
        ]
        for key in required:
            assert key in stats, f"Missing key: {key}"
            assert isinstance(stats[key], (int, float)), (
                f"Key {key} is not a number: {type(stats[key])}"
            )
            assert np.isfinite(stats[key]), f"Key {key} is not finite: {stats[key]}"

    def test_residual_stats_values(self):
        with open(os.path.join(RESULTS_DIR, "residual_stats.json")) as f:
            stats = json.load(f)
        assert stats["std"] > 0, f"Residual std should be positive, got {stats['std']}"
        assert stats["min"] < stats["max"], (
            f"Residual min ({stats['min']}) should be less than max ({stats['max']})"
        )
        data_range = stats["max"] - stats["min"]
        assert abs(stats["mean"]) < data_range, (
            f"Residual mean ({stats['mean']}) should be smaller than range ({data_range})"
        )

    def test_residual_stats_locations(self):
        with open(os.path.join(RESULTS_DIR, "residual_stats.json")) as f:
            stats = json.load(f)
        assert 245.0 <= stats["min_lon"] <= 255.0, (
            f"min_lon out of range: {stats['min_lon']}"
        )
        assert 20.0 <= stats["min_lat"] <= 30.0, (
            f"min_lat out of range: {stats['min_lat']}"
        )
        assert 245.0 <= stats["max_lon"] <= 255.0, (
            f"max_lon out of range: {stats['max_lon']}"
        )
        assert 20.0 <= stats["max_lat"] <= 30.0, (
            f"max_lat out of range: {stats['max_lat']}"
        )


class TestProfile:
    """Verify transect profile extraction."""

    def test_profile_exists(self):
        path = os.path.join(RESULTS_DIR, "profile.csv")
        assert os.path.exists(path), f"Missing {path}"

    def test_profile_format(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "profile.csv"))
        expected_cols = ["longitude", "latitude", "distance", "depth"]
        assert list(df.columns) == expected_cols, (
            f"Expected columns {expected_cols}, got {list(df.columns)}"
        )

    def test_profile_point_count(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "profile.csv"))
        assert len(df) == 50, f"Expected 50 profile points, got {len(df)}"

    def test_profile_coordinates(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "profile.csv"))
        assert 245 <= df["longitude"].min() <= 247, (
            f"Profile start longitude unexpected: {df['longitude'].min()}"
        )
        assert 253 <= df["longitude"].max() <= 255, (
            f"Profile end longitude unexpected: {df['longitude'].max()}"
        )
        assert 21 <= df["latitude"].min() <= 23, (
            f"Profile start latitude unexpected: {df['latitude'].min()}"
        )
        assert 27 <= df["latitude"].max() <= 29, (
            f"Profile end latitude unexpected: {df['latitude'].max()}"
        )

    def test_profile_distance_monotonic(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "profile.csv"))
        diffs = df["distance"].diff().dropna()
        assert (diffs >= -1e-6).all(), (
            "Profile distance should be monotonically non-decreasing"
        )

    def test_profile_distance_starts_near_zero(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "profile.csv"))
        assert df["distance"].iloc[0] < 10, (
            f"First distance should be near zero, got {df['distance'].iloc[0]}"
        )

    def test_profile_depth_finite(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "profile.csv"))
        assert df["depth"].notna().all(), "Profile has NaN depth values"
        assert np.all(np.isfinite(df["depth"])), "Profile has non-finite depth values"


class TestProfileStats:
    """Verify profile statistics."""

    def test_profile_stats_exists(self):
        path = os.path.join(RESULTS_DIR, "profile_stats.json")
        assert os.path.exists(path), f"Missing {path}"

    def test_profile_stats_keys(self):
        with open(os.path.join(RESULTS_DIR, "profile_stats.json")) as f:
            stats = json.load(f)
        for key in ["min_depth", "max_depth", "mean_depth", "n_points"]:
            assert key in stats, f"Missing key: {key}"

    def test_profile_stats_values(self):
        with open(os.path.join(RESULTS_DIR, "profile_stats.json")) as f:
            stats = json.load(f)
        assert stats["n_points"] == 50, (
            f"Expected 50 points, got {stats['n_points']}"
        )
        assert stats["min_depth"] < stats["max_depth"], (
            f"min_depth ({stats['min_depth']}) should be less than "
            f"max_depth ({stats['max_depth']})"
        )
        assert stats["min_depth"] < 0, (
            f"min_depth should be negative (below sea level), got {stats['min_depth']}"
        )
        assert np.isfinite(stats["mean_depth"]), "mean_depth should be finite"

    def test_profile_stats_match_csv(self):
        """Profile stats should be consistent with the profile CSV data."""
        with open(os.path.join(RESULTS_DIR, "profile_stats.json")) as f:
            stats = json.load(f)
        df = pd.read_csv(os.path.join(RESULTS_DIR, "profile.csv"))
        assert abs(stats["min_depth"] - df["depth"].min()) < 0.1, (
            "min_depth in stats doesn't match profile.csv"
        )
        assert abs(stats["max_depth"] - df["depth"].max()) < 0.1, (
            "max_depth in stats doesn't match profile.csv"
        )
        assert abs(stats["mean_depth"] - df["depth"].mean()) < 0.1, (
            "mean_depth in stats doesn't match profile.csv"
        )


class TestPipelineConsistency:
    """Verify overall pipeline consistency."""

    def test_all_output_files_present(self):
        expected = [
            "cv_results.csv",
            "optimal_tension.txt",
            "final_grid.nc",
            "grid_info.txt",
            "residual_stats.json",
            "profile.csv",
            "profile_stats.json",
        ]
        for fname in expected:
            path = os.path.join(RESULTS_DIR, fname)
            assert os.path.exists(path), f"Missing output file: {fname}"

    def test_grid_depth_range_reasonable(self):
        """Grid z-values should be in a reasonable range for ocean bathymetry."""
        result = subprocess.run(
            ["gmt", "grdinfo", "-Cn", os.path.join(RESULTS_DIR, "final_grid.nc")],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            values = result.stdout.strip().split()
            zmin, zmax = float(values[4]), float(values[5])
            assert zmin < 0, f"Grid minimum should be negative, got {zmin}"
            assert -8000 < zmin, f"Grid minimum too extreme: {zmin}"
            assert zmax < 1000, f"Grid maximum too large: {zmax}"
