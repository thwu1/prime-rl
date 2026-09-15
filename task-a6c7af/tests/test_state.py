import json
import math
import os
import sqlite3
import pytest
import numpy as np


TC, PC, OMEGA = 304.18, 73.80, 0.2239
R = 0.08314472
KAPPA = 0.37464 + 1.54226 * OMEGA - 0.26992 * OMEGA**2


def _pr(T, P):
    """Reference PR EOS solver. Returns (sorted positive real roots, A, B, a, b)."""
    alpha = (1 + KAPPA * (1 - (T / TC) ** 0.5)) ** 2
    a = 0.45724 * R**2 * TC**2 / PC * alpha
    b = 0.07780 * R * TC / PC
    A = a * P / (R * T) ** 2
    B = b * P / (R * T)
    coeffs = [1, -(1 - B), A - 3 * B**2 - 2 * B, -(A * B - B**2 - B**3)]
    rts = np.roots(coeffs)
    real = sorted(
        [r.real for r in rts if abs(r.imag) < 1e-8 and r.real > B]
    )
    return real, A, B, a, b


def _lnphi(Z, A, B):
    """Reference ln(fugacity coefficient) from PR EOS."""
    s2 = 2**0.5
    return (
        (Z - 1)
        - math.log(Z - B)
        - A / (2 * s2 * B) * math.log((Z + (1 + s2) * B) / (Z + (1 - s2) * B))
    )


def _hdep(T, Z, A, B, a, b):
    """Reference departure enthalpy (kJ/mol) from PR EOS."""
    s2 = 2**0.5
    alpha = (1 + KAPPA * (1 - (T / TC) ** 0.5)) ** 2
    a0 = 0.45724 * R**2 * TC**2 / PC
    dalpha_dT = -KAPPA * alpha**0.5 / (T * TC) ** 0.5
    da_dT = a0 * dalpha_dT
    ln_term = math.log((Z + (1 + s2) * B) / (Z + (1 - s2) * B))
    h = R * T * (Z - 1) + (T * da_dT - a) / (2 * s2 * b) * ln_term
    return h * 0.1  # L-bar/mol -> kJ/mol


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def db():
    conn = sqlite3.connect("/app/thermo.db")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def validation():
    with open("/app/validation.json") as f:
        return json.load(f)


# == Pipeline ==============================================================
class TestPipeline:
    def test_pipeline_exists(self):
        assert os.path.isfile("/app/pipeline.sh"), "pipeline.sh not found"

    def test_pipeline_uses_jq(self):
        with open("/app/pipeline.sh") as f:
            content = f.read()
        assert "jq" in content, "pipeline.sh must invoke jq"

    def test_pipeline_uses_sqlite3_cli(self):
        with open("/app/pipeline.sh") as f:
            content = f.read()
        assert "sqlite3" in content, "pipeline.sh must invoke sqlite3 CLI"


