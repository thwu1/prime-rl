"""
Verification tests for the multi-phase aqueous geochemistry equilibrium solver.

Independently verifies thermodynamic self-consistency:
  - charge balance
  - element mass balances (Na, Cl, Ca, C, S) with mineral contributions
  - equilibrium-constant relationships recomputed with correct B-dot model
  - mineral saturation index consistency
  - physical reasonableness (pH, ionic strength, positivity)

"""
import math
import os
import subprocess
import pytest

# ---- Thermodynamic reference data -------------------------------------------

R_GAS = 8.314462
LN10  = 2.302585093

# Debye-Huckel parameters table (T in K)
DH_TABLE = [
    (273.15, 0.4913, 0.3247, 0.0394),
    (298.15, 0.5085, 0.3281, 0.0410),
    (323.15, 0.5340, 0.3346, 0.0438),
    (348.15, 0.5639, 0.3421, 0.0470),
    (373.15, 0.5998, 0.3510, 0.0500),
]

ION_SIZE = {
    "m_H": 9.0, "m_OH": 3.5, "m_Na": 4.0, "m_Cl": 3.5,
    "m_Ca": 6.0, "m_SO4": 5.0, "m_CO2": 0.0, "m_HCO3": 5.4,
    "m_CO3": 5.4, "m_CaCO3aq": 0.0, "m_NaClaq": 0.0, "m_CaSO4aq": 0.0,
}

CHARGES = {
    "m_H": 1, "m_OH": -1, "m_Na": 1, "m_Cl": -1,
    "m_Ca": 2, "m_SO4": -2, "m_CO2": 0, "m_HCO3": -1,
    "m_CO3": -2, "m_CaCO3aq": 0, "m_NaClaq": 0, "m_CaSO4aq": 0,
}

# log_K_25 and delta_H (J/mol) for van't Hoff
RX = {
    "water":  (-13.991,  55815.0),
    "a1":     ( -6.343,   7646.0),
    "a2":     (-10.326,  14899.0),
    "caco3":  (  3.326, -29000.0),
    "nacl":   ( -0.777,   4000.0),
    "caso4":  (  2.309,   7100.0),
}

MIN_RX = {
    "calcite": (-8.478, -9613.0),
    "gypsum":  (-4.581,  -690.0),
}


def _interp(table_idx, T):
    """Linear interpolation in DH_TABLE for column table_idx (1=A,2=B,3=bdot)."""
    if T <= DH_TABLE[0][0]:
        return DH_TABLE[0][table_idx]
    if T >= DH_TABLE[-1][0]:
        return DH_TABLE[-1][table_idx]
    for i in range(len(DH_TABLE) - 1):
        if T <= DH_TABLE[i + 1][0]:
            frac = (T - DH_TABLE[i][0]) / (DH_TABLE[i + 1][0] - DH_TABLE[i][0])
            return DH_TABLE[i][table_idx] + frac * (DH_TABLE[i + 1][table_idx] - DH_TABLE[i][table_idx])
    return DH_TABLE[-1][table_idx]


def bdot_lg(z, ion_size, I, T):
    """Correct B-dot log10(gamma)."""
    if z == 0:
        return 0.0
    A = _interp(1, T)
    B = _interp(2, T)
    bd = _interp(3, T)
    sI = math.sqrt(max(I, 0.0))
    return -A * z * z * sI / (1.0 + ion_size * B * sI) + bd * I


def logk_T(name, T, data=None):
    """Van't Hoff log_K at temperature T."""
    d = data or RX
    lk25, dH = d[name]
    if abs(T - 298.15) < 0.01:
        return lk25
    return lk25 + dH / (LN10 * R_GAS) * (1.0 / 298.15 - 1.0 / T)


