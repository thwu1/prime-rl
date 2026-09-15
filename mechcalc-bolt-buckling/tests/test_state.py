"""
Tests for the integrated mechanical engineering analysis pipeline.

"""
import json
import subprocess
import math
import os
import pytest


def run_mechcalc(input_data):
    """Run the mechcalc tool and return parsed output."""
    proc = subprocess.run(
        ["python3", "/app/mechcalc.py"],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"mechcalc failed: {proc.stderr}"
    return json.loads(proc.stdout)


def run_report_jq(combined_data):
    """Run report.jq on combined input/output data."""
    proc = subprocess.run(
        ["jq", "-f", "/app/report.jq"],
        input=json.dumps(combined_data),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"jq failed: {proc.stderr}"
    return json.loads(proc.stdout)


# ─── Pre-computed reference values ───
# Bolt test case 1: M12x1.75 bolt, combined loading
# Thread geometry: d2 = 12 - 0.6495*1.75 = 10.86338, d3 = 12 - 1.2269*1.75 = 9.85293
# stress area = pi/4 * ((10.86338+9.85293)/2)^2 = pi/4 * 10.35815^2 = 84.267 mm^2

BOLT_INPUT_1 = {
    "axial_force_kN": 15.0,
    "radial_force_kN": 8.0,
    "bolt_yield_MPa": 900.0,
    "bolt_E_GPa": 210.0,
    "thread_major_mm": 12.0,
    "thread_pitch_mm": 1.75,
    "clamp_height_mm": 40.0,
    "clamp_parts": [
        {"height_mm": 20.0, "E_GPa": 210.0},
        {"height_mm": 20.0, "E_GPa": 70.0},
    ],
    "friction_thread": 0.14,
    "friction_head": 0.12,
    "friction_surfaces": 0.15,
    "tightness_coeff": 1.2,
    "safety_yield_desired": 1.5,
    "force_intro_factor": 0.5,
    "head_outer_dia_mm": 18.0,
    "hole_dia_mm": 13.0,
    "torsion_reduction": 0.5,
    "settlement_mm": 0.01,
}


BUCKLING_INPUT_1 = {
    "force_kN": 10.0,
    "length_mm": 3000.0,
    "mounting": "D",
    "use_practical_coeff": True,
    "profile": {"type": "rectangle", "a_mm": 40.0, "b_mm": 20.0},
    "material_E_GPa": 210.0,
    "material_yield_MPa": 250.0,
    "eccentricity_ratio": 0.25,
    "safety_desired": 3.0,
}


BUCKLING_INPUT_2 = {
    "force_kN": 10.0,
    "length_mm": 300.0,
    "mounting": "A",
    "use_practical_coeff": True,
    "profile": {"type": "rectangle", "a_mm": 40.0, "b_mm": 20.0},
    "material_E_GPa": 210.0,
    "material_yield_MPa": 250.0,
    "eccentricity_ratio": 0.25,
    "safety_desired": 3.0,
}


VBELT_INPUT_1 = {
    "power_kW": 10.0,
    "rpm_driver": 1450.0,
    "rpm_driven": 725.0,
    "service_factor": 1.2,
    "d1_mm": 125.0,
    "d2_mm": 250.0,
    "center_distance_mm": 400.0,
    "belt_section": "A",
    "belt_mass_per_m_kg": 0.105,
    "base_power_per_belt_kW": 2.28,
    "power_increment_kW": 0.304,
}


def make_full_input(bolt=None, buckling=None, vbelt=None):
    return {
        "bolt": bolt or BOLT_INPUT_1,
        "buckling": buckling or BUCKLING_INPUT_1,
        "vbelt": vbelt or VBELT_INPUT_1,
    }


# ──────────────────────── Helper: compute expected values ────────────────────────

def expected_bolt(inp):
    """Compute expected bolt results from formulas."""
    b = inp
    P = b["thread_pitch_mm"]
    d = b["thread_major_mm"]
    d2 = d - 0.6495 * P
    d3 = d - 1.2269 * P
    d_s = (d2 + d3) / 2.0
    A_s = math.pi / 4.0 * d_s ** 2

    E_b = b["bolt_E_GPa"] * 1000.0
    L_c = b["clamp_height_mm"]
    c_b = E_b * A_s / L_c

    alpha = math.radians(30)
    d_hole = b["hole_dia_mm"]
    D_head = b["head_outer_dia_mm"]
    inv_c_total = 0.0
    for part in b["clamp_parts"]:
        Li = part["height_mm"]
        Ei = part["E_GPa"] * 1000.0
        D_cone_end = D_head + 2 * Li * math.tan(alpha)
        num = (D_head + d_hole) * (D_cone_end - d_hole)
        den = (D_head - d_hole) * (D_cone_end + d_hole)
        if num <= 0 or den <= 0 or num / den <= 0:
            ci = 1e15
        else:
            ci = Ei * math.pi * d_hole * math.tan(alpha) / math.log(num / den)
        inv_c_total += 1.0 / ci
    c_clamp = 1.0 / inv_c_total

    n = b["force_intro_factor"]
    phi = n * c_b / (n * c_b + c_clamp)

    Fa = b["axial_force_kN"] * 1000.0
    Fr = b["radial_force_kN"] * 1000.0
    mu_s = b["friction_surfaces"]
    tc = b["tightness_coeff"]

    F0_tight = (tc + phi) * Fa
    F0_slide = Fr / mu_s + phi * Fa
    F0_min = max(F0_tight, F0_slide)

    settle_loss = b["settlement_mm"] * c_b * c_clamp / (c_b + c_clamp)
    F0 = F0_min + settle_loss

    F1_max = F0 + phi * Fa

    sigma = F1_max / A_s

    psi = math.atan(P / (math.pi * d2))
    rho_prime = math.atan(b["friction_thread"])
    M_G = F0 * d2 / 2.0 * math.tan(psi + rho_prime)
    W_p = math.pi / 16.0 * d_s ** 3
    tau = M_G / W_p

    kt = b["torsion_reduction"]
    sigma_red = math.sqrt(sigma ** 2 + 3 * (kt * tau) ** 2)

    safety = b["bolt_yield_MPa"] / sigma_red

    M_head = F0 * b["friction_head"] * (D_head + d_hole) / 4.0
    M_A = M_G + M_head

    F_res = F0 - phi * Fa

    return {
        "thread_stress_area_mm2": A_s,
        "bolt_stiffness_N_per_mm": c_b,
        "clamp_stiffness_N_per_mm": c_clamp,
        "force_ratio": phi,
        "min_preload_kN": F0 / 1000.0,
        "max_bolt_force_kN": F1_max / 1000.0,
        "tensile_stress_MPa": sigma,
        "torsional_stress_MPa": tau,
        "reduced_stress_MPa": sigma_red,
        "safety_yield": safety,
        "tightening_torque_Nm": M_A / 1000.0,
        "clamp_residual_kN": F_res / 1000.0,
        "pass": safety >= b["safety_yield_desired"],
    }


def expected_buckling(inp):
    """Compute expected buckling results."""
    b = inp
    mounting_coeffs = {
        "A": (0.50, 0.65),
        "B": (0.70, 0.80),
        "C": (1.00, 1.20),
        "D": (1.00, 1.00),
        "E": (2.00, 2.10),
        "F": (2.00, 2.00),
    }
    k_theor, k_pract = mounting_coeffs[b["mounting"]]
    k = k_pract if b["use_practical_coeff"] else k_theor
    L_eff = k * b["length_mm"]

    prof = b["profile"]
    if prof["type"] == "rectangle":
        a, bw = prof["a_mm"], prof["b_mm"]
        A = a * bw
        I = min(a * bw ** 3 / 12.0, bw * a ** 3 / 12.0)
    elif prof["type"] == "circle":
        dd = prof["d_mm"]
        A = math.pi / 4.0 * dd ** 2
        I = math.pi / 64.0 * dd ** 4
    elif prof["type"] == "tube":
        do, di = prof["d_outer_mm"], prof["d_inner_mm"]
        A = math.pi / 4.0 * (do ** 2 - di ** 2)
        I = math.pi / 64.0 * (do ** 4 - di ** 4)
    elif prof["type"] == "I":
        bf = prof["bf_mm"]
        tf = prof["tf_mm"]
        hw = prof["hw_mm"]
        tw = prof["tw_mm"]
        h_total = hw + 2 * tf
        A = 2 * bf * tf + hw * tw
        I_strong = (bf * h_total ** 3 - (bf - tw) * hw ** 3) / 12.0
        I_weak = (2 * tf * bf ** 3 + hw * tw ** 3) / 12.0
        I = min(I_strong, I_weak)
    else:
        raise ValueError(f"Unknown profile type: {prof['type']}")

    r_g = math.sqrt(I / A)
    SR = L_eff / r_g

    E = b["material_E_GPa"] * 1000.0
    Sy = b["material_yield_MPa"]
    SR_c = math.sqrt(math.pi ** 2 * E / (0.5 * Sy))

    F = b["force_kN"] * 1000.0
    actual_stress = F / A

    if SR > SR_c:
        zone = "elastic"
    elif SR > 10:
        zone = "inelastic"
    else:
        zone = "compression"

    euler_cr = math.pi ** 2 * E / (SR ** 2) if SR > 0 else None
    johnson_cr = Sy - (Sy ** 2 / (4 * math.pi ** 2 * E)) * SR ** 2

    mu = b["eccentricity_ratio"]
    arg = SR / 2.0 * math.sqrt(F / (A * E))
    cos_val = math.cos(arg)
    if abs(cos_val) < 1e-12:
        secant_max = float("inf")
    else:
        secant_max = actual_stress * (1.0 + mu / cos_val)

    safety_euler = euler_cr / actual_stress if euler_cr else None
    safety_johnson = johnson_cr / actual_stress
    safety_secant = Sy / secant_max if secant_max > 0 and secant_max != float("inf") else 0.0

    desired = b["safety_desired"]
    if zone == "elastic":
        passes = (safety_euler is not None and safety_euler >= desired)
    elif zone == "inelastic":
        passes = safety_johnson >= desired
    else:
        passes = (Sy / actual_stress) >= desired

    return {
        "effective_length_mm": L_eff,
        "area_mm2": A,
        "I_mm4": I,
        "radius_gyration_mm": r_g,
        "slenderness_ratio": SR,
        "critical_slenderness": SR_c,
        "zone": zone,
        "euler_critical_stress_MPa": euler_cr,
        "johnson_critical_stress_MPa": johnson_cr if zone != "elastic" else None,
        "secant_max_stress_MPa": secant_max if secant_max != float("inf") else None,
        "safety_euler": safety_euler,
        "safety_johnson": safety_johnson if zone != "elastic" else None,
        "safety_secant": safety_secant,
        "pass": passes,
    }


def expected_vbelt(inp):
    """Compute expected V-belt results."""
    v = inp
    i_ratio = v["d2_mm"] / v["d1_mm"]
    belt_speed = math.pi * v["d1_mm"] * v["rpm_driver"] / 60000.0

    diff = abs(v["d2_mm"] - v["d1_mm"])
    C = v["center_distance_mm"]
    sin_arg = diff / (2.0 * C)
    sin_arg = min(sin_arg, 1.0)
    alpha_small_rad = math.pi - 2.0 * math.asin(sin_arg)
    alpha_large_rad = math.pi + 2.0 * math.asin(sin_arg)
    alpha_small_deg = math.degrees(alpha_small_rad)
    alpha_large_deg = math.degrees(alpha_large_rad)

    L_belt = (
        2.0 * C
        + math.pi / 2.0 * (v["d1_mm"] + v["d2_mm"])
        + (v["d2_mm"] - v["d1_mm"]) ** 2 / (4.0 * C)
    )

    P_design = v["power_kW"] * v["service_factor"]

    C_wrap = 1.0 - (180.0 - alpha_small_deg) * 0.00278 if alpha_small_deg < 180 else 1.0

    P_corrected = (v["base_power_per_belt_kW"] + v["power_increment_kW"]) * C_wrap

    num_belts = math.ceil(P_design / P_corrected)

    Ft = 1000.0 * P_design / (num_belts * belt_speed)
    Fc = v["belt_mass_per_m_kg"] * belt_speed ** 2

    f_eff = 0.3 / math.sin(math.radians(19))
    f_alpha = f_eff * alpha_small_rad
    exp_fa = math.exp(f_alpha)
    F0 = Ft * (exp_fa + 1) / (2.0 * (exp_fa - 1)) + Fc
    F1 = F0 + Ft / 2.0
    F2 = F0 - Ft / 2.0
    Fs = 2.0 * F0 * math.cos((math.pi - alpha_small_rad) / 2.0) * num_belts

    return {
        "transmission_ratio": i_ratio,
        "belt_speed_m_s": belt_speed,
        "wrap_angle_small_deg": alpha_small_deg,
        "wrap_angle_large_deg": alpha_large_deg,
        "belt_length_mm": L_belt,
        "design_power_kW": P_design,
        "corrected_power_per_belt_kW": P_corrected,
        "num_belts": num_belts,
        "tensile_force_N": Ft,
        "centrifugal_force_N": Fc,
        "preload_force_N": F0,
        "tight_side_N": F1,
        "slack_side_N": F2,
        "shaft_load_N": Fs,
        "pass": alpha_small_deg >= 90.0,
    }


# ──────────────────────── Tests: Bolt Connection ────────────────────────


class TestBoltConnection:
    """Tests for prestressed bolt connection calculations."""

    def setup_method(self):
        self.full_input = make_full_input()
        self.result = run_mechcalc(self.full_input)
        self.bolt = self.result["bolt"]
        self.expected = expected_bolt(BOLT_INPUT_1)

    def test_thread_stress_area(self):
        assert self.bolt["thread_stress_area_mm2"] == pytest.approx(
            self.expected["thread_stress_area_mm2"], rel=0.01
        )

    def test_bolt_stiffness(self):
        assert self.bolt["bolt_stiffness_N_per_mm"] == pytest.approx(
            self.expected["bolt_stiffness_N_per_mm"], rel=0.01
        )

    def test_clamp_stiffness(self):
        assert self.bolt["clamp_stiffness_N_per_mm"] == pytest.approx(
            self.expected["clamp_stiffness_N_per_mm"], rel=0.02
        )

    def test_force_ratio(self):
        assert self.bolt["force_ratio"] == pytest.approx(
            self.expected["force_ratio"], rel=0.02
        )

    def test_min_preload(self):
        assert self.bolt["min_preload_kN"] == pytest.approx(
            self.expected["min_preload_kN"], rel=0.02
        )

    def test_max_bolt_force(self):
        assert self.bolt["max_bolt_force_kN"] == pytest.approx(
            self.expected["max_bolt_force_kN"], rel=0.02
        )

    def test_tensile_stress(self):
        assert self.bolt["tensile_stress_MPa"] == pytest.approx(
            self.expected["tensile_stress_MPa"], rel=0.02
        )

    def test_torsional_stress(self):
        assert self.bolt["torsional_stress_MPa"] == pytest.approx(
            self.expected["torsional_stress_MPa"], rel=0.02
        )

    def test_reduced_stress(self):
        assert self.bolt["reduced_stress_MPa"] == pytest.approx(
            self.expected["reduced_stress_MPa"], rel=0.02
        )

    def test_safety_yield(self):
        assert self.bolt["safety_yield"] == pytest.approx(
            self.expected["safety_yield"], rel=0.02
        )

    def test_tightening_torque(self):
        assert self.bolt["tightening_torque_Nm"] == pytest.approx(
            self.expected["tightening_torque_Nm"], rel=0.02
        )

    def test_clamp_residual(self):
        assert self.bolt["clamp_residual_kN"] == pytest.approx(
            self.expected["clamp_residual_kN"], rel=0.02
        )

    def test_pass_flag(self):
        assert self.bolt["pass"] == self.expected["pass"]


# ──────────────────────── Tests: Buckling ────────────────────────


class TestBuckling:
    """Tests for column buckling calculations."""

    def test_elastic_zone(self):
        inp = make_full_input(buckling=BUCKLING_INPUT_1)
        result = run_mechcalc(inp)
        b = result["buckling"]
        exp = expected_buckling(BUCKLING_INPUT_1)

        assert b["effective_length_mm"] == pytest.approx(exp["effective_length_mm"], rel=0.005)
        assert b["area_mm2"] == pytest.approx(exp["area_mm2"], rel=0.005)
        assert b["I_mm4"] == pytest.approx(exp["I_mm4"], rel=0.005)
        assert b["radius_gyration_mm"] == pytest.approx(exp["radius_gyration_mm"], rel=0.005)
        assert b["slenderness_ratio"] == pytest.approx(exp["slenderness_ratio"], rel=0.01)
        assert b["critical_slenderness"] == pytest.approx(exp["critical_slenderness"], rel=0.01)
        assert b["zone"] == "elastic"
        assert b["euler_critical_stress_MPa"] == pytest.approx(
            exp["euler_critical_stress_MPa"], rel=0.01
        )
        assert b["safety_euler"] == pytest.approx(exp["safety_euler"], rel=0.02)
        assert b["secant_max_stress_MPa"] == pytest.approx(
            exp["secant_max_stress_MPa"], rel=0.02
        )
        assert b["safety_secant"] == pytest.approx(exp["safety_secant"], rel=0.02)
        assert b["pass"] == exp["pass"]

    def test_inelastic_zone(self):
        inp = make_full_input(buckling=BUCKLING_INPUT_2)
        result = run_mechcalc(inp)
        b = result["buckling"]
        exp = expected_buckling(BUCKLING_INPUT_2)

        assert b["zone"] == "inelastic"
        assert b["slenderness_ratio"] == pytest.approx(exp["slenderness_ratio"], rel=0.01)
        assert b["johnson_critical_stress_MPa"] == pytest.approx(
            exp["johnson_critical_stress_MPa"], rel=0.01
        )
        assert b["safety_johnson"] == pytest.approx(exp["safety_johnson"], rel=0.02)
        assert b["secant_max_stress_MPa"] == pytest.approx(
            exp["secant_max_stress_MPa"], rel=0.02
        )
        assert b["pass"] == exp["pass"]

    def test_clamped_free(self):
        """Test clamped-free end (cantilever) mounting E."""
        inp_cf = dict(BUCKLING_INPUT_1)
        inp_cf["mounting"] = "E"
        inp_cf["length_mm"] = 500.0
        full = make_full_input(buckling=inp_cf)
        result = run_mechcalc(full)
        b = result["buckling"]
        exp = expected_buckling(inp_cf)
        assert b["effective_length_mm"] == pytest.approx(exp["effective_length_mm"], rel=0.005)
        assert b["slenderness_ratio"] == pytest.approx(exp["slenderness_ratio"], rel=0.01)
        assert b["zone"] == exp["zone"]

    def test_tube_profile(self):
        """Test with tubular cross-section."""
        inp_tube = {
            "force_kN": 50.0,
            "length_mm": 2000.0,
            "mounting": "D",
            "use_practical_coeff": True,
            "profile": {"type": "tube", "d_outer_mm": 60.0, "d_inner_mm": 50.0},
            "material_E_GPa": 210.0,
            "material_yield_MPa": 250.0,
            "eccentricity_ratio": 0.25,
            "safety_desired": 3.0,
        }
        full = make_full_input(buckling=inp_tube)
        result = run_mechcalc(full)
        b = result["buckling"]
        exp = expected_buckling(inp_tube)
        assert b["area_mm2"] == pytest.approx(exp["area_mm2"], rel=0.005)
        assert b["I_mm4"] == pytest.approx(exp["I_mm4"], rel=0.005)
        assert b["radius_gyration_mm"] == pytest.approx(exp["radius_gyration_mm"], rel=0.005)
        assert b["zone"] == exp["zone"]
        assert b["safety_euler"] == pytest.approx(exp["safety_euler"], rel=0.02)

    def test_ibeam_profile(self):
        """Test I-beam cross-section: buckling should use weak-axis I."""
        inp_ibeam = {
            "force_kN": 300.0,
            "length_mm": 2000.0,
            "mounting": "D",
            "use_practical_coeff": True,
            "profile": {"type": "I", "bf_mm": 100.0, "tf_mm": 10.0, "hw_mm": 200.0, "tw_mm": 8.0},
            "material_E_GPa": 210.0,
            "material_yield_MPa": 250.0,
            "eccentricity_ratio": 0.25,
            "safety_desired": 3.0,
        }
        full = make_full_input(buckling=inp_ibeam)
        result = run_mechcalc(full)
        b = result["buckling"]
        exp = expected_buckling(inp_ibeam)
        assert b["area_mm2"] == pytest.approx(exp["area_mm2"], rel=0.005)
        assert b["I_mm4"] == pytest.approx(exp["I_mm4"], rel=0.005)
        assert b["radius_gyration_mm"] == pytest.approx(exp["radius_gyration_mm"], rel=0.005)
        assert b["zone"] == exp["zone"]
        # With weak-axis I, slenderness is much higher than strong-axis-only
        assert b["slenderness_ratio"] == pytest.approx(exp["slenderness_ratio"], rel=0.01)
        if exp["zone"] == "inelastic":
            assert b["safety_johnson"] == pytest.approx(exp["safety_johnson"], rel=0.02)
        elif exp["zone"] == "elastic":
            assert b["safety_euler"] == pytest.approx(exp["safety_euler"], rel=0.02)


# ──────────────────────── Tests: V-Belt ────────────────────────


class TestVBelt:
    """Tests for V-belt transmission calculations."""

    def setup_method(self):
        self.full_input = make_full_input()
        self.result = run_mechcalc(self.full_input)
        self.vb = self.result["vbelt"]
        self.expected = expected_vbelt(VBELT_INPUT_1)

    def test_transmission_ratio(self):
        assert self.vb["transmission_ratio"] == pytest.approx(
            self.expected["transmission_ratio"], rel=0.005
        )

    def test_belt_speed(self):
        assert self.vb["belt_speed_m_s"] == pytest.approx(
            self.expected["belt_speed_m_s"], rel=0.005
        )

    def test_wrap_angle_small(self):
        assert self.vb["wrap_angle_small_deg"] == pytest.approx(
            self.expected["wrap_angle_small_deg"], rel=0.005
        )

    def test_wrap_angle_large(self):
        assert self.vb["wrap_angle_large_deg"] == pytest.approx(
            self.expected["wrap_angle_large_deg"], rel=0.005
        )

    def test_belt_length(self):
        assert self.vb["belt_length_mm"] == pytest.approx(
            self.expected["belt_length_mm"], rel=0.005
        )

    def test_design_power(self):
        assert self.vb["design_power_kW"] == pytest.approx(
            self.expected["design_power_kW"], rel=0.005
        )

    def test_corrected_power_per_belt(self):
        assert self.vb["corrected_power_per_belt_kW"] == pytest.approx(
            self.expected["corrected_power_per_belt_kW"], rel=0.02
        )

    def test_num_belts(self):
        assert self.vb["num_belts"] == self.expected["num_belts"]

    def test_tensile_force(self):
        assert self.vb["tensile_force_N"] == pytest.approx(
            self.expected["tensile_force_N"], rel=0.02
        )

    def test_centrifugal_force(self):
        assert self.vb["centrifugal_force_N"] == pytest.approx(
            self.expected["centrifugal_force_N"], rel=0.02
        )

    def test_preload_force(self):
        assert self.vb["preload_force_N"] == pytest.approx(
            self.expected["preload_force_N"], rel=0.02
        )

    def test_tight_slack_sides(self):
        assert self.vb["tight_side_N"] == pytest.approx(
            self.expected["tight_side_N"], rel=0.02
        )
        assert self.vb["slack_side_N"] == pytest.approx(
            self.expected["slack_side_N"], rel=0.02
        )

    def test_shaft_load(self):
        assert self.vb["shaft_load_N"] == pytest.approx(
            self.expected["shaft_load_N"], rel=0.02
        )

    def test_pass_flag(self):
        assert self.vb["pass"] == self.expected["pass"]

    def test_equal_pulleys(self):
        """Equal pulleys should give 180-degree wrap angles."""
        inp_eq = dict(VBELT_INPUT_1)
        inp_eq["d1_mm"] = 200.0
        inp_eq["d2_mm"] = 200.0
        inp_eq["rpm_driven"] = 1450.0
        full = make_full_input(vbelt=inp_eq)
        result = run_mechcalc(full)
        assert result["vbelt"]["wrap_angle_small_deg"] == pytest.approx(180.0, abs=0.01)
        assert result["vbelt"]["wrap_angle_large_deg"] == pytest.approx(180.0, abs=0.01)
        assert result["vbelt"]["transmission_ratio"] == pytest.approx(1.0, rel=0.005)


# ──────────────────────── Tests: Integration ────────────────────────


class TestIntegration:
    """Tests for cross-module integration and edge cases."""

    def test_all_three_modules_present(self):
        result = run_mechcalc(make_full_input())
        assert "bolt" in result
        assert "buckling" in result
        assert "vbelt" in result

    def test_bolt_high_settlement(self):
        """High settlement should increase preload significantly."""
        inp_low = dict(BOLT_INPUT_1)
        inp_low["settlement_mm"] = 0.001
        inp_high = dict(BOLT_INPUT_1)
        inp_high["settlement_mm"] = 0.05

        r_low = run_mechcalc(make_full_input(bolt=inp_low))
        r_high = run_mechcalc(make_full_input(bolt=inp_high))
        assert r_high["bolt"]["min_preload_kN"] > r_low["bolt"]["min_preload_kN"]

    def test_malformed_input_exits_nonzero(self):
        proc = subprocess.run(
            ["python3", "/app/mechcalc.py"],
            input="not json",
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode != 0

    def test_bolt_different_parts_count(self):
        """Three clamped parts instead of two."""
        inp_3 = dict(BOLT_INPUT_1)
        inp_3["clamp_parts"] = [
            {"height_mm": 15.0, "E_GPa": 210.0},
            {"height_mm": 10.0, "E_GPa": 110.0},
            {"height_mm": 15.0, "E_GPa": 210.0},
        ]
        inp_3["clamp_height_mm"] = 40.0
        result = run_mechcalc(make_full_input(bolt=inp_3))
        exp = expected_bolt(inp_3)
        assert result["bolt"]["clamp_stiffness_N_per_mm"] == pytest.approx(
            exp["clamp_stiffness_N_per_mm"], rel=0.02
        )
        assert result["bolt"]["force_ratio"] == pytest.approx(
            exp["force_ratio"], rel=0.02
        )

    def test_circle_profile_buckling(self):
        """Circular cross-section buckling."""
        inp_circ = {
            "force_kN": 20.0,
            "length_mm": 1500.0,
            "mounting": "B",
            "use_practical_coeff": True,
            "profile": {"type": "circle", "d_mm": 30.0},
            "material_E_GPa": 210.0,
            "material_yield_MPa": 355.0,
            "eccentricity_ratio": 0.15,
            "safety_desired": 5.0,
        }
        result = run_mechcalc(make_full_input(buckling=inp_circ))
        exp = expected_buckling(inp_circ)
        assert result["buckling"]["area_mm2"] == pytest.approx(exp["area_mm2"], rel=0.005)
        assert result["buckling"]["I_mm4"] == pytest.approx(exp["I_mm4"], rel=0.005)
        assert result["buckling"]["zone"] == exp["zone"]

    def test_bolt_nonzero_torsion(self):
        """Torsional stress must be nonzero for any bolt with thread friction."""
        result = run_mechcalc(make_full_input())
        assert result["bolt"]["torsional_stress_MPa"] > 0

    def test_vbelt_nonzero_centrifugal(self):
        """Centrifugal force must be nonzero when belt speed > 0."""
        result = run_mechcalc(make_full_input())
        assert result["vbelt"]["centrifugal_force_N"] > 0

    def test_vbelt_nonzero_shaft_load(self):
        """Shaft load must be nonzero for any running transmission."""
        result = run_mechcalc(make_full_input())
        assert result["vbelt"]["shaft_load_N"] > 0


# ──────────────────────── Tests: report.jq ────────────────────────


class TestReportJQ:
    """Tests for the jq safety report filter."""

    def _get_combined(self, bolt=None, buckling=None, vbelt=None):
        """Run mechcalc and return combined input+output for report.jq."""
        inp = make_full_input(bolt=bolt, buckling=buckling, vbelt=vbelt)
        result = run_mechcalc(inp)
        return {"input": inp, "output": result}

    def test_report_structure(self):
        """report.jq produces correct top-level structure."""
        combined = self._get_combined()
        report = run_report_jq(combined)
        assert "modules" in report
        assert "overall_pass" in report
        assert "min_margin_pct" in report
        assert isinstance(report["modules"], list)
        assert len(report["modules"]) == 3
        for mod in report["modules"]:
            assert "name" in mod
            assert "pass" in mod
            assert "governing_safety" in mod
            assert "required_safety" in mod
            assert "margin_pct" in mod

    def test_report_bolt_values(self):
        """report.jq correctly computes bolt margin."""
        combined = self._get_combined()
        report = run_report_jq(combined)
        bolt_mod = [m for m in report["modules"] if m["name"] == "bolt"][0]

        bolt_out = combined["output"]["bolt"]
        bolt_in = combined["input"]["bolt"]
        assert bolt_mod["pass"] == bolt_out["pass"]
        assert bolt_mod["governing_safety"] == pytest.approx(
            bolt_out["safety_yield"], rel=0.01
        )
        assert bolt_mod["required_safety"] == pytest.approx(
            bolt_in["safety_yield_desired"], rel=0.01
        )
        expected_margin = (bolt_out["safety_yield"] / bolt_in["safety_yield_desired"] - 1) * 100
        assert bolt_mod["margin_pct"] == pytest.approx(expected_margin, rel=0.01)

    def test_report_buckling_elastic(self):
        """report.jq uses euler safety for elastic zone."""
        combined = self._get_combined(buckling=BUCKLING_INPUT_1)
        report = run_report_jq(combined)
        buck_mod = [m for m in report["modules"] if m["name"] == "buckling"][0]
        assert combined["output"]["buckling"]["zone"] == "elastic"
        assert buck_mod["governing_safety"] == pytest.approx(
            combined["output"]["buckling"]["safety_euler"], rel=0.01
        )
        assert buck_mod["required_safety"] == pytest.approx(
            combined["input"]["buckling"]["safety_desired"], rel=0.01
        )

    def test_report_buckling_inelastic(self):
        """report.jq uses johnson safety for inelastic zone."""
        combined = self._get_combined(buckling=BUCKLING_INPUT_2)
        report = run_report_jq(combined)
        buck_mod = [m for m in report["modules"] if m["name"] == "buckling"][0]
        assert combined["output"]["buckling"]["zone"] == "inelastic"
        assert buck_mod["governing_safety"] == pytest.approx(
            combined["output"]["buckling"]["safety_johnson"], rel=0.01
        )

    def test_report_vbelt_governing(self):
        """report.jq uses wrap_angle/90 as vbelt governing safety."""
        combined = self._get_combined()
        report = run_report_jq(combined)
        vbelt_mod = [m for m in report["modules"] if m["name"] == "vbelt"][0]
        expected_gov = combined["output"]["vbelt"]["wrap_angle_small_deg"] / 90.0
        assert vbelt_mod["governing_safety"] == pytest.approx(expected_gov, rel=0.01)
        assert vbelt_mod["required_safety"] == pytest.approx(1.0, rel=0.01)

    def test_report_overall_pass(self):
        """overall_pass reflects all module pass values."""
        combined = self._get_combined()
        report = run_report_jq(combined)
        all_pass = all(m["pass"] for m in report["modules"])
        assert report["overall_pass"] == all_pass

    def test_report_min_margin(self):
        """min_margin_pct is the minimum of all module margins."""
        combined = self._get_combined()
        report = run_report_jq(combined)
        margins = [m["margin_pct"] for m in report["modules"]]
        assert report["min_margin_pct"] == pytest.approx(min(margins), rel=0.01)


# ──────────────────────── Tests: analyze.sh ────────────────────────


class TestAnalyzeSh:
    """Tests for the analyze.sh pipeline orchestrator."""

    def setup_method(self):
        if os.path.exists("/app/results.db"):
            os.remove("/app/results.db")

    def _write_input(self, path, data):
        with open(path, "w") as f:
            json.dump(data, f)

    def test_run_produces_report(self):
        """analyze.sh run produces valid report JSON on stdout."""
        self._write_input("/tmp/test_run_input.json", make_full_input())
        proc = subprocess.run(
            ["/app/analyze.sh", "run", "/tmp/test_run_input.json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, f"analyze.sh run failed: {proc.stderr}"
        report = json.loads(proc.stdout)
        assert "modules" in report
        assert "overall_pass" in report
        assert "min_margin_pct" in report
        assert len(report["modules"]) == 3
        module_names = {m["name"] for m in report["modules"]}
        assert module_names == {"bolt", "buckling", "vbelt"}

    def test_run_stores_in_sqlite(self):
        """analyze.sh run stores results in SQLite database."""
        self._write_input("/tmp/test_store_input.json", make_full_input())
        subprocess.run(
            ["/app/analyze.sh", "run", "/tmp/test_store_input.json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert os.path.exists("/app/results.db")
        proc = subprocess.run(
            ["sqlite3", "/app/results.db", "SELECT COUNT(*) FROM runs;"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.stdout.strip() == "1"
        # Verify table schema has expected columns
        proc2 = subprocess.run(
            ["sqlite3", "/app/results.db",
             "SELECT id, input_file, timestamp, overall_pass FROM runs LIMIT 1;"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc2.returncode == 0

    def test_history_output(self):
        """analyze.sh history returns JSON array of runs, newest first."""
        self._write_input("/tmp/test_hist1.json", make_full_input())
        self._write_input("/tmp/test_hist2.json", make_full_input())
        subprocess.run(
            ["/app/analyze.sh", "run", "/tmp/test_hist1.json"],
            capture_output=True, text=True, timeout=30,
        )
        subprocess.run(
            ["/app/analyze.sh", "run", "/tmp/test_hist2.json"],
            capture_output=True, text=True, timeout=30,
        )

        proc = subprocess.run(
            ["/app/analyze.sh", "history"],
            capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode == 0, f"history failed: {proc.stderr}"
        history = json.loads(proc.stdout)
        assert isinstance(history, list)
        assert len(history) == 2
        # Newest first (higher id first)
        assert history[0]["id"] > history[1]["id"]
        for entry in history:
            assert "id" in entry
            assert "input_file" in entry
            assert "timestamp" in entry
            assert "overall_pass" in entry

    def test_compare_output(self):
        """analyze.sh compare returns margin deltas between two runs."""
        bolt1 = {**BOLT_INPUT_1, "safety_yield_desired": 1.0}
        bolt2 = {**BOLT_INPUT_1, "safety_yield_desired": 2.0}

        self._write_input("/tmp/test_cmp1.json", make_full_input(bolt=bolt1))
        self._write_input("/tmp/test_cmp2.json", make_full_input(bolt=bolt2))

        subprocess.run(
            ["/app/analyze.sh", "run", "/tmp/test_cmp1.json"],
            capture_output=True, text=True, timeout=30,
        )
        subprocess.run(
            ["/app/analyze.sh", "run", "/tmp/test_cmp2.json"],
            capture_output=True, text=True, timeout=30,
        )

        proc = subprocess.run(
            ["/app/analyze.sh", "compare", "1", "2"],
            capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode == 0, f"compare failed: {proc.stderr}"
        cmp = json.loads(proc.stdout)
        assert "modules" in cmp
        assert "overall_delta" in cmp
        assert len(cmp["modules"]) == 3
        for m in cmp["modules"]:
            assert "name" in m
            assert "margin_delta" in m

        # Bolt margin should decrease (higher required safety = lower margin)
        bolt_delta = [m for m in cmp["modules"] if m["name"] == "bolt"][0]
        assert bolt_delta["margin_delta"] < 0

        # Buckling and vbelt inputs unchanged: deltas should be ~0
        buck_delta = [m for m in cmp["modules"] if m["name"] == "buckling"][0]
        assert buck_delta["margin_delta"] == pytest.approx(0.0, abs=0.01)
        vbelt_delta = [m for m in cmp["modules"] if m["name"] == "vbelt"][0]
        assert vbelt_delta["margin_delta"] == pytest.approx(0.0, abs=0.01)
