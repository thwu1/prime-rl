
import json
import csv
import math
import pytest
from CoolProp.CoolProp import PropsSI


# ---- Data loading helpers ----

def load_results():
    with open("/app/audit_results.json") as f:
        return json.load(f)


def load_systems():
    with open("/app/data/systems.json") as f:
        return json.load(f)["systems"]


def load_conditions():
    with open("/app/data/site/conditions.json") as f:
        return json.load(f)


def load_ambient():
    bins = []
    with open("/app/data/site/ambient_profile.csv") as f:
        for row in csv.DictReader(f):
            bins.append({"T_ambient_C": float(row["T_ambient_C"]),
                         "hours": float(row["hours_per_year"])})
    return bins


def load_environmental():
    with open("/app/data/site/environmental.json") as f:
        return json.load(f)


def load_compressor(model):
    with open(f"/app/data/equipment/compressors/{model}.json") as f:
        return json.load(f)


def load_inventory():
    inv = {}
    with open("/app/data/refrigerant_inventory.csv") as f:
        for row in csv.DictReader(f):
            sid = row["system_id"]
            if sid not in inv:
                inv[sid] = {}
            inv[sid][row["circuit"]] = {
                "charge_kg": float(row["charge_kg"]),
                "gwp": float(row["gwp"])
            }
    return inv


# ---- Computation helpers ----

def eval_eta(comp_spec, PR):
    """Evaluate compressor isentropic efficiency from polynomial curve."""
    c = comp_spec["efficiency_curve"]["coefficients"]
    eta = c[0] + c[1] * PR + c[2] * PR ** 2
    return max(0.1, min(0.95, eta))


def compute_cascade_cop(T_cascade_C, T_evap_C, T_cond_C, approach_K,
                        Q_kW, ltc_fluid, htc_fluid, ltc_comp, htc_comp):
    """Independent COP calculation with variable compressor efficiency."""
    T_evap = T_evap_C + 273.15
    T_cond = T_cond_C + 273.15
    T_cas = T_cascade_C + 273.15
    T_evap_htc = T_cas - approach_K
    Q = Q_kW * 1000.0

    # LTC
    h1 = PropsSI("H", "T", T_evap, "Q", 1, ltc_fluid)
    s1 = PropsSI("S", "T", T_evap, "Q", 1, ltc_fluid)
    P_e_ltc = PropsSI("P", "T", T_evap, "Q", 0, ltc_fluid)
    P_c_ltc = PropsSI("P", "T", T_cas, "Q", 0, ltc_fluid)
    PR_ltc = P_c_ltc / P_e_ltc
    eta_ltc = eval_eta(ltc_comp, PR_ltc)
    h2s = PropsSI("H", "P", P_c_ltc, "S", s1, ltc_fluid)
    h2 = h1 + (h2s - h1) / eta_ltc
    h3 = PropsSI("H", "T", T_cas, "Q", 0, ltc_fluid)
    h4 = h3

    m_ltc = Q / (h1 - h4)
    W_ltc = m_ltc * (h2 - h1)
    Q_cas = m_ltc * (h2 - h3)

    # HTC
    h5 = PropsSI("H", "T", T_evap_htc, "Q", 1, htc_fluid)
    s5 = PropsSI("S", "T", T_evap_htc, "Q", 1, htc_fluid)
    P_e_htc = PropsSI("P", "T", T_evap_htc, "Q", 0, htc_fluid)
    P_c_htc = PropsSI("P", "T", T_cond, "Q", 0, htc_fluid)
    PR_htc = P_c_htc / P_e_htc
    eta_htc = eval_eta(htc_comp, PR_htc)
    h6s = PropsSI("H", "P", P_c_htc, "S", s5, htc_fluid)
    h6 = h5 + (h6s - h5) / eta_htc
    h7 = PropsSI("H", "T", T_cond, "Q", 0, htc_fluid)
    h8 = h7

    m_htc = Q_cas / (h5 - h8)
    W_htc = m_htc * (h6 - h5)
    W_total = W_ltc + W_htc
    COP = Q / W_total

    return COP, W_total / 1000, W_ltc / 1000, W_htc / 1000, m_ltc, m_htc


