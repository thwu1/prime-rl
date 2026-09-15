
"""
Tests for CO2 EOS implementation, transcritical cycle, Makefile pipeline, and gnuplot diagram.
Reference data from NIST Chemistry WebBook (https://webbook.nist.gov).
"""

import sys
import os
import json
import math
import subprocess
import pytest

sys.path.insert(0, "/app")
import co2_eos

M = 0.0440098  # kg/mol
MG = M * 1000  # g/mol = 44.0098, conversion factor for mass->molar units

# ---------------------------------------------------------------------------
# NIST reference data: each entry has mass-based NIST values
# rho in kg/m3, P in MPa, cv/cp in J/(g*K), w in m/s, h in kJ/kg, s in J/(g*K)
# ---------------------------------------------------------------------------
NIST_SINGLE_PHASE = [
    {
        "label": "T=220K sat liquid",
        "T": 220.0, "rho_mass": 1166.1398,
        "P_MPa": 0.59913045,
        "cv_mass": 0.96982617, "cp_mass": 1.9617864,
        "w": 951.21439,
        "h_mass": 86.728161, "s_mass": 0.55166161,
    },
    {
        "label": "T=250K sat liquid",
        "T": 250.0, "rho_mass": 1045.9721,
        "P_MPa": 1.7850442,
        "cv_mass": 0.93643396, "cp_mass": 2.1320485,
        "w": 731.78422,
        "h_mass": 147.71027, "s_mass": 0.80675008,
    },
    {
        "label": "T=280K sat liquid",
        "T": 280.0, "rho_mass": 883.58277,
        "P_MPa": 4.1607391,
        "cv_mass": 0.96045809, "cp_mass": 2.8141186,
        "w": 471.54298,
        "h_mass": 217.29877, "s_mass": 1.0598431,
    },
    {
        "label": "T=220K sat vapor",
        "T": 220.0, "rho_mass": 15.81742,
        "P_MPa": 0.59913045,
        "cv_mass": 0.63893944, "cp_mass": 0.93032468,
        "w": 223.14686,
        "h_mass": 431.63787, "s_mass": 2.119433,
    },
    {
        "label": "T=250K sat vapor",
        "T": 250.0, "rho_mass": 46.644014,
        "P_MPa": 1.7850442,
        "cv_mass": 0.74590622, "cp_mass": 1.2365646,
        "w": 221.21531,
        "h_mass": 437.04388, "s_mass": 1.9640845,
    },
    {
        "label": "T=350K P=1MPa (gas)",
        "T": 350.0, "rho_mass": 15.581285,
        "P_MPa": 1.0000000,
        "cv_mass": 0.71885466, "cp_mass": 0.93681295,
        "w": 284.86323,
        "h_mass": 545.18260, "s_mass": 2.4322149,
    },
    {
        "label": "T=350K P=13MPa (dense SC)",
        "T": 350.0, "rho_mass": 355.71343,
        "P_MPa": 13.000000,
        "cv_mass": 0.92244875, "cp_mass": 2.7845306,
        "w": 252.99213,
        "h_mass": 427.14130, "s_mass": 1.6835110,
    },
    {
        "label": "T=220K P=8MPa (compressed liq)",
        "T": 220.0, "rho_mass": 1181.7185,
        "P_MPa": 8.0000000,
        "cv_mass": 0.97851054, "cp_mass": 1.9145280,
        "w": 992.55955,
        "h_mass": 88.822570, "s_mass": 0.53252881,
    },
    {
        "label": "T=305K P=7.1MPa (near-critical vapor)",
        "T": 305.0, "rho_mass": 256.07472,
        "P_MPa": 7.1000000,
        "cv_mass": 1.0909261, "cp_mass": 5.9768190,
        "w": 196.95061,
        "h_mass": 399.33112, "s_mass": 1.6571776,
    },
]

NIST_SATURATION = [
    {"T": 220.0, "P_MPa": 0.59913045, "rho_l_mass": 1166.1398, "rho_v_mass": 15.81742},
    {"T": 240.0, "P_MPa": 1.2824835, "rho_l_mass": 1088.8692, "rho_v_mass": 33.295138},
    {"T": 260.0, "P_MPa": 2.4187925, "rho_l_mass": 998.88622, "rho_v_mass": 64.417035},
    {"T": 280.0, "P_MPa": 4.1607391, "rho_l_mass": 883.58277, "rho_v_mass": 121.74305},
    {"T": 295.0, "P_MPa": 5.9821714, "rho_l_mass": 752.55936, "rho_v_mass": 209.7231},
]


