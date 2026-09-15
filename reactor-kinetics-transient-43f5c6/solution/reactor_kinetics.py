#!/usr/bin/env python3

"""
Coupled six-group point kinetics + lumped thermal feedback reactor transient solver
with nonlinear spectral correction from a compiled Fortran library,
inhour analysis, and rod calibration capability.
"""

import csv
import ctypes
import json
import math
import os
import re
import subprocess
import sys

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq


def parse_reactor_inp(path):
    """Parse the card-format reactor input file with unit handling."""
    kinetics = {}
    thermal = {}
    xs_source = None

    with open(path, "r") as f:
        lines = f.readlines()

    in_kinetics = False
    in_thermal = False
    in_xs_config = False
    in_precursor = False
    precursors = []

    for raw_line in lines:
        if "!" in raw_line:
            idx = raw_line.index("!")
            code_part = raw_line[:idx].strip()
            comment_part = raw_line[idx:]
        else:
            code_part = raw_line.strip()
            comment_part = ""

        if not code_part:
            continue

        tokens = code_part.split()
        if not tokens:
            continue

        keyword = tokens[0].upper()

        if keyword == "CARD":
            section = tokens[1].upper() if len(tokens) > 1 else ""
            in_kinetics = section == "KINETICS"
            in_thermal = section == "THERMAL"
            in_xs_config = section == "XS_CONFIG"
            continue
        elif keyword == "END_CARD":
            in_kinetics = False
            in_thermal = False
            in_xs_config = False
            continue
        elif keyword == "PRECURSOR_DATA":
            in_precursor = True
            continue
        elif keyword == "END_PRECURSOR_DATA":
            in_precursor = False
            continue

        if in_precursor:
            parts = tokens
            if len(parts) >= 3:
                group_id = int(parts[0])
                decay_const = float(parts[1])
                beta_frac = float(parts[2])
                precursors.append((group_id, decay_const, beta_frac))
            continue

        unit = ""
        bracket_match = re.search(r"\[([^\]]+)\]", comment_part)
        if bracket_match:
            unit = bracket_match.group(1).strip()

        if in_kinetics:
            if keyword == "NUM_PRECURSOR_GROUPS":
                kinetics["ngroups"] = int(tokens[1])
            elif keyword == "PROMPT_GEN_TIME":
                kinetics["generation_time"] = float(tokens[1])

        elif in_thermal:
            value = float(tokens[1])

            if keyword == "POWER_NOMINAL":
                if unit.lower() in ("kw",):
                    value *= 1000.0
                elif unit.lower() in ("mw",):
                    value *= 1.0e6
                thermal["nominal_power_W"] = value
            elif keyword == "FUEL_HEAT_CAP":
                thermal["fuel_heat_capacity_J_per_K"] = value
            elif keyword == "MOD_HEAT_CAP":
                thermal["moderator_heat_capacity_J_per_K"] = value
            elif keyword == "FUEL_MOD_HTC":
                thermal["fuel_to_moderator_htc_W_per_K"] = value
            elif keyword == "MOD_COOL_HTC":
                thermal["moderator_to_coolant_htc_W_per_K"] = value
            elif keyword == "COOLANT_INLET_T":
                if unit.upper() in ("C", "DEG_C", "CELSIUS"):
                    value += 273.15
                thermal["coolant_inlet_temperature_K"] = value
            elif keyword == "ALPHA_FUEL":
                thermal["fuel_temperature_reactivity_coeff_per_K"] = value
            elif keyword == "ALPHA_MOD":
                thermal["moderator_temperature_reactivity_coeff_per_K"] = value

        elif in_xs_config:
            if keyword == "XS_SOURCE":
                xs_source = tokens[1]

    precursors.sort(key=lambda x: x[0])
    kinetics["lambda"] = [p[1] for p in precursors]
    kinetics["beta"] = [p[2] for p in precursors]

    return kinetics, thermal, xs_source


