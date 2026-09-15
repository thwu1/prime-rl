import pytest
import os
import csv
import json
import numpy as np
import h5py
from sklearn.metrics import (
    precision_recall_curve,
    precision_recall_fscore_support,
    roc_auc_score,
    matthews_corrcoef,
)


RAW_DIR = "/app/raw_data"
OUTPUT_DIR = "/app/output"
TARGET_SR = 100


def load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def load_json(path):
    with open(path) as f:
        return json.load(f)


def _decode_hdf5_str(val):
    raw = val[()]
    if isinstance(raw, bytes):
        return raw.decode()
    return str(raw)


# ===========================================================================
# Test Suite 1: metadata.csv structure
# ===========================================================================
class TestDatasetMetadata:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.meta_path = f"{OUTPUT_DIR}/dataset/metadata.csv"
        assert os.path.exists(self.meta_path), "metadata.csv not found"
        self.rows = load_csv(self.meta_path)
        assert len(self.rows) > 0, "metadata.csv is empty"
        self.columns = set(self.rows[0].keys())

    def test_has_trace_name(self):
        assert "trace_name" in self.columns

    def test_has_split(self):
        assert "split" in self.columns

    def test_source_columns_naming(self):
        required = {
            "source_id", "source_origin_time", "source_latitude_deg",
            "source_longitude_deg", "source_depth_km", "source_magnitude",
        }
        missing = required - self.columns
        assert not missing, f"Missing source columns: {missing}"

    def test_station_columns_naming(self):
        required = {
            "station_network_code", "station_code",
            "station_latitude_deg", "station_longitude_deg",
            "station_elevation_m",
        }
        missing = required - self.columns
        assert not missing, f"Missing station columns: {missing}"

    def test_trace_columns_naming(self):
        required = {
            "trace_p_arrival_sample", "trace_s_arrival_sample",
            "trace_sampling_rate_hz", "trace_npts",
            "trace_snr_db", "trace_quality",
        }
        missing = required - self.columns
        assert not missing, f"Missing trace columns: {missing}"

    def test_correct_number_of_rows(self):
        winfo = load_json(f"{RAW_DIR}/waveforms_info.json")
        assert len(self.rows) == len(winfo), \
            f"Expected {len(winfo)} rows, got {len(self.rows)}"

    def test_splits_present(self):
        splits = set(r["split"] for r in self.rows)
        assert splits == {"train", "dev", "test"}, f"Got splits: {splits}"

    def test_split_counts(self):
        split_map = load_json(f"{RAW_DIR}/split_assignment.json")
        expected = {"train": 0, "dev": 0, "test": 0}
        for v in split_map.values():
            expected[v] += 1
        actual = {"train": 0, "dev": 0, "test": 0}
        for row in self.rows:
            actual[row["split"]] += 1
        for sp in ["train", "dev", "test"]:
            assert actual[sp] == expected[sp], \
                f"Split '{sp}': expected {expected[sp]}, got {actual[sp]}"

    def test_trace_name_uses_block_notation(self):
        for row in self.rows:
            assert "$" in row["trace_name"], \
                f"trace_name '{row['trace_name']}' missing block notation ($)"

    def test_all_sampling_rates_100hz(self):
        """All traces must be harmonized to 100 Hz."""
        for row in self.rows:
            sr = float(row["trace_sampling_rate_hz"])
            assert sr == TARGET_SR, \
                f"Trace has sampling rate {sr}, expected {TARGET_SR}"

    def test_all_trace_lengths(self):
        """All traces must be 3000 samples (100 Hz x 30s)."""
        for row in self.rows:
            npts = int(row["trace_npts"])
            assert npts == 3000, \
                f"Trace has {npts} samples, expected 3000"

    def test_quality_tiers_valid(self):
        """Earthquake traces must have valid quality tiers, noise must not."""
        for row in self.rows:
            if row.get("source_type") == "earthquake":
                assert row["trace_quality"] in ("A", "B", "C"), \
                    f"Invalid quality tier: {row['trace_quality']}"
                snr = float(row["trace_snr_db"])
                tier = row["trace_quality"]
                if snr >= 10:
                    assert tier == "A", f"SNR {snr} should be tier A, got {tier}"
                elif snr >= 5:
                    assert tier == "B", f"SNR {snr} should be tier B, got {tier}"
                else:
                    assert tier == "C", f"SNR {snr} should be tier C, got {tier}"
            else:
                assert row["trace_quality"] == "" or row["trace_quality"] is None \
                    or row["trace_quality"] == "N/A", \
                    f"Noise trace should have no quality tier"

    def test_temporal_split_ordering(self):
        events = load_json(f"{RAW_DIR}/events.json")
        event_times = {e["event_id"]: e["origin_time"] for e in events}
        split_times = {"train": [], "dev": [], "test": []}
        for row in self.rows:
            sid = row.get("source_id", "")
            if sid and sid in event_times:
                split_times[row["split"]].append(event_times[sid])
        if split_times["train"] and split_times["dev"]:
            assert max(split_times["train"]) <= min(split_times["dev"])
        if split_times["dev"] and split_times["test"]:
            assert max(split_times["dev"]) <= min(split_times["test"])


