#!/usr/bin/env python3
"""Shell-and-tube heat exchanger thermal rating tool.

Implements Bell-Delaware shell-side HTC, Gnielinski/Hausen tube-side HTC,
Bowman F-factor, and five-resistance overall U model.

"""

import json
import math
import sys


# ============================================================================
# LMTD and F-factor
# ============================================================================

def compute_lmtd(T_h_in, T_h_out, T_c_in, T_c_out):
    dT1 = T_h_in - T_c_out
    dT2 = T_h_out - T_c_in
    if dT1 <= 0 or dT2 <= 0:
        raise ValueError(f"Temperature cross: dT1={dT1}, dT2={dT2}")
    if abs(dT1 - dT2) < 1e-6:
        return (dT1 + dT2) / 2.0
    return (dT1 - dT2) / math.log(dT1 / dT2)


def compute_R(T_h_in, T_h_out, T_c_in, T_c_out):
    dT_cold = T_c_out - T_c_in
    if abs(dT_cold) < 1e-10:
        raise ValueError("Cold side dT is zero")
    return (T_h_in - T_h_out) / dT_cold


def compute_P(T_h_in, T_h_out, T_c_in, T_c_out):
    dT_max = T_h_in - T_c_in
    if abs(dT_max) < 1e-10:
        raise ValueError("No temperature driving force")
    return (T_c_out - T_c_in) / dT_max


def _f_factor_R_eq_1(P):
    """Bowman F-factor when R = 1 (L'Hopital limit)."""
    sqrt2 = math.sqrt(2.0)
    numer = sqrt2 * P / (1.0 - P)
    A = 2.0 - P * (2.0 - sqrt2)
    B = 2.0 - P * (2.0 + sqrt2)
    if B == 0 or A / B <= 0:
        return 0.0
    denom = math.log(A / B)
    if abs(denom) < 1e-15:
        return 0.0
    F = numer / denom
    return max(0.0, min(1.0, F))


def _equivalent_P1(R, P, N):
    """Convert overall P to single-shell equivalent P1 for N shells in series."""
    if abs(R - 1.0) < 1e-6:
        denom = N - (N - 1) * P
        if abs(denom) < 1e-15:
            return 0.0
        return P / denom
    ratio_base = (1 - R * P) / (1 - P)
    if ratio_base <= 0:
        return 0.0
    ratio = ratio_base ** (1.0 / N)
    denom = R - ratio
    if abs(denom) < 1e-15:
        return 0.0
    return (1 - ratio) / denom


def compute_f_factor(R, P, n_shell_passes=1):
    if P <= 0 or P >= 1:
        return 0.0
    if R <= 0:
        return 0.0
    if n_shell_passes > 1:
        P = _equivalent_P1(R, P, n_shell_passes)
        if P <= 0 or P >= 1:
            return 0.0
    if abs(R - 1.0) < 1e-6:
        return _f_factor_R_eq_1(P)
    sqrt_term = math.sqrt(R ** 2 + 1)
    num_ln_arg = (1 - P) / (1 - R * P)
    if num_ln_arg <= 0:
        return 0.0
    numerator = sqrt_term * math.log(num_ln_arg)
    A = 2 - P * (R + 1 - sqrt_term)
    B = 2 - P * (R + 1 + sqrt_term)
    if B == 0 or A / B <= 0:
        return 0.0
    denominator = (R - 1) * math.log(A / B)
    if abs(denominator) < 1e-15:
        return 0.0
    F = numerator / denominator
    return max(0.0, min(1.0, F))


# ============================================================================
# Tube-side HTC
# ============================================================================

def petukhov_friction(Re):
    return (0.790 * math.log(Re) - 1.64) ** (-2)


def hausen_nu(Re, Pr, D, L):
    Gz = Re * Pr * D / L
    Nu = 3.66 + (0.0668 * Gz) / (1.0 + 0.04 * Gz ** (2.0 / 3.0))
    return max(3.66, Nu)


def gnielinski_nu(Re, Pr, f):
    f8 = f / 8.0
    num = f8 * (Re - 1000.0) * Pr
    den = 1.0 + 12.7 * math.sqrt(f8) * (Pr ** (2.0 / 3.0) - 1.0)
    return num / den


