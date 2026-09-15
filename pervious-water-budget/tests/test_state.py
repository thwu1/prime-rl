
import os
import json
import math
import sqlite3
import numpy as np
import pandas as pd
import pytest
import h5py


NUM_STEPS = 8760
TOLERANCE = 0.01
COLUMNS = ["SURO", "IFWO", "AGWO"]

# Reference sums for each segment (computed from validated HSPF PWATER output)
_RS = {
    "P001": {"SURO": 1.8009868563e-01, "IFWO": 2.4565211825e+00, "AGWO": 8.6594338778e+00},
    "P002": {"SURO": 3.0241227752e-01, "IFWO": 1.8653029892e+00, "AGWO": 5.9000444538e+00},
}
_AREA = {"P001": 0.65, "P002": 0.35}

# Spot-check values at specific timesteps (row_index: {col: value})
_SPOT_P001 = {
    0:    {"SURO": 0.0,            "IFWO": 1.4692564e-03, "AGWO": 2.4298239e-03},
    500:  {"SURO": 0.0,            "IFWO": 8.2316773e-04, "AGWO": 3.3574090e-03},
    2324: {"SURO": 1.3599158e-02,  "IFWO": 4.6116444e-03, "AGWO": 2.5891892e-03},
    4000: {"SURO": 0.0,            "IFWO": 0.0,           "AGWO": 0.0},
    8759: {"SURO": 0.0,            "IFWO": 1.0710661e-04, "AGWO": 9.0776006e-04},
}
_SPOT_P002 = {
    0:    {"SURO": 0.0,            "IFWO": 1.4234029e-03, "AGWO": 1.3106953e-03},
    500:  {"SURO": 0.0,            "IFWO": 1.7236056e-04, "AGWO": 1.5545473e-03},
    2324: {"SURO": 2.8021000e-02,  "IFWO": 6.2213552e-03, "AGWO": 2.0892550e-03},
    4000: {"SURO": 0.0,            "IFWO": 0.0,           "AGWO": 0.0},
    8759: {"SURO": 0.0,            "IFWO": 3.5198881e-04, "AGWO": 1.1950893e-03},
}

# Expected parsed parameter values for UCI parsing verification
_EXPECTED_PARAMS = {
    "P001": {
        "CSNOFG": 0, "RTOPFG": 1, "UZFG": 1, "VCSFG": 1,
        "FOREST": 0.0, "LZSN": 7.35, "INFILT": 0.079, "LSUR": 50.0,
        "SLSUR": 0.1548, "KVARY": 1.0, "AGWRC": 0.993,
        "INFEXP": 2.0, "INFILD": 2.0, "DEEPFR": 0.02,
        "BASETP": 0.22, "AGWETP": 0.0,
        "CEPSC": 0.01, "UZSN": 0.85, "NSUR": 0.4,
        "INTFW": 3.0, "IRC": 0.7, "LZETP": 0.73,
    },
    "P002": {
        "CSNOFG": 0, "RTOPFG": 1, "UZFG": 1, "VCSFG": 0,
        "FOREST": 0.1, "LZSN": 5.80, "INFILT": 0.045, "LSUR": 80.0,
        "SLSUR": 0.08, "KVARY": 0.5, "AGWRC": 0.985,
        "INFEXP": 2.0, "INFILD": 2.0, "DEEPFR": 0.05,
        "BASETP": 0.15, "AGWETP": 0.02,
        "CEPSC": 0.03, "UZSN": 1.20, "NSUR": 0.3,
        "INTFW": 2.0, "IRC": 0.5, "LZETP": 0.55,
    },
}
_EXPECTED_STATES = {
    "P001": {"CEPS": 0.0462, "SURS": 0.0, "UZS": 1.6075, "IFWS": 0.0996,
             "LZS": 8.9629, "AGWS": 2.8649, "GWVS": 1.9555},
    "P002": {"CEPS": 0.02, "SURS": 0.0, "UZS": 0.85, "IFWS": 0.05,
             "LZS": 4.50, "AGWS": 1.50, "GWVS": 0.80},
}
_EXPECTED_MONTHLY = [0.09, 0.10, 0.10, 0.14, 0.17, 0.18, 0.18, 0.18, 0.17, 0.15, 0.12, 0.10]