def ionic_strength(r):
    """Recompute ionic strength from reported molalities."""
    charged = [
        ("m_H", 1), ("m_OH", -1), ("m_Na", 1), ("m_Cl", -1),
        ("m_Ca", 2), ("m_SO4", -2), ("m_HCO3", -1), ("m_CO3", -2),
    ]
    return 0.5 * sum(r.get(k, 0.0) * z * z for k, z in charged)


# ---- I/O --------------------------------------------------------------------

def parse_results(path):
    d = {}
    with open(path) as fh:
        for line in fh:
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    d[parts[0]] = float(parts[1])
                except ValueError:
                    d[parts[0]] = parts[1]
    return d


# ---- Fixtures ----------------------------------------------------------------

@pytest.fixture(scope="module")
def case1():
    subprocess.run(
        ["/app/build/geqsolve", "/app/problem_1.txt", "/app/results_1.txt"],
        capture_output=True, text=True, timeout=60,
    )
    assert os.path.exists("/app/results_1.txt"), "results_1.txt not created"
    return parse_results("/app/results_1.txt")


@pytest.fixture(scope="module")
def case2():
    subprocess.run(
        ["/app/build/geqsolve", "/app/problem_2.txt", "/app/results_2.txt"],
        capture_output=True, text=True, timeout=60,
    )
    assert os.path.exists("/app/results_2.txt"), "results_2.txt not created"
    return parse_results("/app/results_2.txt")


@pytest.fixture(scope="module")
def case3():
    subprocess.run(
        ["/app/build/geqsolve", "/app/problem_3.txt", "/app/results_3.txt"],
        capture_output=True, text=True, timeout=60,
    )
    assert os.path.exists("/app/results_3.txt"), "results_3.txt not created"
    return parse_results("/app/results_3.txt")


@pytest.fixture(scope="module")
def case4():
    subprocess.run(
        ["/app/build/geqsolve", "/app/problem_4.txt", "/app/results_4.txt"],
        capture_output=True, text=True, timeout=60,
    )
    assert os.path.exists("/app/results_4.txt"), "results_4.txt not created"
    return parse_results("/app/results_4.txt")


@pytest.fixture(scope="module")
def case5():
    subprocess.run(
        ["/app/build/geqsolve", "/app/problem_5.txt", "/app/results_5.txt"],
        capture_output=True, text=True, timeout=60,
    )
    assert os.path.exists("/app/results_5.txt"), "results_5.txt not created"
    return parse_results("/app/results_5.txt")


# ---- Helper ------------------------------------------------------------------

ALL_MOLALITIES = [
    "m_H", "m_OH", "m_Na", "m_Cl", "m_Ca", "m_SO4",
    "m_CO2", "m_HCO3", "m_CO3", "m_CaCO3aq", "m_NaClaq", "m_CaSO4aq",
]


def check_convergence(r, label):
    assert r["converged"] == 1, f"{label}: solver did not converge"


def check_charge_balance(r, label, tol=1e-5):
    cb = sum(CHARGES[k] * r.get(k, 0.0) for k in ALL_MOLALITIES)
    assert abs(cb) < tol, f"{label}: charge balance = {cb:.3e}"


def check_positivity(r, label):
    for k in ALL_MOLALITIES:
        assert r.get(k, 0.0) >= 0, f"{label}: {k} is negative"
    assert r.get("n_calcite", 0.0) >= -1e-10, f"{label}: n_calcite negative"
    assert r.get("n_gypsum", 0.0) >= -1e-10, f"{label}: n_gypsum negative"


def check_mass_balance(r, label, element, species_list, total, n_minerals=None, tol=1e-3):
    """species_list: list of (key, stoich_coeff) tuples."""
    computed = sum(r.get(k, 0.0) * c for k, c in species_list)
    if n_minerals:
        for mk, mc in n_minerals:
            computed += r.get(mk, 0.0) * mc
    rel = abs(computed - total) / max(total, 1e-15)
    assert rel < tol, f"{label}: {element} mass balance rel err = {rel:.4e}"


