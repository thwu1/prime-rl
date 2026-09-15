"""Tests for soil spectral calibration pipeline."""

import csv
import json
import os

import numpy as np
import pytest

DATA_DIR = "/app/data"
OUTPUT_DIR = "/app/output"
CONFIG_PATH = "/app/config.json"


@pytest.fixture(scope="session")
def config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def raw_data():
    wavelengths = np.loadtxt(
        os.path.join(DATA_DIR, "wavelengths.csv"), delimiter=","
    ).ravel()
    spectra = np.loadtxt(os.path.join(DATA_DIR, "spectra.csv"), delimiter=",")
    props = {}
    oc_arr = []
    with open(os.path.join(DATA_DIR, "properties.csv")) as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = int(float(row["sample_id"]))
            props[sid] = {
                k: float(v) for k, v in row.items() if k != "sample_id"
            }
            oc_arr.append(float(row["OC"]))
    return wavelengths, spectra, props, np.array(oc_arr)


@pytest.fixture(scope="session")
def outputs():
    preprocessed = np.loadtxt(
        os.path.join(OUTPUT_DIR, "preprocessed.csv"), delimiter=","
    )
    with open(os.path.join(OUTPUT_DIR, "train_indices.json")) as f:
        train_indices = json.load(f)
    with open(os.path.join(OUTPUT_DIR, "test_indices.json")) as f:
        test_indices = json.load(f)
    predictions = np.genfromtxt(
        os.path.join(OUTPUT_DIR, "predictions.csv"), delimiter=",", skip_header=1
    )
    with open(os.path.join(OUTPUT_DIR, "metrics.json")) as f:
        metrics = json.load(f)
    return preprocessed, train_indices, test_indices, predictions, metrics


@pytest.fixture(scope="session")
def diagnostics():
    with open(os.path.join(OUTPUT_DIR, "diagnostics.json")) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def cv_curve():
    with open(os.path.join(OUTPUT_DIR, "cv_curve.json")) as f:
        return json.load(f)


# =============================================================================
# Output existence
# =============================================================================
class TestOutputExists:
    def test_preprocessed_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "preprocessed.csv"))

    def test_train_indices_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "train_indices.json"))

    def test_test_indices_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "test_indices.json"))

    def test_predictions_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "predictions.csv"))

    def test_metrics_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "metrics.json"))

    def test_diagnostics_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "diagnostics.json"))

    def test_cv_curve_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "cv_curve.json"))