def get_system_specs(sys_def):
    """Load compressor specs for a system definition."""
    ltc_comp = load_compressor(sys_def["ltc"]["compressor_model"])
    htc_comp = load_compressor(sys_def["htc"]["compressor_model"])
    return sys_def["ltc"]["fluid"], sys_def["htc"]["fluid"], ltc_comp, htc_comp


# ---- Structural tests ----

class TestStructure:
    def test_results_exists(self):
        r = load_results()
        assert isinstance(r, dict)

    def test_top_level_keys(self):
        r = load_results()
        assert "systems" in r
        assert "best_seasonal_COP" in r
        assert "lowest_TEWI" in r

    def test_three_systems(self):
        assert len(load_results()["systems"]) == 3

    def test_system_keys(self):
        required = ["system_id", "ltc_fluid", "htc_fluid",
                     "design_point", "seasonal", "TEWI"]
        for s in load_results()["systems"]:
            for k in required:
                assert k in s, f"Missing system key: {k}"

    def test_design_point_keys(self):
        required = ["T_cond_C", "optimal_cascade_T_C", "COP", "carnot_COP",
                     "second_law_efficiency", "W_total_kW", "W_ltc_kW", "W_htc_kW",
                     "exergy_destruction_total_kW", "dominant_irreversibility"]
        for s in load_results()["systems"]:
            for k in required:
                assert k in s["design_point"], f"Missing design_point key: {k}"

    def test_seasonal_keys(self):
        for s in load_results()["systems"]:
            assert "COP" in s["seasonal"]
            assert "annual_energy_kWh" in s["seasonal"]
            assert "per_bin" in s["seasonal"]

    def test_tewi_keys(self):
        for s in load_results()["systems"]:
            assert "direct_kg_CO2" in s["TEWI"]
            assert "indirect_kg_CO2" in s["TEWI"]
            assert "total_kg_CO2" in s["TEWI"]

    def test_per_bin_count(self):
        ambient = load_ambient()
        for s in load_results()["systems"]:
            assert len(s["seasonal"]["per_bin"]) == len(ambient), \
                f"Expected {len(ambient)} bins, got {len(s['seasonal']['per_bin'])}"

    def test_per_bin_keys(self):
        for s in load_results()["systems"]:
            for b in s["seasonal"]["per_bin"]:
                assert "T_ambient_C" in b
                assert "COP" in b
                assert "optimal_cascade_T_C" in b


# ---- Physical constraint tests ----

