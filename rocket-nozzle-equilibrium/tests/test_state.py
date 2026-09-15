
"""
Tests for chemical equilibrium rocket nozzle performance calculator.
Verifies results against NASA RP-1311 Example 8 (LOX/LH2) reference data.
"""

import json
import os
import pytest

RESULTS_PATH = "/app/results.json"

# NASA RP-1311 Example 8 reference values
REF_CSTAR = 2332.3       # m/s
REF_T_CHAMBER = 3383.84  # K
REF_T_THROAT = 3185.67   # K
REF_P_THROAT = 30.655    # bar
REF_V_THROAT = 1537.9    # m/s

# Chamber mole fractions (equilibrium at 53.3172 bar)
REF_XH2 = 0.29479
REF_XH2O = 0.63456
REF_XOH = 0.03334
REF_XH = 0.03350

# Exit conditions: area_ratio, Isp, CF, Ivac, Mach, T, P_bar
REF_EXITS = [
    {"ar": 25,  "Isp": 4124.4, "CF": 1.7684, "Ivac": 4348.5, "Mach": 3.848, "T": 1468.16, "P": 0.20491},
    {"ar": 50,  "Isp": 4309.1, "CF": 1.8476, "Ivac": 4487.3, "Mach": 4.379, "T": 1219.61, "P": 0.08146},
    {"ar": 75,  "Isp": 4399.1, "CF": 1.8861, "Ivac": 4554.9, "Mach": 4.711, "T": 1088.64, "P": 0.04749},
]


def load_results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        return json.load(f)


def rel_error(computed, reference):
    """Relative error as fraction."""
    return abs(computed - reference) / abs(reference)


class TestResultsStructure:
    def test_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json must exist at /app/results.json"

    def test_top_level_keys(self):
        r = load_results()
        for key in ["chamber", "throat", "c_star_m_per_s", "exit_conditions"]:
            assert key in r, f"Missing top-level key: {key}"

    def test_chamber_keys(self):
        r = load_results()
        ch = r["chamber"]
        for key in ["temperature_K", "pressure_bar", "mole_fractions"]:
            assert key in ch, f"Missing chamber key: {key}"

    def test_throat_keys(self):
        r = load_results()
        th = r["throat"]
        for key in ["temperature_K", "pressure_bar", "velocity_m_per_s"]:
            assert key in th, f"Missing throat key: {key}"

    def test_exit_conditions_count(self):
        r = load_results()
        assert len(r["exit_conditions"]) == 3, "Must have 3 exit conditions"

    def test_exit_condition_keys(self):
        r = load_results()
        for ec in r["exit_conditions"]:
            for key in ["area_ratio", "temperature_K", "pressure_bar",
                        "mach_number", "isp_m_per_s", "ivac_m_per_s", "cf"]:
                assert key in ec, f"Missing exit condition key: {key}"


class TestChamberConditions:
    def test_chamber_temperature(self):
        r = load_results()
        T = r["chamber"]["temperature_K"]
        assert rel_error(T, REF_T_CHAMBER) < 0.015, \
            f"Chamber T={T:.1f} K, expected {REF_T_CHAMBER} K (>1.5% error)"

    def test_chamber_pressure(self):
        r = load_results()
        P = r["chamber"]["pressure_bar"]
        assert rel_error(P, 53.3172) < 0.001, \
            f"Chamber P={P:.4f} bar, expected 53.3172 bar"

    def test_mole_fraction_H2(self):
        r = load_results()
        xH2 = r["chamber"]["mole_fractions"].get("H2", 0)
        assert abs(xH2 - REF_XH2) < 0.015, \
            f"H2 mole fraction={xH2:.5f}, expected {REF_XH2} (abs error > 0.015)"

    def test_mole_fraction_H2O(self):
        r = load_results()
        xH2O = r["chamber"]["mole_fractions"].get("H2O", 0)
        assert abs(xH2O - REF_XH2O) < 0.015, \
            f"H2O mole fraction={xH2O:.5f}, expected {REF_XH2O} (abs error > 0.015)"

    def test_mole_fraction_OH(self):
        r = load_results()
        xOH = r["chamber"]["mole_fractions"].get("OH", 0)
        assert abs(xOH - REF_XOH) < 0.008, \
            f"OH mole fraction={xOH:.5f}, expected {REF_XOH} (abs error > 0.008)"

    def test_mole_fraction_H(self):
        r = load_results()
        xH = r["chamber"]["mole_fractions"].get("H", 0)
        assert abs(xH - REF_XH) < 0.008, \
            f"H mole fraction={xH:.5f}, expected {REF_XH} (abs error > 0.008)"


class TestCharacteristicVelocity:
    def test_c_star(self):
        r = load_results()
        cs = r["c_star_m_per_s"]
        assert rel_error(cs, REF_CSTAR) < 0.015, \
            f"c*={cs:.1f} m/s, expected {REF_CSTAR} m/s (>1.5% error)"