def _load(path):
    return pd.read_csv(path)


def _close(a, b, atol=1e-5):
    """Check if two values are close, handling zeros."""
    if abs(b) < 1e-10:
        return abs(a) < atol
    return abs(a - b) < max(atol, abs(b) * 0.05)


# == UCI Parsing Verification ==================================================

class TestParsedConfig:
    def test_parsed_config_exists(self):
        assert os.path.exists("/app/parsed_config.json"), "parsed_config.json not found"

    def test_parsed_config_valid_json(self):
        with open("/app/parsed_config.json") as f:
            cfg = json.load(f)
        assert "P001" in cfg, "P001 missing from parsed_config"
        assert "P002" in cfg, "P002 missing from parsed_config"

    def test_p001_parameters(self):
        with open("/app/parsed_config.json") as f:
            cfg = json.load(f)
        params = cfg["P001"]["parameters"]
        for key, expected in _EXPECTED_PARAMS["P001"].items():
            assert key in params, f"P001 missing parameter {key}"
            actual = params[key]
            assert _close(actual, expected, 1e-4), \
                f"P001 param {key}: expected {expected}, got {actual}"

    def test_p002_parameters(self):
        with open("/app/parsed_config.json") as f:
            cfg = json.load(f)
        params = cfg["P002"]["parameters"]
        for key, expected in _EXPECTED_PARAMS["P002"].items():
            assert key in params, f"P002 missing parameter {key}"
            actual = params[key]
            assert _close(actual, expected, 1e-4), \
                f"P002 param {key}: expected {expected}, got {actual}"

    def test_p001_states(self):
        with open("/app/parsed_config.json") as f:
            cfg = json.load(f)
        states = cfg["P001"]["states"]
        for key, expected in _EXPECTED_STATES["P001"].items():
            actual = states[key]
            assert _close(actual, expected, 1e-4), \
                f"P001 state {key}: expected {expected}, got {actual}"

    def test_p002_states(self):
        with open("/app/parsed_config.json") as f:
            cfg = json.load(f)
        states = cfg["P002"]["states"]
        for key, expected in _EXPECTED_STATES["P002"].items():
            actual = states[key]
            assert _close(actual, expected, 1e-4), \
                f"P002 state {key}: expected {expected}, got {actual}"

    def test_p001_monthly_cepsc(self):
        with open("/app/parsed_config.json") as f:
            cfg = json.load(f)
        monthly = cfg["P001"]["monthly_cepsc"]
        assert len(monthly) == 12, f"Expected 12 monthly values, got {len(monthly)}"
        for i, (actual, expected) in enumerate(zip(monthly, _EXPECTED_MONTHLY)):
            assert _close(actual, expected, 1e-4), \
                f"P001 monthly_cepsc[{i}]: expected {expected}, got {actual}"

    def test_p002_no_monthly(self):
        with open("/app/parsed_config.json") as f:
            cfg = json.load(f)
        p002 = cfg["P002"]
        if "monthly_cepsc" in p002:
            assert p002["monthly_cepsc"] is None or p002["monthly_cepsc"] == [], \
                "P002 should not have monthly_cepsc (VCSFG=0)"


# == Per-Segment Output Format ==================================================

class TestOutputFormat:
    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_output_exists(self, seg):
        path = f"/app/output_{seg}.csv"
        assert os.path.exists(path), f"Output file {path} not found"

    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_output_shape(self, seg):
        df = _load(f"/app/output_{seg}.csv")
        assert len(df) == NUM_STEPS, f"{seg}: expected {NUM_STEPS} rows, got {len(df)}"
        for col in COLUMNS:
            assert col in df.columns, f"{seg}: missing column {col}"

    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_non_negative(self, seg):
        df = _load(f"/app/output_{seg}.csv")
        for col in COLUMNS:
            assert np.all(df[col].values >= -1e-10), f"{seg}.{col} has negative values"

    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_not_all_zeros(self, seg):
        df = _load(f"/app/output_{seg}.csv")
        for col in COLUMNS:
            assert df[col].sum() > 0, f"{seg}.{col} is all zeros"

    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_reasonable_max(self, seg):
        df = _load(f"/app/output_{seg}.csv")
        for col in COLUMNS:
            assert df[col].max() < 10.0, f"{seg}.{col} max={df[col].max():.4f} exceeds 10.0"