def check_eq_relationship(r, label, rx_name, T, tol=0.02):
    """Check |log10(Q) - log10(K(T))| < tol using B-dot activity model."""
    I = ionic_strength(r)
    lk = logk_T(rx_name, T)

    def lg(key):
        return bdot_lg(CHARGES[key], ION_SIZE[key], I, T)

    if rx_name == "water":
        logQ = (math.log10(r["m_H"]) + lg("m_H")
                + math.log10(r["m_OH"]) + lg("m_OH"))
    elif rx_name == "a1":
        logQ = (math.log10(r["m_H"]) + lg("m_H")
                + math.log10(r["m_HCO3"]) + lg("m_HCO3")
                - math.log10(r["m_CO2"]) - lg("m_CO2"))
    elif rx_name == "a2":
        logQ = (math.log10(r["m_H"]) + lg("m_H")
                + math.log10(r["m_CO3"]) + lg("m_CO3")
                - math.log10(r["m_HCO3"]) - lg("m_HCO3"))
    elif rx_name == "caco3":
        logQ = (math.log10(r["m_CaCO3aq"]) + lg("m_CaCO3aq")
                - math.log10(r["m_Ca"]) - lg("m_Ca")
                - math.log10(r["m_CO3"]) - lg("m_CO3"))
    elif rx_name == "nacl":
        logQ = (math.log10(r["m_NaClaq"]) + lg("m_NaClaq")
                - math.log10(r["m_Na"]) - lg("m_Na")
                - math.log10(r["m_Cl"]) - lg("m_Cl"))
    elif rx_name == "caso4":
        logQ = (math.log10(r["m_CaSO4aq"]) + lg("m_CaSO4aq")
                - math.log10(r["m_Ca"]) - lg("m_Ca")
                - math.log10(r["m_SO4"]) - lg("m_SO4"))
    else:
        raise ValueError(f"Unknown reaction {rx_name}")

    assert abs(logQ - lk) < tol, (
        f"{label}: {rx_name} |logQ-logK|={abs(logQ-lk):.4f} "
        f"(logQ={logQ:.4f}, logK={lk:.4f})"
    )


def check_mineral_si(r, label, mineral, T, tol=0.1):
    """Check reported SI is consistent with molalities and B-dot model."""
    I = ionic_strength(r)
    lgCa = bdot_lg(2, ION_SIZE["m_Ca"], I, T)
    if mineral == "calcite":
        lgCO3 = bdot_lg(-2, ION_SIZE["m_CO3"], I, T)
        lk = logk_T("calcite", T, MIN_RX)
        computed = (math.log10(r["m_Ca"]) + lgCa
                    + math.log10(r["m_CO3"]) + lgCO3 - lk)
        assert abs(r["calcite_SI"] - computed) < tol, (
            f"{label}: calcite SI mismatch: reported={r['calcite_SI']:.4f}, "
            f"computed={computed:.4f}"
        )
    elif mineral == "gypsum":
        lgSO4 = bdot_lg(-2, ION_SIZE["m_SO4"], I, T)
        lk = logk_T("gypsum", T, MIN_RX)
        computed = (math.log10(r["m_Ca"]) + lgCa
                    + math.log10(r["m_SO4"]) + lgSO4 - lk)
        assert abs(r["gypsum_SI"] - computed) < tol, (
            f"{label}: gypsum SI mismatch: reported={r['gypsum_SI']:.4f}, "
            f"computed={computed:.4f}"
        )


# ==============================================================================
# Case 1: dilute NaCl (0.01 M), trace Ca & C, 25 C
# ==============================================================================