class TestPhysics:
    def test_cop_positive(self):
        for s in load_results()["systems"]:
            assert s["design_point"]["COP"] > 0

    def test_cop_less_than_carnot(self):
        for s in load_results()["systems"]:
            dp = s["design_point"]
            assert dp["COP"] < dp["carnot_COP"], \
                f"COP ({dp['COP']}) >= Carnot ({dp['carnot_COP']})"

    def test_second_law_bounded(self):
        for s in load_results()["systems"]:
            eta = s["design_point"]["second_law_efficiency"]
            assert 0 < eta < 1, f"second_law_efficiency out of bounds: {eta}"

    def test_work_positive(self):
        for s in load_results()["systems"]:
            dp = s["design_point"]
            assert dp["W_total_kW"] > 0
            assert dp["W_ltc_kW"] > 0
            assert dp["W_htc_kW"] > 0

    def test_work_sum(self):
        for s in load_results()["systems"]:
            dp = s["design_point"]
            assert abs(dp["W_total_kW"] - dp["W_ltc_kW"] - dp["W_htc_kW"]) < 0.1

    def test_cascade_temp_feasible(self):
        cond = load_conditions()
        for s in load_results()["systems"]:
            T = s["design_point"]["optimal_cascade_T_C"]
            assert cond["evaporator_temperature_C"] < T < s["design_point"]["T_cond_C"]

    def test_cop_realistic(self):
        for s in load_results()["systems"]:
            cop = s["design_point"]["COP"]
            assert 0.5 < cop < 5.0, f"COP out of range: {cop}"

    def test_carnot_cop_correct(self):
        cond = load_conditions()
        T_cond_d = cond["nominal_ambient_C"] + cond["condenser_approach_K"]
        T_L = cond["evaporator_temperature_C"] + 273.15
        T_H = T_cond_d + 273.15
        expected = T_L / (T_H - T_L)
        for s in load_results()["systems"]:
            ratio = abs(s["design_point"]["carnot_COP"] - expected) / expected
            assert ratio < 0.01, f"Carnot COP mismatch: {s['design_point']['carnot_COP']} vs {expected}"

    def test_second_law_consistency(self):
        for s in load_results()["systems"]:
            dp = s["design_point"]
            expected = dp["COP"] / dp["carnot_COP"]
            assert abs(dp["second_law_efficiency"] - expected) / expected < 0.01

    def test_exergy_destruction_positive(self):
        for s in load_results()["systems"]:
            assert s["design_point"]["exergy_destruction_total_kW"] > 0

    def test_dominant_irreversibility_valid(self):
        valid = {"compressor_ltc", "compressor_htc", "condenser", "evaporator",
                 "expansion_valve_ltc", "expansion_valve_htc", "cascade_hx"}
        for s in load_results()["systems"]:
            assert s["design_point"]["dominant_irreversibility"] in valid

    def test_design_cond_temp_correct(self):
        cond = load_conditions()
        expected = cond["nominal_ambient_C"] + cond["condenser_approach_K"]
        for s in load_results()["systems"]:
            assert abs(s["design_point"]["T_cond_C"] - expected) < 0.1


# ---- Design-point COP verification ----

class TestDesignPointCOP:
    def test_cop_accuracy(self):
        """Independently verify COP at reported optimal cascade temperature."""
        cond = load_conditions()
        systems_def = load_systems()
        results = load_results()
        T_cond_d = cond["nominal_ambient_C"] + cond["condenser_approach_K"]

        for i, sys_def in enumerate(systems_def):
            res = results["systems"][i]
            ltc_f, htc_f, ltc_c, htc_c = get_system_specs(sys_def)
            T_opt = res["design_point"]["optimal_cascade_T_C"]

            cop_ref, w_total, w_ltc, w_htc, _, _ = compute_cascade_cop(
                T_opt, cond["evaporator_temperature_C"], T_cond_d,
                cond["cascade_approach_K"], sys_def["cooling_capacity_kW"],
                ltc_f, htc_f, ltc_c, htc_c
            )
            assert abs(cop_ref - res["design_point"]["COP"]) / cop_ref < 0.02, \
                f"COP mismatch for {res['system_id']}: ref={cop_ref:.4f} rep={res['design_point']['COP']:.4f}"

    def test_work_accuracy(self):
        """Independently verify compressor power at reported cascade temperature."""
        cond = load_conditions()
        systems_def = load_systems()
        results = load_results()
        T_cond_d = cond["nominal_ambient_C"] + cond["condenser_approach_K"]

        for i, sys_def in enumerate(systems_def):
            res = results["systems"][i]
            ltc_f, htc_f, ltc_c, htc_c = get_system_specs(sys_def)
            T_opt = res["design_point"]["optimal_cascade_T_C"]

            _, w_total, w_ltc, w_htc, _, _ = compute_cascade_cop(
                T_opt, cond["evaporator_temperature_C"], T_cond_d,
                cond["cascade_approach_K"], sys_def["cooling_capacity_kW"],
                ltc_f, htc_f, ltc_c, htc_c
            )
            assert abs(w_total - res["design_point"]["W_total_kW"]) / w_total < 0.02
            assert abs(w_ltc - res["design_point"]["W_ltc_kW"]) / w_ltc < 0.05
            assert abs(w_htc - res["design_point"]["W_htc_kW"]) / w_htc < 0.05


# ---- Optimization quality ----

