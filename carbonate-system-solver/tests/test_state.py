
"""Tests for the carbonate solver debugging and crossover QC pipeline.

Validates:
1. No forbidden imports (PyCO2SYS or other carbonate libraries)
2. Cross-validation against PyCO2SYS reference values for 3 oceanographic conditions
3. Round-robin internal consistency across all 15 input-pair combinations
4. QC database existence, schema, and crossover offset correctness
"""

import sys
import os
import ast
import math
import importlib
import sqlite3
import json
import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FORBIDDEN_IMPORTS = [
    "PyCO2SYS", "pyco2sys", "cbsyst", "csys", "mocsy", "seacarb",
    "CO2SYS", "co2sys",
]


def _check_no_forbidden_imports(filepath):
    """Parse the AST of a Python file to check for forbidden imports."""
    with open(filepath, "r") as f:
        source = f.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for forbidden in FORBIDDEN_IMPORTS:
                    if forbidden.lower() in alias.name.lower():
                        raise AssertionError(
                            f"Forbidden import '{alias.name}' found in {filepath}"
                        )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                for forbidden in FORBIDDEN_IMPORTS:
                    if forbidden.lower() in node.module.lower():
                        raise AssertionError(
                            f"Forbidden import from '{node.module}' found in {filepath}"
                        )


def _get_pyco2sys_ref(par1, par2, par1_type, par2_type,
                      temperature, salinity, pressure,
                      total_silicate=0.0, total_phosphate=0.0):
    """Compute reference values using PyCO2SYS v1.8."""
    import PyCO2SYS as pyco2

    pyco2_type_map = {1: 1, 2: 2, 3: 3, 4: 5, 5: 6, 6: 7}
    p1type = pyco2_type_map[par1_type]
    p2type = pyco2_type_map[par2_type]

    result = pyco2.sys(
        par1=par1, par2=par2,
        par1_type=p1type, par2_type=p2type,
        salinity=salinity,
        temperature=temperature,
        pressure=pressure,
        total_silicate=total_silicate,
        total_phosphate=total_phosphate,
        opt_k_carbonic=10,
        opt_k_bisulfate=1,
        opt_k_fluoride=1,
        opt_pH_scale=1,
        opt_total_borate=1,
        opt_buffers_mode=1,
    )

    def _extract(d, *keys):
        for k in keys:
            if k in d:
                v = d[k]
                if hasattr(v, '__len__') and not isinstance(v, str):
                    return float(v.flat[0]) if hasattr(v, 'flat') else float(v[0])
                return float(v)
        raise KeyError(f"None of {keys} found in PyCO2SYS result.")

    ref = {}
    ref["pH"] = _extract(result, "pH_total", "pH")
    ref["fCO2"] = _extract(result, "fCO2")
    ref["pCO2"] = _extract(result, "pCO2")
    ref["CO3"] = _extract(result, "carbonate", "CO3")
    ref["HCO3"] = _extract(result, "bicarbonate", "HCO3")
    ref["CO2aq"] = _extract(result, "aqueous_CO2", "CO2")
    ref["OmegaCa"] = _extract(result, "saturation_calcite", "OmegaCa")
    ref["OmegaAr"] = _extract(result, "saturation_aragonite", "OmegaAr")
    ref["Revelle"] = _extract(result, "revelle_factor", "Revelle")
    ref["TA"] = _extract(result, "alkalinity", "TAlk", "TA")
    ref["DIC"] = _extract(result, "dic", "TCO2", "TC")
    return ref


# ---------------------------------------------------------------------------
# Test conditions
# ---------------------------------------------------------------------------

TEST_CONDITIONS = [
    {
        "name": "tropical_surface",
        "par1": 2350.0, "par2": 1950.0,
        "par1_type": 1, "par2_type": 2,
        "temperature": 28.0, "salinity": 36.0, "pressure": 0.0,
        "total_silicate": 0.0, "total_phosphate": 0.0,
    },
    {
        "name": "temperate_surface",
        "par1": 2300.0, "par2": 2050.0,
        "par1_type": 1, "par2_type": 2,
        "temperature": 15.0, "salinity": 34.5, "pressure": 0.0,
        "total_silicate": 5.0, "total_phosphate": 0.5,
    },
    {
        "name": "deep_ocean",
        "par1": 2400.0, "par2": 2250.0,
        "par1_type": 1, "par2_type": 2,
        "temperature": 2.0, "salinity": 34.7, "pressure": 4000.0,
        "total_silicate": 50.0, "total_phosphate": 2.0,
    },
]