# == Per-Segment Numerical Accuracy =============================================

class TestSegmentAccuracy:
    @pytest.mark.parametrize("seg", ["P001", "P002"])
    @pytest.mark.parametrize("col", COLUMNS)
    def test_sum_accuracy(self, seg, col):
        df = _load(f"/app/output_{seg}.csv")
        ref_sum = _RS[seg][col]
        sim_sum = df[col].sum()
        diff = abs(sim_sum - ref_sum)
        assert diff < TOLERANCE, \
            f"{seg}.{col} sum diff={diff:.6f} (sim={sim_sum:.6f}, ref={ref_sum:.6f})"

    @pytest.mark.parametrize("seg,spots", [("P001", _SPOT_P001), ("P002", _SPOT_P002)])
    def test_spot_checks(self, seg, spots):
        df = _load(f"/app/output_{seg}.csv")
        failures = []
        for row, expected_vals in spots.items():
            for col, expected in expected_vals.items():
                actual = df[col].iloc[row]
                if not _close(actual, expected, 1e-5):
                    failures.append(
                        f"  {seg} row {row} {col}: expected {expected:.6e}, got {actual:.6e}"
                    )
        assert not failures, f"Spot check failures:\n" + "\n".join(failures)

    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_ifwo_range(self, seg):
        df = _load(f"/app/output_{seg}.csv")
        ref_sum = _RS[seg]["IFWO"]
        sim_sum = df["IFWO"].sum()
        assert sim_sum > ref_sum * 0.5, \
            f"{seg} IFWO sum ({sim_sum:.4f}) < 50% of ref ({ref_sum:.4f})"
        assert sim_sum < ref_sum * 2.0, \
            f"{seg} IFWO sum ({sim_sum:.4f}) > 200% of ref ({ref_sum:.4f})"


# == Temporal Pattern Checks ====================================================

class TestTemporalPatterns:
    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_storm_response(self, seg):
        inp = _load("/app/input_timeseries.csv")
        sim = _load(f"/app/output_{seg}.csv")
        precip_mask = inp["PREC"] > 0.05
        if precip_mask.sum() > 0:
            suro_during = sim["SURO"][precip_mask].sum()
            assert suro_during > 0, f"{seg} SURO must respond to precipitation"

    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_recession_behavior(self, seg):
        sim = _load(f"/app/output_{seg}.csv")
        agwo = sim["AGWO"].values
        nonzero = np.where(agwo > 1e-6)[0]
        if len(nonzero) > 100:
            start = nonzero[50]
            segment = agwo[start:start + 48]
            if len(segment) == 48 and all(s > 0 for s in segment):
                decreasing = sum(
                    1 for i in range(1, len(segment))
                    if segment[i] <= segment[i - 1] * 1.01
                )
                assert decreasing > 20, \
                    f"{seg} AGWO should show recession during dry periods"


# == Aggregate Output ===========================================================