class TestOptimization:
    def test_design_point_local_max(self):
        """COP at reported optimal T should be >= COP at nearby temperatures."""
        cond = load_conditions()
        systems_def = load_systems()
        results = load_results()
        T_cond_d = cond["nominal_ambient_C"] + cond["condenser_approach_K"]

        for i, sys_def in enumerate(systems_def):
            res = results["systems"][i]
            ltc_f, htc_f, ltc_c, htc_c = get_system_specs(sys_def)
            T_opt = res["design_point"]["optimal_cascade_T_C"]

            cop_opt, *_ = compute_cascade_cop(
                T_opt, cond["evaporator_temperature_C"], T_cond_d,
                cond["cascade_approach_K"], sys_def["cooling_capacity_kW"],
                ltc_f, htc_f, ltc_c, htc_c
            )

            for dT in [-3.0, -1.5, 1.5, 3.0]:
                T_test = T_opt + dT
                if T_test <= cond["evaporator_temperature_C"] + 3:
                    continue
                if T_test >= T_cond_d - cond["cascade_approach_K"] - 2:
                    continue
                try:
                    cop_test, *_ = compute_cascade_cop(
                        T_test, cond["evaporator_temperature_C"], T_cond_d,
                        cond["cascade_approach_K"], sys_def["cooling_capacity_kW"],
                        ltc_f, htc_f, ltc_c, htc_c
                    )
                    assert cop_opt >= cop_test - 0.005, \
                        f"Not local max for {res['system_id']}: " \
                        f"COP({T_opt:.1f})={cop_opt:.4f} < COP({T_test:.1f})={cop_test:.4f}"
                except Exception:
                    pass


# ---- Per-bin COP verification ----

class TestPerBinCOP:
    def test_per_bin_cop_at_selected_ambients(self):
        """Verify COP at extreme and nominal ambient bins independently."""
        cond = load_conditions()
        systems_def = load_systems()
        results = load_results()
        ambient = load_ambient()

        test_ambs = {ambient[0]["T_ambient_C"], cond["nominal_ambient_C"],
                     ambient[-1]["T_ambient_C"]}

        for i, sys_def in enumerate(systems_def):
            res = results["systems"][i]
            ltc_f, htc_f, ltc_c, htc_c = get_system_specs(sys_def)

            for bin_data in res["seasonal"]["per_bin"]:
                if bin_data["T_ambient_C"] not in test_ambs:
                    continue
                T_cond_b = bin_data["T_ambient_C"] + cond["condenser_approach_K"]
                T_cas_b = bin_data.get("optimal_cascade_T_C")
                if T_cas_b is None:
                    continue
                try:
                    cop_ref, *_ = compute_cascade_cop(
                        T_cas_b, cond["evaporator_temperature_C"], T_cond_b,
                        cond["cascade_approach_K"], sys_def["cooling_capacity_kW"],
                        ltc_f, htc_f, ltc_c, htc_c
                    )
                    assert abs(cop_ref - bin_data["COP"]) / cop_ref < 0.02, \
                        f"Per-bin COP mismatch for {res['system_id']} " \
                        f"at T_amb={bin_data['T_ambient_C']}: " \
                        f"ref={cop_ref:.4f} rep={bin_data['COP']:.4f}"
                except Exception:
                    pass

    def test_per_bin_cop_all_positive(self):
        for s in load_results()["systems"]:
            for b in s["seasonal"]["per_bin"]:
                assert b["COP"] > 0, \
                    f"Non-positive per-bin COP for {s['system_id']} at T_amb={b['T_ambient_C']}"

    def test_per_bin_cascade_temp_feasible(self):
        cond = load_conditions()
        for s in load_results()["systems"]:
            for b in s["seasonal"]["per_bin"]:
                T_cond_b = b["T_ambient_C"] + cond["condenser_approach_K"]
                T_cas = b.get("optimal_cascade_T_C")
                if T_cas is not None:
                    assert cond["evaporator_temperature_C"] < T_cas < T_cond_b, \
                        f"Cascade T {T_cas} out of range for {s['system_id']}"


# ---- Seasonal COP verification ----