# == Database ==============================================================
class TestDatabase:
    def test_db_exists(self):
        assert os.path.isfile("/app/thermo.db"), "thermo.db not found"
        assert os.path.getsize("/app/thermo.db") > 4096, "thermo.db appears empty"

    def test_nist_isotherms_schema(self, db):
        cur = db.execute("PRAGMA table_info(nist_isotherms)")
        cols = {row["name"] for row in cur.fetchall()}
        for c in ("temperature_K", "pressure_bar", "volume_L_mol", "phase"):
            assert c in cols, f"nist_isotherms missing column: {c}"

    def test_nist_isotherms_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM nist_isotherms").fetchone()[0]
        assert count >= 50, f"nist_isotherms has {count} rows, expected >= 50"

    def test_nist_isotherms_temperatures(self, db):
        temps = [r[0] for r in db.execute(
            "SELECT DISTINCT temperature_K FROM nist_isotherms ORDER BY temperature_K"
        ).fetchall()]
        assert 250.0 in temps
        assert 300.0 in temps
        assert 350.0 in temps
        assert 400.0 in temps

    def test_nist_isotherms_300K_1bar_volume(self, db):
        row = db.execute(
            "SELECT volume_L_mol FROM nist_isotherms "
            "WHERE temperature_K = 300.0 AND ABS(pressure_bar - 1.0) < 0.01 LIMIT 1"
        ).fetchone()
        assert row is not None, "No row for 300K/1bar in nist_isotherms"
        assert abs(row[0] - 24.822) < 0.01

    def test_nist_isotherms_250K_has_liquid(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM nist_isotherms "
            "WHERE temperature_K = 250.0 AND phase = 'liquid'"
        ).fetchone()[0]
        assert count >= 10, f"Expected >= 10 liquid rows at 250K, got {count}"

    def test_critical_props_schema(self, db):
        cur = db.execute("PRAGMA table_info(critical_props)")
        cols = {row["name"] for row in cur.fetchall()}
        for c in ("fluid", "property", "value", "uncertainty", "source"):
            assert c in cols, f"critical_props missing column: {c}"

    def test_critical_props_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM critical_props").fetchone()[0]
        assert count >= 25, f"critical_props has {count} rows, expected >= 25"

    def test_critical_props_co2_tc_measurements(self, db):
        rows = db.execute(
            "SELECT value FROM critical_props WHERE fluid='CO2' AND property='Tc'"
        ).fetchall()
        assert len(rows) >= 4, f"Expected >= 4 CO2 Tc measurements, got {len(rows)}"
        vals = [r[0] for r in rows]
        assert any(abs(v - 304.18) < 0.01 for v in vals)

    def test_critical_props_multiple_fluids(self, db):
        fluids = [r[0] for r in db.execute(
            "SELECT DISTINCT fluid FROM critical_props"
        ).fetchall()]
        assert len(fluids) >= 3, f"Expected >= 3 fluids, got {fluids}"

    def test_saturation_ref_schema(self, db):
        cur = db.execute("PRAGMA table_info(saturation_ref)")
        cols = {row["name"] for row in cur.fetchall()}
        assert "temperature_K" in cols
        assert "pressure_bar" in cols

    def test_saturation_ref_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM saturation_ref").fetchone()[0]
        assert count == 9, f"saturation_ref has {count} rows, expected 9"

    def test_saturation_ref_280K(self, db):
        row = db.execute(
            "SELECT pressure_bar FROM saturation_ref "
            "WHERE ABS(temperature_K - 280.0) < 0.5"
        ).fetchone()
        assert row is not None
        assert abs(row[0] - 41.636) < 0.1

    def test_saturation_ref_290K(self, db):
        row = db.execute(
            "SELECT pressure_bar FROM saturation_ref "
            "WHERE ABS(temperature_K - 290.0) < 0.5"
        ).fetchone()
        assert row is not None
        assert abs(row[0] - 53.304) < 0.1


# == Validation JSON =======================================================
class TestValidation:
    def test_validation_exists(self):
        assert os.path.isfile("/app/validation.json"), "validation.json not found"

    def test_validation_keys(self, validation):
        for k in ("keys_present", "n_isotherms", "n_fugacity", "n_virial",
                   "db_isotherm_count", "db_saturation_count"):
            assert k in validation, f"validation.json missing key: {k}"

    def test_validation_keys_present_sorted(self, validation):
        expected = sorted([
            "compressibility", "compression_work", "critical_params",
            "departure_enthalpy", "fugacity", "model_accuracy",
            "second_virial", "vle_prediction"
        ])
        assert validation["keys_present"] == expected

    def test_validation_fugacity_count(self, validation):
        assert validation["n_fugacity"] == 4

    def test_validation_virial_count(self, validation):
        assert validation["n_virial"] == 4

    def test_validation_db_isotherm_count(self, validation):
        assert validation["db_isotherm_count"] >= 50

    def test_validation_db_saturation_count(self, validation):
        assert validation["db_saturation_count"] == 9

    def test_validation_n_isotherms_matches_json(self, validation, results):
        total = sum(
            len(results["compressibility"][t]) for t in ("250", "300", "350", "400")
        )
        assert validation["n_isotherms"] == total, (
            f"n_isotherms={validation['n_isotherms']}, JSON total={total}"
        )

    def test_validation_db_count_matches_db(self, validation, db):
        count = db.execute("SELECT COUNT(*) FROM nist_isotherms").fetchone()[0]
        assert validation["db_isotherm_count"] == count, (
            f"validation db_isotherm_count={validation['db_isotherm_count']}, "
            f"actual db count={count}"
        )

    def test_validation_db_gte_json(self, validation):
        assert validation["db_isotherm_count"] >= validation["n_isotherms"], (
            "DB should have >= rows than JSON (raw vs deduplicated)"
        )


