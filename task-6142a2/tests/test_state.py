"""
Tests for FluSight multi-format forecast evaluation pipeline.
Verifies CSV outputs, SQLite database, Parquet export, and jq validation manifest.

"""
import csv
import json
import math
import os
import sqlite3
import subprocess
import pytest


OUTPUT_DIR = "/app/output"


def read_csv(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path) as f:
        return list(csv.DictReader(f))


# ============================================================
# Validation manifest tests (jq tool usage)
# ============================================================

class TestValidationManifest:
    def test_manifest_exists(self):
        path = os.path.join(OUTPUT_DIR, "validation_manifest.json")
        assert os.path.isfile(path), "validation_manifest.json not found"

    def test_manifest_structure(self):
        with open(os.path.join(OUTPUT_DIR, "validation_manifest.json")) as f:
            manifest = json.load(f)
        expected_keys = {"required_quantiles", "value_minimum",
                         "required_horizons", "required_locations"}
        assert expected_keys == set(manifest.keys()), \
            f"Expected keys {expected_keys}, got {set(manifest.keys())}"

    def test_manifest_quantiles(self):
        with open(os.path.join(OUTPUT_DIR, "validation_manifest.json")) as f:
            manifest = json.load(f)
        q = manifest["required_quantiles"]
        assert len(q) == 23, f"Expected 23 quantile levels, got {len(q)}"
        assert q[0] == 0.01
        assert q[-1] == 0.99
        assert q == sorted(q), "Quantiles must be sorted"

    def test_manifest_minimum(self):
        with open(os.path.join(OUTPUT_DIR, "validation_manifest.json")) as f:
            manifest = json.load(f)
        assert manifest["value_minimum"] == 0

    def test_manifest_horizons(self):
        with open(os.path.join(OUTPUT_DIR, "validation_manifest.json")) as f:
            manifest = json.load(f)
        h = manifest["required_horizons"]
        assert sorted(h) == [0, 1, 2]

    def test_manifest_locations(self):
        with open(os.path.join(OUTPUT_DIR, "validation_manifest.json")) as f:
            manifest = json.load(f)
        locs = manifest["required_locations"]
        assert sorted(locs) == sorted(["US", "06", "36", "48"])


# ============================================================
# Results database tests (SQLite tool usage)
# ============================================================

class TestResultsDatabase:
    def get_conn(self):
        path = os.path.join(OUTPUT_DIR, "results.db")
        assert os.path.isfile(path), "results.db not found"
        return sqlite3.connect(path)

    def test_database_exists(self):
        path = os.path.join(OUTPUT_DIR, "results.db")
        assert os.path.isfile(path)

    def test_all_tables_exist(self):
        conn = self.get_conn()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        expected = {"wis_scores", "coverage", "model_rankings",
                    "ensemble_weights", "ensemble_evaluation"}
        assert expected.issubset(tables), \
            f"Missing tables: {expected - tables}"

    def test_wis_scores_table_row_count(self):
        conn = self.get_conn()
        count = conn.execute("SELECT COUNT(*) FROM wis_scores").fetchone()[0]
        conn.close()
        assert count == 120, f"Expected 120 rows in wis_scores, got {count}"

    def test_wis_scores_table_columns(self):
        conn = self.get_conn()
        cursor = conn.execute("PRAGMA table_info(wis_scores)")
        cols = {row[1] for row in cursor.fetchall()}
        conn.close()
        expected = {"model_id", "reference_date", "location", "horizon",
                    "target_end_date", "observed", "wis", "dispersion",
                    "overprediction", "underprediction"}
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_coverage_table_matches_csv(self):
        conn = self.get_conn()
        db_rows = conn.execute(
            "SELECT model_id, coverage_50, coverage_95, n_forecasts "
            "FROM coverage ORDER BY model_id").fetchall()
        conn.close()
        csv_rows = read_csv("coverage.csv")
        csv_sorted = sorted(csv_rows, key=lambda r: r["model_id"])
        assert len(db_rows) == len(csv_sorted), "Row count mismatch"
        for db_row, csv_row in zip(db_rows, csv_sorted):
            assert db_row[0] == csv_row["model_id"]
            assert abs(float(db_row[1]) - float(csv_row["coverage_50"])) < 0.001

    def test_ensemble_evaluation_table(self):
        conn = self.get_conn()
        rows = conn.execute(
            "SELECT model_id FROM ensemble_evaluation").fetchall()
        conn.close()
        models = {r[0] for r in rows}
        assert "Ensemble-Trained" in models
        assert len(rows) == 6

    def test_no_corrupt_model_in_db(self):
        conn = self.get_conn()
        count = conn.execute(
            "SELECT COUNT(*) FROM wis_scores WHERE model_id='TeamF-Corrupt'"
        ).fetchone()[0]
        conn.close()
        assert count == 0, "TeamF-Corrupt should not be in results database"


