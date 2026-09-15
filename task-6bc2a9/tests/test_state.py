
import sys
import json
import os
import subprocess
import ctypes
import numpy as np

sys.path.insert(0, "/app")


# ---------------------------------------------------------------------------
# C shared library tests
# ---------------------------------------------------------------------------

class TestCExtension:
    """Verify the C shared library exists and works correctly."""

    def test_libpeaks_exists(self):
        """libpeaks.so must exist at /app/libpeaks.so."""
        assert os.path.isfile("/app/libpeaks.so"), "libpeaks.so not found at /app/"

    def test_libpeaks_loadable(self):
        """Must be loadable via ctypes with evaluate_peaks exported."""
        lib = ctypes.CDLL("/app/libpeaks.so")
        assert hasattr(lib, "evaluate_peaks"), "evaluate_peaks function not exported"

    def test_libpeaks_single_peak(self):
        """C library must compute correct value for a single peak at origin."""
        lib = ctypes.CDLL("/app/libpeaks.so")
        lib.evaluate_peaks.restype = ctypes.c_double
        lib.evaluate_peaks.argtypes = [
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int,
        ]
        # Single peak at origin: h=50, w=10, evaluate at origin → 50.0
        x = (ctypes.c_double * 2)(0.0, 0.0)
        pos = (ctypes.c_double * 2)(0.0, 0.0)
        h = (ctypes.c_double * 1)(50.0)
        w = (ctypes.c_double * 1)(10.0)
        val = lib.evaluate_peaks(x, 2, pos, h, w, 1)
        assert abs(val - 50.0) < 1e-10, f"Expected 50.0, got {val}"

    def test_libpeaks_off_center(self):
        """C library must compute correct value at a non-zero point."""
        lib = ctypes.CDLL("/app/libpeaks.so")
        lib.evaluate_peaks.restype = ctypes.c_double
        lib.evaluate_peaks.argtypes = [
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int,
        ]
        # Peak at (3, 4), h=60, w=5. Evaluate at (0, 0): dist²=25, val=60/(1+25/25)=30
        x = (ctypes.c_double * 2)(0.0, 0.0)
        pos = (ctypes.c_double * 2)(3.0, 4.0)
        h = (ctypes.c_double * 1)(60.0)
        w = (ctypes.c_double * 1)(5.0)
        val = lib.evaluate_peaks(x, 2, pos, h, w, 1)
        assert abs(val - 30.0) < 1e-10, f"Expected 30.0, got {val}"

    def test_libpeaks_multi_peak(self):
        """C library must return max across multiple peaks."""
        lib = ctypes.CDLL("/app/libpeaks.so")
        lib.evaluate_peaks.restype = ctypes.c_double
        lib.evaluate_peaks.argtypes = [
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int,
        ]
        # Two peaks: peak0 at origin h=40 w=10, peak1 at (1,0) h=50 w=10
        # Evaluate at (1,0): peak0=40/(1+1/100)=39.604, peak1=50/(1+0)=50
        x = (ctypes.c_double * 2)(1.0, 0.0)
        pos = (ctypes.c_double * 4)(0.0, 0.0, 1.0, 0.0)
        h = (ctypes.c_double * 2)(40.0, 50.0)
        w = (ctypes.c_double * 2)(10.0, 10.0)
        val = lib.evaluate_peaks(x, 2, pos, h, w, 2)
        assert abs(val - 50.0) < 1e-10, f"Expected 50.0, got {val}"


# ---------------------------------------------------------------------------
# Makefile tests
# ---------------------------------------------------------------------------