# == Cross-Consistency =====================================================
class TestCrossConsistency:
    def test_db_volume_matches_json_znist(self, results, db):
        """Verify Z_NIST in JSON is consistent with volume stored in database."""
        row = db.execute(
            "SELECT volume_L_mol FROM nist_isotherms "
            "WHERE temperature_K = 300.0 AND ABS(pressure_bar - 1.0) < 0.01 LIMIT 1"
        ).fetchone()
        assert row is not None
        z_from_db = 1.0 * row[0] / (R * 300.0)
        comp = results["compressibility"]["300"]
        e = next(x for x in comp if abs(x["P_bar"] - 1.0) < 0.1)
        assert abs(e["Z_NIST"] - z_from_db) < 0.001, (
            f"Z_NIST from JSON={e['Z_NIST']}, computed from DB volume={z_from_db}"
        )

    def test_saturation_ref_matches_model_accuracy(self, results, db):
        """Verify saturation_ref DB values match model_accuracy NIST references."""
        for entry in results["model_accuracy"]["saturation_validation"]:
            T = entry["T_K"]
            row = db.execute(
                "SELECT pressure_bar FROM saturation_ref "
                "WHERE ABS(temperature_K - ?) < 0.5",
                (T,)
            ).fetchone()
            assert row is not None, f"No saturation_ref row for T={T}K"
            assert abs(row[0] - entry["P_sat_nist_bar"]) < 0.5, (
                f"DB saturation P={row[0]} vs model_accuracy P_nist="
                f"{entry['P_sat_nist_bar']} at {T}K"
            )

    def test_db_400K_volume_matches_json(self, results, db):
        """Cross-check a second isotherm for consistency."""
        row = db.execute(
            "SELECT volume_L_mol FROM nist_isotherms "
            "WHERE temperature_K = 400.0 AND ABS(pressure_bar - 1.0) < 0.01 LIMIT 1"
        ).fetchone()
        assert row is not None
        z_from_db = 1.0 * row[0] / (R * 400.0)
        comp = results["compressibility"]["400"]
        e = next(x for x in comp if abs(x["P_bar"] - 1.0) < 0.1)
        assert abs(e["Z_NIST"] - z_from_db) < 0.001


# == Critical Parameters ===================================================
class TestCriticalParams:
    def test_has_keys(self, results):
        cp = results["critical_params"]
        for k in ("Tc_K", "Pc_bar", "omega"):
            assert k in cp, f"critical_params missing key: {k}"

    def test_tc_range(self, results):
        tc = results["critical_params"]["Tc_K"]
        assert 304.0 < tc < 304.5, f"Tc={tc}, expected near 304.18"

    def test_pc_range(self, results):
        pc = results["critical_params"]["Pc_bar"]
        assert 73.3 < pc < 74.0, f"Pc={pc}, expected near 73.80"

    def test_omega_range(self, results):
        omega = results["critical_params"]["omega"]
        assert 0.22 < omega < 0.23, f"omega={omega}, expected near 0.2239"