class TestCase1:
    T = 298.15

    def test_converged(self, case1):
        check_convergence(case1, "case1")

    def test_charge_balance(self, case1):
        check_charge_balance(case1, "case1", tol=1e-8)

    def test_na_balance(self, case1):
        check_mass_balance(case1, "case1", "Na",
                           [("m_Na", 1), ("m_NaClaq", 1)], 0.01)

    def test_cl_balance(self, case1):
        check_mass_balance(case1, "case1", "Cl",
                           [("m_Cl", 1), ("m_NaClaq", 1)], 0.01)

    def test_ca_balance(self, case1):
        check_mass_balance(case1, "case1", "Ca",
                           [("m_Ca", 1), ("m_CaCO3aq", 1), ("m_CaSO4aq", 1)],
                           1e-6, tol=0.02)

    def test_c_balance(self, case1):
        check_mass_balance(case1, "case1", "C",
                           [("m_CO2", 1), ("m_HCO3", 1), ("m_CO3", 1), ("m_CaCO3aq", 1)],
                           1e-4)

    def test_water_eq(self, case1):
        check_eq_relationship(case1, "case1", "water", self.T)

    def test_a1_eq(self, case1):
        check_eq_relationship(case1, "case1", "a1", self.T)

    def test_a2_eq(self, case1):
        check_eq_relationship(case1, "case1", "a2", self.T)

    def test_caco3_eq(self, case1):
        check_eq_relationship(case1, "case1", "caco3", self.T)

    def test_nacl_eq(self, case1):
        check_eq_relationship(case1, "case1", "nacl", self.T)

    def test_ph_range(self, case1):
        assert 5.0 < case1["pH"] < 9.0, f"case1: pH={case1['pH']}"

    def test_ionic_strength_range(self, case1):
        assert 0.005 < case1["ionic_strength"] < 0.02

    def test_positive(self, case1):
        check_positivity(case1, "case1")

    def test_calcite_si(self, case1):
        check_mineral_si(case1, "case1", "calcite", self.T)

    def test_no_calcite_precip(self, case1):
        assert case1.get("n_calcite", 0.0) < 1e-10


# ==============================================================================
# Case 2: NaCl + NaHCO3 (Na=0.11, Cl=0.1, Ca=1e-5, C=0.01), 25 C
# ==============================================================================

class TestCase2:
    T = 298.15

    def test_converged(self, case2):
        check_convergence(case2, "case2")

    def test_charge_balance(self, case2):
        check_charge_balance(case2, "case2", tol=1e-6)

    def test_na_balance(self, case2):
        check_mass_balance(case2, "case2", "Na",
                           [("m_Na", 1), ("m_NaClaq", 1)], 0.11)

    def test_cl_balance(self, case2):
        check_mass_balance(case2, "case2", "Cl",
                           [("m_Cl", 1), ("m_NaClaq", 1)], 0.1)

    def test_ca_balance(self, case2):
        check_mass_balance(case2, "case2", "Ca",
                           [("m_Ca", 1), ("m_CaCO3aq", 1), ("m_CaSO4aq", 1)],
                           1e-5, tol=0.02)

    def test_c_balance(self, case2):
        check_mass_balance(case2, "case2", "C",
                           [("m_CO2", 1), ("m_HCO3", 1), ("m_CO3", 1), ("m_CaCO3aq", 1)],
                           0.01)

    def test_water_eq(self, case2):
        check_eq_relationship(case2, "case2", "water", self.T)

    def test_a1_eq(self, case2):
        check_eq_relationship(case2, "case2", "a1", self.T)

    def test_a2_eq(self, case2):
        check_eq_relationship(case2, "case2", "a2", self.T)

    def test_caco3_eq(self, case2):
        check_eq_relationship(case2, "case2", "caco3", self.T)

    def test_nacl_eq(self, case2):
        check_eq_relationship(case2, "case2", "nacl", self.T)

    def test_ph_range(self, case2):
        assert 5.0 < case2["pH"] < 10.0

    def test_ionic_strength_range(self, case2):
        assert 0.08 < case2["ionic_strength"] < 0.15

    def test_positive(self, case2):
        check_positivity(case2, "case2")

    def test_no_calcite_precip(self, case2):
        assert case2.get("n_calcite", 0.0) < 1e-10


