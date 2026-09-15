
"""Tests for PWATER pervious land water budget simulation with HDF5 output."""

import csv
import os
import pytest
import h5py
import numpy as np


def load_reference_csv(path):
    """Load reference CSV and return list of dicts with float values."""
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: float(v) for k, v in row.items()})
    return rows


def load_forcing_csv(path):
    """Load forcing CSV and return list of (PREC, PETINP) tuples."""
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((float(row['PREC']), float(row['PETINP'])))
    return rows


def str_attr(obj, name):
    """Read an HDF5 attribute and return as str (handles bytes or str)."""
    val = obj.attrs[name]
    if isinstance(val, bytes):
        return val.decode('utf-8')
    return str(val)


@pytest.fixture
def h5file():
    """Open solver's HDF5 output."""
    path = "/app/output.h5"
    assert os.path.exists(path), f"Output file {path} not found. Did pwater.py run?"
    f = h5py.File(path, 'r')
    yield f
    f.close()


@pytest.fixture
def reference_data():
    """Load reference output from validated HSPF simulation."""
    return load_reference_csv("/tests/reference.csv")


@pytest.fixture
def forcing_data():
    """Load forcing input data."""
    return load_forcing_csv("/app/forcing.csv")


# ---------------------------------------------------------------------------
# HDF5 Structure Validation
# ---------------------------------------------------------------------------


class TestHDF5Structure:
    """Validate HDF5 file structure, groups, datasets, attributes, compression."""

    def test_file_exists_and_valid(self):
        assert os.path.exists("/app/output.h5"), "output.h5 not found"
        assert h5py.is_hdf5("/app/output.h5"), "output.h5 is not a valid HDF5 file"

    def test_pwater_group_exists(self, h5file):
        assert "/PERLND/P101/PWATER" in h5file, "Missing group /PERLND/P101/PWATER"

    def test_state_group_exists(self, h5file):
        assert "/PERLND/P101/STATE" in h5file, "Missing group /PERLND/P101/STATE"

    def test_summary_group_exists(self, h5file):
        assert "/SUMMARY" in h5file, "Missing group /SUMMARY"

    def test_flow_datasets_present(self, h5file):
        g = h5file["/PERLND/P101/PWATER"]
        for name in ["SURO", "IFWO", "AGWO", "PERO"]:
            assert name in g, f"Missing dataset PWATER/{name}"

    def test_state_datasets_present(self, h5file):
        g = h5file["/PERLND/P101/STATE"]
        for name in ["UZS", "LZS", "AGWS"]:
            assert name in g, f"Missing dataset STATE/{name}"

    def test_flow_dataset_shapes(self, h5file, reference_data):
        n = len(reference_data)
        g = h5file["/PERLND/P101/PWATER"]
        for name in ["SURO", "IFWO", "AGWO", "PERO"]:
            assert g[name].shape == (n,), (
                f"PWATER/{name} shape {g[name].shape} != ({n},)"
            )

    def test_state_dataset_shapes(self, h5file, reference_data):
        n = len(reference_data)
        g = h5file["/PERLND/P101/STATE"]
        for name in ["UZS", "LZS", "AGWS"]:
            assert g[name].shape == (n,), (
                f"STATE/{name} shape {g[name].shape} != ({n},)"
            )

    def test_dataset_dtype_float64(self, h5file):
        for path in ["/PERLND/P101/PWATER", "/PERLND/P101/STATE"]:
            g = h5file[path]
            for name in g:
                assert g[name].dtype == np.float64, (
                    f"{path}/{name} dtype {g[name].dtype} != float64"
                )

    def test_flow_datasets_gzip_compressed(self, h5file):
        g = h5file["/PERLND/P101/PWATER"]
        for name in ["SURO", "IFWO", "AGWO", "PERO"]:
            assert g[name].compression == "gzip", (
                f"PWATER/{name} compression={g[name].compression}, expected gzip"
            )

    def test_state_datasets_gzip_compressed(self, h5file):
        g = h5file["/PERLND/P101/STATE"]
        for name in ["UZS", "LZS", "AGWS"]:
            assert g[name].compression == "gzip", (
                f"STATE/{name} compression={g[name].compression}, expected gzip"
            )

    def test_root_model_attribute(self, h5file):
        assert "model" in h5file.attrs, "Missing root attribute 'model'"
        assert str_attr(h5file, "model") == "HSP2-PWATER", (
            f"model attribute = '{str_attr(h5file, 'model')}', expected 'HSP2-PWATER'"
        )

    def test_root_segment_id_attribute(self, h5file):
        assert "segment_id" in h5file.attrs, "Missing root attribute 'segment_id'"
        assert str_attr(h5file, "segment_id") == "P101", (
            f"segment_id attribute = '{str_attr(h5file, 'segment_id')}', expected 'P101'"
        )

    def test_summary_attributes_present(self, h5file):
        g = h5file["/SUMMARY"]
        for attr in ["total_precip", "total_outflow", "total_et",
                      "water_balance_error", "simulation_hours"]:
            assert attr in g.attrs, f"Missing SUMMARY attribute '{attr}'"