# ===========================================================================
# Test Suite 2: waveforms.hdf5 structure
# ===========================================================================
class TestDatasetHDF5:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.hdf5_path = f"{OUTPUT_DIR}/dataset/waveforms.hdf5"
        assert os.path.exists(self.hdf5_path), "waveforms.hdf5 not found"
        self.f = h5py.File(self.hdf5_path, "r")
        yield
        self.f.close()

    def test_data_format_group_exists(self):
        assert "data_format" in self.f

    def test_data_group_exists(self):
        assert "data" in self.f

    def test_dimension_order(self):
        dim_order = _decode_hdf5_str(self.f["data_format"]["dimension_order"])
        assert dim_order == "NCW", f"Expected NCW, got {dim_order}"

    def test_component_order(self):
        co = _decode_hdf5_str(self.f["data_format"]["component_order"])
        assert co == "ZNE", f"Expected ZNE, got {co}"

    def test_sampling_rate(self):
        sr = float(self.f["data_format"]["sampling_rate"][()])
        assert sr == TARGET_SR, f"Expected {TARGET_SR}, got {sr}"

    def test_blocks_exist(self):
        assert len(self.f["data"].keys()) > 0

    def test_block_shapes_are_3d_ncw(self):
        for key in self.f["data"].keys():
            shape = self.f["data"][key].shape
            assert len(shape) == 3, f"Block '{key}' has {len(shape)}D, expected 3D"
            assert shape[1] == 3, f"Block '{key}' C-dim is {shape[1]}, expected 3"
            assert shape[2] == 3000, f"Block '{key}' W-dim is {shape[2]}, expected 3000"

    def test_all_traces_accessible(self):
        rows = load_csv(f"{OUTPUT_DIR}/dataset/metadata.csv")
        for row in rows:
            tn = row["trace_name"]
            assert "$" in tn
            block_name, idx_str = tn.split("$", 1)
            idx = int(idx_str)
            assert block_name in self.f["data"], \
                f"Block '{block_name}' not found for trace '{tn}'"
            assert idx < self.f["data"][block_name].shape[0], \
                f"Index {idx} out of bounds for block '{block_name}'"

    def test_blocks_respect_splits(self):
        rows = load_csv(f"{OUTPUT_DIR}/dataset/metadata.csv")
        block_splits = {}
        for row in rows:
            bn = row["trace_name"].split("$")[0]
            block_splits.setdefault(bn, set()).add(row["split"])
        for bn, splits in block_splits.items():
            assert len(splits) == 1, f"Block '{bn}' mixes splits: {splits}"

    def test_native_zne_traces_match_raw(self):
        """For 100 Hz ZNE traces, output must exactly match raw data."""
        rows = load_csv(f"{OUTPUT_DIR}/dataset/metadata.csv")
        stations_list = load_json(f"{RAW_DIR}/stations.json")
        station_map = {s["station"]: s for s in stations_list}
        winfo = load_json(f"{RAW_DIR}/waveforms_info.json")
        winfo_map = {w["trace_id"]: w for w in winfo}

        checked = 0
        for row in rows:
            if checked >= 5:
                break
            sid = row.get("source_id", "")
            sta_code = row.get("station_code", "")
            if not sid or not sta_code:
                continue
            raw_tid = f"{sid}_{sta_code}"
            raw_path = f"{RAW_DIR}/waveforms/{raw_tid}.npy"
            if not os.path.exists(raw_path):
                continue
            sta = station_map.get(sta_code)
            if not sta or sta["sampling_rate_hz"] != 100 or sta["component_order"] != "ZNE":
                continue

            raw_wf = np.load(raw_path)
            block_name, idx_str = row["trace_name"].split("$", 1)
            idx = int(idx_str)
            stored_wf = self.f["data"][block_name][idx]

            np.testing.assert_allclose(
                stored_wf, raw_wf, atol=1e-5,
                err_msg=f"Waveform mismatch for native ZNE trace {raw_tid}")
            checked += 1

        assert checked >= 3, \
            f"Only verified {checked} native ZNE waveforms, need at least 3"

    def test_component_order_verified_by_energy(self):
        """Z component should have P-wave energy (higher amplitude near P arrival)."""
        rows = load_csv(f"{OUTPUT_DIR}/dataset/metadata.csv")
        checked = 0
        for row in rows:
            if checked >= 10:
                break
            if row.get("source_type") != "earthquake":
                continue
            p_arr = row.get("trace_p_arrival_sample", "")
            s_arr = row.get("trace_s_arrival_sample", "")
            if not p_arr or not s_arr:
                continue
            p_sample = int(p_arr)
            s_sample = int(s_arr)
            snr = float(row.get("trace_snr_db", "0"))
            if snr < 8:
                continue  # only check clear signals

            block_name, idx_str = row["trace_name"].split("$", 1)
            idx = int(idx_str)
            trace = self.f["data"][block_name][idx]  # (C=3, W=3000)

            # Z component (index 0) should have higher energy in P window
            p_window = 200
            z_p_energy = np.mean(trace[0, p_sample:p_sample + p_window] ** 2)
            n_p_energy = np.mean(trace[1, p_sample:p_sample + p_window] ** 2)
            e_p_energy = np.mean(trace[2, p_sample:p_sample + p_window] ** 2)

            assert z_p_energy > n_p_energy * 0.5, \
                f"Z component P-window energy ({z_p_energy:.4f}) not significantly above N ({n_p_energy:.4f})"
            checked += 1

        assert checked >= 3, \
            f"Only verified {checked} traces for component order, need at least 3"


