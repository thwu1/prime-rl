#!/usr/bin/env python3

"""
Single-effect NH3-H2O absorption chiller cycle solver.

Computes state points and performance metrics for a 10-point single-effect
absorption chiller with solution heat exchanger, using the Patek-Klomfar
(1995) correlations for ammonia-water properties.
"""

import argparse
import json
import sys

sys.path.insert(0, "/app")
from nh3h2o_props import (
    bubble_temperature, dew_temperature, vapor_composition,
    liquid_enthalpy, vapor_enthalpy, bubble_pressure, liquid_composition,
    molar_to_mass_fraction, mass_to_molar_fraction,
)


def solve_cycle(config):
    T_evap = config["T_evap_K"]
    T_cond = config["T_cond_K"]
    T_gen = config["T_gen_K"]
    T_abs = config["T_abs_K"]
    eps_shx = config["shx_effectiveness"]
    x_ref = config["x_ref_molar"]

    # ---------------------------------------------------------------
    # Cycle pressures from refrigerant bubble-point conditions
    # ---------------------------------------------------------------
    P_low = bubble_pressure(T_evap, x_ref)
    P_high = bubble_pressure(T_cond, x_ref)

    # ---------------------------------------------------------------
    # Solution compositions from phase equilibrium
    # ---------------------------------------------------------------
    x_strong = liquid_composition(P_low, T_abs)   # absorber outlet
    x_weak = liquid_composition(P_high, T_gen)     # generator outlet

    # ---------------------------------------------------------------
    # Circulation ratio from ammonia mass balance (mass fractions)
    # f * w_strong = 1 * w_ref + (f-1) * w_weak
    # ---------------------------------------------------------------
    w_strong = molar_to_mass_fraction(x_strong)
    w_weak = molar_to_mass_fraction(x_weak)
    w_ref = molar_to_mass_fraction(x_ref)
    f = (w_ref - w_weak) / (w_strong - w_weak)

    # ---------------------------------------------------------------
    # State 1: Strong solution at absorber outlet (saturated liquid)
    # ---------------------------------------------------------------
    T_1 = T_abs
    h_1 = liquid_enthalpy(T_1, x_strong)

    # ---------------------------------------------------------------
    # State 2: After pump (neglect pump work)
    # ---------------------------------------------------------------
    T_2 = T_abs
    h_2 = h_1

    # ---------------------------------------------------------------
    # State 4: Weak solution at generator outlet (saturated liquid)
    # ---------------------------------------------------------------
    T_4 = T_gen
    h_4 = liquid_enthalpy(T_4, x_weak)

    # ---------------------------------------------------------------
    # State 3: After SHX cold side (temperature-based effectiveness)
    # T_3 = T_2 + eps * (T_4 - T_2)
    # ---------------------------------------------------------------
    T_3 = T_2 + eps_shx * (T_4 - T_2)
    h_3 = liquid_enthalpy(T_3, x_strong)

    # ---------------------------------------------------------------
    # State 5: After SHX hot side (energy balance on SHX)
    # f * (h_3 - h_2) = (f-1) * (h_4 - h_5)
    # h_5 = h_4 - [f / (f-1)] * (h_3 - h_2)
    # ---------------------------------------------------------------
    h_5 = h_4 - (f / (f - 1.0)) * (h_3 - h_2)

    # Recover T_5 by inverting liquid_enthalpy(T, x_weak) = h_5
    from scipy.optimize import brentq

    def h_L_residual_5(T):
        return liquid_enthalpy(T, x_weak) - h_5

    T_5 = brentq(h_L_residual_5, 250.0, 500.0, xtol=1e-10)

    # ---------------------------------------------------------------
    # State 6: After solution expansion valve (isenthalpic)
    # ---------------------------------------------------------------
    h_6 = h_5
    T_6 = T_5  # approximate for liquid

    # ---------------------------------------------------------------
    # State 7: Refrigerant vapor at generator outlet
    # ---------------------------------------------------------------
    T_7 = dew_temperature(P_high, x_ref)
    h_7 = vapor_enthalpy(T_7, x_ref)

    # ---------------------------------------------------------------
    # State 8: Refrigerant liquid at condenser outlet
    # ---------------------------------------------------------------
    T_8 = T_cond
    h_8 = liquid_enthalpy(T_8, x_ref)

    # ---------------------------------------------------------------
    # State 9: After refrigerant expansion valve (isenthalpic)
    # ---------------------------------------------------------------
    h_9 = h_8
    T_9 = T_evap  # two-phase region

    # ---------------------------------------------------------------
    # State 10: Refrigerant saturated vapor at evaporator outlet
    # ---------------------------------------------------------------
    T_10 = T_evap
    h_10 = vapor_enthalpy(T_10, x_ref)

    # ---------------------------------------------------------------
    # Heat duties per kg of refrigerant
    # ---------------------------------------------------------------
    Q_evap = h_10 - h_9             # evaporator: cooling effect
    Q_cond = h_7 - h_8              # condenser: heat rejection
    Q_gen = h_7 + (f - 1) * h_4 - f * h_3   # generator: heat input
    Q_abs = h_10 + (f - 1) * h_6 - f * h_1  # absorber: heat rejection

    COP = Q_evap / Q_gen

    state_points = {
        "1":  {"T_K": T_1,  "P_MPa": P_low,  "x_molar": x_strong, "h_kJ_per_kg": h_1},
        "2":  {"T_K": T_2,  "P_MPa": P_high, "x_molar": x_strong, "h_kJ_per_kg": h_2},
        "3":  {"T_K": T_3,  "P_MPa": P_high, "x_molar": x_strong, "h_kJ_per_kg": h_3},
        "4":  {"T_K": T_4,  "P_MPa": P_high, "x_molar": x_weak,   "h_kJ_per_kg": h_4},
        "5":  {"T_K": T_5,  "P_MPa": P_high, "x_molar": x_weak,   "h_kJ_per_kg": h_5},
        "6":  {"T_K": T_6,  "P_MPa": P_low,  "x_molar": x_weak,   "h_kJ_per_kg": h_6},
        "7":  {"T_K": T_7,  "P_MPa": P_high, "x_molar": x_ref,    "h_kJ_per_kg": h_7},
        "8":  {"T_K": T_8,  "P_MPa": P_high, "x_molar": x_ref,    "h_kJ_per_kg": h_8},
        "9":  {"T_K": T_9,  "P_MPa": P_low,  "x_molar": x_ref,    "h_kJ_per_kg": h_9},
        "10": {"T_K": T_10, "P_MPa": P_low,  "x_molar": x_ref,    "h_kJ_per_kg": h_10},
    }

    return {
        "P_high_MPa": P_high,
        "P_low_MPa": P_low,
        "x_strong_molar": x_strong,
        "x_weak_molar": x_weak,
        "f_circulation_ratio": f,
        "COP_cooling": COP,
        "Q_evap_kJ_per_kg_ref": Q_evap,
        "Q_gen_kJ_per_kg_ref": Q_gen,
        "Q_cond_kJ_per_kg_ref": Q_cond,
        "Q_abs_kJ_per_kg_ref": Q_abs,
        "state_points": state_points,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Single-effect NH3-H2O absorption chiller cycle solver"
    )
    parser.add_argument("--config", required=True, help="Path to JSON config file")
    args = parser.parse_args()

    with open(args.config) as fh:
        config = json.load(fh)

    result = solve_cycle(config)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
