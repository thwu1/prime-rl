#!/usr/bin/env python3
"""
Adsorption mixture analysis tool.

Implements:
- IAST (Ideal Adsorbed Solution Theory) for binary gas mixtures
- Isosteric enthalpy via Clausius-Clapeyron equation
- Selectivity vs pressure (SVP) curves

"""

import sys
import json
import numpy as np
from scipy.interpolate import interp1d
from scipy.optimize import brentq
from scipy import stats, constants


def load_isotherm(filepath):
    """Load isotherm data from JSON file, adsorption branch only."""
    with open(filepath) as f:
        data = json.load(f)

    iso_data = data["isotherm_data"]
    # Filter to adsorption branch only (exclude 'des' branch points)
    ads_data = [pt for pt in iso_data if pt.get("branch", "ads") != "des"]

    pressure = np.array([pt["pressure"] for pt in ads_data], dtype=float)
    loading = np.array([pt["loading"] for pt in ads_data], dtype=float)

    # Sort by pressure ascending
    idx = np.argsort(pressure)
    pressure = pressure[idx]
    loading = loading[idx]

    return {
        "pressure": pressure,
        "loading": loading,
        "temperature": float(data["temperature"]),
        "material": data.get("material", ""),
    }


def compute_spreading_pressure_table(pressure, loading):
    """
    Compute the reduced spreading pressure at each tabulated data point.

    SP(P_i) = integral from 0 to P_i of [n(P)/P] dP

    Uses Henry's law from 0 to P[0], and exact analytical integration
    of linearly-interpolated isotherm segments for subsequent intervals.
    For a linear segment n(P) = slope*P + intercept:
       integral of n/P dP = slope*(P2-P1) + intercept*ln(P2/P1)
    """
    sp = np.zeros(len(pressure))

    # From 0 to first data point: Henry's law region
    sp[0] = loading[0]

    # Analytical integration of linear segments
    for i in range(1, len(pressure)):
        slope = (loading[i] - loading[i - 1]) / (pressure[i] - pressure[i - 1])
        intercept = loading[i - 1] - slope * pressure[i - 1]
        segment = slope * (pressure[i] - pressure[i - 1]) + intercept * np.log(
            pressure[i] / pressure[i - 1]
        )
        sp[i] = sp[i - 1] + segment

    return sp


def spreading_pressure_at(pressure, loading, P):
    """
    Compute the reduced spreading pressure at an arbitrary pressure P.

    Uses exact analytical integration matching the pyIAST/pyGAPS approach.
    """
    henry_const = loading[0] / pressure[0]
    n_points = int(np.sum(pressure < P))

    if n_points == 0:
        return henry_const * P

    # Area from 0 to P[0]
    area = loading[0]

    # Full segments
    for i in range(n_points - 1):
        slope = (loading[i + 1] - loading[i]) / (pressure[i + 1] - pressure[i])
        intercept = loading[i] - slope * pressure[i]
        area += slope * (pressure[i + 1] - pressure[i]) + intercept * np.log(
            pressure[i + 1] / pressure[i]
        )

    # Final partial segment (from last data point below P to P)
    n_interp = interp1d(pressure, loading, kind="linear", fill_value="extrapolate")
    loading_at_P = float(n_interp(P))

    slope = (loading_at_P - loading[n_points - 1]) / (P - pressure[n_points - 1])
    intercept = loading[n_points - 1] - slope * pressure[n_points - 1]
    area += slope * (P - pressure[n_points - 1]) + intercept * np.log(
        P / pressure[n_points - 1]
    )

    return area


def make_spreading_pressure_functions(pressure, loading):
    """
    Create forward (P -> SP) and inverse (SP -> P) interpolation functions
    for the spreading pressure of a single-component isotherm.

    Returns: (sp_forward_func, sp_inverse_func, sp_max)
    """
    # Build a fine grid for accurate interpolation
    p_fine = np.logspace(
        np.log10(pressure[0] * 0.01), np.log10(pressure[-1]), 3000
    )
    sp_fine = np.array(
        [spreading_pressure_at(pressure, loading, p) for p in p_fine]
    )

    # Prepend origin (P=0, SP=0)
    p_ext = np.concatenate([[0.0], p_fine])
    sp_ext = np.concatenate([[0.0], sp_fine])

    # Forward: pressure -> spreading pressure
    sp_forward = interp1d(
        p_ext, sp_ext, kind="linear", bounds_error=False, fill_value=(0.0, sp_fine[-1])
    )

    # Inverse: spreading pressure -> pressure
    sp_inverse = interp1d(
        sp_ext, p_ext, kind="linear", bounds_error=False, fill_value=(0.0, p_fine[-1])
    )

    return sp_forward, sp_inverse, float(sp_fine[-1])