# ===========================================================================
# Test Suite 3: Signal quality (SNR)
# ===========================================================================
class TestSignalQuality:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.meta_path = f"{OUTPUT_DIR}/dataset/metadata.csv"
        self.hdf5_path = f"{OUTPUT_DIR}/dataset/waveforms.hdf5"
        assert os.path.exists(self.meta_path)
        assert os.path.exists(self.hdf5_path)
        self.rows = load_csv(self.meta_path)
        self.f = h5py.File(self.hdf5_path, "r")
        yield
        self.f.close()

    def test_snr_values_match(self):
        """Verify trace_snr_db matches independent SNR computation from output HDF5."""
        eq_rows = [r for r in self.rows
                    if r.get("source_type") == "earthquake"
                    and r.get("trace_p_arrival_sample")
                    and r.get("trace_s_arrival_sample")]

        checked = 0
        for row in eq_rows:
            if checked >= 15:
                break
            p_sample = int(row["trace_p_arrival_sample"])
            s_sample = int(row["trace_s_arrival_sample"])
            if p_sample < 10 or s_sample <= p_sample:
                continue

            block_name, idx_str = row["trace_name"].split("$", 1)
            idx = int(idx_str)
            trace = self.f["data"][block_name][idx]
            z_comp = trace[0]  # Z component in NCW order

            noise = z_comp[:p_sample]
            signal = z_comp[p_sample:s_sample]
            if len(noise) < 5 or len(signal) < 5:
                continue

            noise_power = float(np.mean(noise.astype(np.float64) ** 2))
            signal_power = float(np.mean(signal.astype(np.float64) ** 2))

            if noise_power > 0:
                expected_snr = 10 * np.log10(signal_power / noise_power)
            else:
                expected_snr = 50.0

            got_snr = float(row["trace_snr_db"])
            assert abs(got_snr - expected_snr) < 0.5, \
                f"SNR mismatch for {row['trace_name']}: expected {expected_snr:.2f}, got {got_snr:.2f}"
            checked += 1

        assert checked >= 8, \
            f"Only verified {checked} SNR values, need at least 8"

    def test_snr_diversity(self):
        """Ensure all three quality tiers are represented."""
        eq_rows = [r for r in self.rows
                    if r.get("source_type") == "earthquake"
                    and r.get("trace_quality")]
        tiers = set(r["trace_quality"] for r in eq_rows)
        assert "A" in tiers, "No tier A traces found"
        assert "B" in tiers, "No tier B traces found"
        assert "C" in tiers, "No tier C traces found"