class TestMakefile:
    """Verify the Makefile and C source exist and build correctly."""

    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile"), "Makefile not found at /app/"

    def test_peaks_c_exists(self):
        assert os.path.isfile("/app/peaks.c"), "peaks.c not found at /app/"

    def test_makefile_rebuilds(self, tmp_path):
        """Copying sources to a temp dir and running make must produce libpeaks.so."""
        import shutil
        shutil.copy("/app/peaks.c", tmp_path / "peaks.c")
        shutil.copy("/app/Makefile", tmp_path / "Makefile")
        result = subprocess.run(
            ["make", "-C", str(tmp_path)],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"make failed: {result.stderr}"
        assert (tmp_path / "libpeaks.so").exists(), "make didn't produce libpeaks.so"


# ---------------------------------------------------------------------------
# ctypes integration test
# ---------------------------------------------------------------------------

class TestCTypesIntegration:
    """Verify gmpb.py uses ctypes to call the C library."""

    def test_gmpb_uses_ctypes(self):
        with open("/app/gmpb.py") as f:
            source = f.read()
        assert "ctypes" in source, "gmpb.py must import and use ctypes"
        assert "libpeaks" in source, "gmpb.py must load libpeaks.so"


# ---------------------------------------------------------------------------
# GMPB correctness tests
# ---------------------------------------------------------------------------

class TestGMPBInitialization:
    """Verify GMPB initialization produces values matching the spec."""

    def test_init_function_value(self):
        """Function value at origin must match reference computation."""
        from gmpb import GMPB

        seed, dim, num_peaks = 42, 2, 3
        shift_severity = 1.0

        # Reference: replicate the exact RNG call order from the spec
        rng = np.random.default_rng(seed)
        positions, heights, widths = [], [], []
        for _ in range(num_peaks):
            positions.append(rng.uniform(-50, 50, dim))
            heights.append(float(rng.uniform(30.0, 70.0)))
            widths.append(float(rng.uniform(5.0, 20.0)))
            v = rng.standard_normal(dim)  # consumed for velocity init

        x = np.zeros(dim)
        expected = max(
            h / (1.0 + np.sum((x - p) ** 2) / w ** 2)
            for p, h, w in zip(positions, heights, widths)
        )

        b = GMPB(dim=dim, num_peaks=num_peaks, shift_severity=shift_severity,
                 change_frequency=1000, num_environments=5, seed=seed)
        actual = b.evaluate(x)
        assert abs(actual - expected) < 1e-10, (
            f"Init value mismatch: expected {expected}, got {actual}"
        )

    def test_init_off_center(self):
        """Check value at a non-origin point."""
        from gmpb import GMPB

        seed, dim, num_peaks = 99, 3, 4
        shift_severity = 2.0

        rng = np.random.default_rng(seed)
        positions, heights, widths = [], [], []
        for _ in range(num_peaks):
            positions.append(rng.uniform(-50, 50, dim))
            heights.append(float(rng.uniform(30.0, 70.0)))
            widths.append(float(rng.uniform(5.0, 20.0)))
            rng.standard_normal(dim)

        x = np.array([12.5, -7.3, 40.0])
        expected = max(
            h / (1.0 + np.sum((x - p) ** 2) / w ** 2)
            for p, h, w in zip(positions, heights, widths)
        )

        b = GMPB(dim=dim, num_peaks=num_peaks, shift_severity=shift_severity,
                 change_frequency=500, num_environments=3, seed=seed)
        actual = b.evaluate(x)
        assert abs(actual - expected) < 1e-10, (
            f"Off-center value mismatch: expected {expected}, got {actual}"
        )


class TestGMPBDynamics:
    """Verify environment change dynamics match the spec."""

    def test_env_change_values(self):
        """After exhausting env 1, values in env 2 must match reference."""
        from gmpb import GMPB

        seed, dim, num_peaks = 42, 2, 2
        shift_severity = 1.0
        change_freq = 10
        lam, sigma_h, sigma_w = 0.5, 1.0, 0.5

        # Reference init
        rng = np.random.default_rng(seed)
        positions, heights, widths, velocities = [], [], [], []
        for _ in range(num_peaks):
            positions.append(rng.uniform(-50, 50, dim).copy())
            heights.append(float(rng.uniform(30.0, 70.0)))
            widths.append(float(rng.uniform(5.0, 20.0)))
            v = rng.standard_normal(dim)
            nrm = np.linalg.norm(v)
            v = shift_severity * v / nrm
            velocities.append(v.copy())

        # Reference env change
        for k in range(num_peaks):
            r = rng.standard_normal(dim)
            r = r / np.linalg.norm(r)
            v_dir = velocities[k] / np.linalg.norm(velocities[k])
            u = lam * v_dir + (1 - lam) * r
            velocities[k] = shift_severity * u / np.linalg.norm(u)
            positions[k] = np.clip(positions[k] + velocities[k], -100, 100)
            heights[k] = float(np.clip(
                heights[k] + sigma_h * rng.standard_normal(), 30.0, 70.0))
            widths[k] = float(np.clip(
                widths[k] + sigma_w * rng.standard_normal(), 5.0, 20.0))

        x = np.array([10.0, -5.0])
        expected = max(
            h / (1.0 + np.sum((x - p) ** 2) / w ** 2)
            for p, h, w in zip(positions, heights, widths)
        )

        # Module: exhaust env 1, then evaluate in env 2
        b = GMPB(dim=dim, num_peaks=num_peaks, shift_severity=shift_severity,
                 change_frequency=change_freq, num_environments=5, seed=seed)
        for _ in range(change_freq):
            b.evaluate(np.zeros(dim))
        actual = b.evaluate(x)
        assert abs(actual - expected) < 1e-10, (
            f"Dynamics mismatch: expected {expected}, got {actual}"
        )

    def test_two_env_changes(self):
        """Verify values after two consecutive environment changes."""
        from gmpb import GMPB

        seed, dim, num_peaks = 77, 2, 3
        shift_severity = 1.5
        change_freq = 5
        lam, sigma_h, sigma_w = 0.5, 1.0, 0.5

        rng = np.random.default_rng(seed)
        positions, heights, widths, velocities = [], [], [], []
        for _ in range(num_peaks):
            positions.append(rng.uniform(-50, 50, dim).copy())
            heights.append(float(rng.uniform(30.0, 70.0)))
            widths.append(float(rng.uniform(5.0, 20.0)))
            v = rng.standard_normal(dim)
            v = shift_severity * v / np.linalg.norm(v)
            velocities.append(v.copy())

        # Two environment changes
        for _env in range(2):
            for k in range(num_peaks):
                r = rng.standard_normal(dim)
                r = r / np.linalg.norm(r)
                v_dir = velocities[k] / np.linalg.norm(velocities[k])
                u = lam * v_dir + (1 - lam) * r
                velocities[k] = shift_severity * u / np.linalg.norm(u)
                positions[k] = np.clip(positions[k] + velocities[k], -100, 100)
                heights[k] = float(np.clip(
                    heights[k] + sigma_h * rng.standard_normal(), 30.0, 70.0))
                widths[k] = float(np.clip(
                    widths[k] + sigma_w * rng.standard_normal(), 5.0, 20.0))

        x = np.array([-20.0, 30.0])
        expected = max(
            h / (1.0 + np.sum((x - p) ** 2) / w ** 2)
            for p, h, w in zip(positions, heights, widths)
        )

        b = GMPB(dim=dim, num_peaks=num_peaks, shift_severity=shift_severity,
                 change_frequency=change_freq, num_environments=10, seed=seed)
        for _ in range(2 * change_freq):
            b.evaluate(np.zeros(dim))
        actual = b.evaluate(x)
        assert abs(actual - expected) < 1e-10, (
            f"Two-change mismatch: expected {expected}, got {actual}"
        )


class TestGMPBProperties:
    """Property-based checks for GMPB correctness."""

    def test_peak_center_equals_height(self):
        """Evaluating at a peak center should return its height."""
        from gmpb import GMPB

        b = GMPB(dim=2, num_peaks=5, shift_severity=1.0,
                 change_frequency=5000, num_environments=10, seed=42)
        pos, val = b.get_global_optimum()
        actual = b.evaluate(pos)
        assert abs(actual - val) < 1e-6, (
            f"Peak center value {actual} != height {val}"
        )

    def test_function_bounded(self):
        """All values must be positive and at most the optimum."""
        from gmpb import GMPB

        b = GMPB(dim=2, num_peaks=5, shift_severity=1.0,
                 change_frequency=5000, num_environments=10, seed=42)
        _, opt_val = b.get_global_optimum()
        rng = np.random.default_rng(9999)
        for _ in range(50):
            x = rng.uniform(-100, 100, 2)
            v = b.evaluate(x)
            assert v > 0, f"Function value must be positive, got {v}"
            assert v <= opt_val + 1e-6, (
                f"Value {v} exceeds optimum {opt_val}"
            )

    def test_deterministic(self):
        """Two instances with the same seed must produce identical values."""
        from gmpb import GMPB

        params = dict(dim=3, num_peaks=4, shift_severity=1.5,
                      change_frequency=100, num_environments=5, seed=7)
        b1 = GMPB(**params)
        b2 = GMPB(**params)
        x = np.array([10.0, -20.0, 5.0])
        assert abs(b1.evaluate(x) - b2.evaluate(x)) < 1e-14

    def test_environment_counter(self):
        """Environment index must increment after change_frequency evals."""
        from gmpb import GMPB

        b = GMPB(dim=2, num_peaks=3, shift_severity=1.0,
                 change_frequency=20, num_environments=4, seed=55)
        assert b.get_current_environment() == 1
        for _ in range(20):
            b.evaluate(np.zeros(2))
        assert b.get_current_environment() == 2
        for _ in range(20):
            b.evaluate(np.zeros(2))
        assert b.get_current_environment() == 3

    def test_has_changed_flag(self):
        """has_changed must be True only on the triggering evaluation."""
        from gmpb import GMPB

        b = GMPB(dim=2, num_peaks=2, shift_severity=1.0,
                 change_frequency=5, num_environments=3, seed=11)
        for i in range(4):
            b.evaluate(np.zeros(2))
            assert not b.has_changed(), f"Unexpected change at eval {i+1}"
        b.evaluate(np.zeros(2))  # 5th eval triggers change
        assert b.has_changed(), "Change not flagged after change_frequency evals"
        b.evaluate(np.zeros(2))  # 6th eval, new env
        assert not b.has_changed(), "Change flag not reset after next eval"

    def test_termination(self):
        """has_terminated must be True after all evaluations are used."""
        from gmpb import GMPB

        b = GMPB(dim=2, num_peaks=2, shift_severity=1.0,
                 change_frequency=5, num_environments=2, seed=33)
        for _ in range(10):
            assert not b.has_terminated()
            b.evaluate(np.zeros(2))
        assert b.has_terminated()

    def test_offline_error_nonneg(self):
        """Offline error must be non-negative."""
        from gmpb import GMPB

        b = GMPB(dim=2, num_peaks=3, shift_severity=0.5,
                 change_frequency=50, num_environments=2, seed=44)
        rng = np.random.default_rng(0)
        for _ in range(100):
            b.evaluate(rng.uniform(-100, 100, 2))
        err = b.get_offline_error()
        assert err >= 0, f"Offline error must be non-negative, got {err}"
        assert err > 0, "Random search should have positive offline error"

    def test_env_stats_tracking(self):
        """get_env_stats must return per-environment statistics."""
        from gmpb import GMPB

        b = GMPB(dim=2, num_peaks=3, shift_severity=1.0,
                 change_frequency=20, num_environments=3, seed=55)
        rng = np.random.default_rng(999)
        for _ in range(60):
            b.evaluate(rng.uniform(-100, 100, 2))
        stats = b.get_env_stats()
        assert len(stats) == 3, f"Expected 3 env stats entries, got {len(stats)}"
        for s in stats:
            assert "env_index" in s, "Missing env_index key"
            assert "avg_error" in s, "Missing avg_error key"
            assert "best_found" in s, "Missing best_found key"
            assert "optimum_value" in s, "Missing optimum_value key"
            assert s["avg_error"] >= 0, f"avg_error must be non-negative: {s['avg_error']}"
            assert 30.0 <= s["optimum_value"] <= 70.0, (
                f"optimum_value {s['optimum_value']} outside [30, 70]"
            )


# ---------------------------------------------------------------------------
# Optimizer performance tests
# ---------------------------------------------------------------------------

class TestOptimizerPerformance:
    """Verify the optimizer achieves required offline error thresholds."""

    def test_instance_1(self):
        """Instance 1 (D=2, m=5, easy): offline error < 8.0."""
        from gmpb import GMPB
        from optimizer import DynamicOptimizer

        b = GMPB(dim=2, num_peaks=5, shift_severity=1.0,
                 change_frequency=5000, num_environments=10, seed=42)
        opt = DynamicOptimizer(b, seed=42)
        result = opt.run()
        err = result["offline_error"]
        assert err < 8.0, (
            f"Instance 1: offline error {err:.4f} >= 8.0"
        )

    def test_instance_2(self):
        """Instance 2 (D=5, m=10, medium): offline error < 15.0."""
        from gmpb import GMPB
        from optimizer import DynamicOptimizer

        b = GMPB(dim=5, num_peaks=10, shift_severity=1.0,
                 change_frequency=2500, num_environments=20, seed=123)
        opt = DynamicOptimizer(b, seed=42)
        result = opt.run()
        err = result["offline_error"]
        assert err < 15.0, (
            f"Instance 2: offline error {err:.4f} >= 15.0"
        )

    def test_instance_3(self):
        """Instance 3 (D=5, m=10, hard): offline error < 25.0."""
        from gmpb import GMPB
        from optimizer import DynamicOptimizer

        b = GMPB(dim=5, num_peaks=10, shift_severity=2.0,
                 change_frequency=1000, num_environments=30, seed=456)
        opt = DynamicOptimizer(b, seed=42)
        result = opt.run()
        err = result["offline_error"]
        assert err < 25.0, (
            f"Instance 3: offline error {err:.4f} >= 25.0"
        )


# ---------------------------------------------------------------------------
# Results file tests
# ---------------------------------------------------------------------------

class TestResultsFile:
    """Verify the results.json output file."""

    def test_results_format(self):
        """results.json must contain all instances with offline_error values."""
        with open("/app/results.json") as f:
            results = json.load(f)
        for inst in ["instance_1", "instance_2", "instance_3"]:
            assert inst in results, f"Missing {inst} in results.json"
            assert "offline_error" in results[inst], (
                f"Missing offline_error for {inst}"
            )
            assert isinstance(results[inst]["offline_error"], (int, float)), (
                f"offline_error for {inst} must be numeric"
            )


# ---------------------------------------------------------------------------
# SQLite database tests
# ---------------------------------------------------------------------------

class TestSQLiteResults:
    """Verify the SQLite database schema and data."""

    def test_database_exists(self):
        assert os.path.isfile("/app/results.db"), "results.db not found at /app/"

    def test_runs_schema(self):
        """runs table must have the required columns."""
        import sqlite3
        conn = sqlite3.connect("/app/results.db")
        cursor = conn.execute("PRAGMA table_info(runs)")
        cols = {row[1] for row in cursor.fetchall()}
        conn.close()
        expected = {"instance_name", "dim", "num_peaks", "shift_severity",
                    "change_frequency", "num_environments", "seed",
                    "offline_error", "threshold", "passed"}
        missing = expected - cols
        assert not missing, f"Missing columns in runs table: {missing}"

    def test_env_stats_schema(self):
        """env_stats table must have the required columns."""
        import sqlite3
        conn = sqlite3.connect("/app/results.db")
        cursor = conn.execute("PRAGMA table_info(env_stats)")
        cols = {row[1] for row in cursor.fetchall()}
        conn.close()
        expected = {"instance_name", "env_index", "avg_error",
                    "best_found", "optimum_value"}
        missing = expected - cols
        assert not missing, f"Missing columns in env_stats table: {missing}"

    def test_runs_data(self):
        """All three instances must be present in the runs table."""
        import sqlite3
        conn = sqlite3.connect("/app/results.db")
        rows = conn.execute(
            "SELECT instance_name, offline_error, passed FROM runs "
            "ORDER BY instance_name"
        ).fetchall()
        conn.close()
        assert len(rows) == 3, f"Expected 3 rows in runs, got {len(rows)}"
        names = {r[0] for r in rows}
        for inst in ["instance_1", "instance_2", "instance_3"]:
            assert inst in names, f"{inst} missing from runs table"

    def test_env_stats_data(self):
        """Each instance must have env_stats entries."""
        import sqlite3
        conn = sqlite3.connect("/app/results.db")
        for inst in ["instance_1", "instance_2", "instance_3"]:
            count = conn.execute(
                "SELECT COUNT(*) FROM env_stats WHERE instance_name = ?",
                (inst,)
            ).fetchone()[0]
            assert count > 0, f"No env_stats entries for {inst}"
        conn.close()

    def test_env_stats_consistency(self):
        """avg_error must be non-negative and optimum_value in [30, 70]."""
        import sqlite3
        conn = sqlite3.connect("/app/results.db")
        rows = conn.execute(
            "SELECT avg_error, optimum_value FROM env_stats"
        ).fetchall()
        conn.close()
        assert len(rows) > 0, "env_stats table is empty"
        for avg_err, opt_val in rows:
            assert avg_err >= 0, f"Negative avg_error: {avg_err}"
            assert 30.0 <= opt_val <= 70.0, (
                f"optimum_value {opt_val} outside [30, 70]"
            )

    def test_sqlite3_cli_query(self):
        """Database must be queryable via sqlite3 CLI tool."""
        result = subprocess.run(
            ["sqlite3", "/app/results.db", "SELECT COUNT(*) FROM runs;"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"sqlite3 CLI failed: {result.stderr}"
        count = int(result.stdout.strip())
        assert count == 3, f"Expected 3 rows via CLI, got {count}"
