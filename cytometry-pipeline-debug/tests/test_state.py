"""
test_state.py — Verification tests for the flow cytometry pipeline.

Each test independently computes expected values and compares against
the pipeline output. The tests cover:
  1. FCS binary parsing correctness
  2. Spillover compensation accuracy
  3. Logicle transform numerical correctness
  4. Rectangle gating population counts
  5. Output structure and metadata

"""

import json
import os
import numpy as np
from scipy.optimize import brentq
import pytest


# ============================================================================
# Reference implementations for independent verification
# ============================================================================

def get_spillover_matrix():
    """Return the 4x4 spillover matrix matching the FCS $SPILLOVER keyword."""
    return np.array([
        [1.0,   0.25,  0.01,  0.002],
        [0.1,   1.0,   0.20,  0.01],
        [0.005, 0.15,  1.0,   0.15],
        [0.001, 0.01,  0.10,  1.0],
    ])


def reference_compensate(raw_data, fl_indices):
    """Apply correct spillover compensation: raw @ inv(spillover)."""
    S = get_spillover_matrix()
    result = raw_data.copy()
    result[:, fl_indices] = raw_data[:, fl_indices] @ np.linalg.inv(S)
    return result


def reference_logicle_params(T=262144, W=0.5, M=4.5, A=0):
    """Compute correct logicle internal parameters."""
    w = W / (M + A)
    x2 = A / (M + A)
    x1 = x2 + w
    x0 = x2 + 2 * w
    b = (M + A) * np.log(10)

    # Correct equation: 2*(ln(d) - ln(b)) + b*(x1 - x0) = 0
    def eq(d):
        return 2 * (np.log(d) - np.log(b)) + b * (x1 - x0)

    d = brentq(eq, 1e-10, 100, xtol=1e-14)

    c_a = np.exp(x0 * (b + d))
    mf_a = np.exp(b * x1) - c_a / np.exp(d * x1)
    a = T / ((np.exp(b) - mf_a) - c_a / np.exp(d))
    c = c_a * a
    f = -mf_a * a

    return dict(a=a, b=b, c=c, d=d, f=f, w=w,
                x0=x0, x1=x1, x2=x2, T=T, W=W, M=M, A=A)


def reference_logicle_transform(data, T=262144, W=0.5, M=4.5, A=0):
    """Vectorized logicle transform using Newton's method."""
    params = reference_logicle_params(T, W, M, A)
    a, b, c, d, f = params["a"], params["b"], params["c"], params["d"], params["f"]
    M_val = params["M"]
    x1 = params["x1"]

    data = np.asarray(data, dtype=np.float64)

    # Initial guesses
    y = np.where(
        data > 0,
        np.maximum(np.log(np.maximum(data / a, 1e-30)) / b, x1),
        np.where(
            data < 0,
            np.minimum(-np.log(np.maximum(-data / c, 1e-30)) / d, x1),
            x1
        ),
    )

    # Newton iterations
    for _ in range(200):
        exp_by = np.exp(np.clip(b * y, -500, 500))
        exp_ndy = np.exp(np.clip(-d * y, -500, 500))
        By = a * exp_by - c * exp_ndy + f
        Bpy = a * b * exp_by + c * d * exp_ndy
        Bpy = np.where(np.abs(Bpy) < 1e-300, 1e-300, Bpy)
        delta = (By - data) / Bpy
        y = y - delta
        if np.max(np.abs(delta)) < 1e-12:
            break

    return y * M_val


# ============================================================================
# Load pipeline outputs
# ============================================================================

RAW_CSV = "/app/data/test_sample_raw.csv"
PARSED_CSV = "/app/output/parsed_data.csv"
COMP_CSV = "/app/output/compensated_data.csv"
TRANS_CSV = "/app/output/transformed_data.csv"
GATE_JSON = "/app/output/gate_results.json"
SUMMARY_JSON = "/app/output/summary.json"

PARAM_NAMES = ["FSC-H", "SSC-H", "FL1-H", "FL2-H",
               "FL3-H", "FL4-H", "Time", "FSC-A"]
FL_INDICES = [2, 3, 4, 5]  # FL1-H through FL4-H


def load_csv(path):
    """Load a CSV with header row."""
    return np.loadtxt(path, delimiter=",", skiprows=1)


# ============================================================================
# Tests
# ============================================================================