# ===========================================================================
# Test Suite 4: quality_report.json
# ===========================================================================
class TestQualityReport:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.report_path = f"{OUTPUT_DIR}/quality_report.json"
        assert os.path.exists(self.report_path), "quality_report.json not found"
        with open(self.report_path) as f:
            self.report = json.load(f)

    def test_has_tier_counts(self):
        assert "tier_counts" in self.report
        for split in ["train", "dev", "test"]:
            assert split in self.report["tier_counts"]
            for tier in ["A", "B", "C"]:
                assert tier in self.report["tier_counts"][split]

    def test_has_snr_statistics(self):
        assert "snr_statistics" in self.report
        for key in ["mean_db", "median_db", "min_db", "max_db"]:
            assert key in self.report["snr_statistics"]

    def test_tier_counts_sum(self):
        """Tier counts per split must sum to earthquake trace count per split."""
        rows = load_csv(f"{OUTPUT_DIR}/dataset/metadata.csv")
        eq_per_split = {"train": 0, "dev": 0, "test": 0}
        for r in rows:
            if r.get("source_type") == "earthquake":
                eq_per_split[r["split"]] += 1

        for split in ["train", "dev", "test"]:
            tier_sum = sum(self.report["tier_counts"][split].values())
            assert tier_sum == eq_per_split[split], \
                f"Tier counts for {split} sum to {tier_sum}, expected {eq_per_split[split]}"

    def test_snr_stats_reasonable(self):
        stats = self.report["snr_statistics"]
        assert stats["min_db"] < stats["mean_db"] < stats["max_db"]
        assert stats["min_db"] < stats["median_db"] < stats["max_db"]