# ============================================================
# Parquet summary export tests (DuckDB tool usage)
# ============================================================

class TestSummaryParquet:
    def test_parquet_exists(self):
        path = os.path.join(OUTPUT_DIR, "summary.parquet")
        assert os.path.isfile(path), "summary.parquet not found"

    def test_parquet_readable(self):
        import pyarrow.parquet as pq
        path = os.path.join(OUTPUT_DIR, "summary.parquet")
        table = pq.read_table(path)
        assert table.num_rows == 6, f"Expected 6 rows, got {table.num_rows}"

    def test_parquet_columns(self):
        import pyarrow.parquet as pq
        path = os.path.join(OUTPUT_DIR, "summary.parquet")
        table = pq.read_table(path)
        cols = set(table.column_names)
        expected = {"model_id", "mean_wis", "relative_wis", "weight"}
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_parquet_ensemble_null_weight(self):
        import pyarrow.parquet as pq
        path = os.path.join(OUTPUT_DIR, "summary.parquet")
        table = pq.read_table(path)
        df = table.to_pydict()
        for i, mid in enumerate(df["model_id"]):
            if mid == "Ensemble-Trained":
                assert df["weight"][i] is None, \
                    "Ensemble-Trained weight should be NULL"
                return
        pytest.fail("Ensemble-Trained not found in summary.parquet")

    def test_parquet_sorted_by_mean_wis(self):
        import pyarrow.parquet as pq
        path = os.path.join(OUTPUT_DIR, "summary.parquet")
        table = pq.read_table(path)
        df = table.to_pydict()
        wis_values = df["mean_wis"]
        assert wis_values == sorted(wis_values), "Parquet not sorted by mean_wis"

    def test_parquet_component_weights_present(self):
        import pyarrow.parquet as pq
        path = os.path.join(OUTPUT_DIR, "summary.parquet")
        table = pq.read_table(path)
        df = table.to_pydict()
        non_null_weights = [w for w in df["weight"] if w is not None]
        assert len(non_null_weights) == 5, \
            f"Expected 5 component weights, got {len(non_null_weights)}"
        assert abs(sum(non_null_weights) - 1.0) < 0.02


# ============================================================
# Data validation tests — corrupt model must be excluded
# ============================================================

class TestDataValidation:
    def test_corrupt_model_excluded_from_wis(self):
        rows = read_csv("wis_scores.csv")
        models = set(r["model_id"] for r in rows)
        assert "TeamF-Corrupt" not in models, \
            "TeamF-Corrupt should be excluded (non-conforming submission)"

    def test_corrupt_model_excluded_from_rankings(self):
        rows = read_csv("model_rankings.csv")
        models = set(r["model_id"] for r in rows)
        assert "TeamF-Corrupt" not in models

    def test_corrupt_model_excluded_from_coverage(self):
        rows = read_csv("coverage.csv")
        models = set(r["model_id"] for r in rows)
        assert "TeamF-Corrupt" not in models

    def test_corrupt_model_excluded_from_ensemble(self):
        rows = read_csv("ensemble_evaluation.csv")
        models = set(r["model_id"] for r in rows)
        assert "TeamF-Corrupt" not in models


# ============================================================
# File existence and structure tests
# ============================================================

class TestOutputFilesExist:
    def test_wis_scores_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, "wis_scores.csv"))

    def test_coverage_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, "coverage.csv"))

    def test_model_rankings_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, "model_rankings.csv"))

    def test_ensemble_weights_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, "ensemble_weights.csv"))

    def test_ensemble_evaluation_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, "ensemble_evaluation.csv"))