def rel_err(computed, reference):
    """Relative error magnitude."""
    if reference == 0:
        return abs(computed)
    return abs((computed - reference) / reference)


# ===========================================================================
# Test 1: Pressure
# ===========================================================================
class TestPressure:
    @pytest.mark.parametrize("pt", NIST_SINGLE_PHASE, ids=[p["label"] for p in NIST_SINGLE_PHASE])
    def test_pressure(self, pt):
        T = pt["T"]
        rho = pt["rho_mass"] / M
        P_ref = pt["P_MPa"] * 1e6
        P_calc = co2_eos.pressure(T, rho)
        assert rel_err(P_calc, P_ref) < 0.001, (
            f"P at {pt['label']}: calc={P_calc:.6g}, ref={P_ref:.6g}, err={rel_err(P_calc, P_ref):.2e}"
        )


# ===========================================================================
# Test 2: Heat capacities
# ===========================================================================
class TestHeatCapacities:
    @pytest.mark.parametrize("pt", NIST_SINGLE_PHASE, ids=[p["label"] for p in NIST_SINGLE_PHASE])
    def test_cv(self, pt):
        T = pt["T"]
        rho = pt["rho_mass"] / M
        cv_ref = pt["cv_mass"] * MG
        cv_calc = co2_eos.cv(T, rho)
        assert rel_err(cv_calc, cv_ref) < 0.001, (
            f"cv at {pt['label']}: calc={cv_calc:.6g}, ref={cv_ref:.6g}, err={rel_err(cv_calc, cv_ref):.2e}"
        )

    @pytest.mark.parametrize("pt", NIST_SINGLE_PHASE, ids=[p["label"] for p in NIST_SINGLE_PHASE])
    def test_cp(self, pt):
        T = pt["T"]
        rho = pt["rho_mass"] / M
        cp_ref = pt["cp_mass"] * MG
        cp_calc = co2_eos.cp(T, rho)
        # Near-critical point has elevated cp sensitivity
        tol = 0.01 if "near-critical" in pt["label"] else 0.001
        assert rel_err(cp_calc, cp_ref) < tol, (
            f"cp at {pt['label']}: calc={cp_calc:.6g}, ref={cp_ref:.6g}, err={rel_err(cp_calc, cp_ref):.2e}"
        )


# ===========================================================================
# Test 3: Speed of sound
# ===========================================================================
class TestSpeedOfSound:
    @pytest.mark.parametrize("pt", NIST_SINGLE_PHASE, ids=[p["label"] for p in NIST_SINGLE_PHASE])
    def test_w(self, pt):
        T = pt["T"]
        rho = pt["rho_mass"] / M
        w_ref = pt["w"]
        w_calc = co2_eos.speed_of_sound(T, rho)
        tol = 0.005 if "near-critical" in pt["label"] else 0.001
        assert rel_err(w_calc, w_ref) < tol, (
            f"w at {pt['label']}: calc={w_calc:.6g}, ref={w_ref:.6g}, err={rel_err(w_calc, w_ref):.2e}"
        )


# ===========================================================================
# Test 4: Enthalpy and entropy (IIR reference state)
# ===========================================================================
class TestEnthalpyEntropy:
    @pytest.mark.parametrize("pt", NIST_SINGLE_PHASE, ids=[p["label"] for p in NIST_SINGLE_PHASE])
    def test_enthalpy(self, pt):
        T = pt["T"]
        rho = pt["rho_mass"] / M
        h_ref = pt["h_mass"] * MG  # kJ/kg -> J/mol
        h_calc = co2_eos.enthalpy(T, rho)
        assert rel_err(h_calc, h_ref) < 0.001, (
            f"h at {pt['label']}: calc={h_calc:.6g}, ref={h_ref:.6g}, err={rel_err(h_calc, h_ref):.2e}"
        )

    @pytest.mark.parametrize("pt", NIST_SINGLE_PHASE, ids=[p["label"] for p in NIST_SINGLE_PHASE])
    def test_entropy(self, pt):
        T = pt["T"]
        rho = pt["rho_mass"] / M
        s_ref = pt["s_mass"] * MG  # J/(g*K) -> J/(mol*K)
        s_calc = co2_eos.entropy(T, rho)
        assert rel_err(s_calc, s_ref) < 0.001, (
            f"s at {pt['label']}: calc={s_calc:.6g}, ref={s_ref:.6g}, err={rel_err(s_calc, s_ref):.2e}"
        )


