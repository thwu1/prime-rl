
import json
import math
import os
import sqlite3
import subprocess
import pytest


@pytest.fixture(scope="session")
def results():
    """Run the pipeline and load results."""
    result = subprocess.run(
        ["python3", "/app/episuite_pipeline.py"],
        capture_output=True, text=True, cwd="/app", timeout=180
    )
    assert result.returncode == 0, f"Pipeline failed: {result.stderr}"
    assert os.path.exists("/app/results.json"), "results.json not created"
    with open("/app/results.json") as f:
        data = json.load(f)
    assert isinstance(data, list), "results.json must contain a JSON array"
    return data


@pytest.fixture(scope="session")
def chemical_results(results):
    """Return dict mapping CAS -> result object (excluding SUMMARY)."""
    return {r["cas"]: r for r in results if r["cas"] != "SUMMARY"}


@pytest.fixture(scope="session")
def summary(results):
    """Return the SUMMARY record."""
    summaries = [r for r in results if r["cas"] == "SUMMARY"]
    assert len(summaries) == 1, "Exactly one SUMMARY record required"
    return summaries[0]


@pytest.fixture(scope="session")
def db(results):
    """Open SQLite database after pipeline has run."""
    db_path = "/app/results.db"
    assert os.path.exists(db_path), "results.db not created by pipeline"
    conn = sqlite3.connect(db_path)
    yield conn
    conn.close()


# ============================================================
# JSON Schema tests
# ============================================================

class TestSchema:
    def test_result_count(self, results):
        assert len(results) == 30

    def test_required_fields(self, chemical_results):
        required = {"cas", "koc_mci_log", "koc_mci", "koc_kow_log", "koc_kow",
                     "bcf_log", "bcf", "koc_mci_residual", "koc_kow_residual",
                     "better_method"}
        for cas, rec in chemical_results.items():
            assert required.issubset(set(rec.keys())), \
                f"Missing fields in {cas}: {required - set(rec.keys())}"

    def test_summary_fields(self, summary):
        required = {"cas", "mci_rmse", "kow_rmse", "mci_wins", "kow_wins",
                     "mean_bcf_log"}
        assert required.issubset(set(summary.keys())), \
            f"Missing summary fields: {required - set(summary.keys())}"


# ============================================================
# SQLite database structure tests
# ============================================================

