"""
Tests for the electrolyte solution analysis pipeline.

Validates the engine API, Makefile pipeline, SQLite integration,
charge-balance validation, and activity coefficient accuracy against
CRC Handbook experimental data.

"""

import json
import os
import sqlite3
import sys

import numpy as np
import pytest

sys.path.insert(0, "/app")

from electrolyte_engine import (
    compute_activity_coefficient,
    compute_ionic_strength,
    compute_osmotic_coefficient,
    compute_osmotic_pressure,
    compute_water_activity,
)


# ---------------------------------------------------------------------------
# Makefile and pipeline infrastructure tests
# ---------------------------------------------------------------------------


class TestMakefile:
    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile")

    def test_makefile_has_init_db(self):
        content = open("/app/Makefile").read()
        assert "init-db" in content

    def test_makefile_has_run(self):
        content = open("/app/Makefile").read()
        assert "run" in content

    def test_makefile_has_validate(self):
        content = open("/app/Makefile").read()
        assert "validate" in content

    def test_makefile_has_all(self):
        content = open("/app/Makefile").read()
        assert "all" in content

    def test_parameters_db_exists(self):
        """init-db target should have created parameters.db."""
        assert os.path.isfile("/app/parameters.db")

    def test_parameters_db_constants_table(self):
        conn = sqlite3.connect("/app/parameters.db")
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='constants'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_parameters_db_salt_parameters_table(self):
        conn = sqlite3.connect("/app/parameters.db")
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='salt_parameters'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_parameters_db_has_salt_data(self):
        conn = sqlite3.connect("/app/parameters.db")
        count = conn.execute("SELECT COUNT(*) FROM salt_parameters").fetchone()[0]
        conn.close()
        assert count >= 8


class TestResultsDB:
    def test_results_db_exists(self):
        assert os.path.isfile("/app/results.db")

    def test_results_db_has_results_table(self):
        conn = sqlite3.connect("/app/results.db")
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='results'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_results_db_schema(self):
        conn = sqlite3.connect("/app/results.db")
        cursor = conn.execute("PRAGMA table_info(results)")
        columns = {row[1] for row in cursor}
        conn.close()
        required = {
            "solution_id",
            "ionic_strength",
            "activity_coefficient",
            "osmotic_coefficient",
            "water_activity",
            "osmotic_pressure_bar",
        }
        assert required.issubset(columns), f"Missing columns: {required - columns}"

    def test_results_db_row_count(self):
        conn = sqlite3.connect("/app/results.db")
        count = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        conn.close()
        assert count >= 5

    def test_results_db_solution_ids(self):
        conn = sqlite3.connect("/app/results.db")
        ids = {
            row[0]
            for row in conn.execute("SELECT solution_id FROM results").fetchall()
        }
        conn.close()
        expected = {"nacl_05", "nacl_20", "bacl2_01", "k2so4_01", "mixed_nacl_kcl"}
        assert expected.issubset(ids), f"Missing solution IDs: {expected - ids}"

    def test_results_db_consistency_with_json(self):
        """results.db and results.json must contain matching data."""
        with open("/app/results.json") as f:
            json_results = json.load(f)

        conn = sqlite3.connect("/app/results.db")
        conn.row_factory = sqlite3.Row
        db_results = conn.execute(
            "SELECT * FROM results ORDER BY solution_id"
        ).fetchall()
        conn.close()

        json_by_id = {s["id"]: s for s in json_results["solutions"]}

        for row in db_results:
            sid = row["solution_id"]
            assert sid in json_by_id, f"Solution {sid} in DB but not in JSON"
            j = json_by_id[sid]
            assert np.isclose(
                row["ionic_strength"], j["ionic_strength"], rtol=0.01
            ), f"{sid}: ionic_strength mismatch"
            assert np.isclose(
                row["activity_coefficient"], j["activity_coefficient"], rtol=0.01
            ), f"{sid}: activity_coefficient mismatch"
            assert np.isclose(
                row["osmotic_coefficient"], j["osmotic_coefficient"], rtol=0.01
            ), f"{sid}: osmotic_coefficient mismatch"
            assert np.isclose(
                row["water_activity"], j["water_activity"], rtol=0.01
            ), f"{sid}: water_activity mismatch"
            assert np.isclose(
                row["osmotic_pressure_bar"], j["osmotic_pressure_bar"], rtol=0.01
            ), f"{sid}: osmotic_pressure_bar mismatch"

    def test_results_db_values_physical(self):
        conn = sqlite3.connect("/app/results.db")
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM results").fetchall()
        conn.close()
        for row in rows:
            assert row["ionic_strength"] >= 0, f"{row['solution_id']}: negative I"
            assert row["activity_coefficient"] > 0
            assert row["osmotic_coefficient"] > 0
            assert 0 < row["water_activity"] <= 1.0
            assert row["osmotic_pressure_bar"] > 0


