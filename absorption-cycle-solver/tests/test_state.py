
import json
import subprocess
import sys
import math
import pytest

sys.path.insert(0, "/app")


# =============================================================================
# Correlation benchmark tests
# =============================================================================

class TestBubbleTemperature:

    CASES = [
        (0.1, 0.3, 303.114145),
        (0.2, 0.5, 287.349433),
        (0.5, 0.2, 372.106612),
        (0.5, 0.7, 291.056609),
        (1.0, 0.4, 356.482307),
        (1.0, 0.9, 301.925734),
        (1.5, 0.1, 442.543862),
        (2.0, 0.6, 352.042276),
        (0.05, 0.05, 337.570864),
        (2.0, 0.95, 324.745327),
    ]

    @pytest.mark.parametrize("p,x,expected", CASES)
    def test_bubble_temperature(self, p, x, expected):
        from nh3h2o_props import bubble_temperature
        result = bubble_temperature(p, x)
        assert abs(result - expected) < 0.01, (
            f"bubble_temperature({p}, {x}) = {result}, expected {expected}"
        )


class TestDewTemperature:

    CASES = [
        (0.1, 0.3, 363.194624),
        (0.2, 0.7, 361.033979),
        (0.5, 0.4, 407.420722),
        (0.5, 0.9, 361.070067),
        (1.0, 0.6, 418.506067),
        (1.5, 0.2, 461.512821),
        (2.0, 0.8, 420.863619),
        (0.05, 0.5, 339.047683),
        (1.0, 0.05, 450.514317),
        (2.0, 0.95, 382.341322),
    ]

    @pytest.mark.parametrize("p,y,expected", CASES)
    def test_dew_temperature(self, p, y, expected):
        from nh3h2o_props import dew_temperature
        result = dew_temperature(p, y)
        assert abs(result - expected) < 0.01, (
            f"dew_temperature({p}, {y}) = {result}, expected {expected}"
        )


class TestVaporComposition:

    CASES = [
        (0.05, 0.2, 0.93195779),
        (0.1, 0.4, 0.99405099),
        (0.2, 0.1, 0.67231613),
        (0.5, 0.5, 0.99400818),
        (1.0, 0.3, 0.90827980),
        (1.0, 0.7, 0.99832906),
        (1.5, 0.6, 0.99156131),
        (2.0, 0.2, 0.72167685),
        (0.05, 0.8, 0.99999832),
        (2.0, 0.9, 0.99953670),
    ]

    @pytest.mark.parametrize("p,x,expected", CASES)
    def test_vapor_composition(self, p, x, expected):
        from nh3h2o_props import vapor_composition
        result = vapor_composition(p, x)
        assert abs(result - expected) < 1e-4, (
            f"vapor_composition({p}, {x}) = {result}, expected {expected}"
        )


class TestLiquidEnthalpy:

    CASES = [
        (275, 0.3, -200.5596),
        (280, 0.6, -209.4527),
        (290, 0.5, -181.6531),
        (300, 0.1, 37.9072),
        (320, 0.4, -38.6137),
        (340, 0.8, 172.4887),
        (360, 0.2, 229.4313),
        (400, 0.7, 381.7899),
        (275, 0.9, -69.6826),
        (400, 0.1, 466.9131),
    ]

    @pytest.mark.parametrize("T,x,expected", CASES)
    def test_liquid_enthalpy(self, T, x, expected):
        from nh3h2o_props import liquid_enthalpy
        result = liquid_enthalpy(T, x)
        assert abs(result - expected) < 0.5, (
            f"liquid_enthalpy({T}, {x}) = {result}, expected {expected}"
        )