# ==============================================================================
# Case 3: NaCl + Na2SO4 + trace Ca (Na=0.125, Cl=0.1, Ca=1e-4, C=0.02, S=0.01), 25 C
# ==============================================================================

class TestCase3:
    T = 298.15

    def test_converged(self, case3):
        check_convergence(case3, "case3")

    def test_charge_balance(self, case3):
        check_charge_balance(case3, "case3", tol=1e-5)

    def test_na_balance(self, case3):
        check_mass_balance(case3, "case3", "Na",
                           [("m_Na", 1), ("m_NaClaq", 1)], 0.125)

    def test_cl_balance(self, case3):
        check_mass_balance(case3, "case3", "Cl",
                           [("m_Cl", 1), ("m_NaClaq", 1)], 0.1)

    def test_ca_balance(self, case3):
        check_mass_balance(case3, "case3", "Ca",
                           [("m_Ca", 1), ("m_CaCO3aq", 1), ("m_CaSO4aq", 1)],
                           1e-4, tol=0.02)

    def test_c_balance(self, case3):
        check_mass_balance(case3, "case3", "C",
                           [("m_CO2", 1), ("m_HCO3", 1), ("m_CO3", 1), ("m_CaCO3aq", 1)],
                           0.02)

    def test_s_balance(self, case3):
        check_mass_balance(case3, "case3", "S",
                           [("m_SO4", 1), ("m_CaSO4aq", 1)], 0.01)

    def test_water_eq(self, case3):
        check_eq_relationship(case3, "case3", "water", self.T)

    def test_a1_eq(self, case3):
        check_eq_relationship(case3, "case3", "a1", self.T)

    def test_a2_eq(self, case3):
        check_eq_relationship(case3, "case3", "a2", self.T)

    def test_caco3_eq(self, case3):
        check_eq_relationship(case3, "case3", "caco3", self.T)

    def test_nacl_eq(self, case3):
        check_eq_relationship(case3, "case3", "nacl", self.T)

    def test_caso4_eq(self, case3):
        check_eq_relationship(case3, "case3", "caso4", self.T)

    def test_ph_range(self, case3):
        assert 4.0 < case3["pH"] < 8.5

    def test_ionic_strength_range(self, case3):
        assert 0.08 < case3["ionic_strength"] < 0.25

    def test_positive(self, case3):
        check_positivity(case3, "case3")

    def test_gypsum_si(self, case3):
        check_mineral_si(case3, "case3", "gypsum", self.T)

    def test_no_gypsum_precip(self, case3):
        assert case3.get("n_gypsum", 0.0) < 1e-10


# ==============================================================================
# Case 4: same as case 2 but at 60 C (temperature dependence)
# ==============================================================================

class TestCase4:
    T = 333.15

    def test_converged(self, case4):
        check_convergence(case4, "case4")

    def test_charge_balance(self, case4):
        check_charge_balance(case4, "case4", tol=1e-5)

    def test_na_balance(self, case4):
        check_mass_balance(case4, "case4", "Na",
                           [("m_Na", 1), ("m_NaClaq", 1)], 0.11)

    def test_cl_balance(self, case4):
        check_mass_balance(case4, "case4", "Cl",
                           [("m_Cl", 1), ("m_NaClaq", 1)], 0.1)

    def test_ca_balance(self, case4):
        check_mass_balance(case4, "case4", "Ca",
                           [("m_Ca", 1), ("m_CaCO3aq", 1), ("m_CaSO4aq", 1)],
                           1e-5, tol=0.02)

    def test_c_balance(self, case4):
        check_mass_balance(case4, "case4", "C",
                           [("m_CO2", 1), ("m_HCO3", 1), ("m_CO3", 1), ("m_CaCO3aq", 1)],
                           0.01)

    def test_water_eq(self, case4):
        check_eq_relationship(case4, "case4", "water", self.T)

    def test_a1_eq(self, case4):
        check_eq_relationship(case4, "case4", "a1", self.T)

    def test_a2_eq(self, case4):
        check_eq_relationship(case4, "case4", "a2", self.T)

    def test_caco3_eq(self, case4):
        check_eq_relationship(case4, "case4", "caco3", self.T)

    def test_nacl_eq(self, case4):
        check_eq_relationship(case4, "case4", "nacl", self.T)

    def test_ph_range(self, case4):
        assert 4.0 < case4["pH"] < 8.5

    def test_ionic_strength_range(self, case4):
        assert 0.08 < case4["ionic_strength"] < 0.15

    def test_positive(self, case4):
        check_positivity(case4, "case4")

    def test_calcite_si(self, case4):
        check_mineral_si(case4, "case4", "calcite", self.T)