# ---------------------------------------------------------------------------
# Charge-balance validation tests
# ---------------------------------------------------------------------------


class TestChargeBalance:
    def test_balanced_accepted(self):
        """Charge-balanced solutions should not raise."""
        comp = {"Na+": 0.5, "Cl-": 0.5}
        compute_ionic_strength(comp)

    def test_slight_imbalance_accepted(self):
        """Small imbalance under 1% should be accepted."""
        comp = {"Na+": 0.500, "Cl-": 0.498}
        compute_ionic_strength(comp)

    def test_large_imbalance_rejected(self):
        """Imbalance > 1% must raise ValueError."""
        comp = {"Na+": 0.5, "Cl-": 0.3}
        with pytest.raises(ValueError):
            compute_ionic_strength(comp)

    def test_missing_anion_rejected(self):
        """Pure cation solution must raise ValueError."""
        comp = {"Na+": 0.5}
        with pytest.raises(ValueError):
            compute_ionic_strength(comp)

    def test_missing_cation_rejected(self):
        """Pure anion solution must raise ValueError."""
        comp = {"Cl-": 0.5}
        with pytest.raises(ValueError):
            compute_ionic_strength(comp)

    def test_empty_composition_accepted(self):
        """Empty solution is trivially balanced."""
        result = compute_ionic_strength({})
        assert result == 0.0 or np.isclose(result, 0.0)

    def test_multivalent_imbalance_rejected(self):
        """2:1 electrolyte with wrong stoichiometry must raise ValueError."""
        comp = {"Ba+2": 0.5, "Cl-": 0.5}  # should be 1.0 Cl- for charge balance
        with pytest.raises(ValueError):
            compute_ionic_strength(comp)


# ---------------------------------------------------------------------------
# Ionic strength tests
# ---------------------------------------------------------------------------


class TestIonicStrength:
    def test_nacl(self):
        """1:1 electrolyte NaCl at 0.5 mol/kg."""
        comp = {"Na+": 0.5, "Cl-": 0.5}
        assert np.isclose(compute_ionic_strength(comp), 0.5, rtol=1e-3)

    def test_bacl2(self):
        """2:1 electrolyte BaCl2 at 0.1 mol/kg -> I = 0.3."""
        comp = {"Ba+2": 0.1, "Cl-": 0.2}
        assert np.isclose(compute_ionic_strength(comp), 0.3, rtol=1e-3)

    def test_k2so4(self):
        """1:2 electrolyte K2SO4 at 0.1 mol/kg -> I = 0.3."""
        comp = {"K+": 0.2, "SO4-2": 0.1}
        assert np.isclose(compute_ionic_strength(comp), 0.3, rtol=1e-3)

    def test_mixed(self):
        """Mixed NaCl+KCl."""
        comp = {"Na+": 0.48, "K+": 0.01, "Cl-": 0.49}
        assert np.isclose(compute_ionic_strength(comp), 0.49, rtol=1e-3)


# ---------------------------------------------------------------------------
# Activity coefficient tests against CRC Handbook data (5% tolerance)
# ---------------------------------------------------------------------------