# ---------------------------------------------------------------------------
# Cumulative Flow Accuracy
# ---------------------------------------------------------------------------


class TestCumulativeSums:
    """Verify cumulative flow sums against reference within tolerance."""

    TOLERANCE = 0.01  # inches over simulation period

    def test_cumulative_suro(self, h5file, reference_data):
        suro = h5file["/PERLND/P101/PWATER/SURO"][:]
        ref_sum = sum(r["SURO"] for r in reference_data)
        diff = abs(suro.sum() - ref_sum)
        assert diff < self.TOLERANCE, (
            f"Cumulative SURO diff {diff:.6f} >= {self.TOLERANCE}. "
            f"Computed={suro.sum():.6f}, Reference={ref_sum:.6f}"
        )

    def test_cumulative_ifwo(self, h5file, reference_data):
        ifwo = h5file["/PERLND/P101/PWATER/IFWO"][:]
        ref_sum = sum(r["IFWO"] for r in reference_data)
        diff = abs(ifwo.sum() - ref_sum)
        assert diff < self.TOLERANCE, (
            f"Cumulative IFWO diff {diff:.6f} >= {self.TOLERANCE}. "
            f"Computed={ifwo.sum():.6f}, Reference={ref_sum:.6f}"
        )

    def test_cumulative_agwo(self, h5file, reference_data):
        agwo = h5file["/PERLND/P101/PWATER/AGWO"][:]
        ref_sum = sum(r["AGWO"] for r in reference_data)
        diff = abs(agwo.sum() - ref_sum)
        assert diff < self.TOLERANCE, (
            f"Cumulative AGWO diff {diff:.6f} >= {self.TOLERANCE}. "
            f"Computed={agwo.sum():.6f}, Reference={ref_sum:.6f}"
        )

    def test_cumulative_pero(self, h5file, reference_data):
        """Total pervious outflow (SURO + IFWO + AGWO) must match."""
        pero = h5file["/PERLND/P101/PWATER/PERO"][:]
        ref_sum = sum(r["SURO"] + r["IFWO"] + r["AGWO"] for r in reference_data)
        diff = abs(pero.sum() - ref_sum)
        assert diff < self.TOLERANCE, (
            f"Cumulative PERO diff {diff:.6f} >= {self.TOLERANCE}"
        )


# ---------------------------------------------------------------------------
# Per-Step Accuracy
# ---------------------------------------------------------------------------


class TestPerStepAccuracy:
    """Verify per-step accuracy at specific points."""

    MAX_STEP_ERROR = 0.001

    def test_first_step_ifwo(self, h5file, reference_data):
        val = h5file["/PERLND/P101/PWATER/IFWO"][0]
        ref = reference_data[0]["IFWO"]
        diff = abs(val - ref)
        assert diff < self.MAX_STEP_ERROR, (
            f"Step 0 IFWO error {diff:.8f}: computed={val:.8f}, ref={ref:.8f}"
        )

    def test_first_step_agwo(self, h5file, reference_data):
        val = h5file["/PERLND/P101/PWATER/AGWO"][0]
        ref = reference_data[0]["AGWO"]
        diff = abs(val - ref)
        assert diff < self.MAX_STEP_ERROR, (
            f"Step 0 AGWO error {diff:.8f}: computed={val:.8f}, ref={ref:.8f}"
        )

    def test_mid_simulation_accuracy(self, h5file, reference_data):
        step = min(180, len(reference_data) - 1)
        for var in ["SURO", "IFWO", "AGWO"]:
            val = h5file[f"/PERLND/P101/PWATER/{var}"][step]
            ref = reference_data[step][var]
            diff = abs(val - ref)
            assert diff < self.MAX_STEP_ERROR, (
                f"Step {step} {var} error {diff:.8f}: "
                f"computed={val:.8f}, ref={ref:.8f}"
            )

    def test_rain_event_response(self, h5file, reference_data):
        for i, row in enumerate(reference_data):
            if row["SURO"] > 1e-6:
                for var in ["SURO", "IFWO", "AGWO"]:
                    val = h5file[f"/PERLND/P101/PWATER/{var}"][i]
                    diff = abs(val - row[var])
                    assert diff < self.MAX_STEP_ERROR, (
                        f"Rain event step {i} {var} error {diff:.8f}"
                    )
                break