# == Structure =============================================================
class TestStructure:
    def test_top_keys(self, results):
        for k in (
            "critical_params",
            "compressibility",
            "fugacity",
            "departure_enthalpy",
            "second_virial",
            "vle_prediction",
            "compression_work",
            "model_accuracy",
        ):
            assert k in results, f"Missing key: {k}"

    def test_compressibility_temps(self, results):
        for t in ("250", "300", "350", "400"):
            assert t in results["compressibility"]
            assert len(results["compressibility"][t]) >= 3

    def test_fugacity_count(self, results):
        assert len(results["fugacity"]) == 4

    def test_departure_enthalpy_count(self, results):
        assert len(results["departure_enthalpy"]) == 4

    def test_virial_count(self, results):
        assert len(results["second_virial"]) == 4

    def test_vle_count(self, results):
        assert len(results["vle_prediction"]) == 2

    def test_compression_work_keys(self, results):
        cw = results["compression_work"]
        for k in ("T_K", "P1_bar", "P2_bar", "W_ideal_kJ_per_mol", "W_real_kJ_per_mol"):
            assert k in cw, f"compression_work missing key: {k}"


# == Data parsing (Z_NIST) =================================================
class TestParsing:
    def test_z_nist_300K_1bar(self, results):
        comp = results["compressibility"]["300"]
        e = next(x for x in comp if abs(x["P_bar"] - 1.0) < 0.1)
        assert abs(e["Z_NIST"] - 0.995134) < 0.002

    def test_z_nist_300K_81bar(self, results):
        comp = results["compressibility"]["300"]
        e = next(x for x in comp if abs(x["P_bar"] - 81.0) < 0.5)
        assert abs(e["Z_NIST"] - 0.18893) < 0.003

    def test_z_nist_250K_1bar(self, results):
        comp = results["compressibility"]["250"]
        e = next(x for x in comp if abs(x["P_bar"] - 1.0) < 0.1)
        expected = 1.0 * 20.601 / (R * 250)
        assert abs(e["Z_NIST"] - expected) < 0.002

    def test_z_nist_400K_1bar(self, results):
        comp = results["compressibility"]["400"]
        e = next(x for x in comp if abs(x["P_bar"] - 1.0) < 0.1)
        expected = 1.0 * 33.198 / (R * 400)
        assert abs(e["Z_NIST"] - expected) < 0.002


# == Phase labels ==========================================================
class TestPhase:
    def test_300K_1bar_vapor(self, results):
        comp = results["compressibility"]["300"]
        e = next(x for x in comp if abs(x["P_bar"] - 1.0) < 0.1)
        assert e["phase"] == "vapor"

    def test_300K_81bar_liquid(self, results):
        comp = results["compressibility"]["300"]
        e = next(x for x in comp if abs(x["P_bar"] - 81.0) < 0.5)
        assert e["phase"] == "liquid"

    def test_250K_1bar_vapor(self, results):
        comp = results["compressibility"]["250"]
        e = next(x for x in comp if abs(x["P_bar"] - 1.0) < 0.1)
        assert e["phase"] == "vapor"

    def test_no_duplicate_pressures(self, results):
        for t in ("250", "300", "350", "400"):
            pressures = [e["P_bar"] for e in results["compressibility"][t]]
            rounded = [round(p, 3) for p in pressures]
            assert len(rounded) == len(set(rounded)), (
                f"Duplicate pressures in {t}K compressibility data"
            )