class TestActivityCoefficientNaCl:
    """NaCl mean activity coefficients vs CRC Handbook (25 degC)."""

    @pytest.mark.parametrize(
        "m, gamma_crc",
        [
            (0.1, 0.778),
            (0.5, 0.681),
            (1.0, 0.657),
            (2.0, 0.669),
            (5.0, 0.873),
        ],
    )
    def test_nacl(self, m, gamma_crc):
        comp = {"Na+": m, "Cl-": m}
        gamma = compute_activity_coefficient(comp, "Na+")
        assert np.isclose(gamma, gamma_crc, rtol=0.05), (
            f"NaCl at {m} mol/kg: got {gamma:.4f}, expected {gamma_crc}"
        )


class TestActivityCoefficientOther:
    """Other electrolyte activity coefficients vs CRC Handbook."""

    def test_kbr_05(self):
        comp = {"K+": 0.5, "Br-": 0.5}
        gamma = compute_activity_coefficient(comp, "K+")
        assert np.isclose(gamma, 0.658, rtol=0.05)

    def test_kbr_10(self):
        comp = {"K+": 1.0, "Br-": 1.0}
        gamma = compute_activity_coefficient(comp, "K+")
        assert np.isclose(gamma, 0.617, rtol=0.05)

    def test_licl_05(self):
        comp = {"Li+": 0.5, "Cl-": 0.5}
        gamma = compute_activity_coefficient(comp, "Li+")
        assert np.isclose(gamma, 0.739, rtol=0.05)

    def test_licl_10(self):
        comp = {"Li+": 1.0, "Cl-": 1.0}
        gamma = compute_activity_coefficient(comp, "Li+")
        assert np.isclose(gamma, 0.775, rtol=0.05)

    def test_hcl_10(self):
        comp = {"H+": 1.0, "Cl-": 1.0}
        gamma = compute_activity_coefficient(comp, "H+")
        assert np.isclose(gamma, 0.811, rtol=0.05)

    def test_rbcl_05(self):
        comp = {"Rb+": 0.5, "Cl-": 0.5}
        gamma = compute_activity_coefficient(comp, "Rb+")
        assert np.isclose(gamma, 0.633, rtol=0.05)


class TestActivityCoefficient21:
    """2:1 and 1:2 electrolyte activity coefficients."""

    def test_bacl2_01(self):
        comp = {"Ba+2": 0.1, "Cl-": 0.2}
        gamma = compute_activity_coefficient(comp, "Ba+2")
        assert np.isclose(gamma, 0.492, rtol=0.05)

    def test_bacl2_05(self):
        comp = {"Ba+2": 0.5, "Cl-": 1.0}
        gamma = compute_activity_coefficient(comp, "Ba+2")
        assert np.isclose(gamma, 0.391, rtol=0.05)

    def test_k2so4_01(self):
        comp = {"K+": 0.2, "SO4-2": 0.1}
        gamma = compute_activity_coefficient(comp, "K+")
        assert np.isclose(gamma, 0.424, rtol=0.05)

    def test_k2so4_005(self):
        comp = {"K+": 0.1, "SO4-2": 0.05}
        gamma = compute_activity_coefficient(comp, "K+")
        assert np.isclose(gamma, 0.511, rtol=0.05)


# ---------------------------------------------------------------------------
# Symmetry test: both ions in a binary salt get same coefficient
# ---------------------------------------------------------------------------


class TestSymmetry:
    def test_nacl_symmetry(self):
        comp = {"Na+": 1.0, "Cl-": 1.0}
        gamma_na = compute_activity_coefficient(comp, "Na+")
        gamma_cl = compute_activity_coefficient(comp, "Cl-")
        assert np.isclose(gamma_na, gamma_cl, rtol=1e-3)

    def test_bacl2_symmetry(self):
        comp = {"Ba+2": 0.1, "Cl-": 0.2}
        gamma_ba = compute_activity_coefficient(comp, "Ba+2")
        gamma_cl = compute_activity_coefficient(comp, "Cl-")
        assert np.isclose(gamma_ba, gamma_cl, rtol=1e-3)