class TestThroatConditions:
    def test_throat_temperature(self):
        r = load_results()
        T = r["throat"]["temperature_K"]
        assert rel_error(T, REF_T_THROAT) < 0.015, \
            f"Throat T={T:.1f} K, expected {REF_T_THROAT} K (>1.5% error)"

    def test_throat_pressure(self):
        r = load_results()
        P = r["throat"]["pressure_bar"]
        assert rel_error(P, REF_P_THROAT) < 0.03, \
            f"Throat P={P:.3f} bar, expected {REF_P_THROAT} bar (>3% error)"

    def test_throat_velocity(self):
        r = load_results()
        v = r["throat"]["velocity_m_per_s"]
        assert rel_error(v, REF_V_THROAT) < 0.015, \
            f"Throat v={v:.1f} m/s, expected {REF_V_THROAT} m/s (>1.5% error)"


class TestExitConditions:
    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_exit_isp(self, idx):
        r = load_results()
        ref = REF_EXITS[idx]
        ec = r["exit_conditions"][idx]
        assert ec["area_ratio"] == ref["ar"], \
            f"Area ratio mismatch: {ec['area_ratio']} vs {ref['ar']}"
        assert rel_error(ec["isp_m_per_s"], ref["Isp"]) < 0.015, \
            f"Ae/At={ref['ar']}: Isp={ec['isp_m_per_s']:.1f}, expected {ref['Isp']} (>1.5%)"

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_exit_cf(self, idx):
        r = load_results()
        ref = REF_EXITS[idx]
        ec = r["exit_conditions"][idx]
        assert rel_error(ec["cf"], ref["CF"]) < 0.025, \
            f"Ae/At={ref['ar']}: CF={ec['cf']:.4f}, expected {ref['CF']} (>2.5%)"

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_exit_ivac(self, idx):
        r = load_results()
        ref = REF_EXITS[idx]
        ec = r["exit_conditions"][idx]
        assert rel_error(ec["ivac_m_per_s"], ref["Ivac"]) < 0.015, \
            f"Ae/At={ref['ar']}: Ivac={ec['ivac_m_per_s']:.1f}, expected {ref['Ivac']} (>1.5%)"

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_exit_mach(self, idx):
        r = load_results()
        ref = REF_EXITS[idx]
        ec = r["exit_conditions"][idx]
        assert rel_error(ec["mach_number"], ref["Mach"]) < 0.03, \
            f"Ae/At={ref['ar']}: Mach={ec['mach_number']:.3f}, expected {ref['Mach']} (>3%)"

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_exit_temperature(self, idx):
        r = load_results()
        ref = REF_EXITS[idx]
        ec = r["exit_conditions"][idx]
        assert rel_error(ec["temperature_K"], ref["T"]) < 0.02, \
            f"Ae/At={ref['ar']}: T={ec['temperature_K']:.1f}, expected {ref['T']} (>2%)"


class TestPhysicalConsistency:
    def test_isp_increases_with_area_ratio(self):
        r = load_results()
        isps = [ec["isp_m_per_s"] for ec in r["exit_conditions"]]
        assert isps[0] < isps[1] < isps[2], \
            f"Isp must increase with area ratio: {isps}"

    def test_cf_increases_with_area_ratio(self):
        r = load_results()
        cfs = [ec["cf"] for ec in r["exit_conditions"]]
        assert cfs[0] < cfs[1] < cfs[2], \
            f"CF must increase with area ratio: {cfs}"

    def test_exit_temp_decreases_with_area_ratio(self):
        r = load_results()
        temps = [ec["temperature_K"] for ec in r["exit_conditions"]]
        assert temps[0] > temps[1] > temps[2], \
            f"Exit T must decrease with area ratio: {temps}"

    def test_cf_equals_isp_over_cstar(self):
        r = load_results()
        cs = r["c_star_m_per_s"]
        for ec in r["exit_conditions"]:
            cf_calc = ec["isp_m_per_s"] / cs
            assert rel_error(ec["cf"], cf_calc) < 0.005, \
                f"CF consistency: CF={ec['cf']}, Isp/c*={cf_calc:.4f}"

    def test_throat_velocity_lt_chamber_zero(self):
        r = load_results()
        assert r["throat"]["velocity_m_per_s"] > 0, "Throat velocity must be positive"
        assert r["throat"]["temperature_K"] < r["chamber"]["temperature_K"], \
            "Throat T must be less than chamber T"

    def test_mole_fractions_sum_to_one(self):
        r = load_results()
        mf = r["chamber"]["mole_fractions"]
        total = sum(mf.values())
        assert abs(total - 1.0) < 0.01, \
            f"Mole fractions must sum to 1.0, got {total:.6f}"