class TestAggregateOutput:
    def test_aggregate_exists(self):
        assert os.path.exists("/app/output.csv"), "Aggregate output.csv not found"

    def test_aggregate_shape(self):
        df = _load("/app/output.csv")
        assert len(df) == NUM_STEPS, f"Expected {NUM_STEPS} rows, got {len(df)}"
        for col in COLUMNS:
            assert col in df.columns, f"Aggregate missing column {col}"

    def test_aggregate_non_negative(self):
        df = _load("/app/output.csv")
        for col in COLUMNS:
            assert np.all(df[col].values >= -1e-10), f"Aggregate {col} has negatives"

    def test_aggregate_consistency(self):
        """Aggregate must equal area-weighted sum of per-segment outputs."""
        agg = _load("/app/output.csv")
        p001 = _load("/app/output_P001.csv")
        p002 = _load("/app/output_P002.csv")
        for col in COLUMNS:
            expected = _AREA["P001"] * p001[col].values + _AREA["P002"] * p002[col].values
            actual = agg[col].values
            max_diff = np.max(np.abs(actual - expected))
            assert max_diff < 1e-8, \
                f"Aggregate {col} not consistent with segments (max diff={max_diff:.2e})"

    @pytest.mark.parametrize("col", COLUMNS)
    def test_aggregate_sum_accuracy(self, col):
        agg = _load("/app/output.csv")
        ref_sum = sum(_AREA[s] * _RS[s][col] for s in _RS)
        sim_sum = agg[col].sum()
        diff = abs(sim_sum - ref_sum)
        assert diff < TOLERANCE, \
            f"Aggregate {col} sum diff={diff:.6f} (sim={sim_sum:.6f}, ref={ref_sum:.6f})"


# == HDF5 Output Verification ===================================================

class TestHDF5Output:
    def test_hdf5_exists(self):
        assert os.path.exists("/app/results.h5"), "results.h5 not found"

    def test_metadata_group_exists(self):
        with h5py.File("/app/results.h5", "r") as f:
            assert "metadata" in f, "Missing /metadata group"

    def test_metadata_attributes(self):
        with h5py.File("/app/results.h5", "r") as f:
            meta = f["metadata"]
            assert "start_date" in meta.attrs, "Missing start_date attribute"
            assert "end_date" in meta.attrs, "Missing end_date attribute"
            assert "units" in meta.attrs, "Missing units attribute"
            assert "num_segments" in meta.attrs, "Missing num_segments attribute"
            assert int(meta.attrs["num_segments"]) == 2, \
                f"num_segments should be 2, got {meta.attrs['num_segments']}"

    def test_segments_group_structure(self):
        with h5py.File("/app/results.h5", "r") as f:
            assert "segments" in f, "Missing /segments group"
            assert "P001" in f["segments"], "Missing /segments/P001"
            assert "P002" in f["segments"], "Missing /segments/P002"

    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_segment_parameters_group(self, seg):
        with h5py.File("/app/results.h5", "r") as f:
            grp_path = f"segments/{seg}/parameters"
            assert grp_path in f, f"Missing /{grp_path}"
            params_grp = f[grp_path]
            for pname in _EXPECTED_PARAMS[seg]:
                assert pname in params_grp, \
                    f"Missing parameter dataset {pname} in {grp_path}"

    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_segment_parameters_values(self, seg):
        with h5py.File("/app/results.h5", "r") as f:
            params_grp = f[f"segments/{seg}/parameters"]
            for pname, expected in _EXPECTED_PARAMS[seg].items():
                if pname in params_grp:
                    actual = float(params_grp[pname][()])
                    assert _close(actual, expected, 1e-4), \
                        f"HDF5 {seg} param {pname}: expected {expected}, got {actual}"

    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_segment_states_group(self, seg):
        with h5py.File("/app/results.h5", "r") as f:
            grp_path = f"segments/{seg}/states"
            assert grp_path in f, f"Missing /{grp_path}"
            states_grp = f[grp_path]
            for sname in ["CEPS", "SURS", "UZS", "IFWS", "LZS", "AGWS", "GWVS"]:
                assert sname in states_grp, f"Missing state dataset {sname} in {grp_path}"

    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_segment_states_values(self, seg):
        with h5py.File("/app/results.h5", "r") as f:
            states_grp = f[f"segments/{seg}/states"]
            for sname, expected in _EXPECTED_STATES[seg].items():
                actual = float(states_grp[sname][()])
                assert _close(actual, expected, 1e-4), \
                    f"HDF5 {seg} state {sname}: expected {expected}, got {actual}"

    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_segment_hourly_datasets(self, seg):
        with h5py.File("/app/results.h5", "r") as f:
            for col in COLUMNS:
                ds_path = f"segments/{seg}/hourly/{col}"
                assert ds_path in f, f"Missing dataset /{ds_path}"
                ds = f[ds_path]
                assert ds.shape == (NUM_STEPS,), \
                    f"{ds_path} shape {ds.shape} != ({NUM_STEPS},)"
                assert ds.dtype == np.float64, \
                    f"{ds_path} dtype {ds.dtype} != float64"

    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_hdf5_hourly_matches_csv(self, seg):
        csv_df = _load(f"/app/output_{seg}.csv")
        with h5py.File("/app/results.h5", "r") as f:
            for col in COLUMNS:
                hdf5_data = f[f"segments/{seg}/hourly/{col}"][:]
                csv_data = csv_df[col].values
                assert np.allclose(hdf5_data, csv_data, atol=1e-10), \
                    f"HDF5 segments/{seg}/hourly/{col} does not match CSV"

    def test_aggregate_group_exists(self):
        with h5py.File("/app/results.h5", "r") as f:
            assert "aggregate" in f, "Missing /aggregate group"

    @pytest.mark.parametrize("col", COLUMNS)
    def test_aggregate_datasets(self, col):
        with h5py.File("/app/results.h5", "r") as f:
            ds_path = f"aggregate/{col}"
            assert ds_path in f, f"Missing dataset /{ds_path}"
            ds = f[ds_path]
            assert ds.shape == (NUM_STEPS,), \
                f"{ds_path} shape {ds.shape} != ({NUM_STEPS},)"
            assert ds.dtype == np.float64, \
                f"{ds_path} dtype {ds.dtype} != float64"

    @pytest.mark.parametrize("col", COLUMNS)
    def test_hdf5_aggregate_matches_csv(self, col):
        agg_csv = _load("/app/output.csv")
        with h5py.File("/app/results.h5", "r") as f:
            hdf5_data = f[f"aggregate/{col}"][:]
            csv_data = agg_csv[col].values
            assert np.allclose(hdf5_data, csv_data, atol=1e-10), \
                f"HDF5 aggregate/{col} does not match CSV"


