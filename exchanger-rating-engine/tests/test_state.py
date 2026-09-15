"""Verification tests for shell-and-tube heat exchanger rating tool.

"""

import json
import math
import subprocess
import pytest


# ============================================================================
# Helpers
# ============================================================================

def run_tool(case_file):
    """Run /app/hx_rate.py on the given case file, return parsed JSON."""
    result = subprocess.run(
        ["python3", "/app/hx_rate.py", case_file],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"Tool failed on {case_file}:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"Tool output is not valid JSON:\n{result.stdout[:500]}")


def rel_err(actual, expected):
    if expected == 0:
        return abs(actual)
    return abs(actual - expected) / abs(expected)


def assert_close(actual, expected, tol, label=""):
    err = rel_err(actual, expected)
    assert err <= tol, (
        f"{label}: expected {expected}, got {actual}, "
        f"rel_err={err:.4f} > tol={tol}"
    )


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def case1():
    return run_tool("/app/case1.json")

@pytest.fixture(scope="module")
def case2():
    return run_tool("/app/case2.json")

@pytest.fixture(scope="module")
def case3():
    return run_tool("/app/case3.json")

@pytest.fixture(scope="module")
def case4():
    return run_tool("/app/case4.json")


# ============================================================================
# Structural tests — all required keys present
# ============================================================================

REQUIRED_KEYS = {
    "lmtd": ["LMTD_K", "R", "P", "F", "LMTD_eff_K"],
    "tube_side": ["Re", "Pr", "Nu", "h_i_W_m2K", "flow_regime"],
    "shell_side": ["Re", "j_i", "J_c", "J_l", "J_b", "J_s", "J_r",
                   "h_ideal_W_m2K", "h_o_W_m2K"],
    "overall": ["U_clean_W_m2K", "U_dirty_W_m2K", "cleanliness_factor",
                "controlling_resistance"],
    "area": ["required_m2", "available_m2", "overdesign_pct"],
}


@pytest.mark.parametrize("case_file", [
    "/app/case1.json", "/app/case2.json", "/app/case3.json", "/app/case4.json",
])
def test_output_structure(case_file):
    out = run_tool(case_file)
    assert "heat_duty_W" in out, "Missing top-level key 'heat_duty_W'"
    for section, keys in REQUIRED_KEYS.items():
        assert section in out, f"Missing section '{section}'"
        for k in keys:
            assert k in out[section], f"Missing key '{section}.{k}'"


# ============================================================================
# Case 1: Turbulent both sides, 30-deg triangular, kerosene-water
# ============================================================================

class TestCase1:
    def test_lmtd(self, case1):
        expected = 20.0 / math.log(4.0 / 3.0)
        assert_close(case1["lmtd"]["LMTD_K"], expected, 0.005, "LMTD")

    def test_R(self, case1):
        assert_close(case1["lmtd"]["R"], 1.5, 0.005, "R")

    def test_P(self, case1):
        assert_close(case1["lmtd"]["P"], 1.0 / 3.0, 0.005, "P")

    def test_F_factor(self, case1):
        assert_close(case1["lmtd"]["F"], 0.9105, 0.01, "F-factor")

    def test_lmtd_eff(self, case1):
        assert_close(case1["lmtd"]["LMTD_eff_K"], 63.30, 0.01, "LMTD_eff")

    def test_tube_Re(self, case1):
        d_i = 0.01483
        n_pp = 224 / 2
        A = n_pp * math.pi / 4 * d_i ** 2
        v = 20.0 / (995.0 * A)
        Re_expected = 995.0 * v * d_i / 0.0008
        assert_close(case1["tube_side"]["Re"], Re_expected, 0.01, "Tube Re")

    def test_tube_Pr(self, case1):
        Pr_expected = 0.0008 * 4180.0 / 0.62
        assert_close(case1["tube_side"]["Pr"], Pr_expected, 0.005, "Tube Pr")

    def test_tube_regime(self, case1):
        assert case1["tube_side"]["flow_regime"] == "turbulent"

    def test_tube_h_i(self, case1):
        assert_close(case1["tube_side"]["h_i_W_m2K"], 5603.0, 0.05, "h_i")

    def test_shell_Re(self, case1):
        assert_close(case1["shell_side"]["Re"], 14117.0, 0.01, "Shell Re")

    def test_shell_J_c(self, case1):
        assert_close(case1["shell_side"]["J_c"], 1.0018, 0.02, "J_c")

    def test_shell_J_l(self, case1):
        assert_close(case1["shell_side"]["J_l"], 0.8343, 0.02, "J_l")

    def test_shell_J_b(self, case1):
        assert_close(case1["shell_side"]["J_b"], 0.9223, 0.02, "J_b")

    def test_shell_J_s(self, case1):
        assert_close(case1["shell_side"]["J_s"], 1.0, 0.005, "J_s")

    def test_shell_J_r(self, case1):
        assert_close(case1["shell_side"]["J_r"], 1.0, 0.005, "J_r")

    def test_shell_h_o(self, case1):
        assert_close(case1["shell_side"]["h_o_W_m2K"], 1061.0, 0.05, "h_o")

    def test_U_dirty(self, case1):
        assert_close(case1["overall"]["U_dirty_W_m2K"], 556.2, 0.05, "U_dirty")

    def test_U_clean(self, case1):
        assert_close(case1["overall"]["U_clean_W_m2K"], 819.8, 0.05, "U_clean")

    def test_U_clean_gt_dirty(self, case1):
        assert case1["overall"]["U_clean_W_m2K"] > case1["overall"]["U_dirty_W_m2K"]

    def test_cleanliness_factor(self, case1):
        cf = case1["overall"]["cleanliness_factor"]
        assert 0 < cf < 1, f"CF={cf} not in (0,1)"
        assert_close(cf, 0.6785, 0.03, "CF")

    def test_controlling_resistance(self, case1):
        assert case1["overall"]["controlling_resistance"] == "shell_film"

    def test_heat_duty(self, case1):
        assert_close(case1["heat_duty_W"], 1260000.0, 0.005, "Q")

    def test_available_area(self, case1):
        A_expected = 224 * math.pi * 0.01905 * 4.88
        assert_close(case1["area"]["available_m2"], A_expected, 0.005, "A_avail")

    def test_required_area(self, case1):
        assert_close(case1["area"]["required_m2"], 35.79, 0.05, "A_req")

    def test_overdesign(self, case1):
        assert_close(case1["area"]["overdesign_pct"], 82.80, 0.05, "OD%")


# ============================================================================
# Case 2: Laminar tube-side (viscous oil), 90-deg square layout
# ============================================================================

class TestCase2:
    def test_lmtd(self, case2):
        expected = 50.0 / math.log(5.0 / 3.0)
        assert_close(case2["lmtd"]["LMTD_K"], expected, 0.005, "LMTD")

    def test_R(self, case2):
        assert_close(case2["lmtd"]["R"], 2.0, 0.005, "R")

    def test_P(self, case2):
        assert_close(case2["lmtd"]["P"], 2.0 / 7.0, 0.005, "P")

    def test_F_factor(self, case2):
        assert_close(case2["lmtd"]["F"], 0.9045, 0.01, "F-factor")

    def test_tube_Re(self, case2):
        d_i = 0.02093
        A = 18 * math.pi / 4 * d_i ** 2
        v = 3.0 / (870.0 * A)
        Re_expected = 870.0 * v * d_i / 0.05
        assert_close(case2["tube_side"]["Re"], Re_expected, 0.01, "Tube Re")

    def test_tube_regime(self, case2):
        assert case2["tube_side"]["flow_regime"] == "laminar"

    def test_tube_h_i(self, case2):
        assert_close(case2["tube_side"]["h_i_W_m2K"], 97.73, 0.05, "h_i")

    def test_shell_Re(self, case2):
        assert_close(case2["shell_side"]["Re"], 8276.0, 0.01, "Shell Re")

    def test_shell_J_factors_range(self, case2):
        for jf in ["J_c", "J_l", "J_b", "J_s", "J_r"]:
            val = case2["shell_side"][jf]
            assert 0 < val <= 2.0, f"{jf}={val} out of range"

    def test_shell_J_s_not_one(self, case2):
        assert case2["shell_side"]["J_s"] < 1.0, "J_s should be < 1 for unequal spacing"

    def test_shell_h_o(self, case2):
        assert_close(case2["shell_side"]["h_o_W_m2K"], 589.0, 0.05, "h_o")

    def test_U_dirty(self, case2):
        assert_close(case2["overall"]["U_dirty_W_m2K"], 66.29, 0.05, "U_dirty")

    def test_U_clean_gt_dirty(self, case2):
        assert case2["overall"]["U_clean_W_m2K"] > case2["overall"]["U_dirty_W_m2K"]

    def test_controlling_resistance(self, case2):
        assert case2["overall"]["controlling_resistance"] == "tube_film"

    def test_heat_duty(self, case2):
        assert_close(case2["heat_duty_W"], 950000.0, 0.005, "Q")

    def test_available_area(self, case2):
        A_expected = 72 * math.pi * 0.0254 * 6.096
        assert_close(case2["area"]["available_m2"], A_expected, 0.005, "A_avail")

    def test_undersized(self, case2):
        assert case2["area"]["overdesign_pct"] < 0


# ============================================================================
# Case 3: R=1 edge case (water-water, equal flow rates)
# ============================================================================

class TestCase3:
    def test_lmtd_equal_dt(self, case3):
        assert_close(case3["lmtd"]["LMTD_K"], 40.0, 0.005, "LMTD (equal dT)")

    def test_R_is_one(self, case3):
        assert_close(case3["lmtd"]["R"], 1.0, 0.005, "R")

    def test_P(self, case3):
        assert_close(case3["lmtd"]["P"], 0.5, 0.005, "P")

    def test_F_factor_R1(self, case3):
        """F-factor at R=1 must NOT be 1.0 for a multi-pass exchanger."""
        F = case3["lmtd"]["F"]
        assert F < 0.95, f"F={F} is too high for R=1, P=0.5 multi-pass"
        assert_close(F, 0.8023, 0.01, "F-factor (R=1)")

    def test_F_in_valid_range(self, case3):
        F = case3["lmtd"]["F"]
        assert 0 < F <= 1.0, f"F={F} out of (0,1]"

    def test_lmtd_eff(self, case3):
        lmtd_eff = case3["lmtd"]["F"] * case3["lmtd"]["LMTD_K"]
        assert_close(case3["lmtd"]["LMTD_eff_K"], lmtd_eff, 0.005, "LMTD_eff consistency")

    def test_tube_regime(self, case3):
        assert case3["tube_side"]["flow_regime"] == "turbulent"

    def test_tube_Re(self, case3):
        d_i = 0.01483
        A = 26 * math.pi / 4 * d_i ** 2
        v = 8.0 / (998.0 * A)
        Re_expected = 998.0 * v * d_i / 0.001
        assert_close(case3["tube_side"]["Re"], Re_expected, 0.01, "Tube Re")

    def test_tube_h_i(self, case3):
        assert_close(case3["tube_side"]["h_i_W_m2K"], 7888.0, 0.05, "h_i")

    def test_shell_h_o(self, case3):
        assert_close(case3["shell_side"]["h_o_W_m2K"], 4291.0, 0.05, "h_o")

    def test_U_dirty(self, case3):
        assert_close(case3["overall"]["U_dirty_W_m2K"], 1182.5, 0.05, "U_dirty")

    def test_U_clean_gt_dirty(self, case3):
        assert case3["overall"]["U_clean_W_m2K"] > case3["overall"]["U_dirty_W_m2K"]

    def test_heat_duty(self, case3):
        assert_close(case3["heat_duty_W"], 1337600.0, 0.005, "Q")


# ============================================================================
# Case 4: 45-deg rotated square, turbulent tube, unequal baffles
# No hardcoded reference values — verified by physics and consistency
# ============================================================================

class TestCase4:
    """Case 4 exercises a different layout angle (45-deg) with unequal baffle
    spacing. Tests verify via independent computation and physics invariants
    rather than pre-computed reference values."""

    def test_lmtd(self, case4):
        # dT1 = 180 - 80 = 100, dT2 = 120 - 40 = 80
        expected = 20.0 / math.log(100.0 / 80.0)
        assert_close(case4["lmtd"]["LMTD_K"], expected, 0.005, "LMTD")

    def test_R(self, case4):
        # R = (180-120)/(80-40) = 1.5
        assert_close(case4["lmtd"]["R"], 1.5, 0.005, "R")

    def test_P(self, case4):
        # P = (80-40)/(180-40) = 2/7
        assert_close(case4["lmtd"]["P"], 2.0 / 7.0, 0.005, "P")

    def test_F_reasonable(self, case4):
        F = case4["lmtd"]["F"]
        assert 0.85 < F <= 1.0, f"F={F} outside expected range for R=1.5, P=2/7"

    def test_tube_Re(self, case4):
        d_i = 0.01483
        n_pp = 108 / 4
        A = n_pp * math.pi / 4 * d_i ** 2
        v = 12.0 / (990.0 * A)
        Re_expected = 990.0 * v * d_i / 0.0009
        assert_close(case4["tube_side"]["Re"], Re_expected, 0.01, "Tube Re")

    def test_tube_Pr(self, case4):
        Pr_expected = 0.0009 * 4100.0 / 0.59
        assert_close(case4["tube_side"]["Pr"], Pr_expected, 0.005, "Tube Pr")

    def test_tube_regime(self, case4):
        assert case4["tube_side"]["flow_regime"] == "turbulent"

    def test_shell_Re_range(self, case4):
        """Shell Re should be in a physically sensible range."""
        Re = case4["shell_side"]["Re"]
        assert 1000 < Re < 50000, f"Shell Re={Re} out of expected range"

    def test_shell_J_factors_range(self, case4):
        for jf in ["J_c", "J_l", "J_b", "J_s", "J_r"]:
            val = case4["shell_side"][jf]
            assert 0 < val <= 2.0, f"{jf}={val} out of valid range"

    def test_shell_J_s_not_one(self, case4):
        """Unequal baffle spacing means J_s != 1."""
        assert case4["shell_side"]["J_s"] < 0.999, "J_s should be < 1 for unequal spacing"

    def test_shell_h_o_range(self, case4):
        h_o = case4["shell_side"]["h_o_W_m2K"]
        assert 200 < h_o < 5000, f"h_o={h_o} outside physically reasonable range"

    def test_U_clean_gt_dirty(self, case4):
        assert case4["overall"]["U_clean_W_m2K"] > case4["overall"]["U_dirty_W_m2K"]

    def test_cleanliness_factor_range(self, case4):
        cf = case4["overall"]["cleanliness_factor"]
        assert 0 < cf < 1, f"CF={cf} not in (0,1)"

    def test_controlling_resistance_valid(self, case4):
        valid = {"shell_film", "tube_film", "shell_fouling", "tube_fouling", "wall"}
        assert case4["overall"]["controlling_resistance"] in valid

    def test_heat_duty(self, case4):
        # Q = 7 * 2300 * |180-120| = 966000
        assert_close(case4["heat_duty_W"], 966000.0, 0.005, "Q")

    def test_available_area(self, case4):
        A_expected = 108 * math.pi * 0.01905 * 4.27
        assert_close(case4["area"]["available_m2"], A_expected, 0.005, "A_avail")

    def test_U_range(self, case4):
        """U_dirty should be in a physically reasonable range."""
        U = case4["overall"]["U_dirty_W_m2K"]
        assert 100 < U < 2000, f"U_dirty={U} outside expected range"


# ============================================================================
# Cross-case consistency tests
# ============================================================================

class TestConsistency:
    @pytest.mark.parametrize("case_file", [
        "/app/case1.json", "/app/case2.json", "/app/case3.json", "/app/case4.json",
    ])
    def test_area_consistency(self, case_file):
        out = run_tool(case_file)
        avail = out["area"]["available_m2"]
        req = out["area"]["required_m2"]
        od_expected = 100.0 * (avail - req) / req
        assert_close(out["area"]["overdesign_pct"], od_expected, 0.005, "OD% consistency")

    @pytest.mark.parametrize("case_file", [
        "/app/case1.json", "/app/case2.json", "/app/case3.json", "/app/case4.json",
    ])
    def test_required_area_consistency(self, case_file):
        out = run_tool(case_file)
        Q = out["heat_duty_W"]
        U = out["overall"]["U_dirty_W_m2K"]
        lmtd_eff = out["lmtd"]["LMTD_eff_K"]
        A_expected = Q / (U * lmtd_eff)
        assert_close(out["area"]["required_m2"], A_expected, 0.005, "A_req consistency")

    @pytest.mark.parametrize("case_file", [
        "/app/case1.json", "/app/case2.json", "/app/case3.json", "/app/case4.json",
    ])
    def test_lmtd_eff_consistency(self, case_file):
        out = run_tool(case_file)
        expected = out["lmtd"]["F"] * out["lmtd"]["LMTD_K"]
        assert_close(out["lmtd"]["LMTD_eff_K"], expected, 0.005, "LMTD_eff = F*LMTD")

    @pytest.mark.parametrize("case_file", [
        "/app/case1.json", "/app/case2.json", "/app/case3.json", "/app/case4.json",
    ])
    def test_h_o_equals_h_ideal_times_J(self, case_file):
        out = run_tool(case_file)
        ss = out["shell_side"]
        J_prod = ss["J_c"] * ss["J_l"] * ss["J_b"] * ss["J_s"] * ss["J_r"]
        h_o_expected = ss["h_ideal_W_m2K"] * J_prod
        assert_close(ss["h_o_W_m2K"], h_o_expected, 0.005, "h_o = h_ideal * J_product")

    @pytest.mark.parametrize("case_file", [
        "/app/case1.json", "/app/case2.json", "/app/case3.json", "/app/case4.json",
    ])
    def test_controlling_resistance_valid(self, case_file):
        out = run_tool(case_file)
        valid = {"shell_film", "tube_film", "shell_fouling", "tube_fouling", "wall"}
        assert out["overall"]["controlling_resistance"] in valid
