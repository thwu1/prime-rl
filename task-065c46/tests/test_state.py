"""
Tests for CFD grid convergence verification assessment.

"""
import json
import math
import os

import numpy as np
import pandas as pd
import pytest

OUTPUT_DIR = "/app/output"


def _read_csv(name):
    path = os.path.join(OUTPUT_DIR, name)
    return pd.read_csv(path)


def _read_json(name):
    path = os.path.join(OUTPUT_DIR, name)
    with open(path) as f:
        return json.load(f)


class TestFileExistence:
    @pytest.mark.parametrize("fname", [
        "continuum_estimates.csv",
        "uncertainty_bounds.csv",
        "convergence_types.csv",
        "ensemble_statistics.json",
        "outliers.json",
    ])
    def test_output_file_exists(self, fname):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, fname)), \
            f"Missing output file: {fname}"


class TestContinuumFormat:
    def test_columns(self):
        df = _read_csv("continuum_estimates.csv")
        required = {"participant_id", "CD_extrapolated", "CL_extrapolated",
                     "CM_extrapolated", "p_CD", "p_CL", "p_CM"}
        assert required.issubset(set(df.columns)), \
            f"Missing columns: {required - set(df.columns)}"

    def test_row_count(self):
        df = _read_csv("continuum_estimates.csv")
        assert len(df) == 12, f"Expected 12 rows, got {len(df)}"


class TestContinuumValues:
    """Verify grid-independent extrapolated values against reference."""

    def _get_row(self, pid):
        df = _read_csv("continuum_estimates.csv")
        row = df[df["participant_id"] == pid]
        assert len(row) == 1, f"No row for {pid}"
        return row.iloc[0]

    def test_p001_cd_extrapolated(self):
        row = self._get_row("P001")
        assert abs(row["CD_extrapolated"] - 0.0253333) < 1e-4

    def test_p001_p_cd(self):
        row = self._get_row("P001")
        assert abs(row["p_CD"] - 2.0) < 0.02

    def test_p002_cd_extrapolated(self):
        row = self._get_row("P002")
        assert abs(row["CD_extrapolated"] - 0.02540) < 1e-4

    def test_p003_cd_extrapolated(self):
        row = self._get_row("P003")
        assert abs(row["CD_extrapolated"] - 0.02540) < 1e-4

    def test_p003_p_cd(self):
        row = self._get_row("P003")
        assert abs(row["p_CD"] - 1.585) < 0.02

    def test_p005_cd_extrapolated(self):
        row = self._get_row("P005")
        assert abs(row["CD_extrapolated"] - 0.0257333) < 1e-4

    def test_p007_cd_extrapolated(self):
        row = self._get_row("P007")
        assert abs(row["CD_extrapolated"] - 0.0255333) < 1e-4

    def test_p008_cd_extrapolated(self):
        row = self._get_row("P008")
        assert abs(row["CD_extrapolated"] - 0.0256667) < 1e-4

    def test_p011_cd_extrapolated(self):
        row = self._get_row("P011")
        assert abs(row["CD_extrapolated"] - 0.02584) < 1e-4

    def test_p011_p_cd(self):
        row = self._get_row("P011")
        assert abs(row["p_CD"] - 1.807) < 0.02

    def test_p012_cd_extrapolated(self):
        row = self._get_row("P012")
        assert abs(row["CD_extrapolated"] - 0.02352) < 1e-4

    def test_p006_cd_is_nan(self):
        row = self._get_row("P006")
        assert pd.isna(row["CD_extrapolated"]) or \
            (isinstance(row["CD_extrapolated"], float) and math.isnan(row["CD_extrapolated"]))


class TestConvergenceTypes:
    def _get_row(self, pid):
        df = _read_csv("convergence_types.csv")
        row = df[df["participant_id"] == pid]
        assert len(row) == 1, f"No row for {pid}"
        return row.iloc[0]

    def test_p006_cd_oscillatory(self):
        row = self._get_row("P006")
        assert row["CD_convergence"].strip().lower() == "oscillatory"

    def test_p006_cm_oscillatory(self):
        row = self._get_row("P006")
        assert row["CM_convergence"].strip().lower() == "oscillatory"

    def test_p006_cl_monotonic(self):
        row = self._get_row("P006")
        assert row["CL_convergence"].strip().lower() == "monotonic"

    @pytest.mark.parametrize("pid", [
        "P001", "P002", "P003", "P004", "P005",
        "P007", "P008", "P009", "P010", "P011", "P012"
    ])
    def test_cd_monotonic(self, pid):
        row = self._get_row(pid)
        assert row["CD_convergence"].strip().lower() == "monotonic"

    def test_all_12_present(self):
        df = _read_csv("convergence_types.csv")
        assert len(df) == 12