def compile_and_load_xs_library(xs_source_path, so_path="/app/libspectral.so"):
    """Compile the Fortran spectral feedback library if not already compiled,
    load it, and extract the spectral correction coefficients."""
    if not os.path.isfile(so_path):
        result = subprocess.run(
            ["gfortran", "-shared", "-fPIC", "-O2", "-o", so_path, xs_source_path],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Fortran compilation failed: {result.stderr.decode()}"
            )

    lib = ctypes.CDLL(so_path)

    lib.compute_feedback.argtypes = [
        ctypes.c_double, ctypes.c_double,
        ctypes.c_double, ctypes.c_double,
        ctypes.c_double, ctypes.c_double,
        ctypes.POINTER(ctypes.c_double),
    ]
    lib.compute_feedback.restype = None

    lib.get_spectral_coefficients.argtypes = [
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
    ]
    lib.get_spectral_coefficients.restype = None

    kf = ctypes.c_double(0.0)
    km = ctypes.c_double(0.0)
    kfm = ctypes.c_double(0.0)
    lib.get_spectral_coefficients(
        ctypes.byref(kf), ctypes.byref(km), ctypes.byref(kfm)
    )

    return lib, kf.value, km.value, kfm.value


def compute_steady_state(kinetics, thermal):
    """Compute critical steady-state initial conditions."""
    beta = np.array(kinetics["beta"])
    lam = np.array(kinetics["lambda"])
    gen_time = kinetics["generation_time"]

    P0 = thermal["nominal_power_W"]
    h_fm = thermal["fuel_to_moderator_htc_W_per_K"]
    h_mc = thermal["moderator_to_coolant_htc_W_per_K"]
    T_inlet = thermal["coolant_inlet_temperature_K"]

    n0 = 1.0
    C0 = beta * n0 / (gen_time * lam)
    T_m0 = T_inlet + P0 / h_mc
    T_f0 = T_m0 + P0 / h_fm

    return n0, C0, T_f0, T_m0


def compute_rod_worth(beta_total, measured_ratio):
    """Compute rod worth from prompt jump relationship.
    ratio = beta / (beta - rho)  =>  rho = beta * (1 - 1/ratio)
    """
    return beta_total * (1.0 - 1.0 / measured_ratio)


def solve_inhour_period(rho, beta, lam, gen_time):
    """Find the stable period from the inhour equation.
    rho = Lambda*omega + sum_i(beta_i*omega / (lambda_i + omega))
    Returns T = 1/omega where omega is the positive root (rho > 0 only).
    """

    def inhour_func(omega):
        result = gen_time * omega
        for b, l in zip(beta, lam):
            result += b * omega / (l + omega)
        return result - rho

    omega_upper = max(abs(rho) / gen_time * 10, 1000.0)
    while inhour_func(omega_upper) < 0:
        omega_upper *= 10

    omega_star = brentq(inhour_func, 1e-15, omega_upper, xtol=1e-14, rtol=1e-14)
    return 1.0 / omega_star


def build_reactivity_func(scenario, beta_total):
    """Construct the external reactivity function."""
    stype = scenario["type"]

    if stype == "step":
        rho_val = scenario["reactivity_dollars"] * beta_total
        return lambda t: rho_val if t >= 0 else 0.0

    elif stype == "ramp_then_hold":
        rate = scenario["rate_pcm_per_s"] * 1.0e-5
        dur = scenario["ramp_duration_s"]
        rho_max = rate * dur

        def rho_ramp(t):
            if t <= 0:
                return 0.0
            elif t <= dur:
                return rate * t
            else:
                return rho_max

        return rho_ramp

    elif stype == "oscillatory":
        amp = scenario["amplitude_pcm"] * 1.0e-5
        omega = 2.0 * math.pi * scenario["frequency_hz"]
        return lambda t: amp * math.sin(omega * t)

    elif stype == "scram":
        rho_val = scenario["reactivity_pcm"] * 1.0e-5
        return lambda t: rho_val if t >= 0 else 0.0

    elif stype == "rod_drop":
        rho_val = compute_rod_worth(beta_total, scenario["measured_prompt_drop_ratio"])
        return lambda t: rho_val if t >= 0 else 0.0

    else:
        raise ValueError(f"Unknown scenario type: {stype}")


