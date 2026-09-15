
import json
import os
import sqlite3
import re
import pytest


DB_PATH = "/app/output/ensemble.db"
TECPLOT_PATH = "/app/output/ensemble_submission.dat"
JSON_PATH = "/app/output/analysis.json"

# Expected clean ensemble statistics (S001-S005, excluding outlier S006)
# Computed from exact data with sample std (ddof=1)
EXPECTED_CL_MEAN = {
    0.0: 0.17817, 1.0: 0.31946, 2.0: 0.46675,
    3.0: 0.60757, 4.0: 0.68657, 5.0: 0.73035,
}
EXPECTED_CD_MEAN = {
    0.0: 0.01879, 1.0: 0.02131, 2.0: 0.02590,
    3.0: 0.03603, 4.0: 0.05205, 5.0: 0.06862,
}
EXPECTED_CM_MEAN = {
    0.0: 0.05465, 1.0: 0.00458, 2.0: -0.03978,
    3.0: -0.07550, 4.0: -0.05921, 5.0: -0.06250,
}

# Grid convergence expected (Richardson extrapolation, exact 2nd order)
EXPECTED_GC = {
    "S001": {"CL_h0": 0.4700, "CD_h0": 0.02580, "CM_h0": -0.04050, "order": 2.0},
    "S002": {"CL_h0": 0.4680, "CD_h0": 0.02565, "CM_h0": -0.04100, "order": 2.0},
    "S003": {"CL_h0": 0.4695, "CD_h0": 0.02575, "CM_h0": -0.03980, "order": 2.0},
}


# ============================================================
# FILE EXISTENCE TESTS
# ============================================================
class TestFilesExist:
    def test_database_exists(self):
        assert os.path.exists(DB_PATH), f"SQLite database not found at {DB_PATH}"

    def test_tecplot_exists(self):
        assert os.path.exists(TECPLOT_PATH), f"Tecplot file not found at {TECPLOT_PATH}"

    def test_json_exists(self):
        assert os.path.exists(JSON_PATH), f"Analysis JSON not found at {JSON_PATH}"


# ============================================================
# DATABASE SCHEMA TESTS
# ============================================================
class TestDatabaseSchema:
    @pytest.fixture(scope="class")
    def conn(self):
        c = sqlite3.connect(DB_PATH)
        yield c
        c.close()

    def _table_exists(self, conn, table):
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        return cur.fetchone() is not None

    def _get_columns(self, conn, table):
        cur = conn.execute(f"PRAGMA table_info({table})")
        return {row[1].lower() for row in cur.fetchall()}

    def test_solvers_table(self, conn):
        assert self._table_exists(conn, "solvers"), "Table 'solvers' missing"
        cols = self._get_columns(conn, "solvers")
        for c in ["solver_id", "solver_name", "turbulence_model", "grid_level", "grid_size"]:
            assert c in cols, f"Column '{c}' missing in solvers table"

    def test_coefficients_table(self, conn):
        assert self._table_exists(conn, "coefficients"), "Table 'coefficients' missing"
        cols = self._get_columns(conn, "coefficients")
        for c in ["solver_id", "alpha", "cl", "cd", "cm"]:
            assert c.lower() in cols, f"Column '{c}' missing in coefficients table"

    def test_statistics_table(self, conn):
        assert self._table_exists(conn, "statistics"), "Table 'statistics' missing"
        cols = self._get_columns(conn, "statistics")
        for c in ["alpha", "cl_mean", "cl_std", "cd_mean", "cd_std", "cm_mean", "cm_std", "n_solvers"]:
            assert c in cols, f"Column '{c}' missing in statistics table"

    def test_outliers_table(self, conn):
        assert self._table_exists(conn, "outliers"), "Table 'outliers' missing"
        cols = self._get_columns(conn, "outliers")
        assert "solver_id" in cols
        assert "reason" in cols

    def test_grid_convergence_table(self, conn):
        assert self._table_exists(conn, "grid_convergence"), "Table 'grid_convergence' missing"
        cols = self._get_columns(conn, "grid_convergence")
        for c in ["solver_id", "cl_h0", "cd_h0", "cm_h0", "order_cl", "order_cd", "order_cm"]:
            assert c in cols, f"Column '{c}' missing in grid_convergence table"

    def test_validation_table(self, conn):
        assert self._table_exists(conn, "validation"), "Table 'validation' missing"
        cols = self._get_columns(conn, "validation")
        for c in ["alpha", "cl_exp", "cl_comp", "cl_delta", "cd_exp", "cd_comp", "cd_delta",
                   "within_uncertainty"]:
            assert c in cols, f"Column '{c}' missing in validation table"