def tube_side_htc(spec):
    geom = spec["geometry"]
    tf = spec["tube_fluid"]
    d_i = geom["tube_id_m"]
    d_o = geom["tube_od_m"]
    L = geom["tube_length_m"]
    n_tubes = geom["n_tubes"]
    n_passes = geom["tube_passes"]

    n_per_pass = n_tubes / n_passes
    A_flow = n_per_pass * math.pi / 4.0 * d_i ** 2
    v = tf["mass_flow_kg_s"] / (tf["density_kg_m3"] * A_flow)
    Re = tf["density_kg_m3"] * v * d_i / tf["viscosity_Pa_s"]
    Pr = tf["viscosity_Pa_s"] * tf["Cp_J_kgK"] / tf["k_W_mK"]

    if Re < 2300:
        Nu_raw = hausen_nu(Re, Pr, d_i, L)
        method = "hausen"
        regime = "laminar"
    else:
        f = petukhov_friction(Re)
        Nu_raw = gnielinski_nu(Re, Pr, f)
        method = "gnielinski"
        regime = "transition" if Re < 10000 else "turbulent"

    mu_w = tf["viscosity_wall_Pa_s"]
    if mu_w and mu_w > 0:
        visc_corr = (tf["viscosity_Pa_s"] / mu_w) ** 0.14
    else:
        visc_corr = 1.0

    Nu = Nu_raw * visc_corr
    h_i = Nu * tf["k_W_mK"] / d_i

    return {
        "Re": Re, "Pr": Pr, "Nu": Nu,
        "h_i_W_m2K": h_i, "flow_regime": regime,
    }


# ============================================================================
# Bell-Delaware shell-side HTC
# ============================================================================

# Taborek Table 10 — ideal bank j_i coefficients
# (Re_lo, Re_hi, a1, a2, a3, a4)
_JI_COEFFS = {
    30: [
        (1e0, 1e1, 1.40, -0.667, 1.450, 0.519),
        (1e1, 1e2, 0.321, -0.388, 1.450, 0.519),
        (1e2, 1e3, 0.321, -0.388, 1.450, 0.519),
        (1e3, 1e4, 0.321, -0.388, 1.450, 0.519),
        (1e4, 1e5, 0.321, -0.388, 1.450, 0.519),
    ],
    45: [
        (1e0, 1e1, 1.550, -0.667, 1.930, 0.500),
        (1e1, 1e2, 0.498, -0.656, 1.930, 0.500),
        (1e2, 1e3, 0.730, -0.500, 1.930, 0.500),
        (1e3, 1e4, 0.370, -0.396, 1.930, 0.500),
        (1e4, 1e5, 0.370, -0.396, 1.930, 0.500),
    ],
    60: [
        (1e0, 1e1, 1.40, -0.667, 1.450, 0.519),
        (1e1, 1e2, 0.321, -0.388, 1.450, 0.519),
        (1e2, 1e3, 0.321, -0.388, 1.450, 0.519),
        (1e3, 1e4, 0.321, -0.388, 1.450, 0.519),
        (1e4, 1e5, 0.321, -0.388, 1.450, 0.519),
    ],
    90: [
        (1e0, 1e1, 0.970, -0.667, 1.187, 0.370),
        (1e1, 1e2, 0.900, -0.631, 1.187, 0.370),
        (1e2, 1e3, 0.408, -0.460, 1.187, 0.370),
        (1e3, 1e4, 0.107, -0.266, 1.187, 0.370),
        (1e4, 1e5, 0.370, -0.395, 1.187, 0.370),
    ],
}


def ideal_bank_ji(Re, layout_angle, pitch_ratio):
    coeffs = _JI_COEFFS[layout_angle]
    for Re_lo, Re_hi, a1, a2, a3, a4 in coeffs:
        if Re_lo <= Re < Re_hi:
            a = a3 / (1.0 + 0.14 * Re ** a4)
            return a1 * (1.33 / pitch_ratio) ** a * Re ** a2
    # Re >= 1e5: use last band
    _, _, a1, a2, a3, a4 = coeffs[-1]
    a = a3 / (1.0 + 0.14 * Re ** a4)
    return a1 * (1.33 / pitch_ratio) ** a * Re ** a2