# ---------------------------------------------------------------------------
# Dilute solution behavior
# ---------------------------------------------------------------------------


class TestDiluteBehavior:
    def test_very_dilute_approaches_ideal(self):
        """At very low concentration, activity coefficient should approach 1."""
        comp = {"Na+": 0.001, "Cl-": 0.001}
        gamma = compute_activity_coefficient(comp, "Na+")
        assert 0.95 < gamma < 1.05, f"Very dilute NaCl: gamma={gamma:.4f}"

    def test_dilute_bacl2(self):
        """Dilute 2:1 electrolyte should also approach ideal."""
        comp = {"Ba+2": 0.001, "Cl-": 0.002}
        gamma = compute_activity_coefficient(comp, "Ba+2")
        assert 0.85 < gamma < 1.05, f"Very dilute BaCl2: gamma={gamma:.4f}"


# ---------------------------------------------------------------------------
# Osmotic coefficient tests
# ---------------------------------------------------------------------------


class TestOsmoticCoefficient:
    def test_nacl_05(self):
        """NaCl 0.5 mol/kg: phi ~ 0.921."""
        comp = {"Na+": 0.5, "Cl-": 0.5}
        phi = compute_osmotic_coefficient(comp)
        assert np.isclose(phi, 0.921, rtol=0.05)

    def test_nacl_20(self):
        """NaCl 2.0 mol/kg: phi ~ 0.984."""
        comp = {"Na+": 2.0, "Cl-": 2.0}
        phi = compute_osmotic_coefficient(comp)
        assert np.isclose(phi, 0.984, rtol=0.05)

    def test_positive(self):
        """Osmotic coefficient must be positive."""
        comp = {"Na+": 0.5, "Cl-": 0.5}
        phi = compute_osmotic_coefficient(comp)
        assert phi > 0


# ---------------------------------------------------------------------------
# Water activity tests
# ---------------------------------------------------------------------------


class TestWaterActivity:
    def test_nacl_05(self):
        """NaCl 0.5 mol/kg: a_w ~ 0.984."""
        comp = {"Na+": 0.5, "Cl-": 0.5}
        aw = compute_water_activity(comp)
        assert np.isclose(aw, 0.984, rtol=0.01)

    def test_nacl_20(self):
        """NaCl 2.0 mol/kg: a_w ~ 0.932."""
        comp = {"Na+": 2.0, "Cl-": 2.0}
        aw = compute_water_activity(comp)
        assert np.isclose(aw, 0.932, rtol=0.02)

    def test_bounds(self):
        """Water activity must be in (0, 1]."""
        comp = {"Na+": 0.5, "Cl-": 0.5}
        aw = compute_water_activity(comp)
        assert 0 < aw <= 1.0

    def test_monotonic_decrease(self):
        """Water activity must decrease with increasing concentration."""
        aw_low = compute_water_activity({"Na+": 0.1, "Cl-": 0.1})
        aw_high = compute_water_activity({"Na+": 2.0, "Cl-": 2.0})
        assert aw_low > aw_high


# ---------------------------------------------------------------------------
# Osmotic pressure tests
# ---------------------------------------------------------------------------


class TestOsmoticPressure:
    def test_nacl_05(self):
        """NaCl 0.5 mol/kg: pi ~ 22.8 bar."""
        comp = {"Na+": 0.5, "Cl-": 0.5}
        pi = compute_osmotic_pressure(comp)
        assert np.isclose(pi, 22.8, rtol=0.10)

    def test_nacl_20(self):
        """NaCl 2.0 mol/kg: pi ~ 97.6 bar."""
        comp = {"Na+": 2.0, "Cl-": 2.0}
        pi = compute_osmotic_pressure(comp)
        assert np.isclose(pi, 97.6, rtol=0.10)

    def test_positive(self):
        """Osmotic pressure must be positive."""
        comp = {"Na+": 0.5, "Cl-": 0.5}
        pi = compute_osmotic_pressure(comp)
        assert pi > 0

    def test_monotonic_increase(self):
        """Osmotic pressure must increase with concentration."""
        pi_low = compute_osmotic_pressure({"Na+": 0.1, "Cl-": 0.1})
        pi_high = compute_osmotic_pressure({"Na+": 2.0, "Cl-": 2.0})
        assert pi_high > pi_low

    def test_temperature_increases_pressure(self):
        """Osmotic pressure should increase with temperature."""
        comp = {"Na+": 1.0, "Cl-": 1.0}
        pi_25 = compute_osmotic_pressure(comp, temperature_K=298.15)
        pi_50 = compute_osmotic_pressure(comp, temperature_K=323.15)
        assert pi_50 > pi_25