class TestVaporEnthalpy:

    CASES = [
        (240, 0.3, 2088.672),
        (250, 0.6, 1755.4486),
        (260, 0.9, 1398.5846),
        (270, 0.4, 2031.6651),
        (280, 0.7, 1687.3509),
        (290, 0.2, 2302.9904),
        (310, 0.5, 1988.0644),
        (320, 0.8, 1643.0898),
        (240, 0.1, 2312.0784),
        (320, 0.1, 2472.9598),
    ]

    @pytest.mark.parametrize("T,y,expected", CASES)
    def test_vapor_enthalpy(self, T, y, expected):
        from nh3h2o_props import vapor_enthalpy
        result = vapor_enthalpy(T, y)
        assert abs(result - expected) < 0.5, (
            f"vapor_enthalpy({T}, {y}) = {result}, expected {expected}"
        )


# =============================================================================
# Inverse function tests
# =============================================================================

class TestInverseFunctions:

    BUBBLE_PRESSURE_CASES = [
        (0.1, 0.3),
        (0.5, 0.5),
        (1.0, 0.2),
        (1.5, 0.7),
        (2.0, 0.4),
    ]

    @pytest.mark.parametrize("p_orig,x", BUBBLE_PRESSURE_CASES)
    def test_bubble_pressure_roundtrip(self, p_orig, x):
        from nh3h2o_props import bubble_temperature, bubble_pressure
        T = bubble_temperature(p_orig, x)
        p_recovered = bubble_pressure(T, x)
        rel_err = abs(p_recovered - p_orig) / p_orig
        assert rel_err < 1e-4, (
            f"Round-trip failed: p_orig={p_orig}, p_recovered={p_recovered}, rel_err={rel_err}"
        )

    LIQUID_COMPOSITION_CASES = [
        (0.2, 0.3),
        (0.5, 0.6),
        (1.0, 0.4),
        (1.5, 0.5),
        (2.0, 0.8),
    ]

    @pytest.mark.parametrize("p,x_orig", LIQUID_COMPOSITION_CASES)
    def test_liquid_composition_roundtrip(self, p, x_orig):
        from nh3h2o_props import bubble_temperature, liquid_composition
        T = bubble_temperature(p, x_orig)
        x_recovered = liquid_composition(p, T)
        rel_err = abs(x_recovered - x_orig) / x_orig
        assert rel_err < 1e-4, (
            f"Round-trip failed: x_orig={x_orig}, x_recovered={x_recovered}, rel_err={rel_err}"
        )


# =============================================================================
# Molar/mass fraction conversion tests
# =============================================================================

class TestFractionConversion:

    def test_molar_to_mass_pure_ammonia(self):
        from nh3h2o_props import molar_to_mass_fraction
        assert abs(molar_to_mass_fraction(1.0) - 1.0) < 1e-10

    def test_molar_to_mass_pure_water(self):
        from nh3h2o_props import molar_to_mass_fraction
        assert abs(molar_to_mass_fraction(0.0)) < 1e-10

    def test_molar_mass_roundtrip(self):
        from nh3h2o_props import molar_to_mass_fraction, mass_to_molar_fraction
        for x in [0.1, 0.3, 0.5, 0.7, 0.9]:
            w = molar_to_mass_fraction(x)
            x_back = mass_to_molar_fraction(w)
            assert abs(x_back - x) < 1e-10, f"Roundtrip failed for x={x}"

    def test_molar_to_mass_midpoint(self):
        from nh3h2o_props import molar_to_mass_fraction
        expected = 0.5 * 17.031 / (0.5 * 17.031 + 0.5 * 18.015)
        result = molar_to_mass_fraction(0.5)
        assert abs(result - expected) < 1e-8


# =============================================================================
# Cycle solver tests
# =============================================================================