# =============================================================================
# Diagnostics validation
# =============================================================================
class TestDiagnostics:
    def test_required_keys(self, diagnostics):
        required = {"splice_location_nm", "mean_splice_offset",
                     "n_bands_processed", "outlier_indices"}
        assert required.issubset(set(diagnostics.keys())), (
            f"Missing: {required - set(diagnostics.keys())}"
        )

    def test_splice_location(self, diagnostics, config):
        expected_splice = config["splice_wavelength"]
        assert abs(diagnostics["splice_location_nm"] - expected_splice) < 50.0, (
            f"Splice location {diagnostics['splice_location_nm']} too far "
            f"from expected ~{expected_splice}"
        )

    def test_mean_splice_offset_positive(self, diagnostics):
        assert diagnostics["mean_splice_offset"] > 0.01, (
            f"Mean splice offset {diagnostics['mean_splice_offset']} too small"
        )

    def test_mean_splice_offset_reasonable(self, diagnostics):
        assert diagnostics["mean_splice_offset"] < 0.2, (
            f"Mean splice offset {diagnostics['mean_splice_offset']} too large"
        )

    def test_n_bands_processed_matches_matrix(self, diagnostics, outputs):
        assert diagnostics["n_bands_processed"] == outputs[0].shape[1], (
            f"n_bands_processed={diagnostics['n_bands_processed']} "
            f"!= matrix cols={outputs[0].shape[1]}"
        )

    def test_outlier_indices_type(self, diagnostics):
        assert isinstance(diagnostics["outlier_indices"], list)
        for idx in diagnostics["outlier_indices"]:
            assert isinstance(idx, int)
            assert 0 <= idx < 200

    def test_outlier_indices_sorted(self, diagnostics):
        assert diagnostics["outlier_indices"] == sorted(diagnostics["outlier_indices"])

    def test_outlier_detection_accuracy(self, diagnostics, raw_data, config):
        """Independently detect outliers and verify solver found them."""
        wavelengths, spectra, _, _ = raw_data
        splice_wl = config["splice_wavelength"]
        n_bands = config["splice_n_bands"]

        si_mask = wavelengths <= splice_wl
        pbs_mask = wavelengths > splice_wl
        si_idx = np.where(si_mask)[0][-n_bands:]
        pbs_idx = np.where(pbs_mask)[0][:n_bands]

        offsets = []
        for i in range(spectra.shape[0]):
            offset = abs(
                np.median(spectra[i, pbs_idx]) - np.median(spectra[i, si_idx])
            )
            offsets.append(offset)
        offsets = np.array(offsets)
        mean_off = np.mean(offsets)
        std_off = np.std(offsets, ddof=0)
        threshold = mean_off + 2.0 * std_off
        expected_outliers = sorted(
            int(i) for i in range(len(offsets)) if offsets[i] > threshold
        )

        solver_outliers = diagnostics["outlier_indices"]
        # Must detect at least 80% of true outliers
        if len(expected_outliers) > 0:
            recall = len(set(solver_outliers) & set(expected_outliers)) / len(
                expected_outliers
            )
            assert recall >= 0.8, (
                f"Outlier recall={recall:.2f}. Expected {expected_outliers}, "
                f"got {solver_outliers}"
            )
        # False positive rate must be low
        false_pos = set(solver_outliers) - set(expected_outliers)
        assert len(false_pos) <= 2, (
            f"Too many false positive outliers: {sorted(false_pos)}"
        )


# =============================================================================
# CV curve validation
# =============================================================================
class TestCVCurve:
    def test_is_list(self, cv_curve):
        assert isinstance(cv_curve, list)
        assert len(cv_curve) >= 2, "CV curve must evaluate at least 2 component counts"

    def test_entries_format(self, cv_curve):
        for entry in cv_curve:
            assert "n_components" in entry, f"Missing n_components in {entry}"
            assert "rmsecv" in entry, f"Missing rmsecv in {entry}"
            assert isinstance(entry["n_components"], int)
            assert isinstance(entry["rmsecv"], (int, float))
            assert entry["rmsecv"] > 0

    def test_component_counts_sequential(self, cv_curve):
        counts = [e["n_components"] for e in cv_curve]
        assert counts == sorted(set(counts)), (
            "Component counts must be unique and ascending"
        )

    def test_optimal_matches_metrics(self, cv_curve, outputs):
        """The n_components with lowest RMSECV must match metrics.n_components."""
        best = min(cv_curve, key=lambda e: e["rmsecv"])
        assert best["n_components"] == outputs[4]["n_components"], (
            f"CV curve optimal={best['n_components']} != "
            f"metrics n_components={outputs[4]['n_components']}"
        )

    def test_starts_at_one(self, cv_curve):
        assert cv_curve[0]["n_components"] == 1

    def test_max_components_reasonable(self, cv_curve):
        max_comp = max(e["n_components"] for e in cv_curve)
        assert max_comp <= 20


# =============================================================================
# Preprocessed matrix format
# =============================================================================
class TestPreprocessedFormat:
    def test_rows(self, outputs):
        assert outputs[0].shape[0] == 200, (
            f"Expected 200 rows, got {outputs[0].shape[0]}"
        )

    def test_cols_reasonable(self, outputs):
        ncols = outputs[0].shape[1]
        assert 50 <= ncols <= 500, (
            f"Preprocessed has {ncols} columns — outside reasonable range"
        )

    def test_no_nans(self, outputs):
        assert not np.any(np.isnan(outputs[0]))

    def test_no_infs(self, outputs):
        assert not np.any(np.isinf(outputs[0]))

    def test_has_both_signs(self, outputs):
        assert np.any(outputs[0] > 0) and np.any(outputs[0] < 0)