# == PR EOS Z values =======================================================
class TestCompressibility:
    @pytest.mark.parametrize(
        "T,P,expected_Z,tol",
        [
            (300, 1, 0.99462, 0.005),
            (300, 21, 0.88006, 0.012),
            (300, 41, 0.74474, 0.018),
            (350, 1, 0.99670, 0.005),
            (400, 1, 0.99792, 0.005),
        ],
    )
    def test_z_pr_vapor(self, results, T, P, expected_Z, tol):
        comp = results["compressibility"][str(T)]
        e = next(x for x in comp if abs(x["P_bar"] - P) < 0.5)
        assert abs(e["Z_PR"] - expected_Z) < tol, (
            f"Z_PR({T}K,{P}bar)={e['Z_PR']}, expected ~{expected_Z}"
        )

    def test_z_pr_liquid_300K(self, results):
        comp = results["compressibility"]["300"]
        e = next(x for x in comp if abs(x["P_bar"] - 81.0) < 0.5)
        assert 0.05 < e["Z_PR"] < 0.35, f"Z_PR(300K,81bar)={e['Z_PR']}"

    def test_z_pr_supercritical_350K(self, results):
        comp = results["compressibility"]["350"]
        e = next(x for x in comp if abs(x["P_bar"] - 101.0) < 0.5)
        assert 0.4 < e["Z_PR"] < 0.9, f"Z_PR(350K,101bar)={e['Z_PR']}"

    def test_z_pr_positive(self, results):
        for t in ("250", "300", "350", "400"):
            for e in results["compressibility"][t]:
                assert e["Z_PR"] > 0, f"Z_PR({t}K,{e['P_bar']}bar) not positive"


# == Fugacity ==============================================================
class TestFugacity:
    @pytest.mark.parametrize("T,P", [(300, 10), (300, 50), (350, 100), (400, 200)])
    def test_fugacity_against_ref(self, results, T, P):
        real, A, B, a, b = _pr(T, P)
        Z = max(real)
        ref = _lnphi(Z, A, B)
        entry = next(
            x for x in results["fugacity"] if x["T_K"] == T and x["P_bar"] == P
        )
        assert abs(entry["ln_phi"] - ref) < 0.02, (
            f"ln_phi({T},{P})={entry['ln_phi']}, ref={ref:.6f}"
        )

    def test_fugacity_negative(self, results):
        for e in results["fugacity"]:
            assert e["ln_phi"] < 0, (
                f"ln_phi({e['T_K']},{e['P_bar']})={e['ln_phi']} should be negative"
            )


# == Departure enthalpy ====================================================
class TestDepartureEnthalpy:
    @pytest.mark.parametrize("T,P", [(300, 10), (300, 50), (350, 100), (400, 200)])
    def test_hdep_against_ref(self, results, T, P):
        real, A, B, a, b = _pr(T, P)
        Z = max(real)
        ref = _hdep(T, Z, A, B, a, b)
        entry = next(
            x
            for x in results["departure_enthalpy"]
            if x["T_K"] == T and x["P_bar"] == P
        )
        assert abs(entry["H_dep_kJ_per_mol"] - ref) / abs(ref) < 0.05, (
            f"H_dep({T},{P})={entry['H_dep_kJ_per_mol']}, ref={ref:.6f}"
        )

    def test_hdep_negative(self, results):
        for e in results["departure_enthalpy"]:
            assert e["H_dep_kJ_per_mol"] < 0, (
                f"H_dep({e['T_K']},{e['P_bar']})={e['H_dep_kJ_per_mol']} should be <0"
            )