class TestSQLiteStructure:
    def test_required_tables_exist(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert "equations" in tables, \
            f"Missing 'equations' table. Found: {tables}"
        assert "fragment_corrections" in tables, \
            f"Missing 'fragment_corrections' table. Found: {tables}"
        assert "compound_results" in tables, \
            f"Missing 'compound_results' table. Found: {tables}"

    def test_equations_row_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM equations").fetchone()[0]
        assert count == 4, f"Expected 4 equation rows, got {count}"

    def test_compound_results_row_count(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM compound_results"
        ).fetchone()[0]
        assert count == 29, f"Expected 29 compound result rows, got {count}"


# ============================================================
# SQLite equation parameter verification
# ============================================================

class TestSQLiteEquations:
    def test_equation_coefficients_present(self, db):
        """Verify all 4 regression equations stored with correct coefficients."""
        rows = db.execute(
            "SELECT coefficient_a, coefficient_b FROM equations"
        ).fetchall()
        assert len(rows) == 4

        expected_pairs = [
            (0.5213, 0.60),
            (0.8679, -0.0004),
            (0.55313, 0.9251),
            (0.6598, -0.333),
        ]
        for ea, eb in expected_pairs:
            found = any(
                abs(a - ea) < 0.001 and abs(b - eb) < 0.01
                for a, b in rows
            )
            assert found, \
                f"Equation ({ea}, {eb}) not found in equations table"


# ============================================================
# SQLite fragment corrections verification
# ============================================================

class TestSQLiteCorrections:
    def test_mci_corrections_count(self, db):
        cursor = db.execute(
            "SELECT COUNT(*) FROM fragment_corrections "
            "WHERE LOWER(method) LIKE '%mci%'"
        )
        count = cursor.fetchone()[0]
        assert count >= 13, f"Expected >=13 MCI corrections, got {count}"

    def test_kow_corrections_count(self, db):
        cursor = db.execute(
            "SELECT COUNT(*) FROM fragment_corrections "
            "WHERE LOWER(method) LIKE '%kow%'"
        )
        count = cursor.fetchone()[0]
        assert count >= 13, f"Expected >=13 Kow corrections, got {count}"

    def test_critical_mci_correction_values(self, db):
        """Verify key MCI correction values are stored correctly."""
        cursor = db.execute(
            "SELECT fragment_name, correction_value "
            "FROM fragment_corrections "
            "WHERE LOWER(method) LIKE '%mci%'"
        )
        corrections = {}
        for name, val in cursor.fetchall():
            corrections[
                name.lower().replace(' ', '_').replace('-', '_')
            ] = val

        checks = [
            ("aliphatic_alcohol", -1.3179, 0.02),
            ("organic_acid", -1.6249, 0.02),
            ("polychloro_aromatic", 0.3438, 0.02),
        ]
        for frag, expected, tol in checks:
            assert frag in corrections, \
                f"MCI correction '{frag}' not found. " \
                f"Available: {list(corrections.keys())}"
            assert abs(corrections[frag] - expected) < tol, \
                f"MCI '{frag}': {corrections[frag]}, expected {expected}"

    def test_critical_kow_correction_values(self, db):
        """Verify key Kow correction values are stored correctly."""
        cursor = db.execute(
            "SELECT fragment_name, correction_value "
            "FROM fragment_corrections "
            "WHERE LOWER(method) LIKE '%kow%'"
        )
        corrections = {}
        for name, val in cursor.fetchall():
            corrections[
                name.lower().replace(' ', '_').replace('-', '_')
            ] = val

        checks = [
            ("aliphatic_alcohol", -0.4114, 0.02),
            ("organic_acid", -0.7694, 0.02),
            ("polychloro_aromatic", 0.1444, 0.02),
        ]
        for frag, expected, tol in checks:
            assert frag in corrections, \
                f"Kow correction '{frag}' not found. " \
                f"Available: {list(corrections.keys())}"
            assert abs(corrections[frag] - expected) < tol, \
                f"Kow '{frag}': {corrections[frag]}, expected {expected}"


# ============================================================
# SQLite-JSON consistency
# ============================================================

class TestSQLiteConsistency:
    def test_compound_results_match_json(self, db, chemical_results):
        """SQLite compound_results values must match JSON output."""
        rows = db.execute(
            "SELECT cas, koc_mci_log, koc_kow_log, bcf_log "
            "FROM compound_results"
        ).fetchall()
        assert len(rows) == 29, f"Expected 29 rows, got {len(rows)}"
        for cas, mci_log, kow_log, bcf_log in rows:
            assert cas in chemical_results, \
                f"CAS {cas} in SQLite but not JSON"
            jr = chemical_results[cas]
            assert abs(mci_log - jr["koc_mci_log"]) < 0.001, \
                f"{cas}: SQLite mci_log={mci_log} vs JSON " \
                f"{jr['koc_mci_log']}"
            assert abs(kow_log - jr["koc_kow_log"]) < 0.001, \
                f"{cas}: SQLite kow_log={kow_log} vs JSON " \
                f"{jr['koc_kow_log']}"
            assert abs(bcf_log - jr["bcf_log"]) < 0.01, \
                f"{cas}: SQLite bcf_log={bcf_log} vs JSON " \
                f"{jr['bcf_log']}"

    def test_sqlite_spot_check_benzene(self, db):
        """Spot-check benzene values directly from SQLite."""
        row = db.execute(
            "SELECT koc_mci_log, koc_kow_log, bcf_log "
            "FROM compound_results WHERE cas='71-43-2'"
        ).fetchone()
        assert row is not None, "Benzene not found in compound_results"
        assert abs(row[0] - 2.1637) < 0.015
        assert abs(row[1] - 1.8482) < 0.015
        assert abs(row[2] - 1.07) < 0.05

    def test_sqlite_spot_check_atrazine(self, db):
        """Spot-check atrazine (multi-correction compound) from SQLite."""
        row = db.execute(
            "SELECT koc_mci_log, koc_kow_log "
            "FROM compound_results WHERE cas='1912-24-9'"
        ).fetchone()
        assert row is not None, "Atrazine not found in compound_results"
        assert abs(row[0] - 2.3512) < 0.015
        assert abs(row[1] - 2.1581) < 0.015


# ============================================================
# MCI-based Koc tests (non-polar, no corrections)
# ============================================================

class TestKocMciNonPolar:
    @pytest.mark.parametrize("cas,expected_log", [
        ("71-43-2", 2.1637),
        ("108-88-3", 2.3690),
        ("71-55-6", 1.6424),
        ("67-66-3", 1.5027),
        ("56-23-5", 1.6424),
        ("91-20-3", 3.1887),
        ("85-01-8", 4.2226),
        ("129-00-0", 4.7351),
        ("75-09-2", 1.3370),
    ])
    def test_koc_mci_log(self, chemical_results, cas, expected_log):
        actual = chemical_results[cas]["koc_mci_log"]
        assert abs(actual - expected_log) < 0.015, \
            f"{cas}: koc_mci_log={actual}, expected={expected_log}"


# ============================================================
# Kow-based Koc tests (non-polar equation)
# ============================================================

class TestKocKowNonPolar:
    @pytest.mark.parametrize("cas,expected_log", [
        ("71-43-2", 1.8482),
        ("108-88-3", 2.3690),
        ("67-66-3", 1.7094),
        ("56-23-5", 2.4558),
        ("91-20-3", 2.8637),
        ("85-01-8", 3.8704),
        ("129-00-0", 4.2350),
    ])
    def test_koc_kow_log(self, chemical_results, cas, expected_log):
        actual = chemical_results[cas]["koc_kow_log"]
        assert abs(actual - expected_log) < 0.015, \
            f"{cas}: koc_kow_log={actual}, expected={expected_log}"


# ============================================================
# Fragment correction tests (MCI method)
# ============================================================

class TestFragmentCorrectionsMCI:
    @pytest.mark.parametrize("cas,expected_log,desc", [
        ("64-17-5", 0.0191, "ethanol: aliphatic_alcohol"),
        ("75-05-8", 0.6693, "acetonitrile: nitrile"),
        ("67-64-1", 0.3737, "acetone: ketone"),
        ("62-53-3", 1.8465, "aniline: n_aromatic_ring"),
        ("110-86-1", 1.8557, "pyridine: pyridine"),
        ("98-95-3", 2.3549, "nitrobenzene: nitro"),
        ("100-66-3", 1.9704, "anisole: ether_aromatic"),
        ("93-58-3", 1.8273, "methyl benzoate: ester"),
        ("98-86-2", 1.7147, "acetophenone: ketone"),
    ])
    def test_single_correction(self, chemical_results, cas, expected_log, desc):
        actual = chemical_results[cas]["koc_mci_log"]
        assert abs(actual - expected_log) < 0.015, \
            f"{desc}: koc_mci_log={actual}, expected={expected_log}"

    def test_atrazine_multi_correction(self, chemical_results):
        """Atrazine: 3 correction types with per-occurrence semantics."""
        actual = chemical_results["1912-24-9"]["koc_mci_log"]
        expected = 2.3512
        assert abs(actual - expected) < 0.015, \
            f"Atrazine MCI: {actual} vs {expected}"

    def test_2_4_d_compound_correction(self, chemical_results):
        """2,4-D: multiple different fragment corrections."""
        actual = chemical_results["94-75-7"]["koc_mci_log"]
        expected = 1.4717
        assert abs(actual - expected) < 0.015, \
            f"2,4-D MCI: {actual} vs {expected}"

    def test_pentachlorophenol_corrections(self, chemical_results):
        actual = chemical_results["87-86-5"]["koc_mci_log"]
        expected = 3.6954
        assert abs(actual - expected) < 0.015, \
            f"PCP MCI: {actual} vs {expected}"

    def test_hexachlorobenzene_correction(self, chemical_results):
        actual = chemical_results["118-74-1"]["koc_mci_log"]
        expected = 3.7920
        assert abs(actual - expected) < 0.015, \
            f"HCB MCI: {actual} vs {expected}"


# ============================================================
# Fragment correction tests (Kow method)
# ============================================================

class TestFragmentCorrectionsKow:
    def test_atrazine_kow_corrections(self, chemical_results):
        actual = chemical_results["1912-24-9"]["koc_kow_log"]
        expected = 2.1581
        assert abs(actual - expected) < 0.015, \
            f"Atrazine Kow: {actual} vs {expected}"

    def test_2_4_d_kow_corrections(self, chemical_results):
        actual = chemical_results["94-75-7"]["koc_kow_log"]
        expected = 1.7659
        assert abs(actual - expected) < 0.015, \
            f"2,4-D Kow: {actual} vs {expected}"

    def test_pentachlorophenol_kow(self, chemical_results):
        actual = chemical_results["87-86-5"]["koc_kow_log"]
        expected = 4.0684
        assert abs(actual - expected) < 0.015, \
            f"PCP Kow: {actual} vs {expected}"

    def test_hexachlorobenzene_kow(self, chemical_results):
        actual = chemical_results["118-74-1"]["koc_kow_log"]
        expected = 4.2389
        assert abs(actual - expected) < 0.015, \
            f"HCB Kow: {actual} vs {expected}"


# ============================================================
# Equation branching tests
# ============================================================

class TestEquationBranching:
    def test_nonpolar_kow_value(self, chemical_results):
        """Benzene (non-polar, no functional groups) uses nonpolar eq."""
        actual = chemical_results["71-43-2"]["koc_kow_log"]
        assert abs(actual - 1.8482) < 0.015

    def test_polar_acid_kow_value(self, chemical_results):
        """Acetic acid (organic acid) uses polar/acid equation."""
        actual = chemical_results["64-19-7"]["koc_kow_log"]
        assert abs(actual - 0.0617) < 0.015

    def test_polar_corrected_kow_value(self, chemical_results):
        """Aniline (has functional groups) uses polar equation."""
        actual = chemical_results["62-53-3"]["koc_kow_log"]
        assert abs(actual - 1.4013) < 0.015


# ============================================================
# Edge case: over-correction clamping
# ============================================================

class TestEdgeCases:
    def test_acetic_acid_mci_clamp(self, chemical_results):
        """Acetic acid MCI: negative after correction, clamp to 0.0."""
        actual = chemical_results["64-19-7"]["koc_mci_log"]
        assert actual == pytest.approx(0.0, abs=0.001), \
            f"Acetic acid should be clamped to 0.0, got {actual}"

    def test_acetic_acid_koc_mci_value(self, chemical_results):
        """10^0.0 = 1.0"""
        actual = chemical_results["64-19-7"]["koc_mci"]
        assert actual == pytest.approx(1.0, abs=0.1)


# ============================================================
# BCF regression tests
# ============================================================

class TestBCF:
    @pytest.mark.parametrize("cas,expected_log", [
        ("71-43-2", 1.07),
        ("108-88-3", 1.47),
        ("67-66-3", 0.97),
        ("91-20-3", 1.84),
        ("129-00-0", 2.89),
        ("87-86-5", 3.05),
    ])
    def test_standard_bcf(self, chemical_results, cas, expected_log):
        actual = chemical_results[cas]["bcf_log"]
        assert abs(actual - expected_log) < 0.05, \
            f"{cas}: bcf_log={actual}, expected={expected_log}"

    def test_ionic_bcf(self, chemical_results):
        """Ionic compound uses fixed BCF value."""
        actual = chemical_results["94-75-7"]["bcf_log"]
        assert actual == pytest.approx(0.50, abs=0.01), \
            f"2,4-D ionic BCF: {actual} vs 0.50"

    def test_bcf_linear_value(self, chemical_results):
        actual = chemical_results["71-43-2"]["bcf"]
        expected = round(10 ** 1.07, 2)
        assert abs(actual - expected) < 0.5


# ============================================================
# Residual and comparison tests
# ============================================================

class TestResiduals:
    def test_residual_with_data(self, chemical_results):
        rec = chemical_results["71-43-2"]
        assert rec["koc_mci_residual"] is not None
        expected_mci_resid = rec["koc_mci_log"] - 1.75
        assert abs(rec["koc_mci_residual"] - expected_mci_resid) < 0.02

    def test_residual_without_data(self, chemical_results):
        rec = chemical_results["75-05-8"]
        assert rec["koc_mci_residual"] is None
        assert rec["koc_kow_residual"] is None
        assert rec["better_method"] is None

    def test_better_method_kow_wins(self, chemical_results):
        rec = chemical_results["91-20-3"]
        assert rec["better_method"] == "kow"

    def test_better_method_mci_wins(self, chemical_results):
        rec = chemical_results["129-00-0"]
        assert rec["better_method"] == "mci"


# ============================================================
# Summary statistics tests
# ============================================================

class TestSummary:
    def test_summary_exists(self, summary):
        assert summary["cas"] == "SUMMARY"

    def test_rmse_positive(self, summary):
        assert summary["mci_rmse"] > 0
        assert summary["kow_rmse"] > 0

    def test_wins_add_up(self, summary, chemical_results):
        total_with_data = sum(
            1 for r in chemical_results.values()
            if r["better_method"] is not None
        )
        assert summary["mci_wins"] + summary["kow_wins"] == total_with_data

    def test_mean_bcf_log(self, summary, chemical_results):
        bcf_vals = [r["bcf_log"] for r in chemical_results.values()]
        expected = sum(bcf_vals) / len(bcf_vals)
        assert abs(summary["mean_bcf_log"] - expected) < 0.01

    def test_mci_rmse_reasonable(self, summary):
        assert 0.05 < summary["mci_rmse"] < 1.5

    def test_kow_rmse_reasonable(self, summary):
        assert 0.05 < summary["kow_rmse"] < 1.5


# ============================================================
# Linear Koc value tests
# ============================================================

class TestLinearValues:
    @pytest.mark.parametrize("cas,expected_koc_mci", [
        ("71-43-2", 145.8),
        ("108-88-3", 233.9),
        ("67-66-3", 31.82),
    ])
    def test_koc_mci_linear(self, chemical_results, cas, expected_koc_mci):
        actual = chemical_results[cas]["koc_mci"]
        assert abs(actual - expected_koc_mci) / expected_koc_mci < 0.05, \
            f"{cas}: koc_mci={actual}, expected~{expected_koc_mci}"