def _run_cycle_solver(config_path):
    result = subprocess.run(
        [sys.executable, "/app/cycle_solver.py", "--config", config_path],
        capture_output=True, text=True, timeout=120, cwd="/app"
    )
    assert result.returncode == 0, (
        f"cycle_solver.py failed with code {result.returncode}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return json.loads(result.stdout)


class TestCycleSolverConfig1:

    @pytest.fixture(scope="class")
    def cycle_output(self):
        return _run_cycle_solver("/app/data/cycle_config.json")

    def test_output_has_required_keys(self, cycle_output):
        required = [
            "P_high_MPa", "P_low_MPa", "x_strong_molar", "x_weak_molar",
            "f_circulation_ratio", "COP_cooling",
            "Q_evap_kJ_per_kg_ref", "Q_gen_kJ_per_kg_ref",
            "Q_cond_kJ_per_kg_ref", "Q_abs_kJ_per_kg_ref",
            "state_points",
        ]
        for key in required:
            assert key in cycle_output, f"Missing output key: {key}"

    def test_state_points_complete(self, cycle_output):
        sp = cycle_output["state_points"]
        for i in range(1, 11):
            key = str(i)
            assert key in sp, f"Missing state point {key}"
            for field in ["T_K", "P_MPa", "x_molar", "h_kJ_per_kg"]:
                assert field in sp[key], f"State {key} missing field {field}"

    def test_pressure_ordering(self, cycle_output):
        P_low = cycle_output["P_low_MPa"]
        P_high = cycle_output["P_high_MPa"]
        assert 0 < P_low < P_high, f"Bad pressures: P_low={P_low}, P_high={P_high}"
        assert P_low > 0.1, f"P_low={P_low} too small"
        assert P_high < 3.0, f"P_high={P_high} too large"

    def test_composition_ordering(self, cycle_output):
        x_weak = cycle_output["x_weak_molar"]
        x_strong = cycle_output["x_strong_molar"]
        assert 0 < x_weak < x_strong < 1, (
            f"Bad compositions: x_weak={x_weak}, x_strong={x_strong}"
        )

    def test_circulation_ratio(self, cycle_output):
        f = cycle_output["f_circulation_ratio"]
        assert f > 1.0, f"Circulation ratio f={f} must be > 1"
        assert f < 50.0, f"Circulation ratio f={f} unreasonably large"

    def test_cop_range(self, cycle_output):
        cop = cycle_output["COP_cooling"]
        assert 0.1 < cop < 0.9, f"COP={cop} outside expected range [0.1, 0.9]"

    def test_heat_duties_positive(self, cycle_output):
        for key in ["Q_evap_kJ_per_kg_ref", "Q_gen_kJ_per_kg_ref",
                     "Q_cond_kJ_per_kg_ref", "Q_abs_kJ_per_kg_ref"]:
            assert cycle_output[key] > 0, f"{key}={cycle_output[key]} must be positive"

    def test_energy_balance_closure(self, cycle_output):
        Q_gen = cycle_output["Q_gen_kJ_per_kg_ref"]
        Q_evap = cycle_output["Q_evap_kJ_per_kg_ref"]
        Q_cond = cycle_output["Q_cond_kJ_per_kg_ref"]
        Q_abs = cycle_output["Q_abs_kJ_per_kg_ref"]
        imbalance = abs(Q_gen + Q_evap - Q_cond - Q_abs)
        assert imbalance < 0.01, (
            f"Energy balance failed: Q_gen({Q_gen}) + Q_evap({Q_evap}) "
            f"!= Q_cond({Q_cond}) + Q_abs({Q_abs}), imbalance={imbalance}"
        )

    def test_state_point_pressures_consistent(self, cycle_output):
        sp = cycle_output["state_points"]
        P_low = cycle_output["P_low_MPa"]
        P_high = cycle_output["P_high_MPa"]
        low_p_states = ["1", "6", "9", "10"]
        high_p_states = ["2", "3", "4", "5", "7", "8"]
        for s in low_p_states:
            assert abs(sp[s]["P_MPa"] - P_low) / P_low < 0.01, (
                f"State {s} pressure {sp[s]['P_MPa']} != P_low {P_low}"
            )
        for s in high_p_states:
            assert abs(sp[s]["P_MPa"] - P_high) / P_high < 0.01, (
                f"State {s} pressure {sp[s]['P_MPa']} != P_high {P_high}"
            )

    def test_isenthalpic_expansions(self, cycle_output):
        sp = cycle_output["state_points"]
        assert abs(sp["9"]["h_kJ_per_kg"] - sp["8"]["h_kJ_per_kg"]) < 0.01, (
            f"h9={sp['9']['h_kJ_per_kg']} != h8={sp['8']['h_kJ_per_kg']}"
        )
        assert abs(sp["6"]["h_kJ_per_kg"] - sp["5"]["h_kJ_per_kg"]) < 0.01, (
            f"h6={sp['6']['h_kJ_per_kg']} != h5={sp['5']['h_kJ_per_kg']}"
        )
        assert abs(sp["2"]["h_kJ_per_kg"] - sp["1"]["h_kJ_per_kg"]) < 0.01, (
            f"h2={sp['2']['h_kJ_per_kg']} != h1={sp['1']['h_kJ_per_kg']}"
        )

    def test_mass_balance_consistency(self, cycle_output):
        from nh3h2o_props import molar_to_mass_fraction
        x_strong = cycle_output["x_strong_molar"]
        x_weak = cycle_output["x_weak_molar"]
        f = cycle_output["f_circulation_ratio"]
        x_ref = 0.9999

        w_strong = molar_to_mass_fraction(x_strong)
        w_weak = molar_to_mass_fraction(x_weak)
        w_ref = molar_to_mass_fraction(x_ref)

        lhs = f * w_strong
        rhs = w_ref + (f - 1) * w_weak
        assert abs(lhs - rhs) < 0.001, (
            f"Mass balance: f*w_s={lhs} != w_ref + (f-1)*w_w={rhs}"
        )

    def test_shx_temperature(self, cycle_output):
        sp = cycle_output["state_points"]
        T_abs = 308.15
        T_gen = 373.15
        eps = 0.7
        T3_expected = T_abs + eps * (T_gen - T_abs)
        T3_actual = sp["3"]["T_K"]
        assert abs(T3_actual - T3_expected) < 0.1, (
            f"SHX T3={T3_actual}, expected {T3_expected}"
        )


class TestCycleSolverConfig2:

    CONFIG2 = {
        "T_evap_K": 263.15,
        "T_cond_K": 313.15,
        "T_gen_K": 383.15,
        "T_abs_K": 313.15,
        "shx_effectiveness": 0.5,
        "x_ref_molar": 0.999
    }

    @pytest.fixture(scope="class")
    def cycle_output(self, tmp_path_factory):
        cfg_path = str(tmp_path_factory.mktemp("cfg") / "config2.json")
        with open(cfg_path, "w") as f:
            json.dump(self.CONFIG2, f)
        return _run_cycle_solver(cfg_path)

    def test_pressure_ordering(self, cycle_output):
        assert 0 < cycle_output["P_low_MPa"] < cycle_output["P_high_MPa"]

    def test_composition_ordering(self, cycle_output):
        assert 0 < cycle_output["x_weak_molar"] < cycle_output["x_strong_molar"] < 1

    def test_cop_range(self, cycle_output):
        cop = cycle_output["COP_cooling"]
        assert 0.05 < cop < 0.9, f"COP={cop} outside expected range"

    def test_energy_balance_closure(self, cycle_output):
        Q_gen = cycle_output["Q_gen_kJ_per_kg_ref"]
        Q_evap = cycle_output["Q_evap_kJ_per_kg_ref"]
        Q_cond = cycle_output["Q_cond_kJ_per_kg_ref"]
        Q_abs = cycle_output["Q_abs_kJ_per_kg_ref"]
        imbalance = abs(Q_gen + Q_evap - Q_cond - Q_abs)
        assert imbalance < 0.01, f"Energy balance imbalance={imbalance}"

    def test_circulation_ratio(self, cycle_output):
        f = cycle_output["f_circulation_ratio"]
        assert f > 1.0

    def test_isenthalpic_expansions(self, cycle_output):
        sp = cycle_output["state_points"]
        assert abs(sp["9"]["h_kJ_per_kg"] - sp["8"]["h_kJ_per_kg"]) < 0.01
        assert abs(sp["6"]["h_kJ_per_kg"] - sp["5"]["h_kJ_per_kg"]) < 0.01
        assert abs(sp["2"]["h_kJ_per_kg"] - sp["1"]["h_kJ_per_kg"]) < 0.01

    def test_different_from_config1(self, cycle_output):
        result1 = _run_cycle_solver("/app/data/cycle_config.json")
        assert abs(cycle_output["COP_cooling"] - result1["COP_cooling"]) > 0.01, (
            "Different operating conditions should yield different COP"
        )


class TestCycleSolverConfig3:

    CONFIG3 = {
        "T_evap_K": 278.15,
        "T_cond_K": 303.15,
        "T_gen_K": 363.15,
        "T_abs_K": 303.15,
        "shx_effectiveness": 0.0,
        "x_ref_molar": 0.9999
    }

    @pytest.fixture(scope="class")
    def cycle_output(self, tmp_path_factory):
        cfg_path = str(tmp_path_factory.mktemp("cfg") / "config3.json")
        with open(cfg_path, "w") as f:
            json.dump(self.CONFIG3, f)
        return _run_cycle_solver(cfg_path)

    def test_pressure_ordering(self, cycle_output):
        assert 0 < cycle_output["P_low_MPa"] < cycle_output["P_high_MPa"]

    def test_composition_ordering(self, cycle_output):
        assert 0 < cycle_output["x_weak_molar"] < cycle_output["x_strong_molar"] < 1

    def test_cop_range(self, cycle_output):
        cop = cycle_output["COP_cooling"]
        assert 0.05 < cop < 0.9, f"COP={cop} outside expected range"

    def test_energy_balance_closure(self, cycle_output):
        Q_gen = cycle_output["Q_gen_kJ_per_kg_ref"]
        Q_evap = cycle_output["Q_evap_kJ_per_kg_ref"]
        Q_cond = cycle_output["Q_cond_kJ_per_kg_ref"]
        Q_abs = cycle_output["Q_abs_kJ_per_kg_ref"]
        imbalance = abs(Q_gen + Q_evap - Q_cond - Q_abs)
        assert imbalance < 0.01, f"Energy balance imbalance={imbalance}"

    def test_circulation_ratio(self, cycle_output):
        f = cycle_output["f_circulation_ratio"]
        assert f > 1.0

    def test_isenthalpic_expansions(self, cycle_output):
        sp = cycle_output["state_points"]
        assert abs(sp["9"]["h_kJ_per_kg"] - sp["8"]["h_kJ_per_kg"]) < 0.01
        assert abs(sp["6"]["h_kJ_per_kg"] - sp["5"]["h_kJ_per_kg"]) < 0.01
        assert abs(sp["2"]["h_kJ_per_kg"] - sp["1"]["h_kJ_per_kg"]) < 0.01

    def test_no_shx_effect_on_temperature(self, cycle_output):
        sp = cycle_output["state_points"]
        assert abs(sp["3"]["T_K"] - 303.15) < 0.1, (
            f"With eps=0, T3={sp['3']['T_K']} should equal T_abs=303.15"
        )

    def test_no_shx_effect_on_enthalpy(self, cycle_output):
        sp = cycle_output["state_points"]
        assert abs(sp["5"]["h_kJ_per_kg"] - sp["4"]["h_kJ_per_kg"]) < 0.1, (
            f"With eps=0, h5={sp['5']['h_kJ_per_kg']} should equal h4={sp['4']['h_kJ_per_kg']}"
        )

    def test_heat_duties_positive(self, cycle_output):
        for key in ["Q_evap_kJ_per_kg_ref", "Q_gen_kJ_per_kg_ref",
                     "Q_cond_kJ_per_kg_ref", "Q_abs_kJ_per_kg_ref"]:
            assert cycle_output[key] > 0, f"{key}={cycle_output[key]} must be positive"