# == Second virial coefficient =============================================
class TestVirial:
    def test_b_data_300K(self, results):
        e = next(x for x in results["second_virial"] if x["T_K"] == 300)
        assert -160 < e["B_data_cm3_per_mol"] < -90, (
            f"B_data(300K)={e['B_data_cm3_per_mol']}"
        )

    def test_b_data_250K(self, results):
        e = next(x for x in results["second_virial"] if x["T_K"] == 250)
        assert -260 < e["B_data_cm3_per_mol"] < -130

    def test_b_pr_reference(self, results):
        for T_val in [250, 300, 350, 400]:
            alpha = (1 + KAPPA * (1 - (T_val / TC) ** 0.5)) ** 2
            a = 0.45724 * R**2 * TC**2 / PC * alpha
            b = 0.07780 * R * TC / PC
            ref = (b - a / (R * T_val)) * 1000
            e = next(x for x in results["second_virial"] if x["T_K"] == T_val)
            assert abs(e["B_PR_cm3_per_mol"] - ref) / abs(ref) < 0.05, (
                f"B_PR({T_val}K)={e['B_PR_cm3_per_mol']}, ref={ref:.2f}"
            )

    def test_b_negative(self, results):
        for e in results["second_virial"]:
            assert e["B_PR_cm3_per_mol"] < 0
            assert e["B_data_cm3_per_mol"] < 0

    def test_b_monotone_temperature(self, results):
        """B should become less negative (increase) with increasing T."""
        vir = sorted(results["second_virial"], key=lambda x: x["T_K"])
        for i in range(len(vir) - 1):
            assert vir[i]["B_data_cm3_per_mol"] < vir[i + 1]["B_data_cm3_per_mol"], (
                f"B_data not increasing: {vir[i]['T_K']}K={vir[i]['B_data_cm3_per_mol']},"
                f" {vir[i+1]['T_K']}K={vir[i+1]['B_data_cm3_per_mol']}"
            )


# == VLE prediction ========================================================
class TestVLE:
    def test_psat_280K(self, results):
        e = next(x for x in results["vle_prediction"] if x["T_K"] == 280)
        assert 33 < e["P_sat_bar"] < 52, (
            f"P_sat(280K)={e['P_sat_bar']}, NIST~41.64"
        )

    def test_psat_290K(self, results):
        e = next(x for x in results["vle_prediction"] if x["T_K"] == 290)
        assert 42 < e["P_sat_bar"] < 66, (
            f"P_sat(290K)={e['P_sat_bar']}, NIST~53.30"
        )

    def test_psat_ordering(self, results):
        vle = results["vle_prediction"]
        p280 = next(x for x in vle if x["T_K"] == 280)["P_sat_bar"]
        p290 = next(x for x in vle if x["T_K"] == 290)["P_sat_bar"]
        assert p290 > p280, f"P_sat should increase with T: P280={p280}, P290={p290}"

    def test_psat_below_critical(self, results):
        for e in results["vle_prediction"]:
            assert e["P_sat_bar"] < PC, (
                f"P_sat({e['T_K']}K)={e['P_sat_bar']} exceeds Pc={PC}"
            )


# == Compression work ======================================================
class TestCompressionWork:
    def test_ideal_work(self, results):
        cw = results["compression_work"]
        ref = R * 350 * math.log(80.0) * 0.1
        assert abs(cw["W_ideal_kJ_per_mol"] - ref) / ref < 0.01, (
            f"W_ideal={cw['W_ideal_kJ_per_mol']}, ref={ref:.6f}"
        )

    def test_real_work_positive(self, results):
        assert results["compression_work"]["W_real_kJ_per_mol"] > 0

    def test_real_vs_ideal_ratio(self, results):
        cw = results["compression_work"]
        ratio = cw["W_real_kJ_per_mol"] / cw["W_ideal_kJ_per_mol"]
        assert 0.5 < ratio < 1.5, f"W_real/W_ideal = {ratio:.4f}"

    def test_real_work_ref(self, results):
        cw = results["compression_work"]
        T = 350.0
        r1, A1, B1, _, _ = _pr(T, 1.0)
        Z1 = max(r1)
        f1 = 1.0 * math.exp(_lnphi(Z1, A1, B1))
        r2, A2, B2, _, _ = _pr(T, 80.0)
        Z2 = max(r2)
        f2 = 80.0 * math.exp(_lnphi(Z2, A2, B2))
        ref = R * T * math.log(f2 / f1) * 0.1
        assert abs(cw["W_real_kJ_per_mol"] - ref) / abs(ref) < 0.05, (
            f"W_real={cw['W_real_kJ_per_mol']}, ref={ref:.6f}"
        )


