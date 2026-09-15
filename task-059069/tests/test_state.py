"""Tests for the Eurobench gait stability analysis pipeline."""

import os
import subprocess
import pytest
import yaml

OUTPUT_DIR = "/app/output"
INPUT_DIR = "/app/data"


@pytest.fixture(scope="session", autouse=True)
def run_pipeline():
    """Execute the gait analysis pipeline before any tests."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    result = subprocess.run(
        ["/app/run_pi", INPUT_DIR, OUTPUT_DIR],
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, (
        f"Pipeline failed (exit {result.returncode}).\n"
        f"STDOUT:\n{result.stdout[-2000:]}\n"
        f"STDERR:\n{result.stderr[-2000:]}"
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _load_yaml(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    assert os.path.exists(path), f"Missing output file: {filename}"
    with open(path) as f:
        return yaml.safe_load(f)


def _get_mean(data, key):
    """Extract mean value from a metric dict, supporting nested or flat."""
    entry = data[key]
    if isinstance(entry, dict):
        return entry["mean"]
    return float(entry)


# ---------------------------------------------------------------------------
# 1. Output format validator passes
# ---------------------------------------------------------------------------

class TestValidator:
    def test_validator_passes(self):
        result = subprocess.run(
            ["python3", "/app/tools/validate_output.py", INPUT_DIR, OUTPUT_DIR],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (
            f"Validator failed:\n{result.stdout}\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# 2. Output file existence
# ---------------------------------------------------------------------------

class TestOutputFilesExist:
    @pytest.mark.parametrize("cond,run", [(1, 1), (1, 2), (2, 1), (2, 2)])
    def test_spatiotemporal_exists(self, cond, run):
        fn = f"subject_01_cond_{cond:02d}_run_{run:02d}_spatiotemporal.yaml"
        assert os.path.exists(os.path.join(OUTPUT_DIR, fn)), f"Missing {fn}"

    @pytest.mark.parametrize("cond,run", [(1, 1), (1, 2), (2, 1), (2, 2)])
    def test_stability_exists(self, cond, run):
        fn = f"subject_01_cond_{cond:02d}_run_{run:02d}_stability.yaml"
        assert os.path.exists(os.path.join(OUTPUT_DIR, fn)), f"Missing {fn}"

    @pytest.mark.parametrize("cond", [1, 2])
    def test_aggregated_exists(self, cond):
        fn = f"subject_01_cond_{cond:02d}_aggregated.yaml"
        assert os.path.exists(os.path.join(OUTPUT_DIR, fn)), f"Missing {fn}"

    def test_summary_csv_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "summary.csv"))


# ---------------------------------------------------------------------------
# 3. YAML format compliance
# ---------------------------------------------------------------------------

class TestYAMLFormat:
    def test_spatiotemporal_required_keys(self):
        data = _load_yaml("subject_01_cond_01_run_01_spatiotemporal.yaml")
        for key in ["step_time", "stride_time", "step_length",
                     "step_width", "cadence", "walking_speed", "stance_ratio"]:
            assert key in data, f"Missing spatiotemporal key: {key}"

    def test_metric_has_mean_std_unit(self):
        data = _load_yaml("subject_01_cond_01_run_01_spatiotemporal.yaml")
        for key in ["step_time", "stride_time", "step_length"]:
            entry = data[key]
            assert isinstance(entry, dict), f"{key} should be a dict"
            assert "mean" in entry, f"{key} missing 'mean'"
            assert "std" in entry, f"{key} missing 'std'"
            assert "unit" in entry, f"{key} missing 'unit'"

    def test_stability_required_keys(self):
        data = _load_yaml("subject_01_cond_01_run_01_stability.yaml")
        assert "mos_ml" in data, "Missing mos_ml in stability output"
        assert "mos_ap" in data, "Missing mos_ap in stability output"

    def test_stability_has_xcom(self):
        data = _load_yaml("subject_01_cond_01_run_01_stability.yaml")
        has_xcom = any("xcom" in k.lower() for k in data.keys())
        assert has_xcom, "Stability output must include at least one XCoM field"


# ---------------------------------------------------------------------------
# 4. Spatiotemporal values — condition 1 (normal walking, v=1.3 m/s)
# ---------------------------------------------------------------------------

class TestSpatiotemporalCond1:
    @pytest.fixture
    def data(self):
        return _load_yaml("subject_01_cond_01_run_01_spatiotemporal.yaml")

    def test_step_time(self, data):
        v = _get_mean(data, "step_time")
        assert abs(v - 0.50) < 0.06, f"step_time={v}, expected ~0.50 s"

    def test_stride_time(self, data):
        v = _get_mean(data, "stride_time")
        assert abs(v - 1.00) < 0.06, f"stride_time={v}, expected ~1.00 s"

    def test_step_length(self, data):
        v = _get_mean(data, "step_length")
        assert abs(v - 0.65) < 0.06, f"step_length={v}, expected ~0.65 m"

    def test_step_width(self, data):
        v = _get_mean(data, "step_width")
        assert abs(v - 0.20) < 0.04, f"step_width={v}, expected ~0.20 m"

    def test_cadence(self, data):
        v = _get_mean(data, "cadence")
        assert abs(v - 120.0) < 10.0, f"cadence={v}, expected ~120 steps/min"

    def test_walking_speed(self, data):
        v = _get_mean(data, "walking_speed")
        assert abs(v - 1.30) < 0.15, f"walking_speed={v}, expected ~1.30 m/s"

    def test_stance_ratio(self, data):
        v = _get_mean(data, "stance_ratio")
        assert abs(v - 0.62) < 0.07, f"stance_ratio={v}, expected ~0.62"


# ---------------------------------------------------------------------------
# 5. Stability values — condition 1
# ---------------------------------------------------------------------------

class TestStabilityCond1:
    @pytest.fixture
    def data(self):
        return _load_yaml("subject_01_cond_01_run_01_stability.yaml")

    def test_mos_ml_positive(self, data):
        v = _get_mean(data, "mos_ml")
        assert v > 0, f"MoS ML={v} must be positive for stable walking"

    def test_mos_ml_value(self, data):
        v = _get_mean(data, "mos_ml")
        assert abs(v - 0.075) < 0.025, f"MoS ML={v}, expected ~0.075 m"

    def test_mos_ap_negative(self, data):
        v = _get_mean(data, "mos_ap")
        assert v < 0, f"MoS AP={v} must be negative for forward walking"

    def test_mos_ap_value(self, data):
        v = _get_mean(data, "mos_ap")
        assert abs(v - (-0.073)) < 0.045, f"MoS AP={v}, expected ~-0.073 m"


# ---------------------------------------------------------------------------
# 6. Spatiotemporal values — condition 2 (fast walking, v=1.8 m/s)
# ---------------------------------------------------------------------------

class TestSpatiotemporalCond2:
    @pytest.fixture
    def data(self):
        return _load_yaml("subject_01_cond_02_run_01_spatiotemporal.yaml")

    def test_step_time(self, data):
        v = _get_mean(data, "step_time")
        assert abs(v - 0.45) < 0.06, f"step_time={v}, expected ~0.45 s"

    def test_stride_time(self, data):
        v = _get_mean(data, "stride_time")
        assert abs(v - 0.90) < 0.06, f"stride_time={v}, expected ~0.90 s"

    def test_walking_speed(self, data):
        v = _get_mean(data, "walking_speed")
        assert abs(v - 1.80) < 0.20, f"walking_speed={v}, expected ~1.80 m/s"

    def test_step_length(self, data):
        v = _get_mean(data, "step_length")
        assert abs(v - 0.81) < 0.06, f"step_length={v}, expected ~0.81 m"


# ---------------------------------------------------------------------------
# 7. Stability comparison: fast vs. normal
# ---------------------------------------------------------------------------

class TestStabilityComparison:
    @pytest.fixture
    def stab_c1(self):
        return _load_yaml("subject_01_cond_01_run_01_stability.yaml")

    @pytest.fixture
    def stab_c2(self):
        return _load_yaml("subject_01_cond_02_run_01_stability.yaml")

    def test_mos_ap_more_negative_at_fast_speed(self, stab_c1, stab_c2):
        ap_c1 = _get_mean(stab_c1, "mos_ap")
        ap_c2 = _get_mean(stab_c2, "mos_ap")
        assert ap_c2 < ap_c1, (
            f"Fast MoS_AP ({ap_c2:.4f}) should be more negative "
            f"than normal ({ap_c1:.4f})"
        )

    def test_mos_ap_fast_value(self, stab_c2):
        v = _get_mean(stab_c2, "mos_ap")
        assert abs(v - (-0.147)) < 0.050, f"Fast MoS AP={v}, expected ~-0.147 m"


# ---------------------------------------------------------------------------
# 8. Aggregation across runs
# ---------------------------------------------------------------------------

class TestAggregation:
    def test_aggregated_has_spatiotemporal_keys(self):
        data = _load_yaml("subject_01_cond_01_aggregated.yaml")
        found = False
        for key in ["step_time", "stride_time", "step_length", "walking_speed",
                     "mos_ml", "mos_ap"]:
            if key in data:
                found = True
                break
        assert found, "Aggregated file must contain at least one metric key"

    def test_aggregated_consistent_with_run(self):
        agg = _load_yaml("subject_01_cond_01_aggregated.yaml")
        run1 = _load_yaml("subject_01_cond_01_run_01_spatiotemporal.yaml")
        for key in ["step_time", "stride_time", "step_length"]:
            if key in agg and key in run1:
                agg_val = _get_mean(agg, key)
                run_val = _get_mean(run1, key)
                assert abs(agg_val - run_val) < 0.08, (
                    f"Aggregated {key}={agg_val} too far from "
                    f"run1 {key}={run_val}"
                )
                break


# ---------------------------------------------------------------------------
# 9. Summary CSV
# ---------------------------------------------------------------------------

class TestSummaryCSV:
    def test_summary_has_rows(self):
        path = os.path.join(OUTPUT_DIR, "summary.csv")
        with open(path) as f:
            lines = f.readlines()
        # header + at least 4 data rows (2 conds x 2 runs)
        assert len(lines) >= 5, (
            f"summary.csv has {len(lines)} lines, expected header + >=4 rows"
        )

    def test_summary_has_expected_columns(self):
        path = os.path.join(OUTPUT_DIR, "summary.csv")
        with open(path) as f:
            header = f.readline().strip().lower()
        for col in ["condition", "run", "step_time", "mos_ml", "mos_ap"]:
            assert col in header, f"summary.csv header missing column: {col}"


# ---------------------------------------------------------------------------
# 10. Entry point
# ---------------------------------------------------------------------------

class TestEntryPoint:
    def test_run_pi_exists(self):
        assert os.path.exists("/app/run_pi"), "/app/run_pi must exist"

    def test_run_pi_executable(self):
        assert os.access("/app/run_pi", os.X_OK), "/app/run_pi must be executable"
