"""Tests for the dynamic optimizer on the Moving Peaks Benchmark.

Verifies:
  1. C library builds and loads via ctypes.
  2. SQLite config database is queryable and consistent.
  3. Optimizer implements the required ask/tell interface.
  4. Offline error is below threshold on each instance.
"""


import sys
import os
import ctypes
import sqlite3
import importlib.util
import subprocess

import numpy as np
import pytest

sys.path.insert(0, "/app")


@pytest.fixture(scope="session", autouse=True)
def ensure_library_built():
    """Build libgmpb.so if not already present."""
    result = subprocess.run(["make", "-C", "/app"], capture_output=True, text=True)
    if result.returncode != 0:
        pytest.fail(f"Failed to build libgmpb.so:\n{result.stderr}")


def _load_lib():
    from runner import load_library
    return load_library()


def _load_config():
    from runner import load_instances
    return load_instances()


def _load_optimizer():
    spec = importlib.util.spec_from_file_location("optimizer", "/app/optimizer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Optimizer


# ── C library + ctypes tests ─────────────────────────────────────────────

class TestInfrastructure:

    def test_libgmpb_exists(self):
        assert os.path.isfile("/app/libgmpb.so"), \
            "libgmpb.so missing — run 'make' in /app"

    def test_libgmpb_loads_via_ctypes(self):
        lib = _load_lib()
        assert lib is not None

    def test_ctypes_create_evaluate_destroy(self):
        lib = _load_lib()
        ctx = lib.gmpb_create(10, 5, 1000, 1.0, 5, 42)
        assert ctx, "gmpb_create returned NULL"
        x = (ctypes.c_double * 5)(50.0, 50.0, 50.0, 50.0, 50.0)
        val = lib.gmpb_evaluate(ctx, x)
        assert isinstance(val, float) and val > 0
        lib.gmpb_destroy(ctx)

    def test_ctypes_optimum_and_change(self):
        lib = _load_lib()
        ctx = lib.gmpb_create(5, 3, 100, 2.0, 3, 99)
        pos = (ctypes.c_double * 3)()
        opt_val = lib.gmpb_get_optimum(ctx, pos)
        assert opt_val >= 30.0 and opt_val <= 70.0
        lib.gmpb_trigger_change(ctx)
        opt_val2 = lib.gmpb_get_optimum(ctx, pos)
        assert opt_val2 >= 30.0 and opt_val2 <= 70.0
        lib.gmpb_destroy(ctx)


# ── SQLite config tests ──────────────────────────────────────────────────

class TestSQLiteConfig:

    def test_config_db_exists(self):
        assert os.path.isfile("/app/config.db"), "config.db not found"

    def test_instances_table_has_six_rows(self):
        conn = sqlite3.connect("/app/config.db")
        n = conn.execute("SELECT COUNT(*) FROM instances").fetchone()[0]
        assert n == 6, f"Expected 6 instances, got {n}"
        conn.close()

    def test_thresholds_table_has_six_rows(self):
        conn = sqlite3.connect("/app/config.db")
        n = conn.execute("SELECT COUNT(*) FROM thresholds").fetchone()[0]
        assert n == 6, f"Expected 6 thresholds, got {n}"
        conn.close()

    def test_instances_match_thresholds(self):
        instances, thresholds = _load_config()
        assert set(instances.keys()) == set(thresholds.keys()), \
            "Instance names don't match between tables"

    def test_instance_parameters_sane(self):
        instances, _ = _load_config()
        for name, cfg in instances.items():
            assert cfg["num_peaks"] > 0, f"{name}: bad num_peaks"
            assert 1 <= cfg["dimension"] <= 64, f"{name}: bad dimension"
            assert cfg["change_frequency"] > 0, f"{name}: bad change_frequency"
            assert cfg["shift_severity"] > 0, f"{name}: bad shift_severity"


# ── Optimizer interface tests ─────────────────────────────────────────────

class TestOptimizerInterface:

    def test_instantiates(self):
        Opt = _load_optimizer()
        opt = Opt(dimension=5, bounds=(0.0, 100.0), num_peaks=10, seed=42)
        assert opt is not None

    def test_ask_returns_list_of_arrays(self):
        Opt = _load_optimizer()
        opt = Opt(dimension=5, bounds=(0.0, 100.0), num_peaks=10, seed=42)
        solutions = opt.ask()
        assert isinstance(solutions, list) and len(solutions) > 0
        for s in solutions:
            assert isinstance(s, np.ndarray)
            assert s.shape == (5,), f"Expected shape (5,), got {s.shape}"

    def test_tell_accepts_results(self):
        Opt = _load_optimizer()
        opt = Opt(dimension=5, bounds=(0.0, 100.0), num_peaks=10, seed=42)
        sols = opt.ask()
        opt.tell(sols, [1.0] * len(sols), False)
        sols2 = opt.ask()
        opt.tell(sols2, [2.0] * len(sols2), True)

    def test_solutions_within_bounds(self):
        Opt = _load_optimizer()
        opt = Opt(dimension=5, bounds=(0.0, 100.0), num_peaks=10, seed=42)
        rng = np.random.RandomState(99)
        for step in range(20):
            sols = opt.ask()
            for s in sols:
                assert np.all(s >= 0.0) and np.all(s <= 100.0), \
                    f"Out-of-bounds solution at step {step}"
            vals = [float(rng.rand() * 50) for _ in sols]
            opt.tell(sols, vals, step == 10)

    def test_ask_updates_after_tell(self):
        Opt = _load_optimizer()
        opt = Opt(dimension=5, bounds=(0.0, 100.0), num_peaks=10, seed=42)
        s1 = opt.ask()
        opt.tell(s1, [float(i) for i in range(len(s1))], False)
        s2 = opt.ask()
        changed = any(not np.array_equal(a, b) for a, b in zip(s1, s2))
        assert changed, "ask() returned identical solutions after tell()"


# ── Performance tests ─────────────────────────────────────────────────────

class TestOptimizerPerformance:

    @pytest.mark.parametrize("instance", ["F1", "F2", "F3", "F4", "F5", "F6"])
    def test_offline_error(self, instance):
        from runner import load_library, load_instances, run_instance
        lib = load_library()
        instances, thresholds = load_instances()
        Opt = _load_optimizer()
        error = run_instance(lib, instance, instances[instance], Opt,
                             optimizer_seed=42)
        threshold = thresholds[instance]
        assert error < threshold, (
            f"{instance}: offline_error={error:.4f} >= threshold={threshold}. "
            f"Your optimizer must achieve offline_error < {threshold}."
        )