ATOL = {
    "pH": 5e-4,
    "OmegaCa": 0.02,
    "OmegaAr": 0.02,
    "Revelle": 0.15,
}
RTOL = {
    "fCO2": 2e-3,
    "pCO2": 2e-3,
    "CO3": 2e-3,
    "HCO3": 2e-3,
    "CO2aq": 2e-3,
    "TA": 1e-6,
    "DIC": 1e-6,
}

REQUIRED_KEYS = ["TA", "DIC", "pH", "fCO2", "pCO2", "CO3", "HCO3",
                 "CO2aq", "OmegaCa", "OmegaAr", "Revelle"]


# ---------------------------------------------------------------------------
# Solver Tests
# ---------------------------------------------------------------------------

class TestImportCheck:
    """Verify that the solver does not import forbidden packages."""

    def test_no_forbidden_imports(self):
        solver_path = "/app/carbonate_solver.py"
        assert os.path.isfile(solver_path), (
            f"Solver file not found at {solver_path}"
        )
        _check_no_forbidden_imports(solver_path)
        app_dir = "/app"
        for fn in os.listdir(app_dir):
            if fn.endswith(".py") and fn != "carbonate_solver.py":
                fpath = os.path.join(app_dir, fn)
                # Only check files that might be imported by the solver
                with open(fpath) as f:
                    content = f.read()
                if "def solve" in content or "carbonate" in content.lower():
                    _check_no_forbidden_imports(fpath)


class TestSolverInterface:
    """Verify that the solver has the correct interface."""

    def test_module_importable(self):
        sys.path.insert(0, "/app")
        import carbonate_solver
        importlib.reload(carbonate_solver)
        assert hasattr(carbonate_solver, "solve"), (
            "carbonate_solver module must have a 'solve' function"
        )

    def test_return_structure(self):
        sys.path.insert(0, "/app")
        import carbonate_solver
        importlib.reload(carbonate_solver)
        result = carbonate_solver.solve(
            2300.0, 2050.0, 1, 2, 25.0, 35.0, 0.0
        )
        assert isinstance(result, dict), "solve() must return a dict"
        for key in REQUIRED_KEYS:
            assert key in result, f"Missing key '{key}' in result dict"
            assert isinstance(result[key], (int, float)), (
                f"Value for '{key}' must be a number, got {type(result[key])}"
            )


class TestCrossValidation:
    """Cross-validate solver output against PyCO2SYS reference values."""

    @pytest.fixture(autouse=True)
    def setup_solver(self):
        sys.path.insert(0, "/app")
        import carbonate_solver
        importlib.reload(carbonate_solver)
        self.solve = carbonate_solver.solve

    @pytest.mark.parametrize("cond", TEST_CONDITIONS,
                             ids=[c["name"] for c in TEST_CONDITIONS])
    def test_cross_validation(self, cond):
        result = self.solve(
            cond["par1"], cond["par2"],
            cond["par1_type"], cond["par2_type"],
            cond["temperature"], cond["salinity"], cond["pressure"],
            cond["total_silicate"], cond["total_phosphate"],
        )
        ref = _get_pyco2sys_ref(
            cond["par1"], cond["par2"],
            cond["par1_type"], cond["par2_type"],
            cond["temperature"], cond["salinity"], cond["pressure"],
            cond["total_silicate"], cond["total_phosphate"],
        )
        for key in REQUIRED_KEYS:
            rv = result[key]
            rr = ref[key]
            if key in ATOL:
                assert abs(rv - rr) <= ATOL[key], (
                    f"[{cond['name']}] {key}: solver={rv:.8f}, "
                    f"ref={rr:.8f}, diff={abs(rv-rr):.2e}, "
                    f"atol={ATOL[key]}"
                )
            elif key in RTOL:
                if abs(rr) > 1e-15:
                    rel = abs(rv - rr) / abs(rr)
                    assert rel <= RTOL[key], (
                        f"[{cond['name']}] {key}: solver={rv:.8f}, "
                        f"ref={rr:.8f}, rel_diff={rel:.2e}, "
                        f"rtol={RTOL[key]}"
                    )


