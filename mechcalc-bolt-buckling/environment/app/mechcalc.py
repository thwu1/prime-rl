#!/usr/bin/env python3
"""
Mechanical engineering calculator: bolt connections, column buckling, V-belt drives.
Reads JSON from stdin, writes analysis JSON to stdout.

"""
import json
import math
import sys


def compute_bolt(b):
    """Prestressed bolt connection analysis."""
    P = b["thread_pitch_mm"]
    d = b["thread_major_mm"]
    d2 = d - 0.6495 * P
    d3 = d - 1.2269 * P
    d_s = (d2 + d3) / 2.0
    A_s = math.pi / 4.0 * d_s ** 2

    E_b = b["bolt_E_GPa"] * 1000.0  # GPa -> MPa
    L_c = b["clamp_height_mm"]
    c_b = E_b * A_s / L_c

    # Clamp stiffness - annular cylinder approximation
    d_hole = b["hole_dia_mm"]
    D_head = b["head_outer_dia_mm"]
    E_avg = sum(p["E_GPa"] for p in b["clamp_parts"]) / len(b["clamp_parts"]) * 1000.0
    c_clamp = E_avg * math.pi / 4.0 * (D_head ** 2 - d_hole ** 2) / L_c

    # Force ratio
    n = b["force_intro_factor"]
    phi = n * c_b / (n * c_b + c_clamp)

    Fa = b["axial_force_kN"] * 1000.0
    Fr = b["radial_force_kN"] * 1000.0
    mu_s = b["friction_surfaces"]
    tc = b["tightness_coeff"]

    F0_tight = (tc + phi) * Fa
    F0_slide = Fr / mu_s + phi * Fa
    F0_min = max(F0_tight, F0_slide)

    # Preload
    F0 = F0_min

    # Maximum bolt force
    F1_max = F0 + phi * Fa
    sigma = F1_max / A_s

    # Torsional stress
    tau = 0.0

    # Reduced stress
    sigma_red = sigma

    safety = b["bolt_yield_MPa"] / sigma_red

    # Tightening torque
    M_A = 0.0

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
    """Column buckling check."""
    mounting_coeffs = {
        "A": (0.50, 0.65),
        "B": (0.70, 0.80),
        "C": (1.00, 1.20),
        "D": (1.00, 1.00),
        "E": (2.00, 2.00),
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
        # Moment of inertia
        I = (bf * h_total ** 3 - (bf - tw) * hw ** 3) / 12.0
    else:
        raise ValueError(f"Unknown profile type: {ptype}")

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
    johnson_cr = Sy - (Sy ** 2 / (4.0 * math.pi ** 2 * E)) * SR ** 2

    # Secant formula
    secant_max = None

    safety_euler = euler_cr / actual_stress if euler_cr and actual_stress > 0 else None
    safety_johnson = johnson_cr / actual_stress if actual_stress > 0 else None
    safety_secant = 0.0

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
        "secant_max_stress_MPa": round(secant_max, 4) if secant_max is not None else None,
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

    # Wrap angle correction
    if alpha_small_deg < 180.0:
        C_wrap = 1.0 - (180.0 - alpha_small_deg) * 0.00278
    else:
        C_wrap = 1.0

    P_corrected = (v["base_power_per_belt_kW"] + v["power_increment_kW"]) * C_wrap

    num_belts = math.ceil(P_design / P_corrected)

    Ft = 1000.0 * P_design / (num_belts * belt_speed) if belt_speed > 0 else 0

    # Centrifugal force
    Fc = 0.0

    # Belt preload
    F0 = Ft / 2.0

    # Strand forces
    F1 = F0 + Ft / 2.0
    F2 = F0 - Ft / 2.0

    # Shaft load
    Fs = 0.0

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