# =============================================================================
# Train/test partition
# =============================================================================
class TestPartition:
    def test_train_is_list_of_ints(self, outputs):
        train = outputs[1]
        assert isinstance(train, list)
        assert all(isinstance(i, int) for i in train)

    def test_test_is_list_of_ints(self, outputs):
        test = outputs[2]
        assert isinstance(test, list)
        assert all(isinstance(i, int) for i in test)

    def test_disjoint(self, outputs):
        train = set(outputs[1])
        test = set(outputs[2])
        assert train & test == set(), "Train and test sets overlap"

    def test_complete(self, outputs):
        train = set(outputs[1])
        test = set(outputs[2])
        assert train | test == set(range(200)), (
            "Train + test doesn't cover all 200 samples"
        )

    def test_train_size(self, outputs):
        n = len(outputs[1])
        assert 130 <= n <= 140, f"Expected 130-140 training samples, got {n}"

    def test_train_sorted(self, outputs):
        assert outputs[1] == sorted(outputs[1])

    def test_test_sorted(self, outputs):
        assert outputs[2] == sorted(outputs[2])


# =============================================================================
# Predictions format
# =============================================================================
class TestPredictions:
    def test_three_columns(self, outputs):
        assert outputs[3].shape[1] == 3

    def test_row_count(self, outputs):
        assert outputs[3].shape[0] == len(outputs[2])

    def test_sample_ids_match_test(self, outputs):
        pred_ids = set(int(x) for x in outputs[3][:, 0])
        assert pred_ids == set(outputs[2])

    def test_observed_match_properties(self, outputs, raw_data):
        """Observed values in predictions should match source property data."""
        _, _, props, _ = raw_data
        for row in outputs[3]:
            sid = int(row[0])
            expected_oc = props[sid]["OC"]
            assert abs(row[1] - expected_oc) < 0.1, (
                f"Sample {sid}: observed={row[1]}, expected OC={expected_oc}"
            )


# =============================================================================
# Metrics format and consistency
# =============================================================================
class TestMetrics:
    def test_required_keys(self, outputs):
        required = {"rmsep", "rpd", "bias", "sep_b", "r_squared", "n_components"}
        assert required.issubset(set(outputs[4].keys())), (
            f"Missing: {required - set(outputs[4].keys())}"
        )

    def test_rmsep_positive(self, outputs):
        assert outputs[4]["rmsep"] > 0

    def test_rpd_positive(self, outputs):
        assert outputs[4]["rpd"] > 0

    def test_n_components_range(self, outputs):
        n = outputs[4]["n_components"]
        assert 1 <= n <= 20, f"n_components={n} out of [1, 20]"

    def test_rmsep_sep_bias_relation(self, outputs):
        """RMSEP^2 should approximately equal SEP-b^2 + bias^2."""
        m = outputs[4]
        rmsep2 = m["rmsep"] ** 2
        decomp = m["sep_b"] ** 2 + m["bias"] ** 2
        rel_err = abs(rmsep2 - decomp) / max(rmsep2, 1e-10)
        assert rel_err < 0.05, (
            f"RMSEP^2={rmsep2:.4f} != SEP-b^2+bias^2={decomp:.4f} "
            f"(rel err={rel_err:.4f})"
        )

    def test_rpd_formula(self, outputs):
        """RPD = SD(observed) / RMSEP — accept either ddof=0 or ddof=1."""
        m = outputs[4]
        observed = outputs[3][:, 1]
        for ddof in (0, 1):
            expected = np.std(observed, ddof=ddof) / m["rmsep"]
            if abs(m["rpd"] - expected) / max(expected, 1e-10) < 0.05:
                return
        pytest.fail(
            f"RPD={m['rpd']:.4f} doesn't match SD/RMSEP with ddof=0 or ddof=1"
        )

    def test_r_squared_range(self, outputs):
        assert -1 < outputs[4]["r_squared"] <= 1.0

    def test_r_squared_consistency(self, outputs):
        """R^2 should be consistent with predictions."""
        preds = outputs[3]
        obs = preds[:, 1]
        pred = preds[:, 2]
        ss_res = np.sum((obs - pred) ** 2)
        ss_tot = np.sum((obs - np.mean(obs)) ** 2)
        expected_r2 = 1 - ss_res / ss_tot
        assert abs(outputs[4]["r_squared"] - expected_r2) < 0.02, (
            f"R^2={outputs[4]['r_squared']:.4f} != computed {expected_r2:.4f}"
        )