class TestRoundRobin:
    """Round-robin internal consistency test."""

    @pytest.fixture(autouse=True)
    def setup_solver(self):
        sys.path.insert(0, "/app")
        import carbonate_solver
        importlib.reload(carbonate_solver)
        self.solve = carbonate_solver.solve

    def _roundrobin_one_condition(self, temperature, salinity, pressure,
                                  total_silicate=0.0, total_phosphate=0.0):
        base = self.solve(
            2300.0, 2050.0, 1, 2,
            temperature, salinity, pressure,
            total_silicate, total_phosphate,
        )
        par_key = {1: "TA", 2: "DIC", 3: "pH", 4: "fCO2", 5: "CO3", 6: "HCO3"}
        pairs = []
        for i in range(1, 7):
            for j in range(i + 1, 7):
                pairs.append((i, j))
        max_diffs = {k: 0.0 for k in REQUIRED_KEYS}
        for pt1, pt2 in pairs:
            p1_val = base[par_key[pt1]]
            p2_val = base[par_key[pt2]]
            try:
                result = self.solve(
                    p1_val, p2_val, pt1, pt2,
                    temperature, salinity, pressure,
                    total_silicate, total_phosphate,
                )
            except Exception as e:
                raise AssertionError(
                    f"Solver failed for pair ({pt1},{pt2}): {e}"
                )
            for key in REQUIRED_KEYS:
                ref_val = base[key]
                sol_val = result[key]
                if abs(ref_val) > 1e-10:
                    rel_diff = abs(sol_val - ref_val) / abs(ref_val)
                    max_diffs[key] = max(max_diffs[key], rel_diff)
        return max_diffs

    def test_roundrobin_surface(self):
        diffs = self._roundrobin_one_condition(
            temperature=22.0, salinity=35.0, pressure=0.0,
            total_silicate=10.0, total_phosphate=1.0,
        )
        rr_tol = 1e-4
        for key, diff in diffs.items():
            assert diff < rr_tol, (
                f"Round-robin surface: {key} max rel diff = {diff:.2e} "
                f"(tolerance {rr_tol})"
            )

    def test_roundrobin_deep(self):
        diffs = self._roundrobin_one_condition(
            temperature=2.0, salinity=34.7, pressure=3000.0,
            total_silicate=40.0, total_phosphate=2.0,
        )
        rr_tol = 1e-4
        for key, diff in diffs.items():
            assert diff < rr_tol, (
                f"Round-robin deep: {key} max rel diff = {diff:.2e} "
                f"(tolerance {rr_tol})"
            )


class TestEdgeCases:
    """Test solver behavior at edge conditions."""

    @pytest.fixture(autouse=True)
    def setup_solver(self):
        sys.path.insert(0, "/app")
        import carbonate_solver
        importlib.reload(carbonate_solver)
        self.solve = carbonate_solver.solve

    def test_zero_nutrients(self):
        result = self.solve(2300.0, 2050.0, 1, 2, 25.0, 35.0, 0.0, 0.0, 0.0)
        assert 7.0 < result["pH"] < 9.0
        assert result["fCO2"] > 0
        assert result["OmegaCa"] > 0

    def test_high_pressure(self):
        result = self.solve(2400.0, 2300.0, 1, 2, 1.5, 34.8, 5000.0, 80.0, 2.5)
        assert 7.0 < result["pH"] < 9.0
        assert result["fCO2"] > 0

    def test_ph_fco2_pair(self):
        result = self.solve(8.1, 350.0, 3, 4, 25.0, 35.0, 0.0)
        assert result["TA"] > 0
        assert result["DIC"] > 0
        assert result["CO3"] > 0


# ---------------------------------------------------------------------------
# QC Database Tests
# ---------------------------------------------------------------------------

