"""Tests for C-backed GMPB dynamic optimization task."""

import ctypes
import json
import os
import sqlite3
import sys

sys.path.insert(0, '/app')

import numpy as np
import pytest


class TestCLibrary:
    """Verify the C shared library is compiled and loadable."""

    def test_libgmpb_exists(self):
        assert os.path.exists('/app/gmpb_native/libgmpb.so'), \
            "libgmpb.so not found — compile with: make -C /app/gmpb_native"

    def test_libgmpb_loadable(self):
        lib = ctypes.CDLL('/app/gmpb_native/libgmpb.so')
        assert hasattr(lib, 'gmpb_new'), "gmpb_new symbol not found in library"
        assert hasattr(lib, 'gmpb_evaluate'), \
            "gmpb_evaluate symbol not found in library"


class TestCtypesWrapper:
    """Verify the Python ctypes wrapper correctly interfaces with the C lib."""

    def test_create_and_evaluate(self):
        from gmpb import GMPB
        g = GMPB(num_peaks=5, dimension=2, change_frequency=10,
                 num_environments=2, seed=99)
        val = g.evaluate(np.zeros(2))
        assert isinstance(val, float), "evaluate must return a float"
        assert np.isfinite(val), "evaluate must return a finite value"

    def test_environment_change_tracking(self):
        from gmpb import GMPB
        g = GMPB(num_peaks=5, dimension=2, change_frequency=10,
                 num_environments=3, seed=99)
        assert g.get_environment() == 0
        for _ in range(10):
            g.evaluate(np.zeros(2))
        assert g.get_environment() == 1
        for _ in range(10):
            g.evaluate(np.zeros(2))
        assert g.get_environment() == 2

    def test_optimum_at_peak_center(self):
        from gmpb import GMPB
        g = GMPB(num_peaks=5, dimension=2, change_frequency=100,
                 num_environments=2, seed=99)
        while not g.is_finished():
            g.evaluate(g.optimum_position)
        assert g.get_offline_error() < 0.01

    def test_budget_enforcement(self):
        from gmpb import GMPB
        g = GMPB(num_peaks=2, dimension=2, change_frequency=5,
                 num_environments=2, seed=99)
        for _ in range(10):
            g.evaluate(np.zeros(2))
        assert g.is_finished()

    def test_deterministic_with_same_seed(self):
        from gmpb import GMPB
        results1, results2 = [], []
        for results in [results1, results2]:
            g = GMPB(num_peaks=5, dimension=3, change_frequency=20,
                     num_environments=2, seed=42)
            for _ in range(40):
                results.append(g.evaluate(np.ones(3)))
        np.testing.assert_array_equal(results1, results2)

    def test_properties_match_params(self):
        from gmpb import GMPB
        g = GMPB(num_peaks=7, dimension=4, change_frequency=100,
                 num_environments=5, seed=1)
        assert g.dimension == 4
        assert g.num_peaks == 7
        assert g.change_frequency == 100
        assert g.min_coord == -25.0
        assert g.max_coord == 25.0
        assert g.get_remaining_evals() == 500


class TestSQLiteResults:
    """Verify SQLite database structure and data completeness."""

    def test_database_exists(self):
        assert os.path.exists('/app/results.db'), \
            "SQLite database not found at /app/results.db"

    def test_schema_has_env_results_table(self):
        conn = sqlite3.connect('/app/results.db')
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='env_results'")
        row = cursor.fetchone()
        conn.close()
        assert row is not None, "Table 'env_results' not found in database"

    def test_data_completeness(self):
        conn = sqlite3.connect('/app/results.db')
        for inst in ['F1', 'F2', 'F3']:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM env_results WHERE instance = ?",
                (inst,))
            count = cursor.fetchone()[0]
            assert count == 30, \
                f"Expected 30 environment records for {inst}, got {count}"
        conn.close()

    def test_offline_error_via_sql(self):
        conn = sqlite3.connect('/app/results.db')
        cursor = conn.execute(
            "SELECT instance, AVG(mean_error) as oe "
            "FROM env_results GROUP BY instance ORDER BY instance")
        sql_results = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()

        assert os.path.exists('/app/results.json'), \
            "results.json not found"
        with open('/app/results.json') as f:
            json_results = json.load(f)

        for inst in ['F1', 'F2', 'F3']:
            assert inst in sql_results, \
                f"Instance {inst} missing from SQL results"
            json_oe = json_results[inst]['offline_error']
            sql_oe = sql_results[inst]
            assert abs(json_oe - sql_oe) < 0.5, \
                (f"{inst}: results.json ({json_oe:.4f}) and SQL "
                 f"({sql_oe:.4f}) offline errors diverge")

    def test_mean_error_values_positive(self):
        conn = sqlite3.connect('/app/results.db')
        cursor = conn.execute(
            "SELECT MIN(mean_error) FROM env_results")
        min_err = cursor.fetchone()[0]
        conn.close()
        assert min_err >= 0.0, "mean_error values must be non-negative"


class TestOptimizerPerformance:
    """Verify the optimizer achieves required offline error thresholds."""

    def test_optimizer_module_exists(self):
        assert os.path.exists('/app/optimizer.py'), \
            "optimizer.py not found at /app/"

    def test_optimizer_is_callable(self):
        from optimizer import run_optimizer
        assert callable(run_optimizer)

    def test_optimizer_on_novel_instance(self):
        """Run optimizer on an instance NOT in the task spec."""
        from gmpb import GMPB
        from optimizer import run_optimizer
        np.random.seed(9999)
        g = GMPB(num_peaks=8, dimension=4, change_frequency=2000,
                 shift_severity=1.5, num_environments=15, seed=777)
        oe = run_optimizer(g)
        assert isinstance(oe, (int, float)), \
            "run_optimizer must return a numeric offline error"
        assert np.isfinite(oe), "Offline error must be finite"
        assert oe < 20.0, \
            f"Novel instance offline error {oe:.4f} too high (threshold 20.0)"

    def test_f1_results(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        oe = results['F1']['offline_error']
        assert isinstance(oe, (int, float))
        assert oe < 12.0, \
            f"F1 offline error {oe:.4f} exceeds threshold 12.0"

    def test_f2_results(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        oe = results['F2']['offline_error']
        assert isinstance(oe, (int, float))
        assert oe < 15.0, \
            f"F2 offline error {oe:.4f} exceeds threshold 15.0"

    def test_f3_results(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        oe = results['F3']['offline_error']
        assert isinstance(oe, (int, float))
        assert oe < 18.0, \
            f"F3 offline error {oe:.4f} exceeds threshold 18.0"

    def test_results_json_format(self):
        assert os.path.exists('/app/results.json'), \
            "results.json not found at /app/"
        with open('/app/results.json') as f:
            results = json.load(f)
        for key in ['F1', 'F2', 'F3']:
            assert key in results, f"Missing key {key} in results.json"
            assert 'offline_error' in results[key], \
                f"Missing offline_error in results['{key}']"
            assert isinstance(results[key]['offline_error'], (int, float)), \
                f"results['{key}']['offline_error'] must be numeric"