def iast_solve(iso1, iso2, y1, y2, P_total):
    """
    Solve IAST equilibrium for a binary gas mixture.

    Given single-component isotherms and gas-phase composition (y1, y2)
    at total pressure P_total, find the adsorbed-phase composition (x1, x2).

    The IAST equations are:
    1. Equal spreading pressure: SP1(P1_0) = SP2(P2_0)
    2. Raoult's law analog: y_i * P_total = x_i * P_i_0
    3. Sum of fractions: x1 + x2 = 1

    Parameterized by common spreading pressure pi:
      P1_0 = SP1_inv(pi), P2_0 = SP2_inv(pi)
      Objective: y1*P/P1_0 + y2*P/P2_0 - 1 = 0
    """
    sp_fwd1, sp_inv1, sp_max1 = make_spreading_pressure_functions(
        iso1["pressure"], iso1["loading"]
    )
    sp_fwd2, sp_inv2, sp_max2 = make_spreading_pressure_functions(
        iso2["pressure"], iso2["loading"]
    )

    sp_max = min(sp_max1, sp_max2)
    sp_min = 1e-10

    def objective(pi):
        P01 = float(sp_inv1(pi))
        P02 = float(sp_inv2(pi))
        if P01 <= 1e-15 or P02 <= 1e-15:
            return 1e10
        return y1 * P_total / P01 + y2 * P_total / P02 - 1.0

    # Find root using Brent's method
    pi_sol = brentq(objective, sp_min, sp_max * 0.9999, xtol=1e-14, maxiter=2000)

    P01 = float(sp_inv1(pi_sol))
    P02 = float(sp_inv2(pi_sol))

    x1 = y1 * P_total / P01
    x2 = y2 * P_total / P02

    # Normalize to ensure sum = 1
    total = x1 + x2
    x1 /= total
    x2 /= total

    selectivity = (x1 / y1) / (x2 / y2) if (y1 > 0 and y2 > 0) else 0.0

    return [float(x1), float(x2)], float(selectivity)


def isosteric_enthalpy(isotherms, n_points=50):
    """
    Compute isosteric enthalpy of adsorption via the Clausius-Clapeyron equation.

    For each loading point n_a, find the pressure P at each temperature T
    by inverting each isotherm, then perform linear regression of ln(P) vs 1/T.
    The slope gives: delta_H = -slope * R (in J/mol), converted to kJ/mol.
    """
    temperatures = np.array([iso["temperature"] for iso in isotherms])

    # Determine common loading range
    min_loading = 1.01 * max(min(iso["loading"]) for iso in isotherms)
    max_loading = 0.99 * min(max(iso["loading"]) for iso in isotherms)
    loading_points = np.linspace(min_loading, max_loading, n_points)

    # Create inverse interpolations: loading -> pressure for each isotherm
    pressure_at_loading = []
    for iso in isotherms:
        interp = interp1d(iso["loading"], iso["pressure"], kind="linear")
        pressure_at_loading.append(interp)

    inv_T = 1.0 / temperatures
    R = constants.gas_constant  # 8.314 J/(mol*K)

    enthalpies = []
    for n in loading_points:
        pressures = np.array([float(interp(n)) for interp in pressure_at_loading])
        ln_P = np.log(pressures)

        slope, intercept, r_val, p_val, std_err = stats.linregress(inv_T, ln_P)
        enthalpy = -slope * R / 1000.0  # Convert J/mol to kJ/mol
        enthalpies.append(float(enthalpy))

    return loading_points.tolist(), enthalpies, float(np.mean(enthalpies))


def svp(iso1, iso2, y1, y2, P_min, P_max, N):
    """
    Compute IAST selectivity vs total pressure.

    Solves IAST at N linearly-spaced pressures and returns selectivity curve.
    """
    pressures = np.linspace(P_min, P_max, N)
    selectivities = []

    for P in pressures:
        try:
            _, sel = iast_solve(iso1, iso2, y1, y2, float(P))
            selectivities.append(float(sel))
        except Exception:
            selectivities.append(float("nan"))

    return pressures.tolist(), selectivities, float(np.nanmean(selectivities))


def main():
    if len(sys.argv) < 2:
        print("Usage: analyze.py <command> [args...]", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == "iast":
        if len(sys.argv) != 7:
            print(
                "Usage: analyze.py iast <iso1> <iso2> <y1> <y2> <P_total>",
                file=sys.stderr,
            )
            sys.exit(1)
        iso1 = load_isotherm(sys.argv[2])
        iso2 = load_isotherm(sys.argv[3])
        y1 = float(sys.argv[4])
        y2 = float(sys.argv[5])
        P_total = float(sys.argv[6])

        fracs, sel = iast_solve(iso1, iso2, y1, y2, P_total)
        print(json.dumps({"adsorbed_fractions": fracs, "selectivity": sel}))

    elif command == "enthalpy":
        if len(sys.argv) < 4:
            print(
                "Usage: analyze.py enthalpy <iso1> <iso2> [<iso3> ...]",
                file=sys.stderr,
            )
            sys.exit(1)
        isotherms = [load_isotherm(f) for f in sys.argv[2:]]
        loading, enthalpies, avg = isosteric_enthalpy(isotherms)
        print(
            json.dumps(
                {
                    "loading": loading,
                    "isosteric_enthalpy": enthalpies,
                    "average_enthalpy": avg,
                }
            )
        )

    elif command == "svp":
        if len(sys.argv) != 9:
            print(
                "Usage: analyze.py svp <iso1> <iso2> <y1> <y2> <P_min> <P_max> <N>",
                file=sys.stderr,
            )
            sys.exit(1)
        iso1 = load_isotherm(sys.argv[2])
        iso2 = load_isotherm(sys.argv[3])
        y1 = float(sys.argv[4])
        y2 = float(sys.argv[5])
        P_min = float(sys.argv[6])
        P_max = float(sys.argv[7])
        N = int(sys.argv[8])

        pressures, selectivities, mean_sel = svp(iso1, iso2, y1, y2, P_min, P_max, N)
        print(
            json.dumps(
                {
                    "pressures": pressures,
                    "selectivities": selectivities,
                    "mean_selectivity": mean_sel,
                }
            )
        )

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