class TestUncertaintyBounds:
    def _get_row(self, pid):
        df = _read_csv("uncertainty_bounds.csv")
        row = df[df["participant_id"] == pid]
        assert len(row) == 1, f"No row for {pid}"
        return row.iloc[0]

    def test_p006_excluded(self):
        df = _read_csv("uncertainty_bounds.csv")
        assert "P006" not in df["participant_id"].values

    def test_p001_gci_fine(self):
        row = self._get_row("P001")
        assert abs(row["GCI_fine_CD"] - 0.003281) < 5e-4

    def test_p001_asymptotic_ratio(self):
        row = self._get_row("P001")
        assert abs(row["asymptotic_ratio_CD"] - 0.992) < 0.02

    def test_gci_fine_positive(self):
        df = _read_csv("uncertainty_bounds.csv")
        for _, row in df.iterrows():
            assert row["GCI_fine_CD"] > 0, \
                f"{row['participant_id']}: GCI_fine must be positive"

    def test_count(self):
        df = _read_csv("uncertainty_bounds.csv")
        assert len(df) == 11


class TestOutliers:
    def test_p012_flagged(self):
        outliers = _read_json("outliers.json")
        pids = [o["participant_id"] for o in outliers]
        assert "P012" in pids, "P012 should be identified as an outlier"

    def test_p012_chauvenet(self):
        outliers = _read_json("outliers.json")
        p012 = [o for o in outliers if o["participant_id"] == "P012"]
        assert len(p012) == 1
        assert p012[0]["chauvenet_flag"] is True

    def test_p012_modified_z_score(self):
        outliers = _read_json("outliers.json")
        p012 = [o for o in outliers if o["participant_id"] == "P012"]
        assert len(p012) == 1
        mz = p012[0]["modified_z_score"]
        assert abs(mz) > 3.5, f"|modified_z_score| = {abs(mz)} should exceed 3.5"
        assert abs(mz - (-8.15)) < 1.0, \
            f"modified_z_score = {mz}, expected approx -8.15"

    def test_no_false_positives(self):
        outliers = _read_json("outliers.json")
        flagged_pids = {o["participant_id"] for o in outliers
                        if o.get("chauvenet_flag") or abs(o.get("modified_z_score", 0)) > 3.5}
        expected_outliers = {"P012"}
        unexpected = flagged_pids - expected_outliers
        assert len(unexpected) == 0, \
            f"Unexpected outliers: {unexpected}"


class TestEnsembleStatistics:
    def test_n_valid(self):
        stats = _read_json("ensemble_statistics.json")
        assert stats["n_valid"] == 10, \
            f"Expected 10 valid (12 - 1 non-convergent - 1 outlier), got {stats['n_valid']}"

    def test_mean(self):
        stats = _read_json("ensemble_statistics.json")
        assert abs(stats["mean"] - 255.77) < 0.5, \
            f"Mean = {stats['mean']}, expected approx 255.77"

    def test_std(self):
        stats = _read_json("ensemble_statistics.json")
        assert abs(stats["std"] - 1.78) < 0.3, \
            f"Std = {stats['std']}, expected approx 1.78"

    def test_median(self):
        stats = _read_json("ensemble_statistics.json")
        assert abs(stats["median"] - 256.0) < 0.5, \
            f"Median = {stats['median']}, expected approx 256.0"

    def test_iqr(self):
        stats = _read_json("ensemble_statistics.json")
        assert 2.5 < stats["iqr"] < 4.5, \
            f"IQR = {stats['iqr']}, expected in range [2.5, 4.5]"

    def test_keys_present(self):
        stats = _read_json("ensemble_statistics.json")
        for key in ["mean", "std", "median", "iqr", "n_valid"]:
            assert key in stats, f"Missing key: {key}"
