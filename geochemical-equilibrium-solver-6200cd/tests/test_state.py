
import json
import math
import os
import subprocess
import tempfile

import pytest

DATABASE_PATH = "/app/thermodb.json"
SOLVER_PATH = "/app/geochem"
PROBLEMS_DIR = "/app/problems"


def load_database():
    with open(DATABASE_PATH) as f:
        return json.load(f)


def run_solver(config_path):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        output_path = tmp.name
    result = subprocess.run(
        [SOLVER_PATH, "solve", config_path, output_path],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Solver failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
    )
    with open(output_path) as f:
        data = json.load(f)
    os.unlink(output_path)
    return data


def interpolate_logk(logk_array, temperatures, T):
    n = len(temperatures)
    if T <= temperatures[0]:
        return logk_array[0]
    if T >= temperatures[n - 1]:
        return logk_array[n - 1]
    for i in range(n - 1):
        if temperatures[i] <= T <= temperatures[i + 1]:
            frac = (T - temperatures[i]) / (temperatures[i + 1] - temperatures[i])
            return logk_array[i] + frac * (logk_array[i + 1] - logk_array[i])
    return logk_array[n - 1]


def bdot_log_gamma(charge, radius, I, adh, bdh, bdot):
    if charge == 0:
        return 0.0
    sqrt_I = math.sqrt(max(I, 1e-30))
    return -adh * charge ** 2 * sqrt_I / (1 + bdh * radius * sqrt_I) + bdot * I


def get_dh_params(db, T):
    temps = db["header"]["temperatures"]
    adh = interpolate_logk(db["header"]["adh"], temps, T)
    bdh = interpolate_logk(db["header"]["bdh"], temps, T)
    bdot = interpolate_logk(db["header"]["bdot"], temps, T)
    return adh, bdh, bdot


# ---------------------------------------------------------------------------
# Test 1: HCl at pH 2 (simple single-secondary-species equilibrium)
# ---------------------------------------------------------------------------
class TestHCl:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.db = load_database()
        self.result = run_solver(os.path.join(PROBLEMS_DIR, "test1.yaml"))

    def test_output_has_required_fields(self):
        for key in [
            "temperature",
            "ionic_strength",
            "water_activity",
            "pH",
            "charge_balance_error",
            "basis_species",
            "secondary_species",
        ]:
            assert key in self.result, f"Missing field: {key}"

    def test_species_have_required_fields(self):
        for name in ["H2O", "H+", "Cl-"]:
            sp = self.result["basis_species"][name]
            for f in ["molality", "activity_coefficient", "activity"]:
                assert f in sp, f"Missing {f} for {name}"
        sp = self.result["secondary_species"]["OH-"]
        for f in ["molality", "activity_coefficient", "activity"]:
            assert f in sp, f"Missing {f} for OH-"

    def test_temperature(self):
        assert abs(self.result["temperature"] - 25.0) < 1e-6

    def test_ph(self):
        assert abs(self.result["pH"] - 2.0) < 0.01

    def test_charge_balance(self):
        assert abs(self.result["charge_balance_error"]) < 1e-10

    def test_mass_action_OH(self):
        """K_OH = a_w / (a_H+ * a_OH-)"""
        a_w = self.result["water_activity"]
        a_H = self.result["basis_species"]["H+"]["activity"]
        a_OH = self.result["secondary_species"]["OH-"]["activity"]
        assert a_OH > 0
        K_computed = a_w / (a_H * a_OH)
        logK_computed = math.log10(K_computed)
        logK_expected = 13.9951  # database value at 25 C
        assert abs(logK_computed - logK_expected) < 0.01

    def test_activity_coefficient_H(self):
        I = self.result["ionic_strength"]
        gamma_H = self.result["basis_species"]["H+"]["activity_coefficient"]
        adh, bdh, bdot = get_dh_params(self.db, 25.0)
        log_gamma_exp = bdot_log_gamma(1, 9.0, I, adh, bdh, bdot)
        gamma_exp = 10 ** log_gamma_exp
        assert abs(gamma_H - gamma_exp) / gamma_exp < 0.005

    def test_activity_coefficient_Cl(self):
        I = self.result["ionic_strength"]
        gamma_Cl = self.result["basis_species"]["Cl-"]["activity_coefficient"]
        adh, bdh, bdot = get_dh_params(self.db, 25.0)
        log_gamma_exp = bdot_log_gamma(-1, 3.0, I, adh, bdh, bdot)
        gamma_exp = 10 ** log_gamma_exp
        assert abs(gamma_Cl - gamma_exp) / gamma_exp < 0.005

    def test_ionic_strength_self_consistent(self):
        I_expected = 0.0
        for name, sp in self.result["basis_species"].items():
            if name == "H2O":
                continue
            z = self.db["basis_species"][name]["charge"]
            I_expected += z ** 2 * sp["molality"]
        for name, sp in self.result["secondary_species"].items():
            z = self.db["secondary_species"][name]["charge"]
            I_expected += z ** 2 * sp["molality"]
        I_expected *= 0.5
        assert abs(I_expected - self.result["ionic_strength"]) / max(self.result["ionic_strength"], 1e-15) < 0.005

    def test_oh_activity_approximate(self):
        a_OH = self.result["secondary_species"]["OH-"]["activity"]
        # Kw = 10^(-13.9951); a_OH ~ Kw / 0.01 ~ 10^(-11.9951) ~ 1.01e-12
        assert 5e-13 < a_OH < 5e-12

    def test_water_activity_near_one(self):
        a_w = self.result["water_activity"]
        assert 0.999 < a_w < 1.0

    def test_h_activity_matches_constraint(self):
        a_H = self.result["basis_species"]["H+"]["activity"]
        assert abs(a_H - 0.01) / 0.01 < 0.001