class TestWISScoresStructure:
    def test_correct_columns(self):
        rows = read_csv("wis_scores.csv")
        expected_cols = {"model_id", "reference_date", "location", "horizon",
                         "target_end_date", "observed", "wis", "dispersion",
                         "overprediction", "underprediction"}
        assert expected_cols.issubset(set(rows[0].keys()))

    def test_correct_row_count(self):
        """5 valid models x 4 locations x 2 ref_dates x 3 horizons = 120 rows."""
        rows = read_csv("wis_scores.csv")
        assert len(rows) == 120

    def test_all_valid_models_present(self):
        rows = read_csv("wis_scores.csv")
        models = set(r["model_id"] for r in rows)
        expected = {"TeamA-EpiModel", "TeamB-Baseline", "TeamC-Overpredict",
                    "TeamD-NarrowCI", "TeamE-Hybrid"}
        assert models == expected


# ============================================================
# WIS mathematical properties
# ============================================================

class TestWISProperties:
    def test_wis_decomposition_sums(self):
        """WIS must equal dispersion + overprediction + underprediction."""
        rows = read_csv("wis_scores.csv")
        for r in rows:
            wis = float(r["wis"])
            disp = float(r["dispersion"])
            overp = float(r["overprediction"])
            underp = float(r["underprediction"])
            assert abs(wis - (disp + overp + underp)) < 0.02, \
                f"Decomposition failed for {r['model_id']} {r['location']} h={r['horizon']}: " \
                f"{wis} != {disp}+{overp}+{underp}={disp+overp+underp}"

    def test_all_components_nonnegative(self):
        rows = read_csv("wis_scores.csv")
        for r in rows:
            assert float(r["wis"]) >= 0
            assert float(r["dispersion"]) >= 0
            assert float(r["overprediction"]) >= -0.001
            assert float(r["underprediction"]) >= -0.001

    def test_wis_positive(self):
        rows = read_csv("wis_scores.csv")
        for r in rows:
            assert float(r["wis"]) > 0

    def test_overpredict_model_has_large_overprediction(self):
        rows = read_csv("wis_scores.csv")
        for r in rows:
            if (r["model_id"] == "TeamC-Overpredict" and r["location"] == "US"
                    and r["horizon"] == "0" and r["reference_date"] == "2024-01-06"):
                overp = float(r["overprediction"])
                underp = float(r["underprediction"])
                assert overp > underp * 10, \
                    f"TeamC should strongly overpredict on US h=0: overp={overp}, underp={underp}"
                return
        pytest.fail("Could not find TeamC US h=0 ref=2024-01-06")


# ============================================================
# Specific WIS value checks
# ============================================================

class TestWISValues:
    def test_teamA_US_h0(self):
        """TeamA-EpiModel, US, h=0, ref=2024-01-06: expected WIS ~ 679.78"""
        rows = read_csv("wis_scores.csv")
        for r in rows:
            if (r["model_id"] == "TeamA-EpiModel" and r["location"] == "US"
                    and r["horizon"] == "0" and r["reference_date"] == "2024-01-06"):
                wis = float(r["wis"])
                assert abs(wis - 679.7839) < 5.0, f"Expected WIS ~679.78, got {wis}"
                return
        pytest.fail("Row not found")

    def test_teamC_US_h0(self):
        """TeamC-Overpredict, US, h=0, ref=2024-01-06: expected WIS ~ 4430.81"""
        rows = read_csv("wis_scores.csv")
        for r in rows:
            if (r["model_id"] == "TeamC-Overpredict" and r["location"] == "US"
                    and r["horizon"] == "0" and r["reference_date"] == "2024-01-06"):
                wis = float(r["wis"])
                assert abs(wis - 4430.8139) < 10.0, f"Expected WIS ~4430.81, got {wis}"
                return
        pytest.fail("Row not found")

    def test_teamD_NY_h2(self):
        """TeamD-NarrowCI, 36 (NY), h=2, ref=2024-01-13: expected WIS ~ 122.96"""
        rows = read_csv("wis_scores.csv")
        for r in rows:
            if (r["model_id"] == "TeamD-NarrowCI" and r["location"] == "36"
                    and r["horizon"] == "2" and r["reference_date"] == "2024-01-13"):
                wis = float(r["wis"])
                assert abs(wis - 122.9639) < 3.0, f"Expected WIS ~122.96, got {wis}"
                return
        pytest.fail("Row not found")

    def test_baseline_has_largest_dispersion_ratio(self):
        rows = read_csv("wis_scores.csv")
        model_disp_ratios = {}
        for r in rows:
            m = r["model_id"]
            wis = float(r["wis"])
            disp = float(r["dispersion"])
            if m not in model_disp_ratios:
                model_disp_ratios[m] = []
            if wis > 0:
                model_disp_ratios[m].append(disp / wis)

        avg_ratios = {m: sum(v) / len(v) for m, v in model_disp_ratios.items()}
        baseline_ratio = avg_ratios["TeamB-Baseline"]
        for m, ratio in avg_ratios.items():
            if m != "TeamB-Baseline":
                assert baseline_ratio >= ratio - 0.05, \
                    f"TeamB should have highest dispersion ratio: TeamB={baseline_ratio:.3f}, {m}={ratio:.3f}"