# ---------------------------------------------------------------------------
# Physical Constraints
# ---------------------------------------------------------------------------


class TestPhysicalConstraints:
    """Verify physical reasonableness of output."""

    def test_non_negative_flows(self, h5file):
        for var in ["SURO", "IFWO", "AGWO", "PERO"]:
            data = h5file[f"/PERLND/P101/PWATER/{var}"][:]
            assert np.all(data >= 0), f"Negative values in PWATER/{var}"

    def test_non_negative_states(self, h5file):
        for var in ["UZS", "LZS", "AGWS"]:
            data = h5file[f"/PERLND/P101/STATE/{var}"][:]
            assert np.all(data >= 0), f"Negative values in STATE/{var}"

    def test_pero_equals_component_sum(self, h5file):
        """PERO must equal SURO + IFWO + AGWO at every step."""
        suro = h5file["/PERLND/P101/PWATER/SURO"][:]
        ifwo = h5file["/PERLND/P101/PWATER/IFWO"][:]
        agwo = h5file["/PERLND/P101/PWATER/AGWO"][:]
        pero = h5file["/PERLND/P101/PWATER/PERO"][:]
        assert np.allclose(pero, suro + ifwo + agwo, atol=1e-10), (
            "PERO != SURO + IFWO + AGWO at some timestep(s)"
        )

    def test_initial_dry_period_no_surface_runoff(self, h5file, forcing_data):
        suro = h5file["/PERLND/P101/PWATER/SURO"][:]
        for i in range(min(24, len(suro))):
            if forcing_data[i][0] == 0.0:  # PREC == 0
                assert suro[i] < 1e-8, (
                    f"SURO should be ~0 during dry period at step {i}: {suro[i]}"
                )

    def test_surface_runoff_during_rain(self, h5file):
        suro = h5file["/PERLND/P101/PWATER/SURO"][:]
        assert np.any(suro > 1e-6), "No surface runoff detected during simulation"

    def test_interflow_positive_initially(self, h5file):
        ifwo = h5file["/PERLND/P101/PWATER/IFWO"][0]
        assert ifwo > 0, "IFWO should be positive at step 0 (initial IFWS > 0)"

    def test_groundwater_recession_during_dry(self, h5file, forcing_data):
        agwo = h5file["/PERLND/P101/PWATER/AGWO"][:]
        dry_vals = []
        for i in range(min(7, len(agwo))):
            if forcing_data[i][0] == 0 and forcing_data[i][1] == 0:
                dry_vals.append(float(agwo[i]))
        if len(dry_vals) >= 3:
            assert dry_vals[0] >= dry_vals[-1] * 0.99, (
                f"AGWO should be roughly stable during short dry period: {dry_vals}"
            )


# ---------------------------------------------------------------------------
# Water Balance
# ---------------------------------------------------------------------------


class TestWaterBalance:
    """Verify water balance closure and summary attributes."""

    def test_water_balance_error_small(self, h5file):
        err = float(h5file["/SUMMARY"].attrs["water_balance_error"])
        assert err < 0.05, f"Water balance error {err:.6f} >= 0.05 inches"

    def test_simulation_hours_correct(self, h5file, reference_data):
        hours = int(h5file["/SUMMARY"].attrs["simulation_hours"])
        assert hours == len(reference_data), (
            f"simulation_hours={hours}, expected {len(reference_data)}"
        )

    def test_total_precip_positive(self, h5file):
        tp = float(h5file["/SUMMARY"].attrs["total_precip"])
        assert tp > 0, "total_precip should be > 0"

    def test_total_outflow_matches_pero_sum(self, h5file):
        total_outflow = float(h5file["/SUMMARY"].attrs["total_outflow"])
        pero = h5file["/PERLND/P101/PWATER/PERO"][:]
        assert abs(total_outflow - float(pero.sum())) < 1e-8, (
            f"total_outflow attribute {total_outflow:.8f} != sum(PERO) {float(pero.sum()):.8f}"
        )

    def test_total_et_non_negative(self, h5file):
        te = float(h5file["/SUMMARY"].attrs["total_et"])
        assert te >= 0, f"total_et should be >= 0, got {te}"