class TestSeasonalCOP:
    def test_seasonal_cop_formula(self):
        """Verify seasonal COP = total_hours / sum(hours_i / COP_i)."""
        ambient = load_ambient()
        results = load_results()

        for sys in results["systems"]:
            per_bin = sys["seasonal"]["per_bin"]
            total_hours = sum(b["hours"] for b in ambient)
            sum_h_over_cop = 0.0
            for b_data, b_amb in zip(per_bin, ambient):
                sum_h_over_cop += b_amb["hours"] / b_data["COP"]
            expected_scop = total_hours / sum_h_over_cop
            assert abs(sys["seasonal"]["COP"] - expected_scop) / expected_scop < 0.01, \
                f"Seasonal COP mismatch for {sys['system_id']}: " \
                f"expected={expected_scop:.4f} got={sys['seasonal']['COP']:.4f}"

    def test_annual_energy_formula(self):
        """Verify annual_energy = Q_evap * sum(hours_i / COP_i)."""
        ambient = load_ambient()
        results = load_results()
        systems_def = load_systems()

        for i, sys in enumerate(results["systems"]):
            Q = systems_def[i]["cooling_capacity_kW"]
            per_bin = sys["seasonal"]["per_bin"]
            sum_h_over_cop = 0.0
            for b_data, b_amb in zip(per_bin, ambient):
                sum_h_over_cop += b_amb["hours"] / b_data["COP"]
            expected_energy = Q * sum_h_over_cop
            assert abs(sys["seasonal"]["annual_energy_kWh"] - expected_energy) / expected_energy < 0.01, \
                f"Annual energy mismatch for {sys['system_id']}"

    def test_seasonal_cop_between_min_max_bin(self):
        """Seasonal COP (harmonic mean) should be between min and max bin COP."""
        for sys in load_results()["systems"]:
            min_cop = min(b["COP"] for b in sys["seasonal"]["per_bin"])
            max_cop = max(b["COP"] for b in sys["seasonal"]["per_bin"])
            assert min_cop - 0.01 <= sys["seasonal"]["COP"] <= max_cop + 0.01, \
                f"Seasonal COP {sys['seasonal']['COP']} outside [{min_cop}, {max_cop}]"

    def test_low_ambient_higher_cop(self):
        """COP at low ambient should be higher than at high ambient."""
        for sys in load_results()["systems"]:
            bins = sys["seasonal"]["per_bin"]
            lowest = min(bins, key=lambda b: b["T_ambient_C"])
            highest = max(bins, key=lambda b: b["T_ambient_C"])
            assert lowest["COP"] > highest["COP"], \
                f"Expected COP at T_amb={lowest['T_ambient_C']} > " \
                f"COP at T_amb={highest['T_ambient_C']} for {sys['system_id']}"

    def test_seasonal_cop_positive(self):
        for sys in load_results()["systems"]:
            assert sys["seasonal"]["COP"] > 0
            assert sys["seasonal"]["annual_energy_kWh"] > 0


# ---- TEWI verification ----

class TestTEWI:
    def test_direct_tewi(self):
        """Independently verify direct TEWI from inventory and environmental data."""
        env = load_environmental()
        inv = load_inventory()
        results = load_results()
        n = env["system_lifetime_years"]
        L = env["annual_leakage_rate"]
        alpha = env["recovery_efficiency"]

        for sys in results["systems"]:
            sid = sys["system_id"]
            gwp_charge = (inv[sid]["ltc"]["gwp"] * inv[sid]["ltc"]["charge_kg"] +
                          inv[sid]["htc"]["gwp"] * inv[sid]["htc"]["charge_kg"])
            expected = gwp_charge * L * n + gwp_charge * (1 - alpha)
            if expected > 1.0:
                assert abs(sys["TEWI"]["direct_kg_CO2"] - expected) / expected < 0.02, \
                    f"Direct TEWI mismatch for {sid}: expected={expected:.0f} got={sys['TEWI']['direct_kg_CO2']:.0f}"
            else:
                assert abs(sys["TEWI"]["direct_kg_CO2"] - expected) < 10.0

    def test_indirect_tewi(self):
        """Verify indirect TEWI from annual energy and grid carbon intensity."""
        env = load_environmental()
        results = load_results()
        n = env["system_lifetime_years"]
        beta = env["grid_carbon_intensity_kgCO2_per_kWh"]

        for sys in results["systems"]:
            annual_e = sys["seasonal"]["annual_energy_kWh"]
            expected = n * annual_e * beta
            assert abs(sys["TEWI"]["indirect_kg_CO2"] - expected) / expected < 0.02, \
                f"Indirect TEWI mismatch for {sys['system_id']}"

    def test_tewi_total(self):
        for sys in load_results()["systems"]:
            total = sys["TEWI"]["direct_kg_CO2"] + sys["TEWI"]["indirect_kg_CO2"]
            assert abs(sys["TEWI"]["total_kg_CO2"] - total) / max(total, 1.0) < 0.01