class TestFCSParsing:
    """Verify that the FCS binary file is parsed correctly."""

    def test_output_exists(self):
        assert os.path.exists(PARSED_CSV), \
            f"Parsed data file not found: {PARSED_CSV}"

    def test_dimensions(self):
        raw = load_csv(RAW_CSV)
        parsed = load_csv(PARSED_CSV)
        assert parsed.shape == raw.shape, \
            f"Shape mismatch: parsed {parsed.shape} vs raw {raw.shape}"

    def test_values_match_raw(self):
        """Parsed float values must match the original data matrix."""
        raw = load_csv(RAW_CSV)
        parsed = load_csv(PARSED_CSV)
        np.testing.assert_allclose(
            parsed, raw, rtol=1e-5, atol=1e-5,
            err_msg="Parsed data does not match raw FCS binary content"
        )


class TestCompensation:
    """Verify that spillover compensation is applied correctly."""

    def test_output_exists(self):
        assert os.path.exists(COMP_CSV), \
            f"Compensated data file not found: {COMP_CSV}"

    def test_scatter_channels_unchanged(self):
        """Scatter channels (FSC-H, SSC-H) should not be affected."""
        raw = load_csv(RAW_CSV)
        comp = load_csv(COMP_CSV)
        for idx in [0, 1, 6, 7]:  # FSC-H, SSC-H, Time, FSC-A
            np.testing.assert_allclose(
                comp[:, idx], raw[:, idx], rtol=1e-5,
                err_msg=f"Non-fluorescence channel {idx} was modified"
            )

    def test_compensation_values(self):
        """Compensated FL values must match raw @ inv(spillover)."""
        raw = load_csv(RAW_CSV)
        comp = load_csv(COMP_CSV)
        expected = reference_compensate(raw, FL_INDICES)
        np.testing.assert_allclose(
            comp[:, FL_INDICES], expected[:, FL_INDICES],
            rtol=1e-4, atol=1e-2,
            err_msg="Compensation values do not match inv(spillover) result"
        )

    def test_compensation_is_not_identity(self):
        """Compensation should actually change the fluorescence values."""
        raw = load_csv(RAW_CSV)
        comp = load_csv(COMP_CSV)
        diff = np.abs(comp[:, FL_INDICES] - raw[:, FL_INDICES])
        assert np.mean(diff) > 1.0, \
            "Compensation had negligible effect — likely not applied"


class TestLogicleTransform:
    """Verify the logicle biexponential transform."""

    def test_output_exists(self):
        assert os.path.exists(TRANS_CSV), \
            f"Transformed data file not found: {TRANS_CSV}"

    def test_scatter_unchanged(self):
        """Non-fluorescence channels must pass through unchanged."""
        comp = load_csv(COMP_CSV)
        trans = load_csv(TRANS_CSV)
        for idx in [0, 1, 6, 7]:
            np.testing.assert_allclose(
                trans[:, idx], comp[:, idx], rtol=1e-5,
                err_msg=f"Non-FL channel {idx} was modified by transform"
            )

    def test_transform_values(self):
        """Logicle-transformed values must match reference implementation."""
        comp = load_csv(COMP_CSV)
        trans = load_csv(TRANS_CSV)

        for idx in FL_INDICES:
            expected = reference_logicle_transform(comp[:, idx])
            np.testing.assert_allclose(
                trans[:, idx], expected,
                rtol=1e-4, atol=1e-3,
                err_msg=f"Logicle transform mismatch for channel index {idx}"
            )

    def test_transform_range(self):
        """Transformed FL values should be in a reasonable display range."""
        trans = load_csv(TRANS_CSV)
        for idx in FL_INDICES:
            col = trans[:, idx]
            assert np.all(np.isfinite(col)), \
                f"Channel {idx} has non-finite transformed values"
            assert np.min(col) >= -1.0, \
                f"Channel {idx} min too low: {np.min(col)}"
            assert np.max(col) <= 5.0, \
                f"Channel {idx} max too high: {np.max(col)}"

    def test_transform_monotonicity(self):
        """Logicle transform must be monotonically increasing."""
        trans = load_csv(TRANS_CSV)
        comp = load_csv(COMP_CSV)
        for idx in FL_INDICES:
            raw_vals = comp[:, idx]
            trans_vals = trans[:, idx]
            order = np.argsort(raw_vals)
            sorted_trans = trans_vals[order]
            # Allow tiny numerical noise
            diffs = np.diff(sorted_trans)
            assert np.all(diffs >= -1e-6), \
                f"Channel {idx}: logicle transform is not monotone"


