#!/usr/bin/env python3
"""
Integrated mechanical engineering calculator: bolt connections, column buckling, V-belt drives.

"""
import json
import math
import sys


def compute_bolt(b):
    """Prestressed bolt connection analysis per VDI 2230 methodology."""
    P = b["thread_pitch_mm"]
    d = b["thread_major_mm"]
    d2 = d - 0.6495 * P
    d3 = d - 1.2269 * P
    d_s = (d2 + d3) / 2.0
    A_s = math.pi / 4.0 * d_s ** 2

    E_b = b["bolt_E_GPa"] * 1000.0  # GPa -> MPa
    L_c = b["clamp_height_mm"]
    c_b = E_b * A_s / L_c

    # Clamp stiffness via pressure-cone method (30-degree half-angle)
    alpha = math.radians(30)
    d_hole = b["hole_dia_mm"]
    D_head = b["head_outer_dia_mm"]

    inv_c_total = 0.0
    for part in b["clamp_parts"]:
        Li = part["height_mm"]
        Ei = part["E_GPa"] * 1000.0
        D_cone_end = D_head + 2.0 * Li * math.tan(alpha)
        num = (D_head + d_hole) * (D_cone_end - d_hole)
        den = (D_head - d_hole) * (D_cone_end + d_hole)
        if num <= 0 or den <= 0 or num / den <= 0:
            ci = 1e15
        else:
            ci = Ei * math.pi * d_hole * math.tan(alpha) / math.log(num / den)
        inv_c_total += 1.0 / ci

    c_clamp = 1.0 / inv_c_total

    # Force ratio (load introduction factor)
    n = b["force_intro_factor"]
    phi = n * c_b / (n * c_b + c_clamp)

    # Minimum preload
    Fa = b["axial_force_kN"] * 1000.0  # kN -> N
    Fr = b["radial_force_kN"] * 1000.0
    mu_s = b["friction_surfaces"]
    tc = b["tightness_coeff"]

    F0_tight = (tc + phi) * Fa
    F0_slide = Fr / mu_s + phi * Fa
    F0_min = max(F0_tight, F0_slide)

    # Settlement loss compensation
    settle_loss = b["settlement_mm"] * c_b * c_clamp / (c_b + c_clamp)
    F0 = F0_min + settle_loss

    # Maximum bolt force
    F1_max = F0 + phi * Fa

    # Stresses
    sigma = F1_max / A_s

    # Torsional stress from tightening
    psi = math.atan(P / (math.pi * d2))  # thread lead angle
    rho_prime = math.atan(b["friction_thread"])  # friction angle
    M_G = F0 * d2 / 2.0 * math.tan(psi + rho_prime)  # thread moment
    W_p = math.pi / 16.0 * d_s ** 3  # polar section modulus
    tau = M_G / W_p

    # Reduced (von Mises) stress with torsion reduction
    kt = b["torsion_reduction"]
    sigma_red = math.sqrt(sigma ** 2 + 3.0 * (kt * tau) ** 2)

    safety = b["bolt_yield_MPa"] / sigma_red

    # Tightening torque
    M_head = F0 * b["friction_head"] * (D_head + d_hole) / 4.0
    M_A = M_G + M_head

    # Residual clamping force
    F_res = F0 - phi * Fa

    return {
        "thread_stress_area_mm2": round(A_s, 4),
        "bolt_stiffness_N_per_mm": round(c_b, 2),
        "clamp_stiffness_N_per_mm": round(c_clamp, 2),
        "force_ratio": round(phi, 6),
        "min_preload_kN": round(F0 / 1000.0, 4),
        "max_bolt_force_kN": round(F1_max / 1000.0, 4),
        "tensile_stress_MPa": round(sigma, 3),
        "torsional_stress_MPa": round(tau, 3),
        "reduced_stress_MPa": round(sigma_red, 3),
        "safety_yield": round(safety, 4),
        "tightening_torque_Nm": round(M_A / 1000.0, 3),
        "clamp_residual_kN": round(F_res / 1000.0, 4),
        "pass": safety >= b["safety_yield_desired"],
    }


