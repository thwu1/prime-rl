#!/usr/bin/env python3
"""Shell-and-tube heat exchanger thermal rating tool.

Reads a JSON case specification and outputs a JSON rating result.

"""

import json
import math
import sys

from bell_delaware import shell_side_htc


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


def _equivalent_P1(R, P, N):
    """Convert overall P to single-shell equivalent P1 for N shells."""
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
    """Bowman (1940) F-factor for a multi-tube-pass exchanger."""
    if P <= 0 or P >= 1:
        return 0.0
    if R <= 0:
        return 0.0
    if n_shell_passes > 1:
        P = _equivalent_P1(R, P, n_shell_passes)
        if P <= 0 or P >= 1:
            return 0.0
    if abs(R - 1.0) < 1e-6:
        return 1.0
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
    """Petukhov friction factor for turbulent pipe flow."""
    return (0.790 * math.log(Re) - 1.64) ** (-2)


def hausen_nu(Re, Pr, D, L):
    """Hausen correlation for laminar developing flow."""
    Gz = Re * Pr * D / L
    Nu = 3.66 + (0.0668 * Gz) / (1.0 + 0.04 * Gz ** (2.0 / 3.0))
    return max(3.66, Nu)


def gnielinski_nu(Re, Pr, f):
    """Gnielinski correlation for turbulent pipe flow."""
    f8 = f / 8.0
    num = f8 * (Re - 1000.0) * Pr
    den = 1.0 + 12.7 * math.sqrt(f8) * (Pr ** (2.0 / 3.0) - 1.0)
    return num / den


def tube_side_htc(spec):
    """Compute tube-side heat transfer coefficient."""
    geom = spec["geometry"]
    tf = spec["tube_fluid"]
    d_i = geom["tube_id_m"]
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
        regime = "laminar"
    else:
        f = petukhov_friction(Re)
        Nu_raw = gnielinski_nu(Re, Pr, f)
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
# Overall U and area
# ============================================================================

def compute_overall_u(h_i, h_o, d_o, d_i, k_wall, R_f_shell, R_f_tube):
    """Five-resistance overall U model on outer-area basis."""
    ratio = d_o / d_i
    R_shell_film = 1.0 / h_o
    R_tube_film = ratio / h_i
    R_shell_foul = R_f_shell
    R_tube_foul = R_f_tube
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


# ============================================================================
# Main rating function
# ============================================================================

def rate(spec):
    """Rate a heat exchanger and return all computed quantities."""
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
