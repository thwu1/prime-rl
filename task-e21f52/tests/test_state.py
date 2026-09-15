
"""Verification tests for the gaze-during-reading analysis pipeline."""

import importlib.util
import json
import os

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def results():
    path = "/app/results.json"
    assert os.path.exists(path), "results.json not found at /app/results.json"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def pipeline():
    """Import the agent's pipeline module."""
    spec = importlib.util.spec_from_file_location("pipeline", "/app/pipeline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ===========================================================================
# 1. JSON structure
# ===========================================================================

class TestResultsStructure:
    def test_has_fixation_summary(self, results):
        fs = results["fixation_summary"]
        for k in ("total_fixations", "mean_fixation_duration_ms",
                   "mean_saccade_amplitude_px"):
            assert k in fs, f"Missing key fixation_summary.{k}"

    def test_has_reading_measures_summary(self, results):
        rm = results["reading_measures_summary"]
        for k in ("mean_FFD", "mean_GD", "mean_TRT",
                   "overall_skip_rate", "overall_regression_rate"):
            assert k in rm, f"Missing key reading_measures_summary.{k}"

    def test_has_evaluation(self, results):
        ev = results["evaluation"]
        for regime in ("unseen_reader", "unseen_text", "unseen_both"):
            assert regime in ev, f"Missing evaluation regime {regime}"
            for metric in ("rmse", "r2"):
                assert metric in ev[regime], \
                    f"Missing evaluation.{regime}.{metric}"

    def test_has_split_sizes(self, results):
        ss = results["split_sizes"]
        for regime in ("unseen_reader", "unseen_text", "unseen_both"):
            assert regime in ss, f"Missing split_sizes.{regime}"
            for k in ("n_folds", "mean_train_size", "mean_test_size"):
                assert k in ss[regime], f"Missing split_sizes.{regime}.{k}"


# ===========================================================================
# 2. Fixation detection plausibility
# ===========================================================================

class TestFixationDetection:
    def test_total_fixations_in_range(self, results):
        n = results["fixation_summary"]["total_fixations"]
        assert 200 < n < 3000, f"total_fixations={n} outside (200, 3000)"

    def test_mean_duration_in_range(self, results):
        d = results["fixation_summary"]["mean_fixation_duration_ms"]
        assert 80 <= d <= 500, f"mean_fixation_duration_ms={d} outside [80, 500]"

    def test_saccade_amplitude_positive(self, results):
        a = results["fixation_summary"]["mean_saccade_amplitude_px"]
        assert a > 0, "mean_saccade_amplitude_px must be > 0"


# ===========================================================================
# 3. Reading-measure constraints
# ===========================================================================

class TestReadingMeasures:
    def test_ffd_positive(self, results):
        assert results["reading_measures_summary"]["mean_FFD"] > 0

    def test_gd_geq_ffd(self, results):
        rm = results["reading_measures_summary"]
        assert rm["mean_GD"] >= rm["mean_FFD"] - 1e-6, \
            f"GD ({rm['mean_GD']}) must be >= FFD ({rm['mean_FFD']})"

    def test_trt_geq_gd(self, results):
        rm = results["reading_measures_summary"]
        assert rm["mean_TRT"] >= rm["mean_GD"] - 1e-6, \
            f"TRT ({rm['mean_TRT']}) must be >= GD ({rm['mean_GD']})"

    def test_skip_rate_in_range(self, results):
        sr = results["reading_measures_summary"]["overall_skip_rate"]
        assert 0 <= sr <= 0.5, f"skip_rate={sr} outside [0, 0.5]"

    def test_regression_rate_in_range(self, results):
        rr = results["reading_measures_summary"]["overall_regression_rate"]
        assert 0 <= rr <= 0.8, f"regression_rate={rr} outside [0, 0.8]"


# ===========================================================================
# 4. Cross-validation split correctness
# ===========================================================================

class TestCrossValidationSplits:
    def test_unseen_reader_n_folds(self, results):
        assert results["split_sizes"]["unseen_reader"]["n_folds"] == 8

    def test_unseen_text_n_folds(self, results):
        assert results["split_sizes"]["unseen_text"]["n_folds"] == 6

    def test_unseen_both_n_folds(self, results):
        assert results["split_sizes"]["unseen_both"]["n_folds"] == 48

    def test_unseen_reader_sizes(self, results):
        ss = results["split_sizes"]["unseen_reader"]
        assert ss["mean_train_size"] == 42, \
            f"unseen_reader mean_train_size={ss['mean_train_size']}, expected 42"
        assert ss["mean_test_size"] == 6, \
            f"unseen_reader mean_test_size={ss['mean_test_size']}, expected 6"

    def test_unseen_text_sizes(self, results):
        ss = results["split_sizes"]["unseen_text"]
        assert ss["mean_train_size"] == 40, \
            f"unseen_text mean_train_size={ss['mean_train_size']}, expected 40"
        assert ss["mean_test_size"] == 8, \
            f"unseen_text mean_test_size={ss['mean_test_size']}, expected 8"

    def test_unseen_both_sizes(self, results):
        ss = results["split_sizes"]["unseen_both"]
        assert ss["mean_train_size"] == 35, \
            f"unseen_both mean_train_size={ss['mean_train_size']}, expected 35"
        assert ss["mean_test_size"] == 1, \
            f"unseen_both mean_test_size={ss['mean_test_size']}, expected 1"

    def test_total_trials_consistent(self, results):
        """Total test samples across unseen_reader folds = 48."""
        ss = results["split_sizes"]["unseen_reader"]
        assert ss["n_folds"] * ss["mean_test_size"] == 48


# ===========================================================================
# 5. Prediction metrics
# ===========================================================================

class TestPrediction:
    def test_rmse_positive(self, results):
        for regime in ("unseen_reader", "unseen_text", "unseen_both"):
            assert results["evaluation"][regime]["rmse"] > 0

    def test_r2_is_finite(self, results):
        for regime in ("unseen_reader", "unseen_text", "unseen_both"):
            r2 = results["evaluation"][regime]["r2"]
            assert np.isfinite(r2), f"R2 for {regime} is not finite: {r2}"

    def test_rmse_bounded(self, results):
        """RMSE should be < 50 (reading skill range ~30-91)."""
        for regime in ("unseen_reader", "unseen_text", "unseen_both"):
            rmse = results["evaluation"][regime]["rmse"]
            assert rmse < 50, f"RMSE for {regime} too large: {rmse}"

    def test_unseen_reader_has_some_signal(self, results):
        r2 = results["evaluation"]["unseen_reader"]["r2"]
        assert r2 > -1.0, f"R2 for unseen_reader is {r2}; model has no signal"


# ===========================================================================
# 6. I-VT algorithm unit tests
# ===========================================================================

class TestIVTAlgorithm:
    """Directly test the agent's I-VT implementation on synthetic signals."""

    def test_two_fixations(self, pipeline):
        """A still-saccade-still signal must yield exactly two fixations."""
        n1, n_sac, n2 = 100, 20, 100
        total = n1 + n_sac + n2
        ts = list(range(total))
        xs = ([500.0] * n1
              + [500.0 + 200.0 * i / n_sac for i in range(n_sac)]
              + [700.0] * n2)
        ys = [500.0] * total
        pupils = [3.5] * total

        fixes = pipeline.detect_fixations_ivt(
            ts, xs, ys, pupils,
            velocity_threshold=100, min_duration_ms=80)

        assert len(fixes) == 2, f"Expected 2 fixations, got {len(fixes)}"
        assert abs(fixes[0]["centroid_x"] - 500) < 5
        assert abs(fixes[1]["centroid_x"] - 700) < 5

    def test_blink_splits_fixation(self, pipeline):
        """A blink in the middle of a short fixation must prevent detection."""
        ts = list(range(130))
        xs = [500.0] * 50 + [0.0] * 30 + [500.0] * 50
        ys = [500.0] * 50 + [0.0] * 30 + [500.0] * 50
        pupils = [3.5] * 50 + [0.0] * 30 + [3.5] * 50

        fixes = pipeline.detect_fixations_ivt(
            ts, xs, ys, pupils,
            velocity_threshold=100, min_duration_ms=80)

        assert len(fixes) == 0, \
            f"Expected 0 fixations (blink splits short segments), got {len(fixes)}"

    def test_min_duration_filter(self, pipeline):
        """A 50-sample fixation (49 ms) must be filtered at min_duration=80."""
        ts = list(range(50))
        xs = [500.0] * 50
        ys = [500.0] * 50
        pupils = [3.5] * 50

        fixes = pipeline.detect_fixations_ivt(
            ts, xs, ys, pupils,
            velocity_threshold=100, min_duration_ms=80)

        assert len(fixes) == 0, \
            f"Expected 0 fixations (below min duration), got {len(fixes)}"

    def test_long_fixation_detected(self, pipeline):
        """A 200-sample still signal must produce exactly one fixation."""
        ts = list(range(200))
        xs = [400.0] * 200
        ys = [300.0] * 200
        pupils = [3.5] * 200

        fixes = pipeline.detect_fixations_ivt(
            ts, xs, ys, pupils,
            velocity_threshold=100, min_duration_ms=80)

        assert len(fixes) == 1, f"Expected 1 fixation, got {len(fixes)}"
        assert fixes[0]["duration_ms"] >= 80
        assert abs(fixes[0]["centroid_x"] - 400) < 5
        assert abs(fixes[0]["centroid_y"] - 300) < 5

    def test_blink_excluded_from_fixation(self, pipeline):
        """A long blink between two fixations must not create a phantom fixation.

        Signal: 200 ms still at (300,300), 150 ms blink at (0,0), 200 ms still
        at (300,300). Must yield exactly 2 fixations, neither at the origin.
        """
        n1, n_blink, n2 = 200, 150, 200
        total = n1 + n_blink + n2
        ts = list(range(total))
        xs = [300.0] * n1 + [0.0] * n_blink + [300.0] * n2
        ys = [300.0] * n1 + [0.0] * n_blink + [300.0] * n2
        pupils = [3.5] * n1 + [0.0] * n_blink + [3.5] * n2

        fixes = pipeline.detect_fixations_ivt(
            ts, xs, ys, pupils,
            velocity_threshold=100, min_duration_ms=80)

        assert len(fixes) == 2, \
            f"Expected 2 fixations (blink must not create phantom), got {len(fixes)}"
        for f in fixes:
            assert f["centroid_x"] > 50, \
                f"Fixation at x={f['centroid_x']} appears to be a blink artifact"
            assert f["centroid_y"] > 50, \
                f"Fixation at y={f['centroid_y']} appears to be a blink artifact"


# ===========================================================================
# 7. Reading measure logic unit tests
# ===========================================================================

class TestReadingMeasureLogic:
    """Directly test per-word reading measure computation."""

    def test_first_pass_per_word(self, pipeline):
        """After a regression, words visited for the first time must still
        receive first-pass measures (FFD/GD). The first-pass status must be
        tracked independently for each word, not globally."""
        fixations = [
            {'onset_ms': 0, 'offset_ms': 99, 'duration_ms': 100,
             'centroid_x': 100, 'centroid_y': 300, 'word_index': 0},
            {'onset_ms': 120, 'offset_ms': 219, 'duration_ms': 100,
             'centroid_x': 200, 'centroid_y': 300, 'word_index': 1},
            {'onset_ms': 240, 'offset_ms': 339, 'duration_ms': 100,
             'centroid_x': 300, 'centroid_y': 300, 'word_index': 2},
            # Regression back to word 0
            {'onset_ms': 360, 'offset_ms': 459, 'duration_ms': 100,
             'centroid_x': 100, 'centroid_y': 300, 'word_index': 0},
            # Continue forward to word 3 — first time visiting this word
            {'onset_ms': 480, 'offset_ms': 579, 'duration_ms': 100,
             'centroid_x': 400, 'centroid_y': 300, 'word_index': 3},
        ]

        measures = pipeline.compute_word_measures(fixations, 5)

        # Word 3 is visited for the first time AFTER a regression occurred
        # earlier. It must still have first-pass FFD.
        assert measures[3]['FFD'] == 100, \
            f"Word 3 should have FFD=100 (first-pass), got {measures[3]['FFD']}"
        assert measures[3]['regression'] is False, \
            "Word 3 should not be a regression (first visit)"
        # Word 0 was re-visited — must be a regression
        assert measures[0]['regression'] is True, \
            "Word 0 should have regression=True (re-visited)"
        # Word 4 was never visited — must be a skip
        assert measures[4]['skip'] is True, \
            "Word 4 should be skipped (never fixated)"

    def test_refixation_within_first_pass(self, pipeline):
        """Two consecutive fixations on the same word should both count as
        first-pass (gaze has not left the word yet)."""
        fixations = [
            {'onset_ms': 0, 'offset_ms': 99, 'duration_ms': 100,
             'centroid_x': 100, 'centroid_y': 300, 'word_index': 0},
            {'onset_ms': 120, 'offset_ms': 279, 'duration_ms': 160,
             'centroid_x': 100, 'centroid_y': 300, 'word_index': 0},
            {'onset_ms': 300, 'offset_ms': 399, 'duration_ms': 100,
             'centroid_x': 200, 'centroid_y': 300, 'word_index': 1},
        ]

        measures = pipeline.compute_word_measures(fixations, 2)

        # Both fixations on word 0 are first-pass
        assert measures[0]['FFD'] == 100, \
            f"FFD should be first fixation duration (100), got {measures[0]['FFD']}"
        assert measures[0]['GD'] == 260, \
            f"GD should be sum of both first-pass fixations (260), got {measures[0]['GD']}"
        assert measures[0]['TRT'] == 260
        assert measures[0]['regression'] is False