def make_rhs(kinetics, thermal, rho_ext_func, T_f0, T_m0,
             kappa_f, kappa_m, kappa_fm):
    """Build the RHS function for the coupled ODE system with nonlinear
    spectral feedback correction."""
    beta = np.array(kinetics["beta"])
    lam = np.array(kinetics["lambda"])
    gen_time = kinetics["generation_time"]
    beta_total = float(np.sum(beta))

    P0 = thermal["nominal_power_W"]
    Mf_cp = thermal["fuel_heat_capacity_J_per_K"]
    Mm_cp = thermal["moderator_heat_capacity_J_per_K"]
    h_fm = thermal["fuel_to_moderator_htc_W_per_K"]
    h_mc = thermal["moderator_to_coolant_htc_W_per_K"]
    T_inlet = thermal["coolant_inlet_temperature_K"]
    alpha_f = thermal["fuel_temperature_reactivity_coeff_per_K"]
    alpha_m = thermal["moderator_temperature_reactivity_coeff_per_K"]

    def rhs(t, y):
        n = y[0]
        C = y[1:7]
        T_f = y[7]
        T_m = y[8]

        rho_ext = rho_ext_func(t)
        dT_f = T_f - T_f0
        dT_m = T_m - T_m0
        rho_fb = (alpha_f * dT_f + alpha_m * dT_m
                  + kappa_f * dT_f * dT_f
                  + kappa_m * dT_m * dT_m
                  + kappa_fm * dT_f * dT_m)
        rho = rho_ext + rho_fb

        dydt = np.empty(9)
        dydt[0] = (rho - beta_total) / gen_time * n + np.dot(lam, C)
        dydt[1:7] = beta / gen_time * n - lam * C
        dydt[7] = P0 * n / Mf_cp - h_fm / Mf_cp * (T_f - T_m)
        dydt[8] = h_fm / Mm_cp * (T_f - T_m) - h_mc / Mm_cp * (T_m - T_inlet)

        return dydt

    return rhs


def solve_scenario(scenario, kinetics, thermal, n0, C0, T_f0, T_m0,
                   kappa_f, kappa_m, kappa_fm):
    """Integrate one transient scenario."""
    beta_total = float(np.sum(kinetics["beta"]))
    rho_ext_func = build_reactivity_func(scenario, beta_total)
    rhs = make_rhs(kinetics, thermal, rho_ext_func, T_f0, T_m0,
                   kappa_f, kappa_m, kappa_fm)

    y0 = np.zeros(9)
    y0[0] = n0
    y0[1:7] = C0
    y0[7] = T_f0
    y0[8] = T_m0

    t_end = scenario["t_end"]
    n_pts = scenario["n_output_points"]
    t_eval = np.linspace(0.0, t_end, n_pts)

    stype = scenario["type"]
    if stype == "step" and scenario.get("reactivity_dollars", 0) > 1.0:
        max_step = 1e-4
    elif stype == "rod_drop":
        max_step = 0.01
    else:
        max_step = min(0.05, t_end / 200.0)

    sol = solve_ivp(
        fun=rhs,
        t_span=(0.0, t_end),
        y0=y0,
        method="BDF",
        t_eval=t_eval,
        rtol=1e-8,
        atol=1e-10,
        max_step=max_step,
    )

    if not sol.success:
        raise RuntimeError(f"solve_ivp failed for {scenario['name']}: {sol.message}")

    return sol, rho_ext_func


def extract_results(sol, rho_ext_func, thermal, T_f0, T_m0,
                    kappa_f, kappa_m, kappa_fm):
    """Build list-of-dicts from solution."""
    alpha_f = thermal["fuel_temperature_reactivity_coeff_per_K"]
    alpha_m = thermal["moderator_temperature_reactivity_coeff_per_K"]

    rows = []
    for i in range(len(sol.t)):
        t = float(sol.t[i])
        n = float(sol.y[0, i])
        T_f = float(sol.y[7, i])
        T_m = float(sol.y[8, i])
        rho_ext = rho_ext_func(t)
        dT_f = T_f - T_f0
        dT_m = T_m - T_m0
        rho_fb = (alpha_f * dT_f + alpha_m * dT_m
                  + kappa_f * dT_f * dT_f
                  + kappa_m * dT_m * dT_m
                  + kappa_fm * dT_f * dT_m)
        rho_tot = rho_ext + rho_fb

        rows.append(
            {
                "time_s": t,
                "n_relative": n,
                "T_fuel_K": T_f,
                "T_moderator_K": T_m,
                "rho_total": rho_tot,
                "rho_external": rho_ext,
                "rho_feedback": rho_fb,
            }
        )

    return rows