# ---------------------------------------------------------------------------
# Mixed electrolyte tests
# ---------------------------------------------------------------------------


class TestMixedElectrolyte:
    def test_na_activity_in_mixture(self):
        """Na+ in NaCl+KCl mixture should have reasonable activity coeff."""
        comp = {"Na+": 0.48, "K+": 0.010, "Cl-": 0.49}
        gamma = compute_activity_coefficient(comp, "Na+")
        assert 0.60 < gamma < 0.75, f"Got {gamma:.4f}"

    def test_k_activity_in_mixture(self):
        """K+ in NaCl+KCl mixture should have reasonable activity coeff."""
        comp = {"Na+": 0.48, "K+": 0.010, "Cl-": 0.49}
        gamma = compute_activity_coefficient(comp, "K+")
        assert 0.55 < gamma < 0.75, f"Got {gamma:.4f}"

    def test_osmotic_mixture(self):
        """Osmotic coefficient of mixture should be physically reasonable."""
        comp = {"Na+": 0.48, "K+": 0.010, "Cl-": 0.49}
        phi = compute_osmotic_coefficient(comp)
        assert 0.85 < phi < 1.0, f"Got {phi:.4f}"

    def test_water_activity_mixture(self):
        """Water activity of mixture must be valid."""
        comp = {"Na+": 0.48, "K+": 0.010, "Cl-": 0.49}
        aw = compute_water_activity(comp)
        assert 0.95 < aw < 1.0, f"Got {aw:.4f}"


# ---------------------------------------------------------------------------
# Results JSON file validation
# ---------------------------------------------------------------------------


class TestResultsFile:
    def test_file_exists_and_valid(self):
        with open("/app/results.json") as f:
            results = json.load(f)
        assert "solutions" in results
        assert len(results["solutions"]) >= 5

    def test_all_fields_present(self):
        with open("/app/results.json") as f:
            results = json.load(f)
        required = [
            "id",
            "ionic_strength",
            "activity_coefficient",
            "osmotic_coefficient",
            "water_activity",
            "osmotic_pressure_bar",
        ]
        for sol in results["solutions"]:
            for field in required:
                assert field in sol, (
                    f"Missing field '{field}' in solution {sol.get('id', '?')}"
                )

    def test_values_physical(self):
        with open("/app/results.json") as f:
            results = json.load(f)
        for sol in results["solutions"]:
            assert sol["ionic_strength"] >= 0
            assert sol["activity_coefficient"] > 0
            assert sol["osmotic_coefficient"] > 0
            assert 0 < sol["water_activity"] <= 1.0
            assert sol["osmotic_pressure_bar"] > 0

    def test_nacl_05_result(self):
        """Check NaCl 0.5 result is close to expected."""
        with open("/app/results.json") as f:
            results = json.load(f)
        nacl = next(s for s in results["solutions"] if s["id"] == "nacl_05")
        assert np.isclose(nacl["ionic_strength"], 0.5, rtol=0.01)
        assert np.isclose(nacl["activity_coefficient"], 0.681, rtol=0.05)

    def test_bacl2_01_result(self):
        """Check BaCl2 0.1 result."""
        with open("/app/results.json") as f:
            results = json.load(f)
        bacl2 = next(s for s in results["solutions"] if s["id"] == "bacl2_01")
        assert np.isclose(bacl2["ionic_strength"], 0.3, rtol=0.01)
        assert np.isclose(bacl2["activity_coefficient"], 0.492, rtol=0.05)
