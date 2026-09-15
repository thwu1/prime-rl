
import json
import math
import os
import random
import shutil
import subprocess

import numpy as np
import pytest

G = 6.674e-11  # gravitational constant
MGAL = 1e5  # m/s^2 to mGal

# Primary dataset: true buried sources (easting, northing, depth, mass)
PRIMARY_SOURCES = [
    (2500.0, 7000.0, 1200.0, 5e11),
    (7000.0, 3000.0, 2000.0, 1.5e12),
    (4500.0, 5000.0, 800.0, 2e11),
    (8000.0, 8000.0, 2500.0, 2e12),
]

# Secondary dataset: different sources for generalization test
SECONDARY_SOURCES = [
    (1500.0, 2500.0, 1000.0, 4e11),
    (6000.0, 8000.0, 1800.0, 1.2e12),
    (8500.0, 4000.0, 1500.0, 8e11),
]

GRID_SPACING = 200.0
GRID_N = 51
GRID_HEIGHT = 500.0

RMS_PRIMARY = 0.02  # mGal
RMS_SECONDARY = 0.03  # mGal


def compute_gz(e, n, h, sources):
    """Downward gravitational acceleration (mGal) from point-mass sources."""
    gz = 0.0
    for xs, ys, depth, mass in sources:
        dx = e - xs
        dy = n - ys
        dz = h + depth
        r = math.sqrt(dx * dx + dy * dy + dz * dz)
        gz += G * mass * dz / (r ** 3) * MGAL
    return gz


def true_grid_values(sources):
    """Compute noise-free gravity at every prediction grid point."""
    values = []
    for ni in range(GRID_N):
        northing = ni * GRID_SPACING
        for ei in range(GRID_N):
            easting = ei * GRID_SPACING
            gz = compute_gz(easting, northing, GRID_HEIGHT, sources)
            values.append(gz)
    return values


def generate_secondary_survey(filepath, seed=123):
    """Generate a secondary survey CSV from SECONDARY_SOURCES."""
    random.seed(seed)
    with open(filepath, "w") as f:
        f.write("easting,northing,height,gz_mGal\n")
        for _ in range(400):
            e = random.uniform(200, 9800)
            n = random.uniform(200, 9800)
            h = random.uniform(100, 500)
            gz = compute_gz(e, n, h, SECONDARY_SOURCES)
            noise = random.gauss(0, 0.002)
            f.write("{:.2f},{:.2f},{:.2f},{:.10f}\n".format(e, n, h, gz + noise))


def ensure_input_files():
    """Restore input files from backup if they were overwritten."""
    for name in ("survey.csv", "prediction_grid.csv"):
        dst = "/app/" + name
        if os.path.exists(dst):
            continue
        src = "/opt/taskdata/" + name
        if os.path.exists(src):
            shutil.copy2(src, dst)