# ---------------------------------------------------------------------------
# Test 2: NaCl-CaSO4 multi-species equilibrium at 25 C
# ---------------------------------------------------------------------------
class TestMultiSpecies:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.db = load_database()
        self.result = run_solver(os.path.join(PROBLEMS_DIR, "test2.yaml"))

    def test_charge_balance(self):
        assert abs(self.result["charge_balance_error"]) < 1e-10

    def test_ph(self):
        assert abs(self.result["pH"] - 7.0) < 0.01

    def test_mass_balance_Na(self):
        n_w = 1.0
        m_Na = self.result["basis_species"]["Na+"]["molality"]
        total = m_Na
        for sec_name in ["NaCl", "NaSO4-"]:
            if sec_name in self.result["secondary_species"]:
                rxn = self.db["secondary_species"][sec_name]["reaction"]
                coeff = rxn.get("Na+", 0)
                total += coeff * self.result["secondary_species"][sec_name]["molality"]
        assert abs(total * n_w - 0.5) / 0.5 < 0.005

    def test_mass_balance_Ca(self):
        n_w = 1.0
        m_Ca = self.result["basis_species"]["Ca++"]["molality"]
        total = m_Ca
        for sec_name in ["CaSO4", "CaCl+"]:
            if sec_name in self.result["secondary_species"]:
                rxn = self.db["secondary_species"][sec_name]["reaction"]
                coeff = rxn.get("Ca++", 0)
                total += coeff * self.result["secondary_species"][sec_name]["molality"]
        assert abs(total * n_w - 0.02) / 0.02 < 0.005

    def test_mass_balance_SO4(self):
        n_w = 1.0
        m_SO4 = self.result["basis_species"]["SO4--"]["molality"]
        total = m_SO4
        for sec_name in ["NaSO4-", "CaSO4", "HSO4-"]:
            if sec_name in self.result["secondary_species"]:
                rxn = self.db["secondary_species"][sec_name]["reaction"]
                coeff = rxn.get("SO4--", 0)
                total += coeff * self.result["secondary_species"][sec_name]["molality"]
        assert abs(total * n_w - 0.02) / 0.02 < 0.005

    def test_mass_action_all_secondary(self):
        temps = self.db["header"]["temperatures"]
        T = self.result["temperature"]
        a_w = self.result["water_activity"]
        for sec_name in self.result["secondary_species"]:
            sp_data = self.db["secondary_species"][sec_name]
            sp = self.result["secondary_species"][sec_name]
            a_j = sp["activity"]
            if a_j <= 0:
                continue
            logK_db = interpolate_logk(sp_data["logk"], temps, T)
            log_Q = 0.0
            for basis_name, coeff in sp_data["reaction"].items():
                if basis_name == "H2O":
                    log_Q += coeff * math.log10(max(a_w, 1e-30))
                else:
                    a_basis = self.result["basis_species"][basis_name]["activity"]
                    log_Q += coeff * math.log10(max(a_basis, 1e-30))
            logK_computed = log_Q - math.log10(a_j)
            assert abs(logK_computed - logK_db) < 0.05, (
                f"Mass action for {sec_name}: logK_computed={logK_computed:.4f}, "
                f"logK_db={logK_db:.4f}"
            )

    def test_NaCl_ion_pair_forms(self):
        m_NaCl = self.result["secondary_species"]["NaCl"]["molality"]
        assert m_NaCl > 1e-4, "NaCl(aq) should form in 0.5M NaCl"

    def test_CaSO4_ion_pair_forms(self):
        m_CaSO4 = self.result["secondary_species"]["CaSO4"]["molality"]
        assert m_CaSO4 > 1e-5, "CaSO4(aq) should form"

    def test_ionic_strength_reasonable(self):
        I = self.result["ionic_strength"]
        # 0.5M NaCl + 0.02M CaSO4: I ~ 0.5 + 0.5*4*0.02 = 0.54, reduced by pairing
        assert 0.3 < I < 0.7

    def test_gypsum_saturation_present(self):
        assert "mineral_saturation" in self.result
        assert "Gypsum" in self.result["mineral_saturation"]

    def test_gypsum_undersaturated(self):
        si = self.result["mineral_saturation"]["Gypsum"]["saturation_index"]
        # At 0.02 M Ca & SO4 in 0.5M NaCl, Gypsum should be undersaturated
        assert si < 0

    def test_gypsum_si_computation(self):
        """Verify SI = log10(Q/K) is consistent with reported activities"""
        min_data = self.db["minerals"]["Gypsum"]
        temps = self.db["header"]["temperatures"]
        logK_db = interpolate_logk(min_data["logk"], temps, 25.0)
        a_w = self.result["water_activity"]
        log_Q = 0.0
        for basis_name, coeff in min_data["reaction"].items():
            if basis_name == "H2O":
                log_Q += coeff * math.log10(max(a_w, 1e-30))
            else:
                a_basis = self.result["basis_species"][basis_name]["activity"]
                log_Q += coeff * math.log10(max(a_basis, 1e-30))
        si_expected = log_Q - logK_db
        si_reported = self.result["mineral_saturation"]["Gypsum"]["saturation_index"]
        assert abs(si_expected - si_reported) < 0.1

    def test_activity_coefficients_bdot(self):
        """All charged species gammas consistent with B-dot at reported I"""
        I = self.result["ionic_strength"]
        adh, bdh, bdot = get_dh_params(self.db, 25.0)
        for name, sp in self.result["basis_species"].items():
            if name == "H2O":
                continue
            charge = self.db["basis_species"][name]["charge"]
            radius = self.db["basis_species"][name]["radius"]
            if charge == 0:
                continue
            lg_exp = bdot_log_gamma(charge, radius, I, adh, bdh, bdot)
            gamma_exp = 10 ** lg_exp
            gamma_rep = sp["activity_coefficient"]
            assert abs(gamma_rep - gamma_exp) / gamma_exp < 0.01, (
                f"Gamma mismatch for {name}: reported={gamma_rep}, expected={gamma_exp}"
            )

    def test_charge_balance_direct_computation(self):
        """Recompute charge balance from reported molalities"""
        cbe = 0.0
        for name, sp in self.result["basis_species"].items():
            if name == "H2O":
                continue
            z = self.db["basis_species"][name]["charge"]
            cbe += z * sp["molality"]
        for name, sp in self.result["secondary_species"].items():
            z = self.db["secondary_species"][name]["charge"]
            cbe += z * sp["molality"]
        assert abs(cbe) < 1e-8