# ============================================================
# Coverage tests
# ============================================================

class TestCoverage:
    def test_coverage_columns(self):
        rows = read_csv("coverage.csv")
        expected = {"model_id", "coverage_50", "coverage_95", "n_forecasts"}
        assert expected.issubset(set(rows[0].keys()))

    def test_coverage_range(self):
        rows = read_csv("coverage.csv")
        for r in rows:
            c50 = float(r["coverage_50"])
            c95 = float(r["coverage_95"])
            assert 0 <= c50 <= 1
            assert 0 <= c95 <= 1

    def test_coverage_95_ge_50(self):
        rows = read_csv("coverage.csv")
        for r in rows:
            c50 = float(r["coverage_50"])
            c95 = float(r["coverage_95"])
            assert c95 >= c50, f"Model {r['model_id']}: 95% cov ({c95}) < 50% cov ({c50})"

    def test_teamC_low_50_coverage(self):
        rows = read_csv("coverage.csv")
        for r in rows:
            if r["model_id"] == "TeamC-Overpredict":
                c50 = float(r["coverage_50"])
                assert c50 < 0.5, f"TeamC 50% coverage should be low, got {c50}"
                return
        pytest.fail("TeamC not found")

    def test_teamD_imperfect_95_coverage(self):
        rows = read_csv("coverage.csv")
        for r in rows:
            if r["model_id"] == "TeamD-NarrowCI":
                c95 = float(r["coverage_95"])
                assert c95 < 1.0, f"TeamD 95% coverage should be <1.0, got {c95}"
                return
        pytest.fail("TeamD not found")

    def test_n_forecasts(self):
        rows = read_csv("coverage.csv")
        for r in rows:
            assert int(r["n_forecasts"]) == 24, \
                f"Model {r['model_id']} has {r['n_forecasts']} forecasts, expected 24"


# ============================================================
# Model rankings tests
# ============================================================

class TestModelRankings:
    def test_ranking_columns(self):
        rows = read_csv("model_rankings.csv")
        expected = {"rank", "model_id", "mean_wis", "relative_wis"}
        assert expected.issubset(set(rows[0].keys()))

    def test_five_models_ranked(self):
        rows = read_csv("model_rankings.csv")
        assert len(rows) == 5

    def test_ranks_1_to_5(self):
        rows = read_csv("model_rankings.csv")
        ranks = sorted([int(r["rank"]) for r in rows])
        assert ranks == [1, 2, 3, 4, 5]

    def test_ranking_order(self):
        """Expected order: TeamD best, then TeamA, TeamE, TeamB, TeamC worst."""
        rows = read_csv("model_rankings.csv")
        ranked = sorted(rows, key=lambda r: int(r["rank"]))
        order = [r["model_id"] for r in ranked]
        assert order == ["TeamD-NarrowCI", "TeamA-EpiModel", "TeamE-Hybrid",
                         "TeamB-Baseline", "TeamC-Overpredict"]

    def test_relative_wis_geometric_mean_property(self):
        rows = read_csv("model_rankings.csv")
        log_sum = sum(math.log(float(r["relative_wis"])) for r in rows)
        product = math.exp(log_sum)
        assert abs(product - 1.0) < 0.05, f"Product of relative WIS = {product}, expected ~1.0"

    def test_mean_wis_values(self):
        rows = read_csv("model_rankings.csv")
        expected = {
            "TeamD-NarrowCI": 239.4,
            "TeamA-EpiModel": 266.0,
            "TeamE-Hybrid": 335.7,
            "TeamB-Baseline": 543.4,
            "TeamC-Overpredict": 1155.4,
        }
        for r in rows:
            m = r["model_id"]
            mwis = float(r["mean_wis"])
            exp = expected[m]
            assert abs(mwis - exp) < 15.0, \
                f"Mean WIS for {m}: expected ~{exp}, got {mwis}"

    def test_relative_wis_best_model(self):
        rows = read_csv("model_rankings.csv")
        best = min(rows, key=lambda r: int(r["rank"]))
        rwis = float(best["relative_wis"])
        assert rwis < 1.0, f"Best model relative WIS should be < 1, got {rwis}"

    def test_relative_wis_worst_model(self):
        rows = read_csv("model_rankings.csv")
        worst = max(rows, key=lambda r: int(r["rank"]))
        rwis = float(worst["relative_wis"])
        assert rwis > 1.0, f"Worst model relative WIS should be > 1, got {rwis}"


