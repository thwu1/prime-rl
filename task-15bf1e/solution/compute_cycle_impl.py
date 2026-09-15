"""
Transcritical CO2 refrigeration cycle analysis using the Span-Wagner EOS.
"""

import json
import sys
sys.path.insert(0, "/app")
import co2_eos


def _bisect(f, a, b, tol=1e-10, maxiter=200):
    """Simple bisection root finder."""
    fa, fb = f(a), f(b)
    if fa * fb > 0:
        raise ValueError(f"f(a)={fa} and f(b)={fb} have same sign")
    for _ in range(maxiter):
        mid = 0.5 * (a + b)
        fm = f(mid)
        if abs(fm) < tol or (b - a) < tol:
            return mid
        if fa * fm < 0:
            b = mid
            fb = fm
        else:
            a = mid
            fa = fm
    return 0.5 * (a + b)


def find_density_at_TP(T, P, phase):
    """Find density at (T, P) for given phase."""
    return co2_eos.density(T, P, phase)


def find_isentropic_compression(s_target, P_target, T_guess_low, T_guess_high):
    """Find T such that entropy at (T, P_target) in supercritical phase equals s_target."""
    def objective(T):
        rho = co2_eos.density(T, P_target, "supercritical")
        return co2_eos.entropy(T, rho) - s_target

    T_sol = _bisect(objective, T_guess_low, T_guess_high)
    return T_sol


def find_T_from_h_at_P(h_target, P_target, T_guess_low, T_guess_high):
    """Find T such that enthalpy at (T, P_target) in supercritical phase equals h_target."""
    def objective(T):
        rho = co2_eos.density(T, P_target, "supercritical")
        return co2_eos.enthalpy(T, rho) - h_target

    T_sol = _bisect(objective, T_guess_low, T_guess_high)
    return T_sol


def main():
    with open("/app/cycle_params.json") as f:
        params = json.load(f)

    T_evap = params["T_evap_K"]
    dT_sh = params["superheat_K"]
    P_gc = params["P_gas_cooler_Pa"]
    T_gc_out = params["T_gas_cooler_outlet_K"]
    eta_s = params["eta_isentropic"]

    # ---- State 1: Superheated vapor at evaporator exit ----
    P_evap = co2_eos.saturation_pressure(T_evap)
    T1 = T_evap + dT_sh
    rho1 = co2_eos.density(T1, P_evap, "vapor")
    h1 = co2_eos.enthalpy(T1, rho1)
    s1 = co2_eos.entropy(T1, rho1)

    # ---- State 2s: Isentropic compression to P_gc ----
    # s2s = s1, P2 = P_gc
    # Search above Tc since outlet is supercritical
    T_search_low = co2_eos.Tc + 5.0   # above critical for supercritical density solver
    T_search_high = T1 + 250.0
    T2s = find_isentropic_compression(s1, P_gc, T_search_low, T_search_high)
    rho2s = co2_eos.density(T2s, P_gc, "supercritical")
    h2s = co2_eos.enthalpy(T2s, rho2s)

    # ---- State 2: Actual compression ----
    h2 = h1 + (h2s - h1) / eta_s
    # Find T2 at P_gc with h = h2
    T2 = find_T_from_h_at_P(h2, P_gc, T2s, T2s + 150)
    rho2 = co2_eos.density(T2, P_gc, "supercritical")
    s2 = co2_eos.entropy(T2, rho2)

    # ---- State 3: Gas cooler outlet ----
    T3 = T_gc_out
    rho3 = co2_eos.density(T3, P_gc, "supercritical")
    h3 = co2_eos.enthalpy(T3, rho3)
    s3 = co2_eos.entropy(T3, rho3)

    # ---- State 4: Expansion valve (isenthalpic) ----
    # h4 = h3 (two-phase, not computed explicitly)

    # ---- Performance ----
    w_comp = h2 - h1  # compressor work per mol
    q_evap = h1 - h3  # evaporator heat per mol (h4 = h3)
    q_gc = h2 - h3    # gas cooler heat rejection per mol

    COP_cooling = q_evap / w_comp
    COP_heating = q_gc / w_comp

    results = {
        "P_evap_Pa": P_evap,
        "state1": {
            "T_K": T1,
            "P_Pa": P_evap,
            "rho_mol_m3": rho1,
            "h_J_mol": h1,
            "s_J_molK": s1,
        },
        "state2": {
            "T_K": T2,
            "P_Pa": P_gc,
            "rho_mol_m3": rho2,
            "h_J_mol": h2,
            "s_J_molK": s2,
        },
        "state3": {
            "T_K": T3,
            "P_Pa": P_gc,
            "rho_mol_m3": rho3,
            "h_J_mol": h3,
            "s_J_molK": s3,
        },
        "COP_cooling": COP_cooling,
        "COP_heating": COP_heating,
        "compressor_work_J_mol": w_comp,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"COP_cooling = {COP_cooling:.4f}")
    print(f"COP_heating = {COP_heating:.4f}")
    print(f"Compressor work = {w_comp:.2f} J/mol")
    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
