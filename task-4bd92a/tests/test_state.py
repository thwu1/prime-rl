
import pytest
import pandas as pd
import numpy as np
import json
import os


@pytest.fixture(scope="module")
def metadata():
    return pd.read_csv("/app/dataset/metadata.csv")


@pytest.fixture(scope="module")
def config():
    with open("/app/config.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def task1():
    return pd.read_csv("/app/output/task1_targets.csv")


@pytest.fixture(scope="module")
def task23():
    return pd.read_csv("/app/output/task23_targets.csv")


@pytest.fixture(scope="module")
def metrics():
    with open("/app/output/metrics.json") as f:
        return json.load(f)


# ---------- Output existence ----------


class TestOutputFilesExist:
    def test_task1_exists(self):
        assert os.path.exists("/app/output/task1_targets.csv"), \
            "task1_targets.csv not found"

    def test_task23_exists(self):
        assert os.path.exists("/app/output/task23_targets.csv"), \
            "task23_targets.csv not found"

    def test_metrics_exists(self):
        assert os.path.exists("/app/output/metrics.json"), \
            "metrics.json not found"


# ---------- Task 1 structure ----------


class TestTask1Structure:
    def test_required_columns(self, task1):
        required = {"trace_name", "trace_split", "sampling_rate",
                     "start_sample", "end_sample", "trace_type"}
        assert required.issubset(set(task1.columns)), \
            f"Missing columns: {required - set(task1.columns)}"

    def test_trace_types_valid(self, task1):
        assert set(task1["trace_type"].unique()).issubset({"earthquake", "noise"})

    def test_only_eval_splits(self, task1):
        assert set(task1["trace_split"].unique()).issubset({"dev", "test"})

    def test_window_size_upper_bound(self, task1, config):
        max_win = config["task1_window_seconds"] * config["target_sampling_rate"]
        diff = task1["end_sample"] - task1["start_sample"]
        assert (diff <= max_win).all(), "Some task1 windows exceed max size"

    def test_window_size_lower_bound(self, task1):
        diff = task1["end_sample"] - task1["start_sample"]
        assert (diff > 100).all(), "Some task1 windows are too small (<=100)"

    def test_window_bounds_nonnegative(self, task1):
        assert (task1["start_sample"] >= 0).all()
        assert (task1["end_sample"] > task1["start_sample"]).all()

    def test_reasonable_row_count(self, task1):
        # Dev: ~17 traces → ~29 targets; Test: ~19 traces → ~31 targets
        assert len(task1) >= 40, f"Too few task1 targets: {len(task1)}"
        assert len(task1) <= 80, f"Too many task1 targets: {len(task1)}"


# ---------- Task 1 properties ----------


class TestTask1Properties:
    def test_earthquake_traces_have_arrivals(self, task1, metadata, config):
        """Every earthquake target must come from a trace with phase arrivals."""
        phase_dict = config["phase_dict"]
        eq = task1[task1["trace_type"] == "earthquake"]
        for _, row in eq.iterrows():
            trace = metadata[metadata["trace_name"] == row["trace_name"]]
            assert len(trace) > 0, f"Trace {row['trace_name']} not in metadata"
            trace = trace.iloc[0]
            has_arrival = any(
                col in trace.index and pd.notna(trace[col])
                for col in phase_dict
            )
            assert has_arrival, \
                f"Earthquake target for {row['trace_name']} has no arrivals"

    def test_noise_only_traces_produce_noise(self, task1, metadata, config):
        """Traces with no arrivals should only produce noise targets."""
        phase_dict = config["phase_dict"]
        for _, trace in metadata.iterrows():
            if trace["split"] not in ("dev", "test"):
                continue
            has_arrival = any(
                col in trace.index and pd.notna(trace[col])
                for col in phase_dict
            )
            if has_arrival:
                continue
            targets = task1[task1["trace_name"] == trace["trace_name"]]
            assert len(targets) > 0, \
                f"Noise trace {trace['trace_name']} should have a target"
            assert (targets["trace_type"] == "noise").all(), \
                f"Noise trace {trace['trace_name']} has non-noise targets"

    def test_noise_before_early_events(self, task1, metadata, config):
        """Traces where first arrival > window_length should have noise windows."""
        phase_dict = config["phase_dict"]
        target_sr = config["target_sampling_rate"]
        windowlen = config["task1_window_seconds"] * target_sr

        for _, trace in metadata.iterrows():
            if trace["split"] not in ("dev", "test"):
                continue
            sr = trace["trace_sampling_rate_hz"]
            arrivals = []
            for col in phase_dict:
                if col in trace.index and pd.notna(trace[col]):
                    arrivals.append(int(trace[col]) * target_sr / sr)
            if not arrivals:
                continue
            first_arrival = min(arrivals)
            targets = task1[task1["trace_name"] == trace["trace_name"]]
            types = set(targets["trace_type"])

            assert "earthquake" in types, \
                f"Trace {trace['trace_name']} missing earthquake target"
            if first_arrival > windowlen:
                assert "noise" in types, \
                    f"Trace {trace['trace_name']} (first_arrival={first_arrival:.0f}" \
                    f" > {windowlen}) should have a noise target"


# ---------- Task 23 structure ----------


class TestTask23Structure:
    def test_required_columns(self, task23):
        required = {"trace_name", "trace_split", "sampling_rate",
                     "start_sample", "end_sample", "phase_label", "phase_onset"}
        assert required.issubset(set(task23.columns)), \
            f"Missing columns: {required - set(task23.columns)}"

    def test_phase_labels_valid(self, task23):
        assert set(task23["phase_label"].unique()).issubset({"P", "S"})

    def test_only_eval_splits(self, task23):
        assert set(task23["trace_split"].unique()).issubset({"dev", "test"})

    def test_window_size_upper_bound(self, task23, config):
        max_win = config["task23_window_seconds"] * config["target_sampling_rate"]
        diff = task23["end_sample"] - task23["start_sample"]
        assert (diff <= max_win).all(), "Some task23 windows exceed max size"

    def test_window_size_lower_bound(self, task23):
        diff = task23["end_sample"] - task23["start_sample"]
        assert (diff > 100).all(), "Some task23 windows are too small"

    def test_onset_within_window(self, task23):
        assert (task23["phase_onset"] >= task23["start_sample"]).all(), \
            "Some onsets are before window start"
        assert (task23["phase_onset"] < task23["end_sample"]).all(), \
            "Some onsets are at or after window end"

    def test_reasonable_row_count(self, task23):
        # Dev: ~28, Test: ~32 → total ~60
        assert len(task23) >= 40, f"Too few task23 targets: {len(task23)}"
        assert len(task23) <= 80, f"Too many task23 targets: {len(task23)}"


# ---------- Task 23 edge cases ----------


class TestTask23EdgeCases:
    def test_close_spacing_excluded(self, task23, metadata, config):
        """Traces with all arrivals too close together should have 0 task23 targets."""
        phase_dict = config["phase_dict"]
        target_sr = config["target_sampling_rate"]
        min_spacing = config["min_phase_spacing_seconds"] * target_sr
        windowlen = config["task23_window_seconds"] * target_sr

        for _, trace in metadata.iterrows():
            if trace["split"] not in ("dev", "test"):
                continue
            sr = trace["trace_sampling_rate_hz"]
            arrivals = sorted([
                int(trace[col]) * target_sr / sr
                for col in phase_dict
                if col in trace.index and pd.notna(trace[col])
            ])
            if len(arrivals) < 2:
                continue

            # Check if any arrival can be isolated
            any_isolable = False
            for j in range(len(arrivals)):
                before = (arrivals[j - 1] + min_spacing) if j > 0 else 0
                after = (arrivals[j + 1] - min_spacing) if j < len(arrivals) - 1 else float("inf")
                if (after - before >= windowlen and
                        before <= arrivals[j] and after >= arrivals[j]):
                    any_isolable = True
                    break

            if not any_isolable:
                targets = task23[task23["trace_name"] == trace["trace_name"]]
                assert len(targets) == 0, \
                    f"Close-spacing trace {trace['trace_name']} should have 0 " \
                    f"task23 targets but has {len(targets)}"

    def test_noise_traces_excluded(self, task23, metadata, config):
        """Noise-only traces should have no task23 targets."""
        phase_dict = config["phase_dict"]
        for _, trace in metadata.iterrows():
            if trace["split"] not in ("dev", "test"):
                continue
            has_arrival = any(
                col in trace.index and pd.notna(trace[col])
                for col in phase_dict
            )
            if not has_arrival:
                targets = task23[task23["trace_name"] == trace["trace_name"]]
                assert len(targets) == 0, \
                    f"Noise trace {trace['trace_name']} has {len(targets)} task23 targets"

    def test_variant_phase_types_mapped(self, task23, metadata, config):
        """Traces using variant phase columns (Pg, Sg, etc.) produce P/S labels."""
        phase_dict = config["phase_dict"]
        variant_p = {"trace_Pg_arrival_sample", "trace_Pn_arrival_sample",
                     "trace_pP_arrival_sample", "trace_P_arrival_sample"}
        standard_p = "trace_p_arrival_sample"

        for _, trace in metadata.iterrows():
            if trace["split"] not in ("dev", "test"):
                continue
            has_standard = pd.notna(trace.get(standard_p))
            has_variant = any(
                pd.notna(trace.get(col)) for col in variant_p if col in trace.index
            )
            if has_variant and not has_standard:
                targets = task23[task23["trace_name"] == trace["trace_name"]]
                p_targets = targets[targets["phase_label"] == "P"]
                # These traces have P-type arrivals only through variant columns
                # They should still produce P-labeled targets
                if len(p_targets) > 0:
                    assert (p_targets["phase_label"] == "P").all()

    def test_different_sampling_rate_conversion(self, task23, metadata, config):
        """Traces at non-target sampling rates should have correctly converted onsets."""
        phase_dict = config["phase_dict"]
        target_sr = config["target_sampling_rate"]

        for _, trace in metadata.iterrows():
            if trace["split"] not in ("dev", "test"):
                continue
            sr = trace["trace_sampling_rate_hz"]
            if sr == target_sr:
                continue

            targets = task23[task23["trace_name"] == trace["trace_name"]]
            if len(targets) == 0:
                continue

            for _, t in targets.iterrows():
                expected_onsets = []
                for col, phase in phase_dict.items():
                    if col in trace.index and pd.notna(trace[col]):
                        if phase == t["phase_label"]:
                            expected_onsets.append(
                                int(trace[col]) * target_sr / sr
                            )
                assert any(abs(t["phase_onset"] - eo) < 2 for eo in expected_onsets), \
                    f"Onset {t['phase_onset']} for {trace['trace_name']} " \
                    f"(sr={sr}) doesn't match expected {expected_onsets}"

    def test_p_only_traces(self, task23, metadata, config):
        """Traces with only P arrivals should produce only P targets."""
        phase_dict = config["phase_dict"]
        p_cols = [c for c, p in phase_dict.items() if p == "P"]
        s_cols = [c for c, p in phase_dict.items() if p == "S"]

        for _, trace in metadata.iterrows():
            if trace["split"] not in ("dev", "test"):
                continue
            has_p = any(pd.notna(trace.get(c)) for c in p_cols if c in trace.index)
            has_s = any(pd.notna(trace.get(c)) for c in s_cols if c in trace.index)
            if has_p and not has_s:
                targets = task23[task23["trace_name"] == trace["trace_name"]]
                if len(targets) > 0:
                    assert (targets["phase_label"] == "P").all(), \
                        f"P-only trace {trace['trace_name']} has S targets"
                    assert len(targets) >= 1, \
                        f"P-only trace {trace['trace_name']} should have >= 1 target"

    def test_multi_p_arrivals_produce_multiple_targets(self, task23, metadata, config):
        """Traces with well-separated Pg + pP arrivals should produce multiple P targets."""
        target_sr = config["target_sampling_rate"]

        for _, trace in metadata.iterrows():
            if trace["split"] not in ("dev", "test"):
                continue
            sr = trace["trace_sampling_rate_hz"]
            pg = trace.get("trace_Pg_arrival_sample")
            pp = trace.get("trace_pP_arrival_sample")
            if pd.isna(pg) or pd.isna(pp):
                continue
            pg_t = int(pg) * target_sr / sr
            pp_t = int(pp) * target_sr / sr
            spacing = abs(pp_t - pg_t)
            if spacing < config["min_phase_spacing_seconds"] * target_sr:
                continue
            targets = task23[task23["trace_name"] == trace["trace_name"]]
            p_targets = targets[targets["phase_label"] == "P"]
            assert len(p_targets) >= 2, \
                f"Trace {trace['trace_name']} with Pg@{pg_t:.0f} pP@{pp_t:.0f} " \
                f"(spacing={spacing:.0f}) should have >= 2 P targets but has {len(p_targets)}"


# ---------- Metrics ----------


class TestMetrics:
    def test_detection_threshold_present(self, metrics):
        assert "det_threshold" in metrics

    def test_detection_threshold_range(self, metrics):
        assert 0 < metrics["det_threshold"] < 1

    def test_detection_f1_present(self, metrics):
        assert "test_det_f1" in metrics

    def test_detection_f1_quality(self, metrics):
        assert metrics["test_det_f1"] > 0.85, \
            f"Detection F1 = {metrics['test_det_f1']:.3f} is too low"

    def test_detection_auc_present(self, metrics):
        assert "test_det_auc" in metrics

    def test_detection_auc_quality(self, metrics):
        assert metrics["test_det_auc"] > 0.9, \
            f"Detection AUC = {metrics['test_det_auc']:.3f} is too low"

    def test_detection_precision_recall(self, metrics):
        for key in ("test_det_precision", "test_det_recall"):
            assert key in metrics, f"{key} missing from metrics"
            assert 0 <= metrics[key] <= 1, f"{key} = {metrics[key]} out of [0,1]"

    def test_phase_threshold_present(self, metrics):
        assert "phase_threshold" in metrics

    def test_phase_f1_present(self, metrics):
        assert "test_phase_f1" in metrics

    def test_phase_f1_quality(self, metrics):
        assert metrics["test_phase_f1"] > 0.8, \
            f"Phase F1 = {metrics['test_phase_f1']:.3f} is too low"

    def test_onset_mae_present(self, metrics):
        has_mae = any(k.endswith("_mae_s") for k in metrics)
        assert has_mae, "No onset MAE metrics found"

    def test_onset_mae_quality(self, metrics):
        for key in metrics:
            if key.endswith("_mae_s"):
                assert metrics[key] < 0.5, \
                    f"Onset MAE {key} = {metrics[key]:.3f}s is too large"

    def test_dev_metrics_present(self, metrics):
        assert "dev_det_f1" in metrics, "dev_det_f1 missing"
        assert "dev_det_auc" in metrics, "dev_det_auc missing"

    def test_metric_values_finite(self, metrics):
        for key, val in metrics.items():
            assert np.isfinite(val), f"Metric {key} = {val} is not finite"