# ============================================================
# Ensemble weights tests
# ============================================================

class TestEnsembleWeights:
    def test_weights_columns(self):
        rows = read_csv("ensemble_weights.csv")
        expected = {"model_id", "weight"}
        assert expected.issubset(set(rows[0].keys()))

    def test_five_weights(self):
        rows = read_csv("ensemble_weights.csv")
        assert len(rows) == 5

    def test_weights_nonnegative(self):
        rows = read_csv("ensemble_weights.csv")
        for r in rows:
            w = float(r["weight"])
            assert w >= -0.001, f"Weight for {r['model_id']} is negative: {w}"

    def test_weights_sum_to_one(self):
        rows = read_csv("ensemble_weights.csv")
        total = sum(float(r["weight"]) for r in rows)
        assert abs(total - 1.0) < 0.02, f"Weights sum to {total}, expected 1.0"

    def test_best_model_has_largest_weight(self):
        rows = read_csv("ensemble_weights.csv")
        weights = {r["model_id"]: float(r["weight"]) for r in rows}
        max_model = max(weights, key=weights.get)
        assert max_model == "TeamD-NarrowCI", \
            f"Expected TeamD-NarrowCI to have highest weight, got {max_model}"

    def test_worst_model_has_small_weight(self):
        rows = read_csv("ensemble_weights.csv")
        for r in rows:
            if r["model_id"] == "TeamC-Overpredict":
                w = float(r["weight"])
                assert w < 0.15, f"TeamC weight should be small, got {w}"
                return
        pytest.fail("TeamC not found")


# ============================================================
# Ensemble evaluation tests
# ============================================================

class TestEnsembleEvaluation:
    def test_eval_columns(self):
        rows = read_csv("ensemble_evaluation.csv")
        expected = {"model_id", "mean_wis", "relative_wis"}
        assert expected.issubset(set(rows[0].keys()))

    def test_six_entries(self):
        rows = read_csv("ensemble_evaluation.csv")
        assert len(rows) == 6

    def test_ensemble_present(self):
        rows = read_csv("ensemble_evaluation.csv")
        models = [r["model_id"] for r in rows]
        assert "Ensemble-Trained" in models

    def test_ensemble_beats_best_component(self):
        rows = read_csv("ensemble_evaluation.csv")
        ensemble_wis = None
        best_component_wis = float("inf")
        for r in rows:
            mwis = float(r["mean_wis"])
            if r["model_id"] == "Ensemble-Trained":
                ensemble_wis = mwis
            else:
                best_component_wis = min(best_component_wis, mwis)
        assert ensemble_wis is not None
        assert ensemble_wis <= best_component_wis + 5.0, \
            f"Ensemble WIS ({ensemble_wis}) should be <= best component ({best_component_wis})"

    def test_sorted_by_mean_wis(self):
        rows = read_csv("ensemble_evaluation.csv")
        wis_values = [float(r["mean_wis"]) for r in rows]
        assert wis_values == sorted(wis_values), "ensemble_evaluation.csv not sorted by mean_wis"

    def test_ensemble_relative_wis_below_one(self):
        rows = read_csv("ensemble_evaluation.csv")
        for r in rows:
            if r["model_id"] == "Ensemble-Trained":
                rwis = float(r["relative_wis"])
                assert rwis < 0.6, f"Ensemble relative WIS should be < 0.6, got {rwis}"
                return
        pytest.fail("Ensemble not found")