class TestGating:
    """Verify rectangle gating and population counts."""

    def test_output_exists(self):
        assert os.path.exists(GATE_JSON), \
            f"Gate results file not found: {GATE_JSON}"

    def test_gate_structure(self):
        with open(GATE_JSON) as f:
            results = json.load(f)
        for key in ["lymphocyte_gate", "fluorescence_gate", "combined_gate"]:
            assert key in results, f"Missing gate key: {key}"
            gate = results[key]
            for field in ["count", "total", "percentage"]:
                assert field in gate, f"Missing field '{field}' in {key}"

    def test_lymphocyte_gate_count(self):
        """Lymphocyte gate: FSC-H in [200,800], SSC-H in [50,500]."""
        trans = load_csv(TRANS_CSV)
        fsc = trans[:, 0]
        ssc = trans[:, 1]
        expected = int(np.sum(
            (fsc >= 200) & (fsc <= 800) & (ssc >= 50) & (ssc <= 500)
        ))

        with open(GATE_JSON) as f:
            results = json.load(f)
        actual = results["lymphocyte_gate"]["count"]
        assert actual == expected, \
            f"Lymphocyte gate count: got {actual}, expected {expected}"

    def test_fluorescence_gate_count(self):
        """FL gate: FL1-H in [2.0,4.5], FL2-H in [1.5,4.5] (logicle scale)."""
        trans = load_csv(TRANS_CSV)
        fl1 = trans[:, 2]
        fl2 = trans[:, 3]
        expected = int(np.sum(
            (fl1 >= 2.0) & (fl1 <= 4.5) & (fl2 >= 1.5) & (fl2 <= 4.5)
        ))

        with open(GATE_JSON) as f:
            results = json.load(f)
        actual = results["fluorescence_gate"]["count"]
        assert actual == expected, \
            f"Fluorescence gate count: got {actual}, expected {expected}"

    def test_combined_gate_count(self):
        """Combined = intersection of lymphocyte AND fluorescence gates."""
        trans = load_csv(TRANS_CSV)
        fsc = trans[:, 0]
        ssc = trans[:, 1]
        fl1 = trans[:, 2]
        fl2 = trans[:, 3]
        in_lymph = (fsc >= 200) & (fsc <= 800) & (ssc >= 50) & (ssc <= 500)
        in_fl = (fl1 >= 2.0) & (fl1 <= 4.5) & (fl2 >= 1.5) & (fl2 <= 4.5)
        expected = int(np.sum(in_lymph & in_fl))

        with open(GATE_JSON) as f:
            results = json.load(f)
        actual = results["combined_gate"]["count"]
        assert actual == expected, \
            f"Combined gate count: got {actual}, expected {expected}"

    def test_percentage_consistency(self):
        """Percentage should equal count/total * 100."""
        with open(GATE_JSON) as f:
            results = json.load(f)
        for key in ["lymphocyte_gate", "fluorescence_gate", "combined_gate"]:
            gate = results[key]
            expected_pct = gate["count"] / gate["total"] * 100
            assert abs(gate["percentage"] - expected_pct) < 0.01, \
                f"{key} percentage inconsistent"


class TestSummary:
    """Verify summary metadata."""

    def test_output_exists(self):
        assert os.path.exists(SUMMARY_JSON), \
            f"Summary file not found: {SUMMARY_JSON}"

    def test_event_count(self):
        with open(SUMMARY_JSON) as f:
            summary = json.load(f)
        assert summary["n_events"] == 1000

    def test_param_count(self):
        with open(SUMMARY_JSON) as f:
            summary = json.load(f)
        assert summary["n_params"] == 8

    def test_param_names(self):
        with open(SUMMARY_JSON) as f:
            summary = json.load(f)
        names = summary["param_names"].split(",")
        assert names == PARAM_NAMES

    def test_fl_channels(self):
        with open(SUMMARY_JSON) as f:
            summary = json.load(f)
        fl = summary["fl_channels"].split(",")
        assert set(fl) == {"FL1-H", "FL2-H", "FL3-H", "FL4-H"}