# ===========================================================================
# Test Suite 5: evaluation metrics
# ===========================================================================
class TestEvaluationMetrics:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.results_path = f"{OUTPUT_DIR}/results.csv"
        assert os.path.exists(self.results_path), "results.csv not found"
        with open(self.results_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) >= 1, "results.csv is empty"
        self.results = rows[0]

        self.task1_dev = load_csv(f"{RAW_DIR}/predictions/task1_dev.csv")
        self.task1_test = load_csv(f"{RAW_DIR}/predictions/task1_test.csv")
        self.task23_dev = load_csv(f"{RAW_DIR}/predictions/task23_dev.csv")
        self.task23_test = load_csv(f"{RAW_DIR}/predictions/task23_test.csv")

    def test_results_has_all_columns(self):
        required = {
            "det_precision", "det_recall", "det_f1", "det_auc",
            "cls_precision", "cls_recall", "cls_f1", "cls_mcc",
            "p_mean_s", "p_std_s", "p_mae_s",
            "s_mean_s", "s_std_s", "s_mae_s",
        }
        missing = required - set(self.results.keys())
        assert not missing, f"Missing columns: {missing}"

    # --- Task 1: Detection (P-R curve F1 optimization) ---

    def _det_opt_thr(self):
        ds = np.array([float(r["score_detection"]) for r in self.task1_dev])
        dl = np.array([int(r["true_label"]) for r in self.task1_dev])
        prec, recall, thr = precision_recall_curve(dl, ds)
        f1 = 2 * prec * recall / (prec + recall)
        opt_idx = np.nanargmax(f1)
        return thr[opt_idx]

    def test_detection_f1(self):
        opt_thr = self._det_opt_thr()
        ts = np.array([float(r["score_detection"]) for r in self.task1_test])
        tl = np.array([int(r["true_label"]) for r in self.task1_test])
        _, _, exp_f1, _ = precision_recall_fscore_support(
            tl, ts > opt_thr, average="binary")
        got = float(self.results["det_f1"])
        assert abs(got - exp_f1) < 0.02, \
            f"det_f1: expected ~{exp_f1:.4f}, got {got:.4f}"

    def test_detection_precision(self):
        opt_thr = self._det_opt_thr()
        ts = np.array([float(r["score_detection"]) for r in self.task1_test])
        tl = np.array([int(r["true_label"]) for r in self.task1_test])
        exp_p, _, _, _ = precision_recall_fscore_support(
            tl, ts > opt_thr, average="binary")
        got = float(self.results["det_precision"])
        assert abs(got - exp_p) < 0.02, \
            f"det_precision: expected ~{exp_p:.4f}, got {got:.4f}"

    def test_detection_recall(self):
        opt_thr = self._det_opt_thr()
        ts = np.array([float(r["score_detection"]) for r in self.task1_test])
        tl = np.array([int(r["true_label"]) for r in self.task1_test])
        _, exp_r, _, _ = precision_recall_fscore_support(
            tl, ts > opt_thr, average="binary")
        got = float(self.results["det_recall"])
        assert abs(got - exp_r) < 0.02, \
            f"det_recall: expected ~{exp_r:.4f}, got {got:.4f}"

    def test_detection_auc(self):
        ts = np.array([float(r["score_detection"]) for r in self.task1_test])
        tl = np.array([int(r["true_label"]) for r in self.task1_test])
        exp_auc = roc_auc_score(tl, ts)
        got = float(self.results["det_auc"])
        assert abs(got - exp_auc) < 0.02, \
            f"det_auc: expected ~{exp_auc:.4f}, got {got:.4f}"

    # --- Task 2: Phase Classification ---

    def _cls_f1_thr(self):
        ds = np.array([float(r["score_p_or_s"]) for r in self.task23_dev])
        dl = np.array([1 if r["phase_label"] == "P" else 0 for r in self.task23_dev])
        prec, recall, thr = precision_recall_curve(dl, ds)
        f1 = 2 * prec * recall / (prec + recall)
        opt_idx = np.nanargmax(f1)
        return thr[opt_idx]

    def test_classification_f1(self):
        opt_thr = self._cls_f1_thr()
        ts = np.array([float(r["score_p_or_s"]) for r in self.task23_test])
        tl = np.array([1 if r["phase_label"] == "P" else 0 for r in self.task23_test])
        _, _, exp_f1, _ = precision_recall_fscore_support(
            tl, ts > opt_thr, average="binary")
        got = float(self.results["cls_f1"])
        assert abs(got - exp_f1) < 0.02, \
            f"cls_f1: expected ~{exp_f1:.4f}, got {got:.4f}"

    def test_classification_mcc(self):
        """MCC must use separately optimized threshold (50 quantile candidates)."""
        ds = np.array([float(r["score_p_or_s"]) for r in self.task23_dev])
        dl = np.array([1 if r["phase_label"] == "P" else 0 for r in self.task23_dev])
        ts = np.array([float(r["score_p_or_s"]) for r in self.task23_test])
        tl = np.array([1 if r["phase_label"] == "P" else 0 for r in self.task23_test])

        sorted_dev = np.sort(ds)
        mcc_thrs = sorted_dev[np.linspace(0, len(sorted_dev) - 1, 50, dtype=int)]
        mccs = [matthews_corrcoef(dl, ds > t) for t in mcc_thrs]
        mcc_thr = mcc_thrs[np.argmax(mccs)]

        exp_mcc = matthews_corrcoef(tl, ts > mcc_thr)
        got = float(self.results["cls_mcc"])
        assert abs(got - exp_mcc) < 0.03, \
            f"cls_mcc: expected ~{exp_mcc:.4f}, got {got:.4f}"

    # --- Task 3: Onset Timing (RMSE, per-entry sampling rate) ---

    def test_onset_timing_p(self):
        p_rows = [r for r in self.task23_test if r["phase_label"] == "P"]
        diffs = np.array([
            (float(r["p_sample_pred"]) - float(r["phase_onset"]))
            / float(r["sampling_rate"])
            for r in p_rows
        ])

        got_mean = float(self.results["p_mean_s"])
        assert abs(got_mean - float(np.mean(diffs))) < 0.005, \
            f"p_mean_s mismatch: expected {np.mean(diffs):.6f}, got {got_mean:.6f}"

        got_std = float(self.results["p_std_s"])
        exp_rms = float(np.sqrt(np.mean(diffs ** 2)))
        assert abs(got_std - exp_rms) < 0.005, \
            f"p_std_s (RMSE) mismatch: expected {exp_rms:.6f}, got {got_std:.6f}"

        got_mae = float(self.results["p_mae_s"])
        assert abs(got_mae - float(np.mean(np.abs(diffs)))) < 0.005, \
            f"p_mae_s mismatch"

    def test_onset_timing_s(self):
        s_rows = [r for r in self.task23_test if r["phase_label"] == "S"]
        diffs = np.array([
            (float(r["s_sample_pred"]) - float(r["phase_onset"]))
            / float(r["sampling_rate"])
            for r in s_rows
        ])

        got_mean = float(self.results["s_mean_s"])
        assert abs(got_mean - float(np.mean(diffs))) < 0.005, \
            f"s_mean_s mismatch: expected {np.mean(diffs):.6f}, got {got_mean:.6f}"

        got_std = float(self.results["s_std_s"])
        exp_rms = float(np.sqrt(np.mean(diffs ** 2)))
        assert abs(got_std - exp_rms) < 0.005, \
            f"s_std_s (RMSE) mismatch: expected {exp_rms:.6f}, got {got_std:.6f}"

        got_mae = float(self.results["s_mae_s"])
        assert abs(got_mae - float(np.mean(np.abs(diffs)))) < 0.005, \
            f"s_mae_s mismatch"
