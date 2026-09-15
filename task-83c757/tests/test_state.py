
import json
import os
import pytest
import numpy as np
import pandas as pd
from scipy import stats

FEATURE_NAMES = ["temperature", "pressure", "vibration", "humidity", "speed", "load_factor"]
DRIFTED_FEATURES = {"temperature", "vibration", "speed"}
NON_DRIFTED_FEATURES = {"pressure", "humidity", "load_factor"}


@pytest.fixture(scope="module")
def drift_report():
    with open("/app/drift_report.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reference_data():
    return pd.read_csv("/app/data/reference.csv")


@pytest.fixture(scope="module")
def production_data():
    return pd.read_csv("/app/data/production.csv")


# ---------------------------------------------------------------------------
# 1. Report structure
# ---------------------------------------------------------------------------
class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists("/app/drift_report.json"), "drift_report.json not found"

    def test_has_all_features(self, drift_report):
        assert "features" in drift_report
        for feat in FEATURE_NAMES:
            assert feat in drift_report["features"], f"Missing feature: {feat}"

    def test_feature_fields_complete(self, drift_report):
        required = {"ks_statistic", "ks_pvalue", "psi", "kde_overlap", "is_drifted"}
        for feat in FEATURE_NAMES:
            entry = drift_report["features"][feat]
            for key in required:
                assert key in entry, f"Missing field '{key}' for feature '{feat}'"

    def test_has_prediction_drift(self, drift_report):
        pd_section = drift_report.get("prediction_drift", {})
        assert "ks_statistic" in pd_section
        assert "ks_pvalue" in pd_section

    def test_has_summary_fields(self, drift_report):
        for key in ["n_drifted_features", "drifted_feature_names",
                     "severity", "recommended_action"]:
            assert key in drift_report, f"Missing top-level field: {key}"


# ---------------------------------------------------------------------------
# 2. KS statistic verification (independent computation)
# ---------------------------------------------------------------------------
class TestKSStatistics:
    def test_ks_values_match(self, drift_report, reference_data, production_data):
        for feat in FEATURE_NAMES:
            ref_vals = reference_data[feat].values
            prod_vals = production_data[feat].values
            expected_stat, expected_pval = stats.ks_2samp(ref_vals, prod_vals)

            reported = drift_report["features"][feat]
            assert abs(reported["ks_statistic"] - expected_stat) < 0.01, \
                f"KS stat for {feat}: expected {expected_stat:.4f}, got {reported['ks_statistic']:.4f}"

            if expected_pval < 1e-10:
                assert reported["ks_pvalue"] < 1e-5, \
                    f"KS p-value for {feat} should be near zero, got {reported['ks_pvalue']}"
            else:
                assert abs(reported["ks_pvalue"] - expected_pval) < 0.05, \
                    f"KS p-value for {feat}: expected {expected_pval:.4f}, got {reported['ks_pvalue']:.4f}"


# ---------------------------------------------------------------------------
# 3. PSI verification (independent computation)
# ---------------------------------------------------------------------------
class TestPSI:
    @staticmethod
    def _compute_psi(ref_vals, prod_vals, n_bins=10):
        combined = np.concatenate([ref_vals, prod_vals])
        bins = np.linspace(combined.min(), combined.max(), n_bins + 1)
        ref_counts, _ = np.histogram(ref_vals, bins=bins)
        prod_counts, _ = np.histogram(prod_vals, bins=bins)
        ref_props = ref_counts / len(ref_vals)
        prod_props = prod_counts / len(prod_vals)
        ref_props = np.where(ref_props == 0, 1e-4, ref_props)
        prod_props = np.where(prod_props == 0, 1e-4, prod_props)
        return float(np.sum((prod_props - ref_props) * np.log(prod_props / ref_props)))

    def test_psi_values_match(self, drift_report, reference_data, production_data):
        for feat in FEATURE_NAMES:
            expected = self._compute_psi(
                reference_data[feat].values, production_data[feat].values)
            reported = drift_report["features"][feat]["psi"]
            assert abs(reported - expected) < 0.05, \
                f"PSI for {feat}: expected {expected:.4f}, got {reported:.4f}"

    def test_drifted_psi_high(self, drift_report):
        for feat in DRIFTED_FEATURES:
            assert drift_report["features"][feat]["psi"] > 0.1, \
                f"PSI for drifted feature {feat} should be > 0.1"

    def test_non_drifted_psi_low(self, drift_report):
        for feat in NON_DRIFTED_FEATURES:
            assert drift_report["features"][feat]["psi"] < 0.25, \
                f"PSI for non-drifted feature {feat} should be < 0.25"


# ---------------------------------------------------------------------------
# 4. KDE overlap directional checks
# ---------------------------------------------------------------------------
class TestKDEOverlap:
    def test_drifted_low_overlap(self, drift_report):
        for feat in DRIFTED_FEATURES:
            val = drift_report["features"][feat]["kde_overlap"]
            assert val < 0.9, f"KDE overlap for drifted {feat} should be < 0.9, got {val:.4f}"

    def test_non_drifted_high_overlap(self, drift_report):
        for feat in NON_DRIFTED_FEATURES:
            val = drift_report["features"][feat]["kde_overlap"]
            assert val > 0.8, f"KDE overlap for non-drifted {feat} should be > 0.8, got {val:.4f}"

    def test_overlap_in_range(self, drift_report):
        for feat in FEATURE_NAMES:
            val = drift_report["features"][feat]["kde_overlap"]
            assert 0.0 <= val <= 1.0, f"KDE overlap for {feat} out of [0,1]: {val}"


# ---------------------------------------------------------------------------
# 5. Drift classification
# ---------------------------------------------------------------------------
class TestDriftClassification:
    def test_drifted_features_flagged(self, drift_report):
        for feat in DRIFTED_FEATURES:
            assert drift_report["features"][feat]["is_drifted"] is True, \
                f"{feat} should be flagged as drifted"

    def test_non_drifted_features_clean(self, drift_report):
        for feat in NON_DRIFTED_FEATURES:
            assert drift_report["features"][feat]["is_drifted"] is False, \
                f"{feat} should NOT be flagged as drifted"

    def test_n_drifted_count(self, drift_report):
        assert drift_report["n_drifted_features"] == 3

    def test_drifted_names(self, drift_report):
        assert set(drift_report["drifted_feature_names"]) == DRIFTED_FEATURES


# ---------------------------------------------------------------------------
# 6. Severity and action
# ---------------------------------------------------------------------------
class TestAction:
    def test_recommended_action(self, drift_report):
        assert drift_report["recommended_action"] == "retrain"

    def test_severity(self, drift_report):
        assert drift_report["severity"] == "high"


# ---------------------------------------------------------------------------
# 7. MLflow integration
# ---------------------------------------------------------------------------
class TestMLflowIntegration:
    def test_drift_monitoring_run_exists(self):
        import mlflow
        mlflow.set_tracking_uri("sqlite:////app/mlflow.db")
        client = mlflow.tracking.MlflowClient()
        experiment = mlflow.get_experiment_by_name("predictive-maintenance")
        assert experiment is not None

        runs = client.search_runs(experiment_ids=[experiment.experiment_id])
        drift_runs = [r for r in runs if r.info.run_name == "drift-monitoring"]
        assert len(drift_runs) >= 1, "No 'drift-monitoring' run found in MLflow"

    def test_drift_metrics_logged(self):
        import mlflow
        mlflow.set_tracking_uri("sqlite:////app/mlflow.db")
        client = mlflow.tracking.MlflowClient()
        experiment = mlflow.get_experiment_by_name("predictive-maintenance")

        runs = client.search_runs(experiment_ids=[experiment.experiment_id])
        drift_runs = [r for r in runs if r.info.run_name == "drift-monitoring"]
        assert len(drift_runs) >= 1
        run = drift_runs[0]
        metrics = run.data.metrics

        for feat in FEATURE_NAMES:
            assert f"{feat}_ks_statistic" in metrics, \
                f"Metric '{feat}_ks_statistic' not logged"
            assert f"{feat}_psi" in metrics, \
                f"Metric '{feat}_psi' not logged"
            assert f"{feat}_kde_overlap" in metrics, \
                f"Metric '{feat}_kde_overlap' not logged"

    def test_new_model_version_registered(self):
        import mlflow
        mlflow.set_tracking_uri("sqlite:////app/mlflow.db")
        client = mlflow.tracking.MlflowClient()

        versions = client.search_model_versions("name='predictive-maintenance-model'")
        assert len(versions) >= 2, \
            f"Expected >= 2 model versions (original + retrained), found {len(versions)}"

        latest = max(versions, key=lambda v: int(v.version))
        assert latest.tags.get("retrained_reason") == "drift_detected", \
            "Latest model version missing tag retrained_reason=drift_detected"