def compute_buckling(b):
    """Column buckling check: Euler, Johnson, Secant methods."""
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

    # Cross-section properties
    prof = b["profile"]
    ptype = prof["type"]

    if ptype == "rectangle":
        a, bw = prof["a_mm"], prof["b_mm"]
        A = a * bw
        I = min(a * bw ** 3 / 12.0, bw * a ** 3 / 12.0)
    elif ptype == "circle":
        dd = prof["d_mm"]
        A = math.pi / 4.0 * dd ** 2
        I = math.pi / 64.0 * dd ** 4
    elif ptype == "tube":
        do = prof["d_outer_mm"]
        di = prof["d_inner_mm"]
        A = math.pi / 4.0 * (do ** 2 - di ** 2)
        I = math.pi / 64.0 * (do ** 4 - di ** 4)
    elif ptype == "I":
        bf = prof["bf_mm"]
        tf = prof["tf_mm"]
        hw = prof["hw_mm"]
        tw = prof["tw_mm"]
        h_total = hw + 2 * tf
        A = 2 * bf * tf + hw * tw
        I_total = (bf * h_total ** 3 - (bf - tw) * hw ** 3) / 12.0
        I_weak = (2 * tf * bf ** 3 + hw * tw ** 3) / 12.0
        I = min(I_total, I_weak)
    else:
        raise ValueError(f"Unknown profile type: {ptype}")

    r_g = math.sqrt(I / A)
    SR = L_eff / r_g

    E = b["material_E_GPa"] * 1000.0  # GPa -> MPa
    Sy = b["material_yield_MPa"]

    # Critical slenderness
    SR_c = math.sqrt(math.pi ** 2 * E / (0.5 * Sy))

    F = b["force_kN"] * 1000.0  # kN -> N
    actual_stress = F / A

    # Zone classification
    if SR > SR_c:
        zone = "elastic"
    elif SR > 10:
        zone = "inelastic"
    else:
        zone = "compression"

    # Euler critical stress (elastic buckling)
    euler_cr = math.pi ** 2 * E / (SR ** 2) if SR > 0 else None

    # Johnson parabolic (inelastic buckling)
    johnson_cr = Sy - (Sy ** 2 / (4.0 * math.pi ** 2 * E)) * SR ** 2

    # Secant formula
    mu = b["eccentricity_ratio"]
    arg = SR / 2.0 * math.sqrt(F / (A * E))
    cos_val = math.cos(arg)
    if abs(cos_val) < 1e-12:
        secant_max = float("inf")
    else:
        secant_max = actual_stress * (1.0 + mu / cos_val)

    safety_euler = euler_cr / actual_stress if euler_cr and actual_stress > 0 else None
    safety_johnson = johnson_cr / actual_stress if actual_stress > 0 else None
    safety_secant = Sy / secant_max if secant_max > 0 and secant_max != float("inf") else 0.0

    desired = b["safety_desired"]
    if zone == "elastic":
        passes = (safety_euler is not None and safety_euler >= desired)
    elif zone == "inelastic":
        passes = (safety_johnson is not None and safety_johnson >= desired)
    else:
        passes = (Sy / actual_stress >= desired) if actual_stress > 0 else False

    return {
        "effective_length_mm": round(L_eff, 3),
        "area_mm2": round(A, 4),
        "I_mm4": round(I, 4),
        "radius_gyration_mm": round(r_g, 5),
        "slenderness_ratio": round(SR, 4),
        "critical_slenderness": round(SR_c, 4),
        "zone": zone,
        "euler_critical_stress_MPa": round(euler_cr, 4) if euler_cr is not None else None,
        "johnson_critical_stress_MPa": round(johnson_cr, 4) if zone != "elastic" else None,
        "secant_max_stress_MPa": round(secant_max, 4) if secant_max != float("inf") else None,
        "safety_euler": round(safety_euler, 4) if safety_euler is not None else None,
        "safety_johnson": round(safety_johnson, 4) if zone != "elastic" else None,
        "safety_secant": round(safety_secant, 4),
        "pass": passes,
    }