# =============================================================================
# Preprocessing spot-check: independently verify for specific samples
# =============================================================================
class TestPreprocessingSpotCheck:
    @staticmethod
    def _reference_preprocess(wavelengths, spectra, sample_idx, config):
        """Independent reference preprocessing of one sample."""
        from scipy.signal import savgol_filter

        wl_range = config["wavelength_trim"]
        mask = (wavelengths >= wl_range[0]) & (wavelengths <= wl_range[1])
        wl = wavelengths[mask]
        spec = spectra[sample_idx, mask].copy()

        # Splice correction
        splice_wl = config["splice_wavelength"]
        n_bands = config["splice_n_bands"]
        si_mask = wl <= splice_wl
        pbs_mask = wl > splice_wl
        si_bands = np.where(si_mask)[0][-n_bands:]
        pbs_bands = np.where(pbs_mask)[0][:n_bands]
        offset = np.median(spec[pbs_bands]) - np.median(spec[si_bands])
        spec[pbs_mask] -= offset

        # SG derivative
        sg_cfg = config["savitzky_golay"]
        sg = savgol_filter(
            spec, sg_cfg["window_length"], sg_cfg["polyorder"],
            deriv=sg_cfg["deriv"]
        )

        # SNV
        snv = (sg - np.mean(sg)) / np.std(sg, ddof=0)

        # Decimate
        step = int(config["resample_interval_nm"] / config["original_spacing_nm"])
        return snv[::step]

    def test_sample_0(self, raw_data, outputs, config):
        wl, spectra, _, _ = raw_data
        ref = self._reference_preprocess(wl, spectra, 0, config)
        solver = outputs[0][0]
        corr = np.corrcoef(ref, solver)[0, 1]
        assert corr > 0.99, f"Sample 0: correlation={corr:.6f}"

    def test_sample_50(self, raw_data, outputs, config):
        wl, spectra, _, _ = raw_data
        ref = self._reference_preprocess(wl, spectra, 50, config)
        solver = outputs[0][50]
        corr = np.corrcoef(ref, solver)[0, 1]
        assert corr > 0.99, f"Sample 50: correlation={corr:.6f}"

    def test_sample_150(self, raw_data, outputs, config):
        wl, spectra, _, _ = raw_data
        ref = self._reference_preprocess(wl, spectra, 150, config)
        solver = outputs[0][150]
        corr = np.corrcoef(ref, solver)[0, 1]
        assert corr > 0.99, f"Sample 150: correlation={corr:.6f}"

    def test_sample_0_close(self, raw_data, outputs, config):
        """Tighter check: relative RMSE between reference and solver."""
        wl, spectra, _, _ = raw_data
        ref = self._reference_preprocess(wl, spectra, 0, config)
        solver = outputs[0][0]
        rms = np.sqrt(np.mean((ref - solver) ** 2))
        rms_ref = np.sqrt(np.mean(ref ** 2))
        rel_err = rms / max(rms_ref, 1e-10)
        assert rel_err < 0.05, f"Sample 0: relative RMSE={rel_err:.4f}"