# ---------------------------------------------------------------------------
# Test 3: Temperature interpolation at 50 C, higher concentration
# ---------------------------------------------------------------------------
class TestTemperature:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.db = load_database()
        self.result = run_solver(os.path.join(PROBLEMS_DIR, "test3.yaml"))

    def test_temperature(self):
        assert abs(self.result["temperature"] - 50.0) < 1e-6

    def test_charge_balance(self):
        assert abs(self.result["charge_balance_error"]) < 1e-8

    def test_ph(self):
        assert abs(self.result["pH"] - 3.0) < 0.01

    def test_logk_interpolated_between_brackets(self):
        """logK at 50C should lie between 25C and 60C values"""
        temps = self.db["header"]["temperatures"]
        for sec_name in self.result["secondary_species"]:
            sp_data = self.db["secondary_species"][sec_name]
            logK_25 = sp_data["logk"][1]
            logK_60 = sp_data["logk"][2]
            lo = min(logK_25, logK_60)
            hi = max(logK_25, logK_60)
            logK_50 = interpolate_logk(sp_data["logk"], temps, 50.0)
            assert lo - 0.001 <= logK_50 <= hi + 0.001, (
                f"{sec_name}: logK_50={logK_50} not between {logK_25} and {logK_60}"
            )

    def test_mass_action_all_secondary(self):
        temps = self.db["header"]["temperatures"]
        T = self.result["temperature"]
        a_w = self.result["water_activity"]
        for sec_name in self.result["secondary_species"]:
            sp_data = self.db["secondary_species"][sec_name]
            sp = self.result["secondary_species"][sec_name]
            a_j = sp["activity"]
            if a_j <= 0:
                continue
            logK_db = interpolate_logk(sp_data["logk"], temps, T)
            log_Q = 0.0
            for basis_name, coeff in sp_data["reaction"].items():
                if basis_name == "H2O":
                    log_Q += coeff * math.log10(max(a_w, 1e-30))
                else:
                    a_basis = self.result["basis_species"][basis_name]["activity"]
                    log_Q += coeff * math.log10(max(a_basis, 1e-30))
            logK_computed = log_Q - math.log10(a_j)
            assert abs(logK_computed - logK_db) < 0.05, (
                f"Mass action for {sec_name}: logK_computed={logK_computed:.4f}, "
                f"logK_db={logK_db:.4f}"
            )

    def test_mass_balance_Na(self):
        n_w = 1.0
        m_Na = self.result["basis_species"]["Na+"]["molality"]
        total = m_Na
        for sec_name in ["NaCl", "NaSO4-"]:
            if sec_name in self.result["secondary_species"]:
                rxn = self.db["secondary_species"][sec_name]["reaction"]
                coeff = rxn.get("Na+", 0)
                total += coeff * self.result["secondary_species"][sec_name]["molality"]
        assert abs(total * n_w - 1.0) / 1.0 < 0.005

    def test_mass_balance_Ca(self):
        n_w = 1.0
        m_Ca = self.result["basis_species"]["Ca++"]["molality"]
        total = m_Ca
        for sec_name in ["CaSO4", "CaCl+"]:
            if sec_name in self.result["secondary_species"]:
                rxn = self.db["secondary_species"][sec_name]["reaction"]
                coeff = rxn.get("Ca++", 0)
                total += coeff * self.result["secondary_species"][sec_name]["molality"]
        assert abs(total * n_w - 0.05) / 0.05 < 0.005

    def test_ionic_strength_reasonable(self):
        I = self.result["ionic_strength"]
        assert 0.5 < I < 2.0

    def test_gypsum_saturation_present(self):
        assert "Gypsum" in self.result["mineral_saturation"]

    def test_dh_params_interpolated(self):
        """Activity coefficients should use interpolated DH params at 50C"""
        I = self.result["ionic_strength"]
        adh, bdh, bdot = get_dh_params(self.db, 50.0)
        # Verify one species
        gamma_Na = self.result["basis_species"]["Na+"]["activity_coefficient"]
        lg_exp = bdot_log_gamma(1, 4.0, I, adh, bdh, bdot)
        gamma_exp = 10 ** lg_exp
        assert abs(gamma_Na - gamma_exp) / gamma_exp < 0.01, (
            f"Na+ gamma: reported={gamma_Na}, expected={gamma_exp}"
        )

    def test_charge_balance_direct(self):
        cbe = 0.0
        for name, sp in self.result["basis_species"].items():
            if name == "H2O":
                continue
            z = self.db["basis_species"][name]["charge"]
            cbe += z * sp["molality"]
        for name, sp in self.result["secondary_species"].items():
            z = self.db["secondary_species"][name]["charge"]
            cbe += z * sp["molality"]
        assert abs(cbe) < 1e-6

    def test_HSO4_significant_at_low_pH(self):
        """At pH 3, HSO4- should be non-negligible"""
        m_HSO4 = self.result["secondary_species"]["HSO4-"]["molality"]
        assert m_HSO4 > 1e-6