def compute_metrics(rows):
    """Extract summary metrics."""
    n_vals = [r["n_relative"] for r in rows]
    peak_idx = int(np.argmax(n_vals))

    return {
        "peak_power_relative": n_vals[peak_idx],
        "time_of_peak_s": rows[peak_idx]["time_s"],
        "final_power_relative": n_vals[-1],
        "final_fuel_temp_K": rows[-1]["T_fuel_K"],
        "final_mod_temp_K": rows[-1]["T_moderator_K"],
        "final_reactivity_total": rows[-1]["rho_total"],
    }


def write_csv(rows, path):
    """Write result rows to CSV."""
    fieldnames = [
        "time_s",
        "n_relative",
        "T_fuel_K",
        "T_moderator_K",
        "rho_total",
        "rho_external",
        "rho_feedback",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    kinetics, thermal, xs_source = parse_reactor_inp("/app/data/reactor.inp")

    # Compile and load the Fortran spectral feedback library
    xs_path = os.path.join("/app/data", xs_source)
    lib, kappa_f, kappa_m, kappa_fm = compile_and_load_xs_library(xs_path)
    print(f"Spectral coefficients: kf={kappa_f}, km={kappa_m}, kfm={kappa_fm}")

    with open("/app/data/scenarios.json", "r") as f:
        scenarios = json.load(f)

    n0, C0, T_f0, T_m0 = compute_steady_state(kinetics, thermal)
    beta = np.array(kinetics["beta"])
    lam = np.array(kinetics["lambda"])
    beta_total = float(np.sum(beta))
    gen_time = kinetics["generation_time"]

    print(f"Steady-state: n0={n0}, T_f0={T_f0:.1f} K, T_m0={T_m0:.1f} K")
    print(f"Beta_total = {beta_total:.6f}")

    os.makedirs("/app/results", exist_ok=True)

    summary = {}
    analysis = {}

    for scenario in scenarios:
        name = scenario["name"]
        stype = scenario["type"]
        print(f"\nSolving scenario: {name} (type={stype})")

        sol, rho_ext_func = solve_scenario(
            scenario, kinetics, thermal, n0, C0, T_f0, T_m0,
            kappa_f, kappa_m, kappa_fm,
        )
        rows = extract_results(sol, rho_ext_func, thermal, T_f0, T_m0,
                               kappa_f, kappa_m, kappa_fm)
        metrics = compute_metrics(rows)

        csv_path = f"/app/results/scenario_{name}.csv"
        write_csv(rows, csv_path)

        summary[name] = metrics

        if stype == "step":
            rho_step = scenario["reactivity_dollars"] * beta_total
            if rho_step > 0:
                period = solve_inhour_period(rho_step, beta, lam, gen_time)
                analysis[name] = {"inhour_period_s": period}
                print(f"  Inhour period: {period:.6f} s")

        if stype == "rod_drop":
            rod_worth = compute_rod_worth(
                beta_total, scenario["measured_prompt_drop_ratio"]
            )
            analysis[name] = {"rod_worth_dk_k": rod_worth}
            print(f"  Rod worth: {rod_worth:.6f} dk/k")

        print(
            f"  Peak power: {metrics['peak_power_relative']:.4f} "
            f"at t={metrics['time_of_peak_s']:.4f} s"
        )
        print(f"  Final power: {metrics['final_power_relative']:.4f}")

    with open("/app/results/summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    with open("/app/results/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)

    print("\nAll scenarios complete.")


if __name__ == "__main__":
    main()