def run_pipeline(survey, grid, out_csv, out_json, timeout=240):
    """Execute the agent's pipeline script."""
    script = "/app/eqs_pipeline.py"
    assert os.path.exists(script), (
        script + " not found. The task requires creating this script."
    )
    result = subprocess.run(
        ["python3", script, survey, grid, out_csv, out_json],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, (
        "Pipeline failed (code {}).\nstdout:\n{}\nstderr:\n{}".format(
            result.returncode,
            result.stdout[-2000:],
            result.stderr[-2000:],
        )
    )


def load_predictions(path):
    """Load prediction CSV as numpy array."""
    return np.loadtxt(path, delimiter=",", skiprows=1)


def rms_error(predictions, true_values):
    """RMS between predicted gz (column 2) and true values."""
    pred = predictions[:, 2]
    true_arr = np.array(true_values)
    return float(np.sqrt(np.mean((pred - true_arr) ** 2)))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def primary_result():
    """Run pipeline on the primary survey and return (predictions, diagnostics)."""
    ensure_input_files()
    run_pipeline(
        "/app/survey.csv",
        "/app/prediction_grid.csv",
        "/app/predictions.csv",
        "/app/diagnostics.json",
    )
    preds = load_predictions("/app/predictions.csv")
    with open("/app/diagnostics.json") as f:
        diag = json.load(f)
    return preds, diag


# ---------------------------------------------------------------------------
# Tests — Output Format
# ---------------------------------------------------------------------------
class TestOutputFormat:
    def test_predictions_shape(self, primary_result):
        preds, _ = primary_result
        n_expected = GRID_N * GRID_N
        assert preds.shape[0] == n_expected, (
            "Expected {} rows, got {}".format(n_expected, preds.shape[0])
        )
        assert preds.shape[1] >= 4, (
            "predictions.csv must have >= 4 columns "
            "(easting, northing, gz_predicted, gz_uncertainty); "
            "got {}".format(preds.shape[1])
        )

    def test_no_nan_or_inf(self, primary_result):
        preds, _ = primary_result
        assert np.all(np.isfinite(preds)), "Predictions contain NaN or Inf"

    def test_diagnostics_keys(self, primary_result):
        _, diag = primary_result
        for key in (
            "damping",
            "rms_misfit",
            "source_depth",
            "n_sources",
            "mean_prediction_uncertainty",
        ):
            assert key in diag, "Missing diagnostics key: " + key


# ---------------------------------------------------------------------------
# Tests — Diagnostics Sanity
# ---------------------------------------------------------------------------
class TestDiagnostics:
    def test_damping_positive(self, primary_result):
        _, diag = primary_result
        assert diag["damping"] > 0, "damping must be positive"

    def test_depth_positive(self, primary_result):
        _, diag = primary_result
        assert diag["source_depth"] > 0, "source_depth must be positive"

    def test_depth_reasonable(self, primary_result):
        _, diag = primary_result
        assert diag["source_depth"] < 10000, (
            "source_depth {} m unreasonably large".format(diag["source_depth"])
        )

    def test_rms_misfit_reasonable(self, primary_result):
        _, diag = primary_result
        assert diag["rms_misfit"] < 0.1, (
            "RMS misfit {:.6f} mGal too large".format(diag["rms_misfit"])
        )

    def test_n_sources_positive(self, primary_result):
        _, diag = primary_result
        assert diag["n_sources"] > 0

    def test_mean_uncertainty_positive(self, primary_result):
        _, diag = primary_result
        assert diag["mean_prediction_uncertainty"] > 0

    def test_mean_uncertainty_reasonable(self, primary_result):
        _, diag = primary_result
        assert diag["mean_prediction_uncertainty"] < 0.05, (
            "Mean uncertainty {:.6f} mGal too large".format(
                diag["mean_prediction_uncertainty"]
            )
        )


# ---------------------------------------------------------------------------
# Tests — Uncertainty Column
# ---------------------------------------------------------------------------
class TestUncertainty:
    def test_uncertainty_all_positive(self, primary_result):
        preds, _ = primary_result
        unc = preds[:, 3]
        assert np.all(unc > 0), "All prediction uncertainties must be positive"

    def test_uncertainty_all_finite(self, primary_result):
        preds, _ = primary_result
        unc = preds[:, 3]
        assert np.all(np.isfinite(unc)), "Uncertainties contain NaN or Inf"


# ---------------------------------------------------------------------------
# Tests — Primary Dataset Accuracy
# ---------------------------------------------------------------------------
class TestPrimaryAccuracy:
    def test_prediction_rms(self, primary_result):
        preds, _ = primary_result
        true_vals = true_grid_values(PRIMARY_SOURCES)
        rms = rms_error(preds, true_vals)
        assert rms < RMS_PRIMARY, (
            "RMS prediction error {:.6f} mGal exceeds threshold {} mGal".format(
                rms, RMS_PRIMARY
            )
        )


# ---------------------------------------------------------------------------
# Tests — Secondary Dataset (generalization)
# ---------------------------------------------------------------------------
class TestSecondaryAccuracy:
    def test_secondary_rms(self):
        generate_secondary_survey("/tmp/sec_survey.csv")
        run_pipeline(
            "/tmp/sec_survey.csv",
            "/app/prediction_grid.csv",
            "/tmp/sec_predictions.csv",
            "/tmp/sec_diagnostics.json",
        )
        preds = load_predictions("/tmp/sec_predictions.csv")
        true_vals = true_grid_values(SECONDARY_SOURCES)
        rms = rms_error(preds, true_vals)
        assert rms < RMS_SECONDARY, (
            "Secondary RMS error {:.6f} mGal exceeds threshold {} mGal".format(
                rms, RMS_SECONDARY
            )
        )