def compute_bd_geometry(spec):
    g = spec["geometry"]
    c = spec["clearances"]
    sf = spec["shell_fluid"]

    D_s = g["shell_id_m"]
    d_o = g["tube_od_m"]
    P_t = g["tube_pitch_m"]
    layout = g["layout_angle_deg"]
    N_t = g["n_tubes"]
    B_c = g["baffle_cut_pct"]
    B = g["baffle_spacing_central_m"]
    delta_tb = c["delta_tb_m"]
    delta_sb = c["delta_sb_m"]
    delta_bs = c["delta_bundle_shell_m"]
    m_dot = sf["mass_flow_kg_s"]
    mu = sf["viscosity_Pa_s"]

    D_otl = D_s - delta_bs

    cut_ratio = D_s * (1.0 - 2.0 * B_c / 100.0) / D_otl
    cut_ratio = max(-1.0, min(1.0, cut_ratio))
    theta_ctl = 2.0 * math.acos(cut_ratio)
    theta_ds = 2.0 * math.acos(1.0 - 2.0 * B_c / 100.0)

    sin_half = math.sin(theta_ctl / 2.0)
    F_c = (1.0 / math.pi) * (math.pi + 2.0 * cut_ratio * sin_half - theta_ctl)
    F_w = (theta_ctl - math.sin(theta_ctl)) / (2.0 * math.pi)
    N_tw = F_w * N_t

    S_m = B * (D_s - D_otl + D_otl * (P_t - d_o) / P_t)

    S_wg = (D_s ** 2 / 8.0) * (theta_ds - math.sin(theta_ds))
    A_tw = N_tw * math.pi * d_o ** 2 / 4.0
    S_w = S_wg - A_tw

    gap = (math.pi / 4.0) * ((d_o + delta_tb) ** 2 - d_o ** 2)
    N_thru = N_t * (1.0 + F_c) / 2.0
    S_tb = gap * N_thru

    S_sb = math.pi * D_s * (delta_sb / 2.0) * (1.0 - theta_ds / (2.0 * math.pi))

    S_b = B * (D_s - D_otl)

    if layout in (30, 60):
        P_p = P_t * math.cos(math.radians(30))
    elif layout == 45:
        P_p = P_t * math.cos(math.radians(45))
    else:
        P_p = P_t

    N_c = D_s * (1.0 - 2.0 * B_c / 100.0) / P_p
    N_cw = 0.8 * (D_s * B_c / 100.0) / P_p

    G_s = m_dot / S_m
    Re = d_o * G_s / mu

    return {
        "D_otl": D_otl, "F_c": F_c, "F_w": F_w, "N_tw": N_tw,
        "S_m": S_m, "S_w": S_w, "S_tb": S_tb, "S_sb": S_sb, "S_b": S_b,
        "N_c": N_c, "N_cw": N_cw, "P_p": P_p,
        "G_s": G_s, "Re": Re,
    }


def compute_Jc(F_c):
    return 0.55 + 0.72 * F_c


def compute_Jl(S_tb, S_sb, S_m):
    r_lm = (S_tb + S_sb) / S_m
    r_s = S_sb / (S_tb + S_sb) if (S_tb + S_sb) > 0 else 0.0
    return 0.44 * (1.0 - r_s) + (1.0 - 0.44 * (1.0 - r_s)) * math.exp(-2.2 * r_lm)


def compute_Jb(F_bp, N_ss, N_c, Re):
    C_bh = 1.25 if Re >= 100.0 else 1.35
    r_ss = N_ss / N_c if N_c > 0 else 0.0
    if r_ss >= 0.5:
        return 1.0
    return math.exp(-C_bh * F_bp * (1.0 - (2.0 * r_ss) ** (1.0 / 3.0)))


def compute_Js(N_b, L_i, L_o, L_c):
    n = 0.6
    ri = L_i / L_c
    ro = L_o / L_c
    num = (N_b - 1) + ri ** (1.0 - n) + ro ** (1.0 - n)
    den = (N_b - 1) + ri + ro
    return num / den


def compute_Jr(Re, N_c):
    if Re >= 100.0:
        return 1.0
    if Re >= 20.0:
        return (10.0 / N_c) ** 0.18
    return (10.0 / N_c) ** 0.18 * (Re / 20.0) ** 0.5