# ==============================================================================
# Case 5: high salinity at 80 C — calcite must precipitate
# ==============================================================================

class TestCase5:
    T = 353.15

    def test_converged(self, case5):
        check_convergence(case5, "case5")

    def test_charge_balance(self, case5):
        check_charge_balance(case5, "case5", tol=1e-5)

    def test_na_balance(self, case5):
        check_mass_balance(case5, "case5", "Na",
                           [("m_Na", 1), ("m_NaClaq", 1)], 0.56)

    def test_cl_balance(self, case5):
        check_mass_balance(case5, "case5", "Cl",
                           [("m_Cl", 1), ("m_NaClaq", 1)], 0.56)

    def test_ca_balance(self, case5):
        check_mass_balance(case5, "case5", "Ca",
                           [("m_Ca", 1), ("m_CaCO3aq", 1), ("m_CaSO4aq", 1)],
                           0.03,
                           n_minerals=[("n_calcite", 1), ("n_gypsum", 1)])

    def test_c_balance(self, case5):
        check_mass_balance(case5, "case5", "C",
                           [("m_CO2", 1), ("m_HCO3", 1), ("m_CO3", 1), ("m_CaCO3aq", 1)],
                           0.05,
                           n_minerals=[("n_calcite", 1)])

    def test_s_balance(self, case5):
        check_mass_balance(case5, "case5", "S",
                           [("m_SO4", 1), ("m_CaSO4aq", 1)], 0.005,
                           n_minerals=[("n_gypsum", 1)])

    def test_water_eq(self, case5):
        check_eq_relationship(case5, "case5", "water", self.T)

    def test_a1_eq(self, case5):
        check_eq_relationship(case5, "case5", "a1", self.T)

    def test_a2_eq(self, case5):
        check_eq_relationship(case5, "case5", "a2", self.T)

    def test_caco3_eq(self, case5):
        check_eq_relationship(case5, "case5", "caco3", self.T)

    def test_nacl_eq(self, case5):
        check_eq_relationship(case5, "case5", "nacl", self.T)

    def test_caso4_eq(self, case5):
        check_eq_relationship(case5, "case5", "caso4", self.T)

    def test_ph_range(self, case5):
        assert 4.0 < case5["pH"] < 8.0

    def test_ionic_strength_range(self, case5):
        assert 0.3 < case5["ionic_strength"] < 0.7

    def test_positive(self, case5):
        check_positivity(case5, "case5")

    def test_calcite_precipitates(self, case5):
        assert case5.get("n_calcite", 0.0) > 1e-6, "case5: calcite should precipitate"

    def test_calcite_si_at_equilibrium(self, case5):
        if case5.get("n_calcite", 0.0) > 1e-6:
            assert abs(case5["calcite_SI"]) < 0.05, (
                f"case5: calcite SI should be ~0 when precipitated, got {case5['calcite_SI']:.4f}"
            )

    def test_calcite_si_consistent(self, case5):
        check_mineral_si(case5, "case5", "calcite", self.T)

    def test_gypsum_si(self, case5):
        check_mineral_si(case5, "case5", "gypsum", self.T)
