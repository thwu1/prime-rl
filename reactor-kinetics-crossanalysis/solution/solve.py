#!/usr/bin/env python3
"""
Reference solution for H2/Air Multi-Reactor Kinetics Analysis.
Reads config, discovers mechanism, computes ignition delays, CSTR extinction,
sensitivity analysis, crossover detection, and cross-reactor correlation.
"""


import cantera as ct
import numpy as np
import json


# ============================================================
# Read configuration
# ============================================================

with open("/app/config.json") as f:
    config = json.load(f)

MECH = config["mechanism"]
COMP = config["mixture"]
P = config["pressure_atm"] * ct.one_atm
T_LIST = config["temperatures_K"]
T_REF = config["sensitivity_reference_T_K"]
T_INLET = float(config["inlet_T_K"])
PSR_TAU_MULT = config["psr_sensitivity_tau_multiplier"]
EPS = 0.01


# ============================================================
# Ignition delay
# ============================================================

def ignition_delay(T0, P_val, comp=COMP, multiplier=None, rxn_idx=None):
    gas = ct.Solution(MECH)
    gas.TPX = T0, P_val, comp
    if multiplier is not None and rxn_idx is not None:
        gas.set_multiplier(multiplier, rxn_idx)

    reactor = ct.IdealGasReactor(gas)
    net = ct.ReactorNet([reactor])

    times = [0.0]
    temps = [reactor.T]

    while net.time < 10.0:
        net.step()
        times.append(net.time)
        temps.append(reactor.T)
        if reactor.T > T0 + 1500:
            for _ in range(300):
                if net.time > 10.0:
                    break
                net.step()
                times.append(net.time)
                temps.append(reactor.T)
            break

    t = np.array(times)
    T = np.array(temps)
    dTdt = np.diff(T) / np.diff(t)
    idx = int(np.argmax(dTdt))
    tau = 0.5 * (t[idx] + t[idx + 1])
    T_peak = float(np.max(T))
    return float(tau), T_peak


# ============================================================
# Crossover detection
# ============================================================

def detect_crossover(temps_list, ign_delays):
    """Identify the highest temperature showing non-Arrhenius behavior
    via leave-one-out Arrhenius fit analysis."""
    temps = sorted(temps_list)
    n = len(temps)
    inv_T = np.array([1000.0 / t for t in temps])
    ln_tau = np.array([np.log(ign_delays[str(t)]) for t in temps])

    best_dev = 0.0
    crossover = temps[0]

    for i in range(n):
        others = [j for j in range(n) if j != i]
        p = np.polyfit(inv_T[others], ln_tau[others], 1)
        dev = ln_tau[i] - np.polyval(p, inv_T[i])
        if dev > best_dev:
            best_dev = dev
            crossover = temps[i]

    return int(crossover)


# ============================================================
# CSTR helpers
# ============================================================

def cstr_steady_state(P_val, comp, tau, T_init, X_init=None,
                      multiplier=None, rxn_idx=None):
    inlet_gas = ct.Solution(MECH)
    inlet_gas.TPX = T_INLET, P_val, comp

    reactor_gas = ct.Solution(MECH)
    if X_init is not None:
        reactor_gas.TPX = T_init, P_val, X_init
    else:
        reactor_gas.TPX = T_init, P_val, comp

    if multiplier is not None and rxn_idx is not None:
        reactor_gas.set_multiplier(multiplier, rxn_idx)

    inlet = ct.Reservoir(inlet_gas)
    exhaust = ct.Reservoir(inlet_gas)

    reactor = ct.IdealGasReactor(reactor_gas, energy="on")
    reactor.volume = 1.0

    captured_tau = tau
    mfc = ct.MassFlowController(
        upstream=inlet,
        downstream=reactor,
        mdot=lambda t: reactor.mass / captured_tau,
    )
    ct.PressureController(
        upstream=reactor,
        downstream=exhaust,
        primary=mfc,
        K=1e-5,
    )

    net = ct.ReactorNet([reactor])
    net.rtol = 1e-9
    net.atol = 1e-18

    max_time = min(500 * tau, 20.0)
    T_prev = reactor.T
    step_count = 0

    while net.time < max_time:
        net.step()
        step_count += 1
        if step_count % 200 == 0 and net.time > 10 * tau:
            if abs(reactor.T - T_prev) / max(reactor.T, 300) < 1e-7:
                break
            T_prev = reactor.T

    species_names = reactor_gas.species_names
    X_out = dict(zip(species_names, reactor_gas.X))
    return float(reactor.T), X_out


def get_equilibrium_state(P_val, comp):
    gas = ct.Solution(MECH)
    gas.TPX = T_INLET, P_val, comp
    gas.equilibrate("HP")
    return gas.T, dict(zip(gas.species_names, gas.X))


def trace_s_curve(P_val, comp, n_points=250):
    T_eq, X_eq = get_equilibrium_state(P_val, comp)
    taus = np.logspace(0, -7, n_points)
    curve = []

    T_prev = T_eq
    X_prev = X_eq

    for tau in taus:
        T_exit, X_exit = cstr_steady_state(P_val, comp, tau, T_prev, X_prev)
        curve.append([float(tau), float(T_exit)])

        if T_exit < T_INLET + 100:
            break

        T_prev = T_exit
        X_prev = X_exit

    return curve


