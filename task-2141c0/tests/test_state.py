
import json
import math
import os
import sqlite3
import pytest


@pytest.fixture(scope="module")
def results():
    path = "/app/results.json"
    assert os.path.exists(path), "results.json not found at /app/results.json"
    with open(path) as f:
        data = json.load(f)
    return data


def rel_err(computed, reference):
    """Relative error between computed and reference values."""
    if reference == 0:
        return abs(computed)
    return abs(computed - reference) / abs(reference)


# ============================================================
# Grid quality metrics
# ============================================================

class TestGrid:
    def test_dimensions(self, results):
        g = results["grid"]
        assert g["nx"] == 35, f"Expected nx=35, got {g['nx']}"
        assert g["ny"] == 25, f"Expected ny=25, got {g['ny']}"

    def test_first_cell_spacing(self, results):
        y1 = results["grid"]["y1"]
        ref = 8.320034e-6
        assert rel_err(y1, ref) < 0.05, f"y1={y1}, expected ~{ref}"

    def test_max_stretch_ratio(self, results):
        sr = results["grid"]["max_stretch_ratio"]
        ref = 1.629
        assert rel_err(sr, ref) < 0.05, f"stretch_ratio={sr}, expected ~{ref}"


# ============================================================
# Convergence — CFL3D skin friction
# ============================================================

class TestConvergenceCFL3DCf:
    def test_order(self, results):
        p = results["convergence"]["cfl3d_cf"]["p"]
        ref = 1.984
        assert abs(p - ref) < 0.15, f"p={p}, expected ~{ref}"

    def test_extrapolated_value(self, results):
        f_ext = results["convergence"]["cfl3d_cf"]["f_ext"]
        ref = 0.0027052440
        assert rel_err(f_ext, ref) < 0.01, f"f_ext={f_ext}, expected ~{ref}"

    def test_approximate_error(self, results):
        e_a = results["convergence"]["cfl3d_cf"]["e_a_pct"]
        ref = 0.04125
        assert rel_err(e_a, ref) < 0.30, f"e_a_pct={e_a}, expected ~{ref}"

    def test_gci(self, results):
        gci = results["convergence"]["cfl3d_cf"]["gci_pct"]
        ref = 0.01744
        assert rel_err(gci, ref) < 0.30, f"gci_pct={gci}, expected ~{ref}"

    def test_monotonic(self, results):
        assert results["convergence"]["cfl3d_cf"]["monotonic"] is True


# ============================================================
# Convergence — FUN3D skin friction
# ============================================================

class TestConvergenceFUN3DCf:
    def test_order(self, results):
        p = results["convergence"]["fun3d_cf"]["p"]
        ref = 1.341
        assert abs(p - ref) < 0.15, f"p={p}, expected ~{ref}"

    def test_extrapolated_value(self, results):
        f_ext = results["convergence"]["fun3d_cf"]["f_ext"]
        ref = 0.002706005
        assert rel_err(f_ext, ref) < 0.01, f"f_ext={f_ext}, expected ~{ref}"

    def test_monotonic(self, results):
        assert results["convergence"]["fun3d_cf"]["monotonic"] is True


# ============================================================
# Convergence — CFL3D drag
# ============================================================

class TestConvergenceCFL3DCd:
    def test_order(self, results):
        p = results["convergence"]["cfl3d_cd"]["p"]
        ref = 1.750
        assert abs(p - ref) < 0.15, f"p={p}, expected ~{ref}"

    def test_extrapolated_value(self, results):
        f_ext = results["convergence"]["cfl3d_cd"]["f_ext"]
        ref = 0.002859237
        assert rel_err(f_ext, ref) < 0.01, f"f_ext={f_ext}, expected ~{ref}"

    def test_monotonic(self, results):
        assert results["convergence"]["cfl3d_cd"]["monotonic"] is True


# ============================================================
# Convergence — FUN3D drag
# ============================================================

class TestConvergenceFUN3DCd:
    def test_order(self, results):
        p = results["convergence"]["fun3d_cd"]["p"]
        ref = 0.798
        assert abs(p - ref) < 0.15, f"p={p}, expected ~{ref}"

    def test_extrapolated_value(self, results):
        f_ext = results["convergence"]["fun3d_cd"]["f_ext"]
        ref = 0.002858607
        assert rel_err(f_ext, ref) < 0.01, f"f_ext={f_ext}, expected ~{ref}"

    def test_monotonic(self, results):
        assert results["convergence"]["fun3d_cd"]["monotonic"] is True


# ============================================================
# Boundary layer integral quantities
# ============================================================

class TestBoundaryLayer:
    def test_delta99(self, results):
        d99 = results["boundary_layer"]["delta99"]
        ref = 1.433e-2
        assert rel_err(d99, ref) < 0.10, f"delta99={d99}, expected ~{ref}"

    def test_displacement_thickness(self, results):
        ds = results["boundary_layer"]["delta_star"]
        ref = 2.050e-3
        assert rel_err(ds, ref) < 0.10, f"delta_star={ds}, expected ~{ref}"

    def test_momentum_thickness(self, results):
        th = results["boundary_layer"]["theta"]
        ref = 1.549e-3
        assert rel_err(th, ref) < 0.10, f"theta={th}, expected ~{ref}"

    def test_shape_factor(self, results):
        H = results["boundary_layer"]["H"]
        ref = 1.323
        assert rel_err(H, ref) < 0.05, f"H={H}, expected ~{ref}"

    def test_shape_factor_physical_range(self, results):
        H = results["boundary_layer"]["H"]
        assert 1.2 < H < 1.6, f"H={H} outside turbulent BL range [1.2, 1.6]"