class TestQCDatabase:
    """Verify the crossover QC database structure and content."""

    DB_PATH = "/app/qc_results.db"

    def test_database_exists(self):
        assert os.path.isfile(self.DB_PATH), (
            f"QC results database not found at {self.DB_PATH}"
        )

    def test_tables_exist(self):
        conn = sqlite3.connect(self.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        conn.close()
        for t in ["cruise_computations", "crossover_offsets", "adjustments"]:
            assert t in tables, f"Missing table '{t}' in QC database"

    def test_cruise_computations_row_count(self):
        """Verify correct number of rows (only flag-2 data included)."""
        conn = sqlite3.connect(self.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM cruise_computations")
        count = cur.fetchone()[0]
        conn.close()
        # Expected: 48 rows (10+10+10+9+9 after filtering bad-flag rows)
        assert count == 48, (
            f"Expected 48 rows in cruise_computations (flag-2 only), got {count}"
        )

    def test_cruise_computations_all_cruises(self):
        """All 5 cruises must be represented."""
        conn = sqlite3.connect(self.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT cruise_id FROM cruise_computations ORDER BY cruise_id")
        cruises = [row[0] for row in cur.fetchall()]
        conn.close()
        expected = ["cruise_001", "cruise_002", "cruise_003", "cruise_004", "cruise_005"]
        assert cruises == expected, (
            f"Expected cruises {expected}, got {cruises}"
        )

    def test_cruise_computations_columns(self):
        """Verify all required columns exist."""
        conn = sqlite3.connect(self.DB_PATH)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(cruise_computations)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        required = {"cruise_id", "station", "depth", "temperature", "salinity",
                     "pressure", "TA_measured", "DIC_measured", "pH_computed",
                     "fCO2_computed", "pCO2_computed", "CO3_computed",
                     "HCO3_computed", "OmegaCa", "OmegaAr"}
        missing = required - cols
        assert not missing, f"Missing columns in cruise_computations: {missing}"

    def test_cruise_computations_physical_validity(self):
        """Computed values must be physically reasonable."""
        conn = sqlite3.connect(self.DB_PATH)
        cur = conn.cursor()
        cur.execute("""SELECT pH_computed, fCO2_computed, CO3_computed,
                       OmegaCa, OmegaAr FROM cruise_computations""")
        rows = cur.fetchall()
        conn.close()
        for i, (ph, fco2, co3, oca, oar) in enumerate(rows):
            assert 7.0 < ph < 8.8, f"Row {i}: pH={ph} out of range"
            assert 50 < fco2 < 5000, f"Row {i}: fCO2={fco2} out of range"
            assert 10 < co3 < 400, f"Row {i}: CO3={co3} out of range"
            assert 0.1 < oca < 8.0, f"Row {i}: OmegaCa={oca} out of range"
            assert 0.05 < oar < 6.0, f"Row {i}: OmegaAr={oar} out of range"

    def test_crossover_offsets_count(self):
        """Should have 14 offset entries (7 variables x 2 crossover pairs)."""
        conn = sqlite3.connect(self.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM crossover_offsets")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 14, (
            f"Expected 14 rows in crossover_offsets, got {count}"
        )

    def test_crossover_offsets_pairs(self):
        """Both crossover pairs must be represented."""
        conn = sqlite3.connect(self.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT cruise_pair FROM crossover_offsets")
        pairs = {row[0] for row in cur.fetchall()}
        conn.close()
        assert "cruise_001/cruise_004" in pairs, (
            "Missing crossover pair cruise_001/cruise_004"
        )
        assert "cruise_002/cruise_005" in pairs, (
            "Missing crossover pair cruise_002/cruise_005"
        )

    def test_crossover_n_samples(self):
        """Each crossover should have 3 deep samples."""
        conn = sqlite3.connect(self.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT cruise_pair, variable, n_samples FROM crossover_offsets")
        rows = cur.fetchall()
        conn.close()
        for pair, var, n in rows:
            assert n == 3, (
                f"Crossover {pair}/{var}: expected 3 samples, got {n}"
            )

    def test_crossover_dic_offset_southern_ocean(self):
        """cruise_001/cruise_004 DIC offset should be approximately -5.0."""
        conn = sqlite3.connect(self.DB_PATH)
        cur = conn.cursor()
        cur.execute("""SELECT mean_offset FROM crossover_offsets
                       WHERE cruise_pair='cruise_001/cruise_004'
                       AND variable='DIC_measured'""")
        row = cur.fetchone()
        conn.close()
        assert row is not None, "Missing DIC_measured offset for cruise_001/cruise_004"
        offset = row[0]
        assert abs(offset - (-5.0)) < 1.0, (
            f"DIC offset for cruise_001/cruise_004 = {offset:.2f}, expected ~-5.0"
        )

    def test_crossover_ta_offset_north_atlantic(self):
        """cruise_002/cruise_005 TA offset should be approximately +3.0."""
        conn = sqlite3.connect(self.DB_PATH)
        cur = conn.cursor()
        cur.execute("""SELECT mean_offset FROM crossover_offsets
                       WHERE cruise_pair='cruise_002/cruise_005'
                       AND variable='TA_measured'""")
        row = cur.fetchone()
        conn.close()
        assert row is not None, "Missing TA_measured offset for cruise_002/cruise_005"
        offset = row[0]
        assert abs(offset - 3.0) < 1.0, (
            f"TA offset for cruise_002/cruise_005 = {offset:.2f}, expected ~+3.0"
        )

    def test_adjustments_table(self):
        """Adjustments table must have entries for the second cruise in each pair."""
        conn = sqlite3.connect(self.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT cruise_id, variable, adjustment FROM adjustments")
        rows = cur.fetchall()
        conn.close()
        adj_dict = {}
        for cid, var, adj in rows:
            adj_dict[(cid, var)] = adj

        # cruise_004 should have DIC_measured adjustment ≈ -5.0
        key_dic = ("cruise_004", "DIC_measured")
        assert key_dic in adj_dict, (
            f"Missing adjustment for cruise_004/DIC_measured"
        )
        assert abs(adj_dict[key_dic] - (-5.0)) < 1.0, (
            f"cruise_004 DIC adjustment = {adj_dict[key_dic]:.2f}, expected ~-5.0"
        )

        # cruise_005 should have TA_measured adjustment ≈ +3.0
        key_ta = ("cruise_005", "TA_measured")
        assert key_ta in adj_dict, (
            f"Missing adjustment for cruise_005/TA_measured"
        )
        assert abs(adj_dict[key_ta] - 3.0) < 1.0, (
            f"cruise_005 TA adjustment = {adj_dict[key_ta]:.2f}, expected ~+3.0"
        )

    def test_adjustments_count(self):
        """Should have 14 adjustment entries (7 variables x 2 adjusted cruises)."""
        conn = sqlite3.connect(self.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM adjustments")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 14, (
            f"Expected 14 rows in adjustments, got {count}"
        )

    def test_bad_flag_data_excluded(self):
        """Verify that bad-flag data is properly excluded from computations."""
        conn = sqlite3.connect(self.DB_PATH)
        cur = conn.cursor()
        # cruise_004 D2 at depth 100 has DIC_FLAG=4 - should be excluded
        cur.execute("""SELECT COUNT(*) FROM cruise_computations
                       WHERE cruise_id='cruise_004' AND station='D2'
                       AND depth BETWEEN 95 AND 105""")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 0, (
            "Bad-flag row (cruise_004/D2/100m) should be excluded from computations"
        )

    def test_computed_values_match_solver(self):
        """Spot-check: recompute one row and verify it matches the database."""
        sys.path.insert(0, "/app")
        import carbonate_solver
        importlib.reload(carbonate_solver)

        conn = sqlite3.connect(self.DB_PATH)
        cur = conn.cursor()
        # Get the cruise_003 C1 surface row
        cur.execute("""SELECT temperature, salinity, pressure, TA_measured,
                       DIC_measured, pH_computed, fCO2_computed
                       FROM cruise_computations
                       WHERE cruise_id='cruise_003' AND station='C1'
                       AND depth BETWEEN 5 AND 15""")
        row = cur.fetchone()
        conn.close()
        assert row is not None, "Missing cruise_003/C1/10m row"

        T, S, P, TA, DIC, pH_db, fCO2_db = row
        # Recompute using the solver with the cruise data's silicate and phosphate
        # (cruise_003 C1 10m: Si=2.0, PO4=0.10)
        result = carbonate_solver.solve(TA, DIC, 1, 2, T, S, P, 2.0, 0.10)
        assert abs(result["pH"] - pH_db) < 1e-6, (
            f"pH mismatch: solver={result['pH']:.8f}, db={pH_db:.8f}"
        )
        assert abs(result["fCO2"] - fCO2_db) < 0.01, (
            f"fCO2 mismatch: solver={result['fCO2']:.4f}, db={fCO2_db:.4f}"
        )