def shell_side_htc(spec):
    g = spec["geometry"]
    sf = spec["shell_fluid"]

    pitch_ratio = g["tube_pitch_m"] / g["tube_od_m"]
    layout = g["layout_angle_deg"]

    geom = compute_bd_geometry(spec)
    Re = geom["Re"]
    G_s = geom["G_s"]

    j_i = ideal_bank_ji(Re, layout, pitch_ratio)

    mu_w = sf["viscosity_wall_Pa_s"]
    if mu_w and mu_w > 0:
        visc_corr = (sf["viscosity_Pa_s"] / mu_w) ** 0.14
    else:
        visc_corr = 1.0

    Pr = sf["viscosity_Pa_s"] * sf["Cp_J_kgK"] / sf["k_W_mK"]
    h_ideal = j_i * sf["Cp_J_kgK"] * G_s * Pr ** (-2.0 / 3.0) * visc_corr

    F_c = geom["F_c"]
    S_m = geom["S_m"]
    S_tb = geom["S_tb"]
    S_sb = geom["S_sb"]
    S_b = geom["S_b"]
    N_c = geom["N_c"]
    N_b = g["n_baffles"]
    N_ss = g["n_sealing_strip_pairs"]
    F_bp = S_b / S_m

    J_c = compute_Jc(F_c)
    J_l = compute_Jl(S_tb, S_sb, S_m)
    J_b = compute_Jb(F_bp, N_ss, N_c, Re)
    J_s = compute_Js(
        N_b,
        g["baffle_spacing_inlet_m"],
        g["baffle_spacing_outlet_m"],
        g["baffle_spacing_central_m"],
    )
    J_r = compute_Jr(Re, N_c)

    J_prod = J_c * J_l * J_b * J_s * J_r
    h_o = h_ideal * J_prod

    return {
        "Re": Re, "j_i": j_i,
        "J_c": J_c, "J_l": J_l, "J_b": J_b, "J_s": J_s, "J_r": J_r,
        "h_ideal_W_m2K": h_ideal, "h_o_W_m2K": h_o,
    }


# ============================================================================
# Overall U and area
# ============================================================================

def compute_overall_u(h_i, h_o, d_o, d_i, k_wall, R_f_shell, R_f_tube):
    ratio = d_o / d_i
    R_shell_film = 1.0 / h_o
    R_tube_film = ratio / h_i
    R_shell_foul = R_f_shell
    R_tube_foul = R_f_tube * ratio
    R_wall = d_o * math.log(d_o / d_i) / (2.0 * k_wall)

    total_dirty = R_shell_film + R_tube_film + R_shell_foul + R_tube_foul + R_wall
    total_clean = R_shell_film + R_tube_film + R_wall

    U_dirty = 1.0 / total_dirty
    U_clean = 1.0 / total_clean
    CF = U_dirty / U_clean if U_clean > 0 else 0.0

    resistances = {
        "shell_film": R_shell_film,
        "tube_film": R_tube_film,
        "shell_fouling": R_shell_foul,
        "tube_fouling": R_tube_foul,
        "wall": R_wall,
    }
    controlling = max(resistances, key=resistances.get)

    return {
        "U_clean_W_m2K": U_clean,
        "U_dirty_W_m2K": U_dirty,
        "cleanliness_factor": CF,
        "controlling_resistance": controlling,
    }


def rate(spec):
    temps = spec["temperatures"]
    geom = spec["geometry"]
    foul = spec["fouling"]

    T_h_in = temps["T_hot_in_C"]
    T_h_out = temps["T_hot_out_C"]
    T_c_in = temps["T_cold_in_C"]
    T_c_out = temps["T_cold_out_C"]

    # LMTD
    lmtd_val = compute_lmtd(T_h_in, T_h_out, T_c_in, T_c_out)
    R = compute_R(T_h_in, T_h_out, T_c_in, T_c_out)
    P = compute_P(T_h_in, T_h_out, T_c_in, T_c_out)
    F = compute_f_factor(R, P, spec["n_shell_passes"])
    lmtd_eff = F * lmtd_val

    # Tube-side
    ts = tube_side_htc(spec)

    # Shell-side
    ss = shell_side_htc(spec)

    # Overall U
    overall = compute_overall_u(
        ts["h_i_W_m2K"], ss["h_o_W_m2K"],
        geom["tube_od_m"], geom["tube_id_m"],
        geom["k_wall_W_mK"],
        foul["R_f_shell_m2KW"], foul["R_f_tube_m2KW"],
    )

    # Heat duty and area
    sf = spec["shell_fluid"]
    Q = sf["mass_flow_kg_s"] * sf["Cp_J_kgK"] * abs(T_h_in - T_h_out)
    A_avail = geom["n_tubes"] * math.pi * geom["tube_od_m"] * geom["tube_length_m"]
    A_req = Q / (overall["U_dirty_W_m2K"] * lmtd_eff) if lmtd_eff > 0 else float("inf")
    overdesign = 100.0 * (A_avail - A_req) / A_req if A_req > 0 else 0.0

    return {
        "lmtd": {
            "LMTD_K": lmtd_val, "R": R, "P": P,
            "F": F, "LMTD_eff_K": lmtd_eff,
        },
        "tube_side": ts,
        "shell_side": ss,
        "overall": overall,
        "area": {
            "required_m2": A_req,
            "available_m2": A_avail,
            "overdesign_pct": overdesign,
        },
        "heat_duty_W": Q,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 hx_rate.py <input.json>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        spec = json.load(f)
    result = rate(spec)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