# ============================================================
# Law-of-the-wall analysis
# ============================================================

class TestLogLaw:
    def test_kappa_fit(self, results):
        kappa = results["log_law"]["kappa_fit"]
        ref = 0.389
        assert abs(kappa - ref) < 0.05, f"kappa_fit={kappa}, expected ~{ref}"

    def test_B_fit(self, results):
        B = results["log_law"]["B_fit"]
        ref = 4.535
        assert abs(B - ref) < 0.6, f"B_fit={B}, expected ~{ref}"

    def test_rms_standard(self, results):
        rms = results["log_law"]["rms_standard"]
        ref = 0.214
        assert rel_err(rms, ref) < 0.50, f"rms_standard={rms}, expected ~{ref}"

    def test_rms_positive(self, results):
        assert results["log_law"]["rms_standard"] > 0


# ============================================================
# Eddy viscosity statistics
# ============================================================

class TestEddyViscosity:
    def test_peak_value(self, results):
        peak = results["eddy_viscosity"]["peak_mut"]
        ref = 208.3165
        assert rel_err(peak, ref) < 0.05, f"peak_mut={peak}, expected ~{ref}"

    def test_peak_location(self, results):
        y = results["eddy_viscosity"]["peak_y"]
        ref = 6.829e-3
        assert rel_err(y, ref) < 0.10, f"peak_y={y}, expected ~{ref}"

    def test_monotonic_to_peak(self, results):
        assert results["eddy_viscosity"]["monotonic_to_peak"] is True


# ============================================================
# Structure and completeness checks
# ============================================================

class TestStructure:
    def test_all_top_level_keys(self, results):
        required = {"grid", "convergence", "boundary_layer", "log_law", "eddy_viscosity"}
        assert required.issubset(results.keys()), f"Missing keys: {required - set(results.keys())}"

    def test_convergence_has_all_cases(self, results):
        required = {"cfl3d_cf", "fun3d_cf", "cfl3d_cd", "fun3d_cd"}
        assert required.issubset(results["convergence"].keys())

    def test_convergence_fields_complete(self, results):
        for case in ["cfl3d_cf", "fun3d_cf", "cfl3d_cd", "fun3d_cd"]:
            r = results["convergence"][case]
            for field in ["p", "f_ext", "e_a_pct", "gci_pct", "monotonic"]:
                assert field in r, f"Missing {field} in convergence.{case}"


# ============================================================
# Convergence plot (gnuplot EPS)
# ============================================================

class TestConvergencePlot:
    def test_eps_exists(self):
        assert os.path.exists("/app/plots/convergence.eps"), \
            "convergence.eps not found at /app/plots/convergence.eps"

    def test_eps_valid_postscript(self):
        with open("/app/plots/convergence.eps", "rb") as f:
            header = f.read(4)
        assert header == b"%!PS", "File does not start with %!PS — not valid PostScript"

    def test_eps_contains_code_labels(self):
        with open("/app/plots/convergence.eps", "r", errors="replace") as f:
            content = f.read()
        assert "CFL3D" in content, "Plot must label CFL3D data"
        assert "FUN3D" in content, "Plot must label FUN3D data"

    def test_eps_nontrivial_size(self):
        size = os.path.getsize("/app/plots/convergence.eps")
        assert size > 1000, f"EPS file suspiciously small: {size} bytes"


# ============================================================
# SQLite benchmark database
# ============================================================

class TestDatabase:
    @pytest.fixture(scope="class")
    def db(self):
        path = "/app/benchmark.db"
        assert os.path.exists(path), "benchmark.db not found at /app/benchmark.db"
        conn = sqlite3.connect(path)
        yield conn
        conn.close()

    def test_required_tables_exist(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        required = {
            "convergence_raw", "convergence_results",
            "boundary_layer_profile", "analysis_summary",
        }
        assert required.issubset(tables), \
            f"Missing tables: {required - tables}"

    def test_convergence_raw_populated(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM convergence_raw"
        ).fetchone()[0]
        assert count >= 20, \
            f"Expected >=20 rows in convergence_raw, got {count}"

    def test_convergence_results_complete(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM convergence_results"
        ).fetchone()[0]
        assert count == 4, \
            f"Expected 4 rows (2 codes x 2 quantities), got {count}"

    def test_query_cfl3d_cf_extrapolated(self, db):
        row = db.execute(
            "SELECT f_ext FROM convergence_results "
            "WHERE code='CFL3D' AND quantity='cf'"
        ).fetchone()
        assert row is not None, "Missing CFL3D/cf in convergence_results"
        assert rel_err(float(row[0]), 0.0027052440) < 0.01

    def test_query_fun3d_cd_extrapolated(self, db):
        row = db.execute(
            "SELECT f_ext FROM convergence_results "
            "WHERE code='FUN3D' AND quantity='cd'"
        ).fetchone()
        assert row is not None, "Missing FUN3D/cd in convergence_results"
        assert rel_err(float(row[0]), 0.002858607) < 0.01

    def test_boundary_layer_profile_populated(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM boundary_layer_profile"
        ).fetchone()[0]
        assert count > 20, \
            f"boundary_layer_profile should have >20 rows, got {count}"

    def test_analysis_summary_populated(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM analysis_summary"
        ).fetchone()[0]
        assert count >= 5, \
            f"Expected >=5 entries in analysis_summary, got {count}"