# ============================================================
# DATABASE CONTENT TESTS
# ============================================================
class TestDatabaseContent:
    @pytest.fixture(scope="class")
    def conn(self):
        c = sqlite3.connect(DB_PATH)
        c.row_factory = sqlite3.Row
        yield c
        c.close()

    def test_all_solvers_loaded(self, conn):
        cur = conn.execute("SELECT COUNT(*) FROM solvers")
        count = cur.fetchone()[0]
        assert count == 6, f"Expected 6 solvers, got {count}"

    def test_all_coefficients_loaded(self, conn):
        cur = conn.execute("SELECT COUNT(*) FROM coefficients")
        count = cur.fetchone()[0]
        assert count == 36, f"Expected 36 coefficient rows (6 solvers x 6 alphas), got {count}"

    def test_outlier_detected(self, conn):
        cur = conn.execute("SELECT solver_id FROM outliers")
        outlier_ids = {row["solver_id"] for row in cur.fetchall()}
        assert "S006" in outlier_ids, f"S006 should be flagged as outlier. Got: {outlier_ids}"

    def test_outlier_has_reason(self, conn):
        cur = conn.execute("SELECT reason FROM outliers WHERE solver_id='S006'")
        row = cur.fetchone()
        assert row is not None
        assert len(row["reason"]) > 5, "Outlier reason should be descriptive"

    def test_statistics_count(self, conn):
        cur = conn.execute("SELECT COUNT(*) FROM statistics")
        count = cur.fetchone()[0]
        assert count == 6, f"Expected 6 statistics rows (one per alpha), got {count}"

    def test_statistics_n_solvers(self, conn):
        cur = conn.execute("SELECT n_solvers FROM statistics")
        for row in cur.fetchall():
            assert row["n_solvers"] == 5, f"Expected 5 accepted solvers, got {row['n_solvers']}"

    @pytest.mark.parametrize("alpha", [0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    def test_cl_mean(self, conn, alpha):
        cur = conn.execute("SELECT cl_mean FROM statistics WHERE abs(alpha - ?) < 0.01", (alpha,))
        row = cur.fetchone()
        assert row is not None, f"No statistics row for alpha={alpha}"
        expected = EXPECTED_CL_MEAN[alpha]
        assert abs(row["cl_mean"] - expected) < 0.0005, \
            f"CL_mean at alpha={alpha}: got {row['cl_mean']}, expected {expected}"

    @pytest.mark.parametrize("alpha", [0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    def test_cd_mean(self, conn, alpha):
        cur = conn.execute("SELECT cd_mean FROM statistics WHERE abs(alpha - ?) < 0.01", (alpha,))
        row = cur.fetchone()
        assert row is not None
        expected = EXPECTED_CD_MEAN[alpha]
        assert abs(row["cd_mean"] - expected) < 0.00005, \
            f"CD_mean at alpha={alpha}: got {row['cd_mean']}, expected {expected}"

    @pytest.mark.parametrize("alpha", [0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    def test_cm_mean(self, conn, alpha):
        cur = conn.execute("SELECT cm_mean FROM statistics WHERE abs(alpha - ?) < 0.01", (alpha,))
        row = cur.fetchone()
        assert row is not None
        expected = EXPECTED_CM_MEAN[alpha]
        assert abs(row["cm_mean"] - expected) < 0.0005, \
            f"CM_mean at alpha={alpha}: got {row['cm_mean']}, expected {expected}"

    def test_std_uses_bessel(self, conn):
        """Verify standard deviation uses Bessel's correction (N-1 denominator)."""
        cur = conn.execute("SELECT cl_std FROM statistics WHERE abs(alpha - 2.0) < 0.01")
        row = cur.fetchone()
        assert row is not None
        # With N=5, sample std (ddof=1) is ~0.001234
        # Population std (ddof=0) would be ~0.001103
        assert row["cl_std"] > 0.0011, "CL_std too low — may not use Bessel's correction"
        assert row["cl_std"] < 0.002, "CL_std unreasonably high"


# ============================================================
# GRID CONVERGENCE TESTS
# ============================================================
class TestGridConvergence:
    @pytest.fixture(scope="class")
    def conn(self):
        c = sqlite3.connect(DB_PATH)
        c.row_factory = sqlite3.Row
        yield c
        c.close()

    def test_three_solvers_have_gc(self, conn):
        cur = conn.execute("SELECT COUNT(*) FROM grid_convergence")
        count = cur.fetchone()[0]
        assert count == 3, f"Expected 3 grid convergence entries, got {count}"

    @pytest.mark.parametrize("sid", ["S001", "S002", "S003"])
    def test_cl_continuum(self, conn, sid):
        cur = conn.execute("SELECT cl_h0 FROM grid_convergence WHERE solver_id=?", (sid,))
        row = cur.fetchone()
        assert row is not None, f"No grid convergence entry for {sid}"
        expected = EXPECTED_GC[sid]["CL_h0"]
        assert abs(row["cl_h0"] - expected) < 0.001, \
            f"{sid} CL_h0: got {row['cl_h0']}, expected {expected}"

    @pytest.mark.parametrize("sid", ["S001", "S002", "S003"])
    def test_cd_continuum(self, conn, sid):
        cur = conn.execute("SELECT cd_h0 FROM grid_convergence WHERE solver_id=?", (sid,))
        row = cur.fetchone()
        expected = EXPECTED_GC[sid]["CD_h0"]
        assert abs(row["cd_h0"] - expected) < 0.0002, \
            f"{sid} CD_h0: got {row['cd_h0']}, expected {expected}"

    @pytest.mark.parametrize("sid", ["S001", "S002", "S003"])
    def test_cm_continuum(self, conn, sid):
        cur = conn.execute("SELECT cm_h0 FROM grid_convergence WHERE solver_id=?", (sid,))
        row = cur.fetchone()
        expected = EXPECTED_GC[sid]["CM_h0"]
        assert abs(row["cm_h0"] - expected) < 0.001, \
            f"{sid} CM_h0: got {row['cm_h0']}, expected {expected}"

    @pytest.mark.parametrize("sid", ["S001", "S002", "S003"])
    def test_observed_order(self, conn, sid):
        cur = conn.execute("SELECT order_cl FROM grid_convergence WHERE solver_id=?", (sid,))
        row = cur.fetchone()
        expected = EXPECTED_GC[sid]["order"]
        assert abs(row["order_cl"] - expected) < 0.3, \
            f"{sid} order_CL: got {row['order_cl']}, expected {expected}"


# ============================================================
# VALIDATION TABLE TESTS
# ============================================================
class TestValidation:
    @pytest.fixture(scope="class")
    def conn(self):
        c = sqlite3.connect(DB_PATH)
        c.row_factory = sqlite3.Row
        yield c
        c.close()

    def test_validation_rows(self, conn):
        cur = conn.execute("SELECT COUNT(*) FROM validation")
        count = cur.fetchone()[0]
        assert count == 6, f"Expected 6 validation rows, got {count}"

    def test_all_within_uncertainty(self, conn):
        """All alpha values should show CFD within experimental uncertainty."""
        cur = conn.execute("SELECT alpha, within_uncertainty FROM validation")
        for row in cur.fetchall():
            assert row["within_uncertainty"] == 1, \
                f"Alpha={row['alpha']}: CFD should be within experimental uncertainty"

    def test_cl_delta_reasonable(self, conn):
        cur = conn.execute("SELECT alpha, cl_delta FROM validation")
        for row in cur.fetchall():
            assert abs(row["cl_delta"]) < 0.01, \
                f"Alpha={row['alpha']}: CL_delta={row['cl_delta']} too large"

    def test_validation_uses_clean_ensemble(self, conn):
        """Validation CL_comp should match clean ensemble means, not include outlier."""
        cur = conn.execute("SELECT cl_comp FROM validation WHERE abs(alpha - 2.0) < 0.01")
        row = cur.fetchone()
        assert row is not None
        expected = EXPECTED_CL_MEAN[2.0]
        assert abs(row["cl_comp"] - expected) < 0.001, \
            f"Validation CL_comp at alpha=2 should match clean ensemble: got {row['cl_comp']}, expected {expected}"


# ============================================================
# TECPLOT SUBMISSION FILE TESTS
# ============================================================
class TestTecplotSubmission:
    @pytest.fixture(scope="class")
    def content(self):
        with open(TECPLOT_PATH) as f:
            return f.read()

    def test_has_title(self, content):
        assert "TITLE" in content, "Tecplot file must have TITLE line"

    def test_has_variables(self, content):
        assert "VARIABLES" in content, "Tecplot file must have VARIABLES line"

    def test_has_31_variables(self, content):
        # Find VARIABLES line and count quoted variable names
        for line in content.split("\n"):
            if line.strip().startswith("VARIABLES"):
                var_count = line.count('"') // 2
                assert var_count == 31, f"Expected 31 variables, got {var_count}"
                break

    def test_has_zone(self, content):
        assert "ZONE" in content, "Tecplot file must have at least one ZONE"

    def test_participant_id(self, content):
        assert "ENS" in content, "Participant ID should be 'ENS'"

    def test_has_data_rows(self, content):
        """Should have data rows with numerical values."""
        data_lines = 0
        for line in content.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("TITLE") \
               or stripped.startswith("VARIABLES") or stripped.startswith("ZONE") \
               or stripped.startswith("AUXDATA") or stripped.startswith("DATASETAUXDATA"):
                continue
            parts = stripped.split()
            if len(parts) >= 7:
                try:
                    float(parts[0])
                    data_lines += 1
                except ValueError:
                    pass
        assert data_lines >= 6, f"Expected at least 6 data rows, found {data_lines}"

    def test_ensemble_cl_in_data(self, content):
        """Verify ensemble CL at alpha=2 appears in the data."""
        expected = EXPECTED_CL_MEAN[2.0]
        found = False
        for line in content.split("\n"):
            parts = line.strip().split()
            if len(parts) >= 7:
                try:
                    alpha_val = float(parts[5])  # column 6 = ALPHA
                    cl_val = float(parts[6])      # column 7 = CL_TOT
                    if abs(alpha_val - 2.0) < 0.1 and abs(cl_val - expected) < 0.001:
                        found = True
                        break
                except (ValueError, IndexError):
                    pass
        assert found, f"Expected ensemble CL~{expected} at alpha=2.0 in Tecplot data"

    def test_grid_fac_computed(self, content):
        """GRID_FAC (column 3) should be 1/GRID_SIZE^(2/3), not -999."""
        for line in content.split("\n"):
            parts = line.strip().split()
            if len(parts) >= 7:
                try:
                    grid_fac = float(parts[2])
                    if grid_fac != -999:
                        assert grid_fac > 0, f"GRID_FAC should be positive, got {grid_fac}"
                        break
                except (ValueError, IndexError):
                    pass


# ============================================================
# ANALYSIS JSON TESTS
# ============================================================
class TestAnalysisJSON:
    @pytest.fixture(scope="class")
    def analysis(self):
        with open(JSON_PATH) as f:
            return json.load(f)

    def test_n_solvers_total(self, analysis):
        assert analysis["n_solvers_total"] == 6

    def test_n_solvers_accepted(self, analysis):
        assert analysis["n_solvers_accepted"] == 5

    def test_outlier_ids(self, analysis):
        assert "S006" in analysis["outlier_ids"]

    def test_ensemble_cl_alpha2(self, analysis):
        expected = EXPECTED_CL_MEAN[2.0]
        got = analysis["ensemble_cl_at_alpha_2"]
        assert abs(got - expected) < 0.001, f"Expected CL~{expected}, got {got}"

    def test_ensemble_cd_alpha2(self, analysis):
        expected = EXPECTED_CD_MEAN[2.0]
        got = analysis["ensemble_cd_at_alpha_2"]
        assert abs(got - expected) < 0.0001, f"Expected CD~{expected}, got {got}"

    def test_continuum_estimates_present(self, analysis):
        ce = analysis["continuum_estimates"]
        for sid in ["S001", "S002", "S003"]:
            assert sid in ce, f"Missing continuum estimates for {sid}"
            assert "CL_h0" in ce[sid]
            assert "order" in ce[sid]

    def test_continuum_cl_values(self, analysis):
        for sid in ["S001", "S002", "S003"]:
            got = analysis["continuum_estimates"][sid]["CL_h0"]
            expected = EXPECTED_GC[sid]["CL_h0"]
            assert abs(got - expected) < 0.001, \
                f"{sid} CL_h0: got {got}, expected {expected}"
