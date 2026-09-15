
import subprocess
import json
import os
import sqlite3 as sqlite3_mod
import pytest


def run_cli(*args):
    """Run the membrane_analysis CLI and return parsed JSON output."""
    result = subprocess.run(
        ["python3", "-m", "membrane_analysis"] + list(args),
        capture_output=True,
        text=True,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"CLI failed with code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return json.loads(result.stdout)


# ============================================================
# EOS Tests
# ============================================================


class TestEOSPure:
    def test_low_pressure_ideal(self):
        """At 1 bar, N2 at 300 K should behave nearly ideally."""
        out = run_cli("eos", "--gas", "N2", "--T", "300", "--P", "1")
        assert abs(out["Z"] - 1.0) < 0.005
        assert abs(out["phi"] - 1.0) < 0.005
        assert abs(out["fugacity_bar"] - 1.0) < 0.01

    def test_co2_high_pressure(self):
        """CO2 at 350 K, 50 bar shows significant non-ideality."""
        out = run_cli("eos", "--gas", "CO2", "--T", "350", "--P", "50")
        assert 0.80 < out["Z"] < 0.86, f"Z={out['Z']} outside expected range"
        assert 0.82 < out["phi"] < 0.87, f"phi={out['phi']} outside expected range"

    def test_ch4_high_pressure(self):
        """CH4 at 350 K, 50 bar is mildly non-ideal."""
        out = run_cli("eos", "--gas", "CH4", "--T", "350", "--P", "50")
        assert 0.93 < out["Z"] < 0.96
        assert 0.93 < out["phi"] < 0.96

    def test_fugacity_equals_phi_times_p(self):
        """Fugacity must equal phi * P for any pure gas."""
        for gas in ["CO2", "CH4", "N2", "O2"]:
            out = run_cli("eos", "--gas", gas, "--T", "350", "--P", "30")
            expected_f = out["phi"] * 30.0
            assert abs(out["fugacity_bar"] - expected_f) < 0.01, (
                f"{gas}: fugacity mismatch"
            )

    def test_co2_more_nonideal_than_n2(self):
        """CO2 should be more non-ideal than N2 at same T, P."""
        co2 = run_cli("eos", "--gas", "CO2", "--T", "350", "--P", "50")
        n2 = run_cli("eos", "--gas", "N2", "--T", "350", "--P", "50")
        assert co2["Z"] < n2["Z"]
        assert co2["phi"] < n2["phi"]

    def test_h2_nearly_ideal(self):
        """H2 should be nearly ideal even at moderate pressure (far above Tc)."""
        out = run_cli("eos", "--gas", "H2", "--T", "300", "--P", "10")
        assert out["Z"] > 0.99
        assert out["phi"] > 0.99


class TestEOSMixture:
    def test_mixture_structure(self):
        """Mixture output has required keys."""
        out = run_cli(
            "eos",
            "--gas", "CO2,CH4",
            "--composition", "0.15,0.85",
            "--T", "308.15",
            "--P", "50",
        )
        assert "Z_mix" in out
        assert "phi" in out
        assert "fugacity_bar" in out
        assert "CO2" in out["phi"]
        assert "CH4" in out["phi"]
        assert "CO2" in out["fugacity_bar"]
        assert "CH4" in out["fugacity_bar"]

    def test_mixture_z_range(self):
        """Mixture Z should be between pure-component extremes."""
        out = run_cli(
            "eos",
            "--gas", "CO2,CH4",
            "--composition", "0.15,0.85",
            "--T", "308.15",
            "--P", "50",
        )
        assert 0.85 < out["Z_mix"] < 1.0

    def test_mixture_co2_phi_less_than_ch4_phi(self):
        """In CO2/CH4 mixture, CO2 fugacity coefficient should be lower."""
        out = run_cli(
            "eos",
            "--gas", "CO2,CH4",
            "--composition", "0.15,0.85",
            "--T", "308.15",
            "--P", "50",
        )
        assert out["phi"]["CO2"] < out["phi"]["CH4"]

    def test_mixture_fugacity_consistency(self):
        """Component fugacity = phi_i * x_i * P."""
        out = run_cli(
            "eos",
            "--gas", "CO2,CH4",
            "--composition", "0.30,0.70",
            "--T", "350",
            "--P", "40",
        )
        f_co2_expected = out["phi"]["CO2"] * 0.30 * 40.0
        f_ch4_expected = out["phi"]["CH4"] * 0.70 * 40.0
        assert abs(out["fugacity_bar"]["CO2"] - f_co2_expected) < 0.05
        assert abs(out["fugacity_bar"]["CH4"] - f_ch4_expected) < 0.05


# ============================================================
# Validate Tests (NIST cross-check)
# ============================================================


class TestValidate:
    def test_n2_1atm_structure(self):
        """Validate output has required fields and correct structure."""
        out = run_cli("validate", "--gas", "N2", "--pressure", "1")
        assert len(out) > 5
        entry = out[0]
        for field in ["T_K", "P_bar", "Z_computed", "Z_nist", "relative_error"]:
            assert field in entry, f"Missing field: {field}"

    def test_n2_1atm_sorted_ascending(self):
        """Results must be sorted ascending by temperature."""
        out = run_cli("validate", "--gas", "N2", "--pressure", "1")
        temps = [r["T_K"] for r in out]
        assert temps == sorted(temps)
        assert len(temps) == len(set(temps)), "Duplicate temperatures"

    def test_n2_1atm_accuracy(self):
        """At 1 atm, N2 EOS must match NIST within 2% for T > 1.5*Tc."""
        out = run_cli("validate", "--gas", "N2", "--pressure", "1")
        Tc_N2 = 126.192
        high_T = [e for e in out if e["T_K"] > 1.5 * Tc_N2]
        assert len(high_T) > 3, "Expected several points above 1.5*Tc"
        for entry in high_T:
            assert entry["relative_error"] < 0.02, (
                f"N2 at T={entry['T_K']}K: relative_error={entry['relative_error']}"
            )

    def test_co2_1atm_accuracy(self):
        """CO2 at 1 atm must match NIST within 2% above 1.5*Tc."""
        out = run_cli("validate", "--gas", "CO2", "--pressure", "1")
        Tc_CO2 = 304.128
        high_T = [e for e in out if e["T_K"] > 1.5 * Tc_CO2]
        assert len(high_T) > 3
        for entry in high_T:
            assert entry["relative_error"] < 0.02

    def test_h2_50atm_accuracy(self):
        """H2 at 50 atm -- EOS must match NIST within 3% for T > 6*Tc."""
        out = run_cli("validate", "--gas", "H2", "--pressure", "50")
        Tc_H2 = 33.145
        high_T = [e for e in out if e["T_K"] > 6 * Tc_H2]
        assert len(high_T) > 5
        for entry in high_T:
            assert entry["relative_error"] < 0.03, (
                f"H2 at T={entry['T_K']}K: relative_error={entry['relative_error']}"
            )

    def test_n2_50atm_accuracy(self):
        """N2 at 50 atm: EOS must match NIST within 3% for T > 1.5*Tc."""
        out = run_cli("validate", "--gas", "N2", "--pressure", "50")
        Tc_N2 = 126.192
        high_T = [e for e in out if e["T_K"] > 1.5 * Tc_N2]
        assert len(high_T) > 3
        for entry in high_T:
            assert entry["relative_error"] < 0.03, (
                f"N2 at T={entry['T_K']}K: relative_error={entry['relative_error']}"
            )


# ============================================================
# Robeson Upper Bound Tests
# ============================================================


class TestRobeson:
    def test_psf_below_co2_ch4_bound(self):
        """PSf is well below the CO2/CH4 upper bound."""
        out = run_cli("robeson", "--gas-pair", "CO2/CH4", "--polymer", "PSf")
        assert len(out) == 1
        assert not out[0]["exceeds_bound"]
        assert out[0]["ratio"] < 0.05

    def test_6fda_dam_near_or_above_bound(self):
        """6FDA-DAM should be near or above the CO2/CH4 upper bound."""
        out = run_cli("robeson", "--gas-pair", "CO2/CH4", "--polymer", "6FDA-DAM")
        assert out[0]["ratio"] > 0.8

    def test_ranking_sorted_descending(self):
        """All polymers ranked by ratio descending for CO2/CH4."""
        out = run_cli("robeson", "--gas-pair", "CO2/CH4")
        assert len(out) == 12
        ratios = [p["ratio"] for p in out]
        for i in range(len(ratios) - 1):
            assert ratios[i] >= ratios[i + 1], (
                f"Not sorted: {ratios[i]} < {ratios[i+1]}"
            )

    def test_upper_bound_numerical(self):
        """Verify numerical upper bound for PDMS on CO2/CH4."""
        out = run_cli("robeson", "--gas-pair", "CO2/CH4", "--polymer", "PDMS")
        alpha = 3200.0 / 950.0
        k = 5369140.0
        n = 2.636
        P_UB = k * alpha ** (-n)
        expected_ratio = 3200.0 / P_UB
        assert abs(out[0]["ratio"] - expected_ratio) / expected_ratio < 0.01

    def test_o2_n2_gas_pair(self):
        """Robeson evaluation works for O2/N2 gas pair."""
        out = run_cli("robeson", "--gas-pair", "O2/N2")
        assert len(out) == 12
        ptmsp = next(p for p in out if p["polymer"] == "PTMSP")
        assert ptmsp["ratio"] < 0.1
        assert not ptmsp["exceeds_bound"]

    def test_required_fields_present(self):
        """Each entry has all required fields."""
        out = run_cli("robeson", "--gas-pair", "H2/CH4", "--polymer", "PIM-1")
        entry = out[0]
        for field in ["polymer", "P_A", "alpha", "P_upper_bound", "ratio", "exceeds_bound"]:
            assert field in entry, f"Missing field: {field}"


# ============================================================
# Cascade Design Tests
# ============================================================


class TestCascade:
    @pytest.fixture(scope="class")
    def result(self):
        return run_cli("cascade", "--config", "/app/data/cascade_scenario.json")

    def test_converged(self, result):
        assert result["converged"] is True

    def test_iterations_reasonable(self, result):
        assert 2 < result["iterations"] < 500

    def test_total_mass_balance(self, result):
        """Feed = product + reject within 0.1%."""
        total_out = result["product"]["flow_mol_per_s"] + result["reject"]["flow_mol_per_s"]
        assert abs(total_out - 1000.0) / 1000.0 < 0.001

    def test_co2_mass_balance(self, result):
        """CO2 in = CO2 out within 0.1%."""
        feed_co2 = 1000.0 * 0.15
        out_co2 = (
            result["product"]["flow_mol_per_s"] * result["product"]["CO2_mol_frac"]
            + result["reject"]["flow_mol_per_s"] * result["reject"]["CO2_mol_frac"]
        )
        assert abs(out_co2 - feed_co2) / feed_co2 < 0.001

    def test_product_meets_spec(self, result):
        """Product CO2 must be at or below target (2%) with small tolerance."""
        assert result["product"]["CO2_mol_frac"] <= 0.021

    def test_methane_recovery_reasonable(self, result):
        """Methane recovery should be high for a two-stage cascade."""
        assert result["methane_recovery"] > 0.90

    def test_stage_areas_positive(self, result):
        assert result["stage1"]["area_m2"] > 0
        assert result["stage2"]["area_m2"] > 0

    def test_stage_cuts_valid(self, result):
        assert 0 < result["stage1"]["stage_cut"] < 1
        assert 0 < result["stage2"]["stage_cut"] < 1

    def test_recycle_nonzero(self, result):
        """Two-stage cascade must have non-zero recycle."""
        assert result["recycle"]["flow_mol_per_s"] > 10.0
        assert 0 < result["recycle"]["CO2_mol_frac"] < 1

    def test_reject_enriched_in_co2(self, result):
        """Reject stream (Stage 2 permeate) should be CO2-enriched."""
        assert result["reject"]["CO2_mol_frac"] > 0.5

    def test_stage_compositions_consistent(self, result):
        """Stage retentate and permeate CO2 fractions must sum to 1 with CH4."""
        for stage_name in ["stage1", "stage2"]:
            stage = result[stage_name]
            ret = stage["retentate"]
            perm = stage["permeate"]
            assert abs(ret["CO2"] + ret["CH4"] - 1.0) < 1e-6
            assert abs(perm["CO2"] + perm["CH4"] - 1.0) < 1e-6


# ============================================================
# Makefile Pipeline Tests — Preprocess (awk)
# ============================================================


class TestPreprocess:
    def test_processed_dir_exists(self):
        """make preprocess must create /app/processed/."""
        assert os.path.isdir("/app/processed"), (
            "/app/processed not found; did 'make preprocess' run?"
        )

    def test_csv_files_exist(self):
        """Preprocessed CSVs must exist for all NIST TSV files."""
        expected = [
            "N2_1atm.csv", "N2_50atm.csv", "O2_1atm.csv",
            "CO2_1atm.csv", "CH4_1atm.csv", "H2_1atm.csv", "H2_50atm.csv",
        ]
        for name in expected:
            path = f"/app/processed/{name}"
            assert os.path.isfile(path), f"Missing: {path}"

    def test_csv_header_correct(self):
        """Preprocessed CSVs must have the specified header."""
        with open("/app/processed/N2_1atm.csv") as f:
            header = f.readline().strip()
        assert header == "gas,temperature_k,pressure_atm,density_kg_m3,z_nist", (
            f"Unexpected header: {header}"
        )

    def test_csv_has_data_rows(self):
        """Preprocessed CSVs must contain data rows."""
        with open("/app/processed/N2_1atm.csv") as f:
            lines = f.readlines()
        assert len(lines) > 5, "Expected data rows in preprocessed CSV"

    def test_csv_z_values_reasonable_1atm(self):
        """Z values at 1 atm must be near 1.0 for ideal-gas-like conditions."""
        with open("/app/processed/N2_1atm.csv") as f:
            lines = f.readlines()[1:]
        for line in lines:
            parts = line.strip().split(",")
            assert len(parts) == 5, f"Expected 5 columns, got {len(parts)}"
            z = float(parts[4])
            assert 0.9 < z < 1.1, f"Z={z} unreasonable for N2 at 1 atm"

    def test_csv_z_computed_by_awk(self):
        """Verify awk-computed z_nist matches the expected formula."""
        R = 8.314462
        MW_N2 = 0.028014
        with open("/app/processed/N2_1atm.csv") as f:
            lines = f.readlines()[1:]
        for line in lines:
            parts = line.strip().split(",")
            T = float(parts[1])
            patm = float(parts[2])
            rho = float(parts[3])
            z_csv = float(parts[4])
            P_pa = patm * 101325.0
            z_expected = P_pa * MW_N2 / (rho * R * T)
            assert abs(z_csv - z_expected) / z_expected < 1e-4, (
                f"awk Z={z_csv} vs expected={z_expected} at T={T}"
            )

    def test_csv_excludes_nonvapor(self):
        """Preprocessed CSVs must only contain vapor-phase data."""
        for fname in os.listdir("/app/processed/"):
            if not fname.endswith(".csv"):
                continue
            with open(f"/app/processed/{fname}") as f:
                lines = f.readlines()[1:]
            for line in lines:
                parts = line.strip().split(",")
                # All values after gas name should be numeric
                for p in parts[1:]:
                    float(p)  # raises ValueError if non-numeric


# ============================================================
# Makefile Pipeline Tests — Database (sqlite3 + jq)
# ============================================================


class TestDatabase:
    def test_database_exists(self):
        """make database must create /app/analysis.db."""
        assert os.path.isfile("/app/analysis.db"), (
            "/app/analysis.db not found; did 'make database' run?"
        )

    def test_nist_reference_table(self):
        """nist_reference table must exist with correct schema and data."""
        conn = sqlite3_mod.connect("/app/analysis.db")
        # Check table exists
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "nist_reference" in table_names
        # Check has data
        count = conn.execute("SELECT COUNT(*) FROM nist_reference").fetchone()[0]
        assert count > 40, f"nist_reference has only {count} rows"
        # Check columns
        cols = conn.execute("PRAGMA table_info(nist_reference)").fetchall()
        col_names = [c[1] for c in cols]
        for expected in ["gas", "temperature_k", "pressure_atm", "density_kg_m3", "z_nist"]:
            assert expected in col_names, f"Missing column: {expected}"
        conn.close()

    def test_eos_validation_table(self):
        """eos_validation table must exist with data from all gas/pressure combos."""
        conn = sqlite3_mod.connect("/app/analysis.db")
        count = conn.execute("SELECT COUNT(*) FROM eos_validation").fetchone()[0]
        assert count > 40, f"eos_validation has only {count} rows"
        # Check multiple gases are present
        gases = conn.execute(
            "SELECT DISTINCT gas FROM eos_validation"
        ).fetchall()
        gas_names = {g[0] for g in gases}
        assert len(gas_names) >= 5, f"Expected >=5 gases, got {gas_names}"
        conn.close()

    def test_robeson_ranking_table(self):
        """robeson_ranking table must have data for all gas pairs."""
        conn = sqlite3_mod.connect("/app/analysis.db")
        count = conn.execute("SELECT COUNT(*) FROM robeson_ranking").fetchone()[0]
        pairs = conn.execute(
            "SELECT COUNT(DISTINCT gas_pair) FROM robeson_ranking"
        ).fetchone()[0]
        conn.close()
        assert count >= 100, f"robeson_ranking has only {count} rows (expected ~120)"
        assert pairs == 10, f"Expected 10 gas pairs, got {pairs}"

    def test_worst_eos_errors_view(self):
        """worst_eos_errors view must return top 10 errors in DESC order."""
        conn = sqlite3_mod.connect("/app/analysis.db")
        rows = conn.execute("SELECT * FROM worst_eos_errors").fetchall()
        conn.close()
        assert len(rows) == 10, f"Expected 10 rows, got {len(rows)}"
        errors = [r[2] for r in rows]
        for i in range(len(errors) - 1):
            assert errors[i] >= errors[i + 1], (
                f"View not sorted: {errors[i]} < {errors[i+1]}"
            )

    def test_eos_validation_data_reasonable(self):
        """EOS validation errors in database should be physically reasonable."""
        conn = sqlite3_mod.connect("/app/analysis.db")
        max_err = conn.execute(
            "SELECT MAX(relative_error) FROM eos_validation"
        ).fetchone()[0]
        conn.close()
        assert max_err < 0.15, f"Max EOS error {max_err} too large"

    def test_robeson_exceeds_bound_column(self):
        """exceeds_bound must be INTEGER (0 or 1)."""
        conn = sqlite3_mod.connect("/app/analysis.db")
        values = conn.execute(
            "SELECT DISTINCT exceeds_bound FROM robeson_ranking"
        ).fetchall()
        conn.close()
        vals = {v[0] for v in values}
        assert vals.issubset({0, 1}), f"exceeds_bound has unexpected values: {vals}"
        assert 0 in vals and 1 in vals, "Expected both 0 and 1 in exceeds_bound"


# ============================================================
# Makefile Pipeline Tests — Report (sqlite3 queries + jq)
# ============================================================


class TestReport:
    def test_report_exists(self):
        """make report must produce /app/report.json."""
        assert os.path.isfile("/app/report.json"), (
            "/app/report.json not found; did 'make report' run?"
        )

    def test_report_structure(self):
        """report.json must have all required fields."""
        with open("/app/report.json") as f:
            report = json.load(f)
        for key in [
            "total_nist_points",
            "mean_relative_error",
            "max_relative_error",
            "polymers_exceeding_bound",
            "gas_pairs_evaluated",
        ]:
            assert key in report, f"Missing key in report: {key}"

    def test_report_total_nist_points(self):
        """total_nist_points must match nist_reference row count."""
        with open("/app/report.json") as f:
            report = json.load(f)
        assert isinstance(report["total_nist_points"], int)
        assert report["total_nist_points"] > 40

    def test_report_error_statistics(self):
        """Error statistics must be positive and reasonable."""
        with open("/app/report.json") as f:
            report = json.load(f)
        assert 0 < report["mean_relative_error"] < 0.05
        assert 0 < report["max_relative_error"] < 0.15
        assert report["max_relative_error"] >= report["mean_relative_error"]

    def test_report_polymers_exceeding_bound(self):
        """polymers_exceeding_bound must be a non-empty list."""
        with open("/app/report.json") as f:
            report = json.load(f)
        poly_list = report["polymers_exceeding_bound"]
        assert isinstance(poly_list, list)
        assert len(poly_list) > 0, "Expected at least one polymer exceeding bound"
        for p in poly_list:
            assert isinstance(p, str) and len(p) > 0

    def test_report_gas_pairs_evaluated(self):
        """gas_pairs_evaluated must equal 10."""
        with open("/app/report.json") as f:
            report = json.load(f)
        assert report["gas_pairs_evaluated"] == 10