def compute_vbelt(v):
    """V-belt transmission sizing and force analysis."""
    d1 = v["d1_mm"]
    d2 = v["d2_mm"]
    C = v["center_distance_mm"]

    i_ratio = d2 / d1
    belt_speed = math.pi * d1 * v["rpm_driver"] / 60000.0  # m/s

    # Wrap angles
    diff = abs(d2 - d1)
    sin_arg = min(diff / (2.0 * C), 1.0)
    alpha_small_rad = math.pi - 2.0 * math.asin(sin_arg)
    alpha_large_rad = math.pi + 2.0 * math.asin(sin_arg)
    alpha_small_deg = math.degrees(alpha_small_rad)
    alpha_large_deg = math.degrees(alpha_large_rad)

    # Belt length
    L_belt = (
        2.0 * C
        + math.pi / 2.0 * (d1 + d2)
        + (d2 - d1) ** 2 / (4.0 * C)
    )

    # Design power
    P_design = v["power_kW"] * v["service_factor"]

    # Wrap angle correction factor
    if alpha_small_deg < 180.0:
        C_wrap = 1.0 - (180.0 - alpha_small_deg) * 0.00278
    else:
        C_wrap = 1.0

    # Corrected power per belt
    P_corrected = (v["base_power_per_belt_kW"] + v["power_increment_kW"]) * C_wrap

    # Number of belts
    num_belts = math.ceil(P_design / P_corrected)

    # Force analysis
    Ft = 1000.0 * P_design / (num_belts * belt_speed) if belt_speed > 0 else 0

    # Centrifugal force per belt
    Fc = v["belt_mass_per_m_kg"] * belt_speed ** 2

    # Effective friction for V-belt groove
    groove_half_angle = math.radians(19)
    f_base = 0.3
    f_eff = f_base / math.sin(groove_half_angle)

    f_alpha = f_eff * alpha_small_rad
    exp_fa = math.exp(f_alpha)

    # Belt preload
    F0 = Ft * (exp_fa + 1.0) / (2.0 * (exp_fa - 1.0)) + Fc

    # Tight and slack side forces
    F1 = F0 + Ft / 2.0
    F2 = F0 - Ft / 2.0

    # Total shaft load
    Fs = 2.0 * F0 * math.cos((math.pi - alpha_small_rad) / 2.0) * num_belts

    return {
        "transmission_ratio": round(i_ratio, 5),
        "belt_speed_m_s": round(belt_speed, 5),
        "wrap_angle_small_deg": round(alpha_small_deg, 4),
        "wrap_angle_large_deg": round(alpha_large_deg, 4),
        "belt_length_mm": round(L_belt, 4),
        "design_power_kW": round(P_design, 5),
        "corrected_power_per_belt_kW": round(P_corrected, 5),
        "num_belts": num_belts,
        "tensile_force_N": round(Ft, 4),
        "centrifugal_force_N": round(Fc, 5),
        "preload_force_N": round(F0, 4),
        "tight_side_N": round(F1, 4),
        "slack_side_N": round(F2, 4),
        "shaft_load_N": round(Fs, 3),
        "pass": alpha_small_deg >= 90.0,
    }


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error: invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        result = {
            "bolt": compute_bolt(data["bolt"]),
            "buckling": compute_buckling(data["buckling"]),
            "vbelt": compute_vbelt(data["vbelt"]),
        }
    except (KeyError, TypeError, ValueError) as e:
        print(f"Error: missing or invalid field: {e}", file=sys.stderr)
        sys.exit(1)

    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