def find_tau_ext(s_curve_data, P_val, comp, n_bisect=35):
    T_eq, X_eq = get_equilibrium_state(P_val, comp)

    for i in range(1, len(s_curve_data)):
        _, T_curr = s_curve_data[i]
        tau_prev, T_prev_val = s_curve_data[i - 1]

        if T_prev_val > 1000 and T_curr < T_INLET + 300:
            tau_hi = tau_prev
            tau_lo = s_curve_data[i][0]

            for _ in range(n_bisect):
                tau_mid = np.exp(0.5 * (np.log(tau_lo) + np.log(tau_hi)))
                T_exit, _ = cstr_steady_state(
                    P_val, comp, tau_mid, T_eq, X_eq
                )
                if T_exit > 1000:
                    tau_hi = tau_mid
                else:
                    tau_lo = tau_mid

            return float(tau_hi)

    return float(s_curve_data[-1][0])


def get_hot_psr_state(P_val, comp, tau_target, n_steps=40,
                      multiplier=None, rxn_idx=None):
    T_eq, X_eq = get_equilibrium_state(P_val, comp)
    T_curr, X_curr = T_eq, X_eq

    taus = np.logspace(-1, np.log10(tau_target), n_steps)
    for tau in taus:
        T_curr, X_curr = cstr_steady_state(
            P_val, comp, tau, T_curr, X_curr,
            multiplier=multiplier, rxn_idx=rxn_idx
        )
        if T_curr < T_INLET + 100:
            break

    return T_curr, X_curr


# ============================================================
# Spearman correlation
# ============================================================

def spearman_rho(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)

    order_x = np.argsort(x)
    rx = np.empty(n, dtype=float)
    rx[order_x] = np.arange(1, n + 1, dtype=float)

    order_y = np.argsort(y)
    ry = np.empty(n, dtype=float)
    ry[order_y] = np.arange(1, n + 1, dtype=float)

    d = rx - ry
    return float(1.0 - 6.0 * np.sum(d ** 2) / (n * (n ** 2 - 1)))


# ============================================================
# Main
# ============================================================

def main():
    gas_ref = ct.Solution(MECH)
    n_species = gas_ref.n_species
    n_rxns = gas_ref.n_reactions
    rxn_eqs = [gas_ref.reaction(i).equation for i in range(n_rxns)]

    results = {
        "mechanism_n_species": n_species,
        "mechanism_n_reactions": n_rxns,
    }

    # Ignition delays
    print("Computing ignition delays ...")
    ign_delays = {}
    peak_temps = {}
    for T0 in T_LIST:
        tau, Tp = ignition_delay(T0, P)
        ign_delays[str(T0)] = tau
        peak_temps[str(T0)] = Tp
        print(f"  T0={T0} K : tau = {tau:.4e} s, T_peak = {Tp:.1f} K")

    results["ignition_delays"] = ign_delays
    results["cv_peak_temperatures"] = peak_temps

    # Crossover detection
    crossover_T = detect_crossover(T_LIST, ign_delays)
    results["crossover_temperature"] = crossover_T
    print(f"Crossover temperature: {crossover_T} K")

    # CV sensitivity at reference temperature
    print(f"Computing CV sensitivity at {T_REF} K ...")
    tau_base, _ = ignition_delay(T_REF, P)
    cv_sens = []
    for i in range(n_rxns):
        tau_pert, _ = ignition_delay(T_REF, P, multiplier=1.0 + EPS, rxn_idx=i)
        s = (np.log(tau_pert) - np.log(tau_base)) / EPS
        cv_sens.append({
            "index": int(i),
            "equation": rxn_eqs[i],
            "sensitivity": float(s),
        })
    cv_sens.sort(key=lambda r: abs(r["sensitivity"]), reverse=True)
    results["cv_sensitivity"] = cv_sens

    # PSR extinction
    print("Tracing S-curve ...")
    s_curve = trace_s_curve(P, COMP)
    results["s_curve"] = s_curve
    print(f"  {len(s_curve)} points on S-curve")

    tau_ext = find_tau_ext(s_curve, P, COMP)
    results["tau_ext"] = tau_ext
    print(f"  tau_ext = {tau_ext:.4e} s")

    # PSR sensitivity at multiplier * tau_ext
    tau_eval = PSR_TAU_MULT * tau_ext
    print(f"Computing PSR sensitivity at tau = {tau_eval:.4e} s ...")

    T_hot, X_hot = get_hot_psr_state(P, COMP, tau_eval)
    print(f"  Baseline T_exit = {T_hot:.1f} K")

    psr_sens = []
    for i in range(n_rxns):
        T_pert, _ = cstr_steady_state(
            P, COMP, tau_eval, T_hot, X_hot, multiplier=1.0 + EPS, rxn_idx=i
        )
        s = (T_pert - T_hot) / (T_hot * EPS)
        psr_sens.append({
            "index": int(i),
            "equation": rxn_eqs[i],
            "sensitivity": float(s),
        })
    psr_sens.sort(key=lambda r: abs(r["sensitivity"]), reverse=True)
    results["psr_sensitivity"] = psr_sens

    # Cross-analysis
    print("Computing cross-analysis ...")
    cv_abs = np.zeros(n_rxns)
    psr_abs = np.zeros(n_rxns)
    for r in cv_sens:
        cv_abs[r["index"]] = abs(r["sensitivity"])
    for r in psr_sens:
        psr_abs[r["index"]] = abs(r["sensitivity"])

    rho = spearman_rho(cv_abs, psr_abs)
    results["spearman_rho"] = rho
    print(f"  Spearman rho = {rho:.4f}")

    results["top5_cv"] = [r["equation"] for r in cv_sens[:5]]
    results["top5_psr"] = [r["equation"] for r in psr_sens[:5]]

    # Write output
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