# == Model Accuracy ========================================================
class TestModelAccuracy:
    def test_has_saturation_validation(self, results):
        ma = results["model_accuracy"]
        assert "saturation_validation" in ma
        assert len(ma["saturation_validation"]) == 2

    def test_saturation_validation_structure(self, results):
        for entry in results["model_accuracy"]["saturation_validation"]:
            for k in ("T_K", "P_sat_nist_bar", "P_sat_predicted_bar", "relative_error"):
                assert k in entry, f"saturation_validation missing key: {k}"

    def test_saturation_nist_280K(self, results):
        entry = next(
            x for x in results["model_accuracy"]["saturation_validation"]
            if x["T_K"] == 280
        )
        assert 40.0 < entry["P_sat_nist_bar"] < 43.0, (
            f"NIST P_sat(280K)={entry['P_sat_nist_bar']}, expected ~41.6"
        )

    def test_saturation_nist_290K(self, results):
        entry = next(
            x for x in results["model_accuracy"]["saturation_validation"]
            if x["T_K"] == 290
        )
        assert 52.0 < entry["P_sat_nist_bar"] < 55.0, (
            f"NIST P_sat(290K)={entry['P_sat_nist_bar']}, expected ~53.3"
        )

    def test_saturation_relative_error_reasonable(self, results):
        for entry in results["model_accuracy"]["saturation_validation"]:
            assert abs(entry["relative_error"]) < 0.25, (
                f"Relative error at {entry['T_K']}K = {entry['relative_error']}, "
                f"expected < 0.25"
            )

    def test_saturation_relative_error_consistent(self, results):
        """Check that relative_error is consistent with predicted and NIST values."""
        for entry in results["model_accuracy"]["saturation_validation"]:
            expected_re = (
                (entry["P_sat_predicted_bar"] - entry["P_sat_nist_bar"])
                / entry["P_sat_nist_bar"]
            )
            assert abs(entry["relative_error"] - expected_re) < 0.01, (
                f"Relative error inconsistent at {entry['T_K']}K: "
                f"reported={entry['relative_error']}, computed={expected_re:.6f}"
            )

    def test_has_compressibility_rmse(self, results):
        ma = results["model_accuracy"]
        assert "compressibility_rmse" in ma
        for t in ("250", "300", "350", "400"):
            assert t in ma["compressibility_rmse"], (
                f"compressibility_rmse missing temperature {t}"
            )
            entry = ma["compressibility_rmse"][t]
            for k in ("rmse", "max_abs_error", "n_points"):
                assert k in entry, (
                    f"compressibility_rmse[{t}] missing key: {k}"
                )

    def test_rmse_positive_and_consistent(self, results):
        for t in ("250", "300", "350", "400"):
            entry = results["model_accuracy"]["compressibility_rmse"][t]
            assert entry["rmse"] > 0, f"RMSE({t}K) should be positive"
            assert entry["n_points"] >= 3, f"n_points({t}K) should be >= 3"
            assert entry["max_abs_error"] >= entry["rmse"] - 1e-9, (
                f"max_abs_error({t}K)={entry['max_abs_error']} < rmse={entry['rmse']}"
            )

    def test_rmse_supercritical_reasonable(self, results):
        for t in ("350", "400"):
            entry = results["model_accuracy"]["compressibility_rmse"][t]
            assert entry["rmse"] < 0.15, (
                f"RMSE for {t}K = {entry['rmse']}, expected < 0.15"
            )

    def test_rmse_independent_calculation(self, results):
        """Verify RMSE against independently computed values for one isotherm."""
        comp_400 = results["compressibility"]["400"]
        errors_sq = [(e["Z_PR"] - e["Z_NIST"])**2 for e in comp_400]
        n = len(comp_400)
        expected_rmse = (sum(errors_sq) / n) ** 0.5
        reported_rmse = results["model_accuracy"]["compressibility_rmse"]["400"]["rmse"]
        assert abs(reported_rmse - expected_rmse) < 0.001, (
            f"RMSE(400K) reported={reported_rmse}, computed={expected_rmse:.6f}"
        )
