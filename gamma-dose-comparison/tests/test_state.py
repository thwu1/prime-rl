
import ctypes
import os
import sqlite3
import subprocess
import sys

sys.path.insert(0, "/app")

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Build system tests
# ---------------------------------------------------------------------------

class TestMakeBuild:
    def test_make_lib_produces_so(self):
        """make lib must produce accel/libshell.so."""
        assert os.path.isfile("/app/accel/libshell.so"), (
            "libshell.so not found — did 'make lib' succeed?"
        )

    def test_make_clean_and_rebuild(self):
        """make clean removes .so; make (default target) rebuilds it."""
        result = subprocess.run(
            ["make", "-C", "/app", "clean"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"make clean failed:\n{result.stderr}"
        assert not os.path.isfile("/app/accel/libshell.so"), (
            "libshell.so still present after make clean"
        )

        result = subprocess.run(
            ["make", "-C", "/app"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"make (default) failed:\n{result.stderr}"
        assert os.path.isfile("/app/accel/libshell.so"), (
            "libshell.so not rebuilt by default target"
        )


# ---------------------------------------------------------------------------
# Direct C library tests via ctypes
# ---------------------------------------------------------------------------

def _load_c_lib():
    lib = ctypes.CDLL("/app/accel/libshell.so")

    lib.shell_count_2d.argtypes = [ctypes.c_double, ctypes.c_double]
    lib.shell_count_2d.restype = ctypes.c_int

    lib.shell_count_3d.argtypes = [ctypes.c_double, ctypes.c_double]
    lib.shell_count_3d.restype = ctypes.c_int

    lib.shell_1d.argtypes = [
        ctypes.c_double,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_int),
    ]
    lib.shell_1d.restype = None

    lib.shell_2d.argtypes = [
        ctypes.c_double, ctypes.c_double,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_int),
    ]
    lib.shell_2d.restype = None

    lib.shell_3d.argtypes = [
        ctypes.c_double, ctypes.c_double,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_int),
    ]
    lib.shell_3d.restype = None

    return lib


class TestCLibraryDirect:
    def test_load_library(self):
        """The shared library must load via ctypes.CDLL."""
        lib = _load_c_lib()
        assert lib is not None

    def test_c_shell_2d_count(self):
        """shell_count_2d must return the correct point count."""
        lib = _load_c_lib()
        # ceil(2*pi*1.0 / 0.1) + 1 = 63 + 1 = 64
        assert lib.shell_count_2d(1.0, 0.1) == 64

    def test_c_shell_2d_on_circle(self):
        """2D shell points from C must lie on the circle at the given radius."""
        lib = _load_c_lib()
        radius, gap = 0.5, 0.05
        n_pts = lib.shell_count_2d(radius, gap)
        x = (ctypes.c_double * n_pts)()
        y = (ctypes.c_double * n_pts)()
        n = ctypes.c_int()
        lib.shell_2d(radius, gap, x, y, ctypes.byref(n))

        xa = np.array(x[: n.value])
        ya = np.array(y[: n.value])
        radii = np.sqrt(xa ** 2 + ya ** 2)
        np.testing.assert_allclose(radii, radius, atol=1e-10)

    def test_c_shell_3d_on_sphere(self):
        """3D shell points from C must lie on the sphere."""
        lib = _load_c_lib()
        radius, gap = 1.0, 0.1
        n_pts = lib.shell_count_3d(radius, gap)
        x = (ctypes.c_double * n_pts)()
        y = (ctypes.c_double * n_pts)()
        z = (ctypes.c_double * n_pts)()
        n = ctypes.c_int()
        lib.shell_3d(radius, gap, x, y, z, ctypes.byref(n))

        xa = np.array(x[: n.value])
        ya = np.array(y[: n.value])
        za = np.array(z[: n.value])
        radii = np.sqrt(xa ** 2 + ya ** 2 + za ** 2)
        np.testing.assert_allclose(radii, radius, atol=1e-10)

    def test_c_shell_1d_zero(self):
        """1D shell at distance 0 must give a single zero point."""
        lib = _load_c_lib()
        x = (ctypes.c_double * 2)()
        n = ctypes.c_int()
        lib.shell_1d(0.0, x, ctypes.byref(n))
        assert n.value == 1
        assert x[0] == 0.0

    def test_c_shell_1d_nonzero(self):
        """1D shell at distance d must give exactly +d and -d."""
        lib = _load_c_lib()
        x = (ctypes.c_double * 2)()
        n = ctypes.c_int()
        lib.shell_1d(2.5, x, ctypes.byref(n))
        assert n.value == 2
        assert set(round(abs(v), 10) for v in x[: n.value]) == {2.5}


# ---------------------------------------------------------------------------
# Python ctypes wrapper tests (calculate_shell_coordinates)
# ---------------------------------------------------------------------------

def _get_test_data():
    """Construct the standard 3D regression test case."""
    grid_x = np.arange(0, 1, 0.1)
    grid_y = np.arange(0, 1.2, 0.1)
    grid_z = np.arange(0, 1.4, 0.1)
    dims = (len(grid_x), len(grid_y), len(grid_z))
    coords = (grid_x, grid_y, grid_z)

    reference = np.zeros(dims)
    reference[3:-2, 4:-2, 5:-2] = 1.015

    evaluation = np.zeros(dims)
    evaluation[2:-2, 2:-2, 2:-2] = 1.0

    expected = np.zeros(dims)
    expected[2:-2, 2:-2, 2:-2] = 0.4
    expected[3:-3, 3:-3, 3:-3] = 0.7
    expected[4:-4, 4:-4, 4:-4] = 1.0
    expected[3:-2, 4:-2, 5:-2] = 0.5

    return coords, reference, evaluation, expected


class TestShellCoordinates:
    def test_3d_coverage(self):
        """Shell points lie on the sphere and max nearest-neighbor gap
        does not exceed distance_step_size."""
        from gamma import calculate_shell_coordinates

        distance = 1.0
        step_size = 0.1
        x, y, z = calculate_shell_coordinates(distance, 3, step_size)

        radii = np.sqrt(x ** 2 + y ** 2 + z ** 2)
        np.testing.assert_allclose(radii, distance, atol=1e-10)

        coords = np.column_stack([x, y, z])
        diff = coords[:, None, :] - coords[None, :, :]
        sq_dist = np.sum(diff ** 2, axis=2)
        np.fill_diagonal(sq_dist, np.inf)
        nearest_distances = np.sqrt(np.min(sq_dist, axis=1))
        assert np.max(nearest_distances) <= step_size, (
            f"Max nearest-neighbor gap {np.max(nearest_distances):.6f} "
            f"exceeds step_size {step_size}"
        )
        assert np.max(nearest_distances) > step_size * 0.5

    def test_distance_zero(self):
        """Distance 0 must produce a single point at the origin."""
        from gamma import calculate_shell_coordinates

        for ndim in (1, 2, 3):
            shell = calculate_shell_coordinates(0, ndim, 0.1)
            assert len(shell) == ndim
            for c in shell:
                assert len(c) == 1, f"Expected 1 point for {ndim}D at distance 0"
                assert c[0] == 0.0

    def test_2d_coverage(self):
        """2D shell points lie on a circle and obey gap constraint."""
        from gamma import calculate_shell_coordinates

        distance = 0.5
        step_size = 0.05
        x, y = calculate_shell_coordinates(distance, 2, step_size)

        radii = np.sqrt(x ** 2 + y ** 2)
        np.testing.assert_allclose(radii, distance, atol=1e-10)

        coords = np.column_stack([x, y])
        diff = coords[:, None, :] - coords[None, :, :]
        sq_dist = np.sum(diff ** 2, axis=2)
        np.fill_diagonal(sq_dist, np.inf)
        nearest_distances = np.sqrt(np.min(sq_dist, axis=1))
        assert np.max(nearest_distances) <= step_size

    def test_1d_nonzero(self):
        """1D shell at nonzero distance must give exactly two points."""
        from gamma import calculate_shell_coordinates

        shell = calculate_shell_coordinates(2.5, 1, 0.1)
        assert len(shell) == 1
        pts = shell[0]
        assert len(pts) == 2
        assert set(np.round(np.abs(pts), 10)) == {2.5}


# ---------------------------------------------------------------------------
# Gamma regression tests
# ---------------------------------------------------------------------------

class TestGammaRegression:
    def test_3d(self):
        """3D gamma regression against known expected values."""
        from gamma import gamma

        coords, reference, evaluation, expected = _get_test_data()
        result = np.round(
            gamma(
                coords, reference, coords, evaluation,
                3, 0.3, lower_percent_dose_cutoff=0,
            ),
            decimals=1,
        )
        np.testing.assert_array_equal(expected, result)

    def test_2d(self):
        """2D gamma (y-z slice at x index 5)."""
        from gamma import gamma

        coords, reference, evaluation, expected = _get_test_data()
        result = np.round(
            gamma(
                coords[1:], reference[5, :, :],
                coords[1:], evaluation[5, :, :],
                3, 0.3, lower_percent_dose_cutoff=0,
            ),
            decimals=1,
        )
        np.testing.assert_array_equal(expected[5, :, :], result)

    def test_1d(self):
        """1D gamma (z line at x=5, y=5)."""
        from gamma import gamma

        coords, reference, evaluation, expected = _get_test_data()
        result = np.round(
            gamma(
                (coords[2],), reference[5, 5, :],
                (coords[2],), evaluation[5, 5, :],
                3, 0.3, lower_percent_dose_cutoff=0,
            ),
            decimals=1,
        )
        np.testing.assert_array_equal(expected[5, 5, :], result)


# ---------------------------------------------------------------------------
# Gamma behavior tests
# ---------------------------------------------------------------------------

class TestGammaBehavior:
    def test_lower_dose_cutoff(self):
        """Reference points below the lower dose cutoff must be NaN."""
        from gamma import gamma

        ref = np.array([0, 1, 1.9, 2, 2.1, 3, 4, 5, 10, 10], dtype=np.float64)
        coords_ref = (np.arange(len(ref), dtype=np.float64),)

        evl = np.full(len(ref) + 2, 10.0)
        coords_evl = (np.arange(len(evl), dtype=np.float64) - 4.0,)

        result = gamma(coords_ref, ref, coords_evl, evl, 10, 1)

        np.testing.assert_array_equal(
            ref < 2.0, np.isnan(result),
            err_msg="NaN pattern does not match expected lower dose cutoff",
        )

    def test_local_vs_global(self):
        """Local normalisation yields higher gamma at sub-maximum ref points."""
        from gamma import gamma

        x = np.linspace(0, 1, 11)
        ref = np.zeros(11)
        ref[2] = 5.0
        ref[3:8] = 10.0
        ref[8] = 5.0

        evl = np.zeros(11)
        evl[2] = 5.2
        evl[3:8] = 10.2
        evl[8] = 5.2

        global_g = gamma(
            (x,), ref, (x,), evl, 3, 0.3, lower_percent_dose_cutoff=10,
        )
        local_g = gamma(
            (x,), ref, (x,), evl, 3, 0.3,
            lower_percent_dose_cutoff=10, local_gamma=True,
        )

        np.testing.assert_allclose(global_g[3:8], local_g[3:8], atol=1e-6)
        np.testing.assert_allclose(global_g[2], 2.0 / 3.0, atol=0.01)
        np.testing.assert_allclose(local_g[2], 4.0 / 3.0, atol=0.01)
        np.testing.assert_allclose(global_g[8], 2.0 / 3.0, atol=0.01)
        np.testing.assert_allclose(local_g[8], 4.0 / 3.0, atol=0.01)

    def test_max_gamma_cap(self):
        """max_gamma must cap computed values."""
        from gamma import gamma

        x = np.linspace(0, 5, 6)
        ref = np.array([0.0, 0.0, 10.0, 0.0, 0.0, 0.0])
        evl = np.array([0.0, 0.0, 7.0, 0.0, 0.0, 0.0])

        result = gamma(
            (x,), ref, (x,), evl, 3, 1,
            lower_percent_dose_cutoff=0, max_gamma=2,
        )

        assert np.all(np.isfinite(result))
        assert result[2] == 2.0
        assert result[0] == 0.0
        assert result[5] == 0.0

    def test_different_grids(self):
        """Reference and evaluation may use different coordinate axes."""
        from gamma import gamma

        x_ref = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        ref = np.array([0.0, 5.0, 10.0, 5.0, 0.0])

        x_evl = np.array([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0])
        evl = np.array([0.0, 2.5, 5.0, 7.5, 10.0, 7.5, 5.0, 2.5, 0.0])

        result = gamma(
            (x_ref,), ref, (x_evl,), evl, 3, 1,
            lower_percent_dose_cutoff=20,
        )

        assert np.isnan(result[0])
        assert np.isnan(result[4])
        np.testing.assert_allclose(result[1:4], 0.0, atol=1e-6)


# ---------------------------------------------------------------------------
# QA report tests (including SQLite persistence)
# ---------------------------------------------------------------------------

class TestQAReport:
    def test_identical_distributions(self):
        """Identical reference and evaluation must yield 100% pass rate."""
        from qa_report import generate_qa_report

        report = generate_qa_report(
            "/app/data/case_identical_reference.csv",
            "/app/data/case_identical_evaluation.csv",
            "/app/data/case_identical_axes.json",
            "/app/data/case_identical_criteria.json",
        )

        assert isinstance(report, dict)
        required_keys = {
            "pass_rate", "mean_gamma", "max_gamma",
            "points_evaluated", "points_passing", "passed",
        }
        assert set(report.keys()) == required_keys

        assert report["pass_rate"] == 100.0
        assert report["mean_gamma"] == 0.0
        assert report["max_gamma"] == 0.0
        assert report["points_evaluated"] == 2
        assert report["points_passing"] == 2
        assert report["passed"] is True

    def test_report_types(self):
        """Report values must have the correct Python types."""
        from qa_report import generate_qa_report

        report = generate_qa_report(
            "/app/data/case_identical_reference.csv",
            "/app/data/case_identical_evaluation.csv",
            "/app/data/case_identical_axes.json",
            "/app/data/case_identical_criteria.json",
        )

        assert isinstance(report["pass_rate"], float)
        assert isinstance(report["mean_gamma"], float)
        assert isinstance(report["max_gamma"], float)
        assert isinstance(report["points_evaluated"], int)
        assert isinstance(report["points_passing"], int)
        assert isinstance(report["passed"], bool)


class TestSQLitePersistence:
    def _clean_db(self):
        if os.path.exists("/app/results.db"):
            os.remove("/app/results.db")

    def test_database_created(self):
        """generate_qa_report must create /app/results.db."""
        from qa_report import generate_qa_report

        self._clean_db()
        generate_qa_report(
            "/app/data/case_identical_reference.csv",
            "/app/data/case_identical_evaluation.csv",
            "/app/data/case_identical_axes.json",
            "/app/data/case_identical_criteria.json",
        )
        assert os.path.isfile("/app/results.db"), "results.db not created"

    def test_sessions_table_schema(self):
        """The sessions table must have all required columns."""
        from qa_report import generate_qa_report

        self._clean_db()
        generate_qa_report(
            "/app/data/case_identical_reference.csv",
            "/app/data/case_identical_evaluation.csv",
            "/app/data/case_identical_axes.json",
            "/app/data/case_identical_criteria.json",
        )

        conn = sqlite3.connect("/app/results.db")
        cursor = conn.execute("PRAGMA table_info(sessions)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        expected = {
            "id", "session_name", "created_at",
            "pass_rate", "mean_gamma", "max_gamma",
            "points_evaluated", "points_passing", "passed",
        }
        assert columns == expected, f"Schema mismatch: {columns} vs {expected}"

    def test_row_values(self):
        """Persisted row must match the returned report values."""
        from qa_report import generate_qa_report

        self._clean_db()
        generate_qa_report(
            "/app/data/case_identical_reference.csv",
            "/app/data/case_identical_evaluation.csv",
            "/app/data/case_identical_axes.json",
            "/app/data/case_identical_criteria.json",
        )

        conn = sqlite3.connect("/app/results.db")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM sessions").fetchone()
        conn.close()

        assert row["session_name"] == "case_identical_reference"
        assert row["pass_rate"] == 100.0
        assert row["mean_gamma"] == 0.0
        assert row["max_gamma"] == 0.0
        assert row["points_evaluated"] == 2
        assert row["points_passing"] == 2
        assert row["passed"] == 1
        # created_at must be a non-empty ISO 8601 string
        assert len(row["created_at"]) >= 10

    def test_replace_on_conflict(self):
        """Repeated calls with the same reference must not duplicate rows."""
        from qa_report import generate_qa_report

        self._clean_db()
        for _ in range(3):
            generate_qa_report(
                "/app/data/case_identical_reference.csv",
                "/app/data/case_identical_evaluation.csv",
                "/app/data/case_identical_axes.json",
                "/app/data/case_identical_criteria.json",
            )

        conn = sqlite3.connect("/app/results.db")
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.close()
        assert count == 1, f"Expected 1 row after repeated inserts, got {count}"