# ===========================================================================
# Test 5: Saturation solver
# ===========================================================================
class TestSaturation:
    @pytest.mark.parametrize("pt", NIST_SATURATION,
                             ids=[f"T={p['T']}K" for p in NIST_SATURATION])
    def test_saturation_pressure(self, pt):
        T = pt["T"]
        P_ref = pt["P_MPa"] * 1e6
        P_calc = co2_eos.saturation_pressure(T)
        assert rel_err(P_calc, P_ref) < 0.002, (
            f"Psat at T={T}K: calc={P_calc:.6g}, ref={P_ref:.6g}, err={rel_err(P_calc, P_ref):.2e}"
        )

    @pytest.mark.parametrize("pt", NIST_SATURATION,
                             ids=[f"T={p['T']}K" for p in NIST_SATURATION])
    def test_saturation_densities(self, pt):
        T = pt["T"]
        rho_l_ref = pt["rho_l_mass"] / M
        rho_v_ref = pt["rho_v_mass"] / M
        rho_l_calc, rho_v_calc = co2_eos.saturation_densities(T)
        assert rel_err(rho_l_calc, rho_l_ref) < 0.005, (
            f"rho_l at T={T}K: calc={rho_l_calc:.6g}, ref={rho_l_ref:.6g}"
        )
        assert rel_err(rho_v_calc, rho_v_ref) < 0.005, (
            f"rho_v at T={T}K: calc={rho_v_calc:.6g}, ref={rho_v_ref:.6g}"
        )


# ===========================================================================
# Test 6: Density solver consistency
# ===========================================================================
class TestDensitySolver:
    def test_density_liquid(self):
        T, P = 250.0, 1.7850442e6
        rho = co2_eos.density(T, P, "liquid")
        P_back = co2_eos.pressure(T, rho)
        assert rel_err(P_back, P) < 0.001

    def test_density_vapor(self):
        T, P = 250.0, 1.7850442e6
        rho = co2_eos.density(T, P, "vapor")
        P_back = co2_eos.pressure(T, rho)
        assert rel_err(P_back, P) < 0.001

    def test_density_supercritical(self):
        T, P = 350.0, 13.0e6
        rho = co2_eos.density(T, P, "supercritical")
        P_back = co2_eos.pressure(T, rho)
        assert rel_err(P_back, P) < 0.001


# ===========================================================================
# Test 7: Makefile and pipeline
# ===========================================================================
class TestMakefile:
    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile"), "Makefile not found at /app/Makefile"

    def test_makefile_has_targets(self):
        with open("/app/Makefile") as f:
            content = f.read()
        for target in ["extract", "compute", "diagram", "all"]:
            assert target in content, f"Makefile missing target: {target}"

    def test_extract_used_jq(self):
        """The extract target must use jq."""
        with open("/app/Makefile") as f:
            content = f.read()
        assert "jq" in content, "Makefile extract target must use jq"

    def test_coefficients_extracted(self):
        """co2_coefficients.json must exist and have valid structure."""
        path = "/app/co2_coefficients.json"
        assert os.path.isfile(path), "co2_coefficients.json not produced by make extract"
        with open(path) as f:
            data = json.load(f)
        assert "gas_constant" in data, "co2_coefficients.json missing gas_constant"
        assert "molar_mass" in data, "co2_coefficients.json missing molar_mass"
        assert "alpha0" in data, "co2_coefficients.json missing alpha0"
        assert "alphar" in data, "co2_coefficients.json missing alphar"
        assert isinstance(data["alpha0"], list), "alpha0 must be a list"
        assert isinstance(data["alphar"], list), "alphar must be a list"
        assert len(data["alphar"]) >= 2, "alphar must have at least 2 term groups"

    def test_diagram_used_gnuplot(self):
        """The diagram target must use gnuplot."""
        with open("/app/Makefile") as f:
            content = f.read()
        assert "gnuplot" in content, "Makefile diagram target must use gnuplot"

    def test_diagram_exists(self):
        """ph_diagram.png must exist and be a valid PNG."""
        path = "/app/ph_diagram.png"
        assert os.path.isfile(path), "ph_diagram.png not produced by make diagram"
        with open(path, "rb") as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', "ph_diagram.png is not a valid PNG file"
        fsize = os.path.getsize(path)
        assert fsize > 1000, f"ph_diagram.png too small ({fsize} bytes), likely empty"