# == SQLite Output Verification =================================================

class TestSQLiteOutput:
    def test_db_exists(self):
        assert os.path.exists("/app/watershed.db"), "watershed.db not found"

    def test_segments_table_schema(self):
        conn = sqlite3.connect("/app/watershed.db")
        cursor = conn.execute("PRAGMA table_info(segments)")
        col_names = {row[1] for row in cursor.fetchall()}
        conn.close()
        for expected_col in ["segment_id", "forest", "lzsn", "infilt", "agwrc", "kvary"]:
            assert expected_col in col_names, \
                f"segments table missing column '{expected_col}'"

    def test_segments_table_rows(self):
        conn = sqlite3.connect("/app/watershed.db")
        cursor = conn.execute("SELECT COUNT(*) FROM segments")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 2, f"segments table has {count} rows, expected 2"

    def test_segments_data_values(self):
        conn = sqlite3.connect("/app/watershed.db")
        for seg_id in ["P001", "P002"]:
            cursor = conn.execute(
                "SELECT lzsn, infilt, agwrc, kvary, forest FROM segments WHERE segment_id=?",
                (seg_id,)
            )
            row = cursor.fetchone()
            assert row is not None, f"No row for {seg_id} in segments table"
            lzsn, infilt, agwrc, kvary, forest = row
            assert _close(lzsn, _EXPECTED_PARAMS[seg_id]["LZSN"], 1e-3), \
                f"{seg_id} lzsn: expected {_EXPECTED_PARAMS[seg_id]['LZSN']}, got {lzsn}"
            assert _close(infilt, _EXPECTED_PARAMS[seg_id]["INFILT"], 1e-4), \
                f"{seg_id} infilt: expected {_EXPECTED_PARAMS[seg_id]['INFILT']}, got {infilt}"
            assert _close(agwrc, _EXPECTED_PARAMS[seg_id]["AGWRC"], 1e-4), \
                f"{seg_id} agwrc: expected {_EXPECTED_PARAMS[seg_id]['AGWRC']}, got {agwrc}"
        conn.close()

    def test_hourly_output_table_schema(self):
        conn = sqlite3.connect("/app/watershed.db")
        cursor = conn.execute("PRAGMA table_info(hourly_output)")
        col_names = {row[1] for row in cursor.fetchall()}
        conn.close()
        for expected_col in ["segment_id", "hour", "suro", "ifwo", "agwo"]:
            assert expected_col in col_names, \
                f"hourly_output table missing column '{expected_col}'"

    def test_hourly_output_row_count(self):
        conn = sqlite3.connect("/app/watershed.db")
        cursor = conn.execute("SELECT COUNT(*) FROM hourly_output")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 17520, f"hourly_output has {count} rows, expected 17520"

    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_hourly_output_per_segment_count(self, seg):
        conn = sqlite3.connect("/app/watershed.db")
        cursor = conn.execute(
            "SELECT COUNT(*) FROM hourly_output WHERE segment_id=?", (seg,)
        )
        count = cursor.fetchone()[0]
        conn.close()
        assert count == NUM_STEPS, \
            f"hourly_output has {count} rows for {seg}, expected {NUM_STEPS}"

    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_hourly_output_sums_match_csv(self, seg):
        conn = sqlite3.connect("/app/watershed.db")
        cursor = conn.execute(
            "SELECT SUM(suro), SUM(ifwo), SUM(agwo) FROM hourly_output WHERE segment_id=?",
            (seg,)
        )
        db_sums = cursor.fetchone()
        conn.close()
        csv_df = _load(f"/app/output_{seg}.csv")
        for i, col in enumerate(COLUMNS):
            csv_sum = csv_df[col].sum()
            assert abs(db_sums[i] - csv_sum) < 0.001, \
                f"SQLite {seg} {col} sum {db_sums[i]:.6f} != CSV sum {csv_sum:.6f}"

    def test_water_balance_table_schema(self):
        conn = sqlite3.connect("/app/watershed.db")
        cursor = conn.execute("PRAGMA table_info(water_balance)")
        col_names = {row[1] for row in cursor.fetchall()}
        conn.close()
        for expected_col in ["segment_id", "total_precip", "total_et", "total_suro",
                             "total_ifwo", "total_agwo", "total_deep", "balance_error"]:
            assert expected_col in col_names, \
                f"water_balance table missing column '{expected_col}'"

    def test_water_balance_row_count(self):
        conn = sqlite3.connect("/app/watershed.db")
        cursor = conn.execute("SELECT COUNT(*) FROM water_balance")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 2, f"water_balance has {count} rows, expected 2"

    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_water_balance_closure(self, seg):
        conn = sqlite3.connect("/app/watershed.db")
        cursor = conn.execute(
            "SELECT balance_error FROM water_balance WHERE segment_id=?", (seg,)
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None, f"No water_balance row for {seg}"
        assert row[0] < 0.5, \
            f"Water balance error for {seg} = {row[0]:.6f} exceeds 0.5"

    @pytest.mark.parametrize("seg", ["P001", "P002"])
    def test_water_balance_sums_consistent(self, seg):
        """Water balance suro/ifwo/agwo totals should match CSV sums."""
        conn = sqlite3.connect("/app/watershed.db")
        cursor = conn.execute(
            "SELECT total_suro, total_ifwo, total_agwo FROM water_balance WHERE segment_id=?",
            (seg,)
        )
        row = cursor.fetchone()
        conn.close()
        csv_df = _load(f"/app/output_{seg}.csv")
        for i, col in enumerate(COLUMNS):
            csv_sum = csv_df[col].sum()
            assert abs(row[i] - csv_sum) < 0.01, \
                f"water_balance {seg} {col}: {row[i]:.6f} != CSV {csv_sum:.6f}"

    def test_water_balance_precip_positive(self):
        """Total precip should be positive (sanity check)."""
        conn = sqlite3.connect("/app/watershed.db")
        cursor = conn.execute("SELECT total_precip FROM water_balance")
        for row in cursor.fetchall():
            assert row[0] > 0, "total_precip should be positive"
        conn.close()