# =============================================================================
# Sample selection structural property
# =============================================================================
class TestSelectionProperty:
    def test_most_distant_pair_in_training(self, raw_data, outputs, config):
        """The two most-distant points in selection space must both be in the
        training set (a proper space-filling design initializes with this pair)."""
        wavelengths, spectra, _, _ = raw_data

        wl_range = config["wavelength_trim"]
        mask = (wavelengths >= wl_range[0]) & (wavelengths <= wl_range[1])
        wl = wavelengths[mask]
        spec = spectra[:, mask].copy()
        n = spec.shape[0]

        # Splice correction
        splice_wl = config["splice_wavelength"]
        n_bands = config["splice_n_bands"]
        si_mask = wl <= splice_wl
        pbs_mask = wl > splice_wl
        si_idx = np.where(si_mask)[0][-n_bands:]
        pbs_idx = np.where(pbs_mask)[0][:n_bands]
        for i in range(n):
            offset = np.median(spec[i, pbs_idx]) - np.median(spec[i, si_idx])
            spec[i, pbs_mask] -= offset

        # Reflectance
        refl = np.power(10.0, -spec)

        # Continuum removal (upper convex hull)
        cr = np.zeros_like(refl)
        for i in range(n):
            hull = []
            for j in range(len(wl)):
                while len(hull) >= 2:
                    p0x, p0y = hull[-2]
                    p1x, p1y = hull[-1]
                    cross = (p1x - p0x) * (refl[i, j] - p0y) - (
                        p1y - p0y
                    ) * (wl[j] - p0x)
                    if cross >= 0:
                        hull.pop()
                    else:
                        break
                hull.append((wl[j], refl[i, j]))
            hull_arr = np.array(hull)
            cont = np.interp(wl, hull_arr[:, 0], hull_arr[:, 1])
            cr[i] = refl[i] / np.maximum(cont, 1e-10)

        # PCA
        pca_thresh = config["kennard_stone"]["pca_variance_threshold"]
        cr_c = cr - cr.mean(axis=0)
        U, S, _ = np.linalg.svd(cr_c, full_matrices=False)
        ev = S ** 2
        cumvar = np.cumsum(ev) / np.sum(ev)
        n_pca = int(np.searchsorted(cumvar, pca_thresh)) + 1
        scores = U[:, :n_pca] * S[:n_pca]

        # Standardize
        scores_std = (scores - scores.mean(axis=0)) / scores.std(axis=0, ddof=0)

        # Most distant pair
        from scipy.spatial.distance import cdist

        D = cdist(scores_std, scores_std, "euclidean")
        flat = np.argmax(D)
        i_max, j_max = divmod(int(flat), n)

        train_set = set(outputs[1])
        assert i_max in train_set, (
            f"Point {i_max} of most-distant pair not in training set"
        )
        assert j_max in train_set, (
            f"Point {j_max} of most-distant pair not in training set"
        )


# =============================================================================
# Model quality
# =============================================================================
class TestCalibrationQuality:
    def test_rmsep_below_sd(self, outputs):
        """RMSEP should be smaller than SD of observed (model should be useful)."""
        sd_obs = np.std(outputs[3][:, 1])
        assert outputs[4]["rmsep"] < sd_obs

    def test_rpd_minimum(self, outputs):
        assert outputs[4]["rpd"] > 1.2, f"RPD={outputs[4]['rpd']:.2f} too low"

    def test_r_squared_minimum(self, outputs):
        assert outputs[4]["r_squared"] > 0.3, (
            f"R^2={outputs[4]['r_squared']:.2f} too low"
        )

    def test_positive_correlation(self, outputs):
        preds = outputs[3]
        corr = np.corrcoef(preds[:, 1], preds[:, 2])[0, 1]
        assert corr > 0.5, f"Observed-predicted correlation={corr:.2f} too low"

    def test_bias_small(self, outputs):
        """Bias should be small relative to RMSEP."""
        m = outputs[4]
        assert abs(m["bias"]) < m["rmsep"], "Bias should be < RMSEP"
