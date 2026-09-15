
import json
import math
import os
import sqlite3
import subprocess
import pytest


RESULTS_PATH = "/app/results.json"
DB_PATH = "/app/data/geomag_2024.db"
OMM_PATH = "/app/data/omm_52140.json"
MU = 398600.4418


@pytest.fixture
def results():
    """Load and return the results JSON."""
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH, "r") as f:
        data = json.load(f)
    return data


class TestResultsSchema:
    """Verify results.json has the correct structure and types."""

    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json does not exist"

    def test_required_keys(self, results):
        required = {"best_index", "best_lag_hours", "best_r_squared", "n_data_points"}
        assert required.issubset(results.keys()), (
            f"Missing keys: {required - set(results.keys())}"
        )

    def test_best_index_type(self, results):
        assert isinstance(results["best_index"], str)

    def test_best_lag_type(self, results):
        assert isinstance(results["best_lag_hours"], (int, float))

    def test_r_squared_type(self, results):
        assert isinstance(results["best_r_squared"], (int, float))

    def test_n_data_points_type(self, results):
        assert isinstance(results["n_data_points"], (int, float))


class TestCorrelationResults:
    """Verify the computed correlation results are correct."""

    def test_best_index_is_ap(self, results):
        """The ap index should yield the strongest lag-correlation with orbital decay."""
        assert results["best_index"] == "ap", (
            f"Expected best_index='ap', got '{results['best_index']}'"
        )

    def test_best_lag_range(self, results):
        """The optimal lag should be in the range [16, 22] hours."""
        lag = results["best_lag_hours"]
        assert 16 <= lag <= 22, (
            f"Expected best_lag_hours in [16,22], got {lag}"
        )

    def test_r_squared_range(self, results):
        """The r-squared should be in a plausible range for ap correlation."""
        r2 = results["best_r_squared"]
        assert 0.30 <= r2 <= 0.60, (
            f"Expected best_r_squared in [0.30, 0.60], got {r2}"
        )

    def test_n_data_points_range(self, results):
        """The number of paired data points should be reasonable."""
        n = results["n_data_points"]
        assert 50 <= n <= 90, (
            f"Expected n_data_points in [50, 90], got {n}"
        )


class TestSQLiteDatabase:
    """Verify the SQLite database has been updated with results."""

    def test_source_db_exists(self):
        """The geomagnetic SQLite database should exist."""
        assert os.path.exists(DB_PATH), f"Database not found at {DB_PATH}"

    def test_source_schema_has_expected_tables(self):
        """Source database should have the normalized geomag tables."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {r[0] for r in c.fetchall()}
        conn.close()
        expected = {"epoch_info", "geomag_indices", "solar_wind", "solar_activity"}
        assert expected.issubset(tables), (
            f"Missing source tables: {expected - tables}"
        )

    def test_correlation_results_table_exists(self):
        """A correlation_results table should have been created."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='correlation_results'")
        found = c.fetchone()
        conn.close()
        assert found is not None, (
            "Table 'correlation_results' not found in database"
        )

    def test_correlation_results_has_data(self):
        """The correlation_results table should have at least one row."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM correlation_results")
        count = c.fetchone()[0]
        conn.close()
        assert count >= 1, "correlation_results table is empty"

    def test_correlation_results_match_json(self, results):
        """The SQLite results should match the JSON results."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT best_index, best_lag_hours, best_r_squared, n_data_points FROM correlation_results LIMIT 1")
        row = c.fetchone()
        conn.close()
        assert row is not None, "No row in correlation_results"
        assert row[0] == results["best_index"], (
            f"SQLite best_index={row[0]} != JSON best_index={results['best_index']}"
        )
        assert row[1] == results["best_lag_hours"], (
            f"SQLite best_lag_hours={row[1]} != JSON best_lag_hours={results['best_lag_hours']}"
        )
        assert abs(row[2] - results["best_r_squared"]) < 0.001, (
            f"SQLite best_r_squared={row[2]} != JSON best_r_squared={results['best_r_squared']}"
        )
        assert row[3] == results["n_data_points"], (
            f"SQLite n_data_points={row[3]} != JSON n_data_points={results['n_data_points']}"
        )

    def test_correlation_results_columns(self):
        """The correlation_results table should have the correct column names."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("PRAGMA table_info(correlation_results)")
        cols = {r[1] for r in c.fetchall()}
        conn.close()
        expected = {"best_index", "best_lag_hours", "best_r_squared", "n_data_points"}
        assert expected.issubset(cols), (
            f"Missing columns: {expected - cols}"
        )


class TestSourceDataIntegrity:
    """Verify source data is properly structured."""

    def test_epoch_info_has_records(self):
        """epoch_info table should have hourly records."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM epoch_info")
        count = c.fetchone()[0]
        conn.close()
        assert count >= 1500, f"Expected 1500+ epoch records, got {count}"

    def test_geomag_has_null_values(self):
        """geomag_indices should contain NULL values (missing data)."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM geomag_indices WHERE ap_index IS NULL")
        null_count = c.fetchone()[0]
        conn.close()
        assert null_count > 0, "Expected NULL ap values in geomag_indices"
        assert null_count < 50, f"Too many NULL ap values: {null_count}"

    def test_omm_json_structure(self):
        """OMM JSON should be an array with CCSDS fields."""
        with open(OMM_PATH) as f:
            omm = json.load(f)
        assert isinstance(omm, list), "OMM JSON should be a list"
        assert len(omm) >= 100, f"Expected 100+ OMM records, got {len(omm)}"
        required_fields = {"EPOCH", "MEAN_MOTION", "ECCENTRICITY", "INCLINATION",
                          "CCSDS_OMM_VERS", "MEAN_ELEMENT_THEORY"}
        first_keys = set(omm[0].keys())
        assert required_fields.issubset(first_keys), (
            f"Missing OMM fields: {required_fields - first_keys}"
        )

    def test_omm_mean_motion_to_sma(self):
        """First OMM record should yield a plausible LEO semi-major axis."""
        with open(OMM_PATH) as f:
            omm = json.load(f)
        mm = omm[0]["MEAN_MOTION"]
        n_rad_s = mm * 2.0 * math.pi / 86400.0
        a_km = (MU / n_rad_s**2) ** (1.0 / 3.0)
        assert 6700 < a_km < 6900, (
            f"First OMM semi-major axis should be ~6778 km, got {a_km:.2f}"
        )

    def test_maneuvers_present_in_omm(self):
        """OMM data should contain maneuver events (positive delta-a)."""
        with open(OMM_PATH) as f:
            omm = json.load(f)
        sma_values = []
        for rec in omm:
            mm = rec["MEAN_MOTION"]
            n_rad_s = mm * 2.0 * math.pi / 86400.0
            a_km = (MU / n_rad_s**2) ** (1.0 / 3.0)
            sma_values.append(a_km)
        positive_changes = sum(
            1 for i in range(1, len(sma_values))
            if sma_values[i] - sma_values[i-1] >= 0
        )
        assert positive_changes >= 3, (
            f"Expected at least 3 maneuver events, found {positive_changes}"
        )

    def test_best_index_not_dst_or_ae(self, results):
        """ap should clearly outperform Dst and AE."""
        assert results["best_index"] not in ("Dst", "AE"), (
            f"best_index should be 'ap', not '{results['best_index']}'"
        )

    def test_r_squared_is_valid(self, results):
        """r-squared must be between 0 and 1."""
        r2 = results["best_r_squared"]
        assert 0.0 <= r2 <= 1.0, f"r-squared must be in [0,1], got {r2}"
