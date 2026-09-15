"""Bell-Delaware shell-side heat transfer correlations — FIXED.

"""

import math

# Taborek Table 10 — ideal bank j_i coefficients
# Format per row: (Re_lo, Re_hi, a1, a2, a3, a4)
JI_COEFFS = {
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
    coeffs = JI_COEFFS[layout_angle]
    for Re_lo, Re_hi, a1, a2, a3, a4 in coeffs:
        if Re_lo <= Re < Re_hi:
            a = a3 / (1.0 + 0.14 * Re ** a4)
            return a1 * (1.33 / pitch_ratio) ** a * Re ** a2
    _, _, a1, a2, a3, a4 = coeffs[-1]
    a = a3 / (1.0 + 0.14 * Re ** a4)
    return a1 * (1.33 / pitch_ratio) ** a * Re ** a2


def compute_geometry(spec):
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

    if layout in (30, 60):
        P_p = P_t * math.cos(math.radians(30))
    elif layout == 45:
        P_p = P_t * math.cos(math.radians(45))
    else:
        P_p = P_t

    # FIX: D_otl multiplier restored in crossflow area
    S_m = B * (D_s - D_otl + D_otl * (P_t - d_o) / P_t)

    S_wg = (D_s ** 2 / 8.0) * (theta_ds - math.sin(theta_ds))
    A_tw = N_tw * math.pi * d_o ** 2 / 4.0
    S_w = S_wg - A_tw

    gap = (math.pi / 4.0) * ((d_o + delta_tb) ** 2 - d_o ** 2)
    N_thru = N_t * (1.0 + F_c) / 2.0
    S_tb = gap * N_thru

    S_sb = math.pi * D_s * (delta_sb / 2.0) * (1.0 - theta_ds / (2.0 * math.pi))

    S_b = B * (D_s - D_otl)

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
    # FIX: cube root restored on (2*r_ss) term
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

    geom = compute_geometry(spec)
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