# ===========================================================================
# Test 8: Cycle results
# ===========================================================================
class TestCycleResults:
    @pytest.fixture(autouse=True)
    def load_results(self):
        results_path = "/app/results.json"
        assert os.path.isfile(results_path), "results.json not found at /app/results.json"
        with open(results_path) as f:
            self.results = json.load(f)

    def test_schema(self):
        required_keys = ["P_evap_Pa", "state1", "state2", "state3",
                         "COP_cooling", "COP_heating", "compressor_work_J_mol"]
        for k in required_keys:
            assert k in self.results, f"Missing key: {k}"
        state_keys = ["T_K", "P_Pa", "rho_mol_m3", "h_J_mol", "s_J_molK"]
        for s in ["state1", "state2", "state3"]:
            for k in state_keys:
                assert k in self.results[s], f"Missing key {k} in {s}"

    def test_cop_range(self):
        cop_c = self.results["COP_cooling"]
        cop_h = self.results["COP_heating"]
        assert 1.0 < cop_c < 6.0, f"COP_cooling={cop_c} out of physical range"
        assert 2.0 < cop_h < 7.0, f"COP_heating={cop_h} out of physical range"

    def test_energy_balance(self):
        """COP_heating must equal COP_cooling + 1 (exact thermodynamic identity)."""
        cop_c = self.results["COP_cooling"]
        cop_h = self.results["COP_heating"]
        assert abs(cop_h - cop_c - 1.0) < 0.01, (
            f"Energy balance violated: COP_h={cop_h:.4f}, COP_c={cop_c:.4f}, diff={cop_h-cop_c:.4f}"
        )

    def test_compressor_work_positive(self):
        w = self.results["compressor_work_J_mol"]
        assert w > 0, f"Compressor work must be positive, got {w}"

    def test_state_pressures(self):
        """State 2 and 3 must be at gas cooler pressure."""
        with open("/app/cycle_params.json") as f:
            params = json.load(f)
        P_gc = params["P_gas_cooler_Pa"]
        assert rel_err(self.results["state2"]["P_Pa"], P_gc) < 0.01
        assert rel_err(self.results["state3"]["P_Pa"], P_gc) < 0.01

    def test_state1_conditions(self):
        """State 1 must be at evaporator conditions."""
        with open("/app/cycle_params.json") as f:
            params = json.load(f)
        T1_expected = params["T_evap_K"] + params["superheat_K"]
        assert rel_err(self.results["state1"]["T_K"], T1_expected) < 0.001
        P_evap = self.results["P_evap_Pa"]
        assert rel_err(self.results["state1"]["P_Pa"], P_evap) < 0.01

    def test_entropy_increase(self):
        """Compressor outlet entropy must be >= inlet (irreversible process)."""
        s1 = self.results["state1"]["s_J_molK"]
        s2 = self.results["state2"]["s_J_molK"]
        assert s2 >= s1 - 0.1, f"s2={s2} < s1={s1}: entropy should not decrease in compression"

    def test_cop_self_consistency(self):
        """Verify COP is consistent with state point enthalpies."""
        h1 = self.results["state1"]["h_J_mol"]
        h2 = self.results["state2"]["h_J_mol"]
        h3 = self.results["state3"]["h_J_mol"]
        w = h2 - h1
        cop_c_check = (h1 - h3) / w
        cop_h_check = (h2 - h3) / w
        assert rel_err(self.results["COP_cooling"], cop_c_check) < 0.001
        assert rel_err(self.results["COP_heating"], cop_h_check) < 0.001