# ---- Rankings ----

class TestRankings:
    def test_best_seasonal_cop(self):
        results = load_results()
        best = max(results["systems"], key=lambda s: s["seasonal"]["COP"])
        assert results["best_seasonal_COP"] == best["system_id"]

    def test_lowest_tewi(self):
        results = load_results()
        lowest = min(results["systems"], key=lambda s: s["TEWI"]["total_kg_CO2"])
        assert results["lowest_TEWI"] == lowest["system_id"]

    def test_natural_refrigerants_lower_tewi(self):
        """CO2/NH3 (GWP 1/0) should have lower TEWI than R23/R134a (GWP 14800/1430)."""
        results = load_results()
        systems = {s["system_id"]: s for s in results["systems"]}
        assert systems["SYS-A"]["TEWI"]["total_kg_CO2"] < systems["SYS-C"]["TEWI"]["total_kg_CO2"]

    def test_r23_not_lowest_tewi(self):
        """R23 has GWP=14800 so SYS-C should not be lowest TEWI."""
        results = load_results()
        assert results["lowest_TEWI"] != "SYS-C"


# ---- Exergy consistency ----

class TestExergyConsistency:
    def test_exergy_equals_work_minus_product(self):
        """Gouy-Stodola: total exergy destruction = W_total - product_exergy."""
        cond = load_conditions()
        systems_def = load_systems()
        T_0 = cond["dead_state_temperature_C"] + 273.15
        T_L = cond["evaporator_temperature_C"] + 273.15

        for i, sys in enumerate(load_results()["systems"]):
            Q = systems_def[i]["cooling_capacity_kW"]
            product_ex = Q * (T_0 / T_L - 1.0)
            dp = sys["design_point"]
            expected_ed = dp["W_total_kW"] - product_ex
            assert abs(dp["exergy_destruction_total_kW"] - expected_ed) / expected_ed < 0.05, \
                f"Exergy balance mismatch for {sys['system_id']}: " \
                f"Ed={dp['exergy_destruction_total_kW']:.2f} vs W-Ex_prod={expected_ed:.2f}"

    def test_dominant_matches_independent(self):
        """Verify dominant irreversibility by independent exergy calculation."""
        cond = load_conditions()
        systems_def = load_systems()
        T_0 = cond["dead_state_temperature_C"] + 273.15
        T_cond_d = cond["nominal_ambient_C"] + cond["condenser_approach_K"]
        T_evap_C = cond["evaporator_temperature_C"]
        approach_K = cond["cascade_approach_K"]

        for i, sys_def in enumerate(systems_def):
            res = load_results()["systems"][i]
            T_opt = res["design_point"]["optimal_cascade_T_C"]
            ltc_f, htc_f, ltc_c, htc_c = get_system_specs(sys_def)
            Q_kW = sys_def["cooling_capacity_kW"]

            T_evap_K = T_evap_C + 273.15
            T_cas_K = T_opt + 273.15
            T_cond_K = T_cond_d + 273.15
            T_evap_htc_K = T_cas_K - approach_K
            Q_W = Q_kW * 1000.0

            # Recompute all state points
            h1 = PropsSI("H", "T", T_evap_K, "Q", 1, ltc_f)
            s1 = PropsSI("S", "T", T_evap_K, "Q", 1, ltc_f)
            P_e_l = PropsSI("P", "T", T_evap_K, "Q", 0, ltc_f)
            P_c_l = PropsSI("P", "T", T_cas_K, "Q", 0, ltc_f)
            eta_l = eval_eta(ltc_c, P_c_l / P_e_l)
            h2s = PropsSI("H", "P", P_c_l, "S", s1, ltc_f)
            h2 = h1 + (h2s - h1) / eta_l
            s2 = PropsSI("S", "H", h2, "P", P_c_l, ltc_f)
            h3 = PropsSI("H", "T", T_cas_K, "Q", 0, ltc_f)
            s3 = PropsSI("S", "T", T_cas_K, "Q", 0, ltc_f)
            h4 = h3
            s4 = PropsSI("S", "H", h4, "P", P_e_l, ltc_f)

            h5 = PropsSI("H", "T", T_evap_htc_K, "Q", 1, htc_f)
            s5 = PropsSI("S", "T", T_evap_htc_K, "Q", 1, htc_f)
            P_e_h = PropsSI("P", "T", T_evap_htc_K, "Q", 0, htc_f)
            P_c_h = PropsSI("P", "T", T_cond_K, "Q", 0, htc_f)
            eta_h = eval_eta(htc_c, P_c_h / P_e_h)
            h6s = PropsSI("H", "P", P_c_h, "S", s5, htc_f)
            h6 = h5 + (h6s - h5) / eta_h
            s6 = PropsSI("S", "H", h6, "P", P_c_h, htc_f)
            h7 = PropsSI("H", "T", T_cond_K, "Q", 0, htc_f)
            s7 = PropsSI("S", "T", T_cond_K, "Q", 0, htc_f)
            h8 = h7
            s8 = PropsSI("S", "H", h8, "P", P_e_h, htc_f)

            m_l = Q_W / (h1 - h4)
            m_h = m_l * (h2 - h3) / (h5 - h8)

            comps = {
                "compressor_ltc": T_0 * m_l * (s2 - s1) / 1000,
                "compressor_htc": T_0 * m_h * (s6 - s5) / 1000,
                "condenser": (T_0 * m_h * (s7 - s6) + m_h * (h6 - h7)) / 1000,
                "expansion_valve_ltc": T_0 * m_l * (s4 - s3) / 1000,
                "expansion_valve_htc": T_0 * m_h * (s8 - s7) / 1000,
                "cascade_hx": T_0 * (m_l * (s3 - s2) + m_h * (s5 - s8)) / 1000,
                "evaporator": T_0 * (m_l * (s1 - s4) - Q_W / T_evap_K) / 1000,
            }

            expected_dominant = max(comps, key=lambda k: comps[k])
            assert res["design_point"]["dominant_irreversibility"] == expected_dominant, \
                f"Dominant mismatch for {res['system_id']}: " \
                f"expected={expected_dominant} got={res['design_point']['dominant_irreversibility']}"


# ---- Cross-system consistency ----

class TestCrossSystem:
    def test_system_ids_match_data(self):
        """Reported system IDs must match the data files."""
        systems_def = load_systems()
        results = load_results()
        expected_ids = {s["id"] for s in systems_def}
        actual_ids = {s["system_id"] for s in results["systems"]}
        assert expected_ids == actual_ids

    def test_fluids_match_data(self):
        """Reported fluid names must match system definitions."""
        systems_def = load_systems()
        results = load_results()
        for sys_def, sys_res in zip(systems_def, results["systems"]):
            assert sys_res["ltc_fluid"] == sys_def["ltc"]["fluid"]
            assert sys_res["htc_fluid"] == sys_def["htc"]["fluid"]

    def test_ambient_bins_match_profile(self):
        """Per-bin ambient temperatures must match the ambient profile."""
        ambient = load_ambient()
        expected_temps = sorted([b["T_ambient_C"] for b in ambient])
        for sys in load_results()["systems"]:
            actual_temps = sorted([b["T_ambient_C"] for b in sys["seasonal"]["per_bin"]])
            assert actual_temps == expected_temps, \
                f"Ambient bins mismatch for {sys['system_id']}"
