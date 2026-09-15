#!/usr/bin/env python3
"""
Multi-ramp supersonic inlet performance analyzer.
Supports calorically perfect gas (CPG) and thermally perfect gas (TPG) models.
"""

import json
import math
import numpy as np
from scipy.optimize import brentq, minimize_scalar, minimize


# =========================================================================
# Gas models
# =========================================================================

class CPGModel:
    """Calorically perfect gas model with constant gamma."""

    def __init__(self, gamma, R):
        self.gamma = gamma
        self.R = R
        self._cp = gamma * R / (gamma - 1.0)

    def cp(self, T):
        return self._cp

    def enthalpy(self, T):
        return self._cp * T

    def speed_of_sound(self, T):
        return math.sqrt(self.gamma * self.R * T)

    def gamma_at(self, T):
        return self.gamma

    def total_temperature(self, T, M):
        return T * (1.0 + (self.gamma - 1.0) / 2.0 * M ** 2)

    def total_pressure_isentropic(self, P, T, Tt):
        g = self.gamma
        return P * (Tt / T) ** (g / (g - 1.0))


class TPGModel:
    """Thermally perfect gas model using NASA 7-coefficient polynomials."""

    def __init__(self, gas_data, species_name="air"):
        self.R_u = gas_data["R_universal_J_per_kmol_K"]

        if species_name in gas_data.get("mixtures", {}):
            mix = gas_data["mixtures"][species_name]
            comp = mix["composition_mole_fraction"]

            # Molecular weight of mixture
            M_mix = sum(
                x * gas_data["species"][sp]["molecular_weight"]
                for sp, x in comp.items()
            )
            self.R = self.R_u / M_mix

            # Mass fractions
            self.mass_fractions = {}
            for sp, x in comp.items():
                Mi = gas_data["species"][sp]["molecular_weight"]
                self.mass_fractions[sp] = x * Mi / M_mix

            self.species_data = {
                sp: gas_data["species"][sp] for sp in comp
            }
        else:
            sp_data = gas_data["species"][species_name]
            self.R = self.R_u / sp_data["molecular_weight"]
            self.mass_fractions = {species_name: 1.0}
            self.species_data = {species_name: sp_data}

    def _get_coeffs(self, sp_name, T):
        ranges = self.species_data[sp_name]["ranges"]
        for r in ranges:
            if r["T_low"] <= T <= r["T_high"]:
                return r["coefficients"]
        # Extrapolate using nearest
        if T < ranges[0]["T_low"]:
            return ranges[0]["coefficients"]
        return ranges[-1]["coefficients"]

    def _cp_over_R_sp(self, sp_name, T):
        a = self._get_coeffs(sp_name, T)
        return a[0] + a[1] * T + a[2] * T ** 2 + a[3] * T ** 3 + a[4] * T ** 4

    def _h_over_RT_sp(self, sp_name, T):
        a = self._get_coeffs(sp_name, T)
        return (
            a[0]
            + a[1] * T / 2.0
            + a[2] * T ** 2 / 3.0
            + a[3] * T ** 3 / 4.0
            + a[4] * T ** 4 / 5.0
            + a[5] / T
        )

    def _s_over_R_sp(self, sp_name, T):
        a = self._get_coeffs(sp_name, T)
        return (
            a[0] * math.log(T)
            + a[1] * T
            + a[2] * T ** 2 / 2.0
            + a[3] * T ** 3 / 3.0
            + a[4] * T ** 4 / 4.0
            + a[6]
        )

    def cp(self, T):
        cp_mix = 0.0
        for sp, y in self.mass_fractions.items():
            R_sp = self.R_u / self.species_data[sp]["molecular_weight"]
            cp_mix += y * self._cp_over_R_sp(sp, T) * R_sp
        return cp_mix

    def enthalpy(self, T):
        h_mix = 0.0
        for sp, y in self.mass_fractions.items():
            R_sp = self.R_u / self.species_data[sp]["molecular_weight"]
            h_mix += y * self._h_over_RT_sp(sp, T) * R_sp * T
        return h_mix

    def entropy_per_mass(self, T):
        s_mix = 0.0
        for sp, y in self.mass_fractions.items():
            R_sp = self.R_u / self.species_data[sp]["molecular_weight"]
            s_mix += y * self._s_over_R_sp(sp, T) * R_sp
        return s_mix

    def gamma_at(self, T):
        cp_val = self.cp(T)
        return cp_val / (cp_val - self.R)

    def speed_of_sound(self, T):
        return math.sqrt(self.gamma_at(T) * self.R * T)

    def total_temperature(self, T, M):
        """Find Tt such that h(Tt) = h(T) + V^2/2."""
        V = M * self.speed_of_sound(T)
        h_total = self.enthalpy(T) + 0.5 * V ** 2

        def residual(Tt):
            return self.enthalpy(Tt) - h_total

        # Find upper bracket by stepping up until residual changes sign
        T_upper = T * 1.1
        for _ in range(200):
            if residual(T_upper) > 0:
                break
            T_upper *= 1.5
        else:
            T_upper = T * 50.0

        return brentq(residual, T + 0.01, T_upper, xtol=1e-8)

    def total_pressure_isentropic(self, P, T, Tt):
        """Compute Pt from P, T, Tt using isentropic relation.
        R*ln(Pt/P) = integral_{T}^{Tt} Cp(T')/T' dT'
        """
        # Numerical integration via Simpson's rule
        N = 2000
        Tarr = np.linspace(T, Tt, N + 1)
        integrand = np.array([self.cp(Ti) / Ti for Ti in Tarr])
        integral = np.trapezoid(integrand, Tarr)
        return P * math.exp(integral / self.R)


# =========================================================================
# CPG shock relations
# =========================================================================

def cpg_theta_from_beta(M, beta_rad, gamma):
    """theta-beta-M relation: deflection angle from shock angle."""
    sin2b = math.sin(beta_rad) ** 2
    Mn1_sq = M ** 2 * sin2b
    if Mn1_sq <= 1.0:
        return 0.0
    num = 2.0 * (Mn1_sq - 1.0) / math.tan(beta_rad)
    den = M ** 2 * (gamma + math.cos(2.0 * beta_rad)) + 2.0
    if abs(den) < 1e-15:
        return 0.0
    return math.atan2(num, den)


def cpg_solve_weak_beta(M, theta_deg, gamma):
    """Solve for weak oblique shock angle."""
    theta_rad = math.radians(theta_deg)
    mu = math.asin(1.0 / M)

    res = minimize_scalar(
        lambda b: -cpg_theta_from_beta(M, b, gamma),
        bounds=(mu + 1e-8, math.pi / 2 - 1e-8),
        method="bounded",
    )
    beta_peak = res.x
    theta_max = -res.fun

    if theta_rad > theta_max + 1e-10:
        raise ValueError(
            f"Detached shock: theta={theta_deg} > max={math.degrees(theta_max):.2f}"
        )

    beta = brentq(
        lambda b: cpg_theta_from_beta(M, b, gamma) - theta_rad,
        mu + 1e-10,
        beta_peak - 1e-10,
    )
    return beta


def cpg_normal_shock(Mn1, gamma):
    """CPG normal shock property ratios."""
    Mn1_sq = Mn1 ** 2
    gp1 = gamma + 1.0
    gm1 = gamma - 1.0

    P_ratio = (2.0 * gamma * Mn1_sq - gm1) / gp1
    rho_ratio = gp1 * Mn1_sq / (gm1 * Mn1_sq + 2.0)
    T_ratio = P_ratio / rho_ratio
    Mn2 = math.sqrt((gm1 * Mn1_sq + 2.0) / (2.0 * gamma * Mn1_sq - gm1))

    term1 = (gp1 * Mn1_sq / (gm1 * Mn1_sq + 2.0)) ** (gamma / gm1)
    term2 = (gp1 / (2.0 * gamma * Mn1_sq - gm1)) ** (1.0 / gm1)
    Pt_ratio = term1 * term2

    return P_ratio, T_ratio, rho_ratio, Mn2, Pt_ratio


def cpg_oblique_shock(M1, theta_deg, gamma, T1, P1):
    """CPG oblique shock: returns (result_dict, M2, T2, P2)."""
    beta_rad = cpg_solve_weak_beta(M1, theta_deg, gamma)
    theta_rad = math.radians(theta_deg)

    Mn1 = M1 * math.sin(beta_rad)
    P_ratio, T_ratio, rho_ratio, Mn2, Pt_ratio = cpg_normal_shock(Mn1, gamma)

    M2 = Mn2 / math.sin(beta_rad - theta_rad)
    T2 = T1 * T_ratio
    P2 = P1 * P_ratio

    result = {
        "ramp_angle_deg": theta_deg,
        "shock_angle_deg": math.degrees(beta_rad),
        "upstream_mach": M1,
        "downstream_mach": M2,
        "pressure_ratio": P_ratio,
        "temperature_ratio": T_ratio,
        "density_ratio": rho_ratio,
        "total_pressure_ratio": Pt_ratio,
    }
    return result, M2, T2, P2


# =========================================================================
# TPG shock relations
# =========================================================================

def tpg_normal_shock_solve(gas, u1, T1, P1):
    """Solve TPG normal shock conservation equations.
    Given upstream normal velocity u1, T1, P1, find downstream T2, P2, u2.
    Conservation:
      mass:     rho1*u1 = rho2*u2
      momentum: P1 + rho1*u1^2 = P2 + rho2*u2^2
      energy:   h1 + u1^2/2 = h2 + u2^2/2
    """
    rho1 = P1 / (gas.R * T1)
    h1 = gas.enthalpy(T1)
    mdot = rho1 * u1
    F = P1 + rho1 * u1 ** 2
    H = h1 + 0.5 * u1 ** 2

    def residual(T2):
        h2 = gas.enthalpy(T2)
        u2_sq = 2.0 * (H - h2)
        if u2_sq <= 0:
            return 1e10
        u2 = math.sqrt(u2_sq)
        rho2 = mdot / u2
        P2 = rho2 * gas.R * T2
        return (P2 + rho2 * u2 ** 2) - F

    # Find bracket: T2 > T1 for a shock
    T2 = brentq(residual, T1 * 1.001, T1 * 30.0, xtol=1e-6)

    h2 = gas.enthalpy(T2)
    u2 = math.sqrt(2.0 * (H - h2))
    rho2 = mdot / u2
    P2 = rho2 * gas.R * T2

    return T2, P2, u2


def tpg_oblique_shock(gas, M1, theta_deg, T1, P1):
    """TPG oblique shock solver with nested iteration."""
    theta_rad = math.radians(theta_deg)
    a1 = gas.speed_of_sound(T1)
    V1 = M1 * a1

    # Total temperature (conserved across shock)
    Tt = gas.total_temperature(T1, M1)
    Pt1 = gas.total_pressure_isentropic(P1, T1, Tt)

    mu = math.asin(1.0 / M1)

    def deflection_residual(beta_rad):
        if beta_rad <= mu or beta_rad >= math.pi / 2:
            return 1e10
        u1 = V1 * math.sin(beta_rad)
        w = V1 * math.cos(beta_rad)
        try:
            T2, P2, u2 = tpg_normal_shock_solve(gas, u1, T1, P1)
        except Exception:
            return 1e10
        delta = beta_rad - math.atan2(u2, w)
        return delta - theta_rad

    # Bracket search for weak solution
    n_pts = 300
    betas = np.linspace(mu + 0.005, math.pi / 2 - 0.005, n_pts)
    residuals = []
    for b in betas:
        try:
            residuals.append(deflection_residual(b))
        except Exception:
            residuals.append(1e10)

    beta_sol = None
    for i in range(len(residuals) - 1):
        if residuals[i] * residuals[i + 1] < 0 and abs(residuals[i]) < 1.0:
            try:
                beta_sol = brentq(deflection_residual, betas[i], betas[i + 1], xtol=1e-8)
            except Exception:
                continue
            break

    if beta_sol is None:
        raise ValueError(
            f"TPG: could not find shock angle for M={M1}, theta={theta_deg}"
        )

    u1 = V1 * math.sin(beta_sol)
    w = V1 * math.cos(beta_sol)
    T2, P2, u2 = tpg_normal_shock_solve(gas, u1, T1, P1)

    V2 = math.sqrt(u2 ** 2 + w ** 2)
    a2 = gas.speed_of_sound(T2)
    M2 = V2 / a2

    # Total pressure downstream
    Tt2 = gas.total_temperature(T2, M2)
    Pt2 = gas.total_pressure_isentropic(P2, T2, Tt2)
    Pt_ratio = Pt2 / Pt1

    rho_ratio = (P2 / P1) * (T1 / T2)

    result = {
        "ramp_angle_deg": theta_deg,
        "shock_angle_deg": math.degrees(beta_sol),
        "upstream_mach": M1,
        "downstream_mach": M2,
        "pressure_ratio": P2 / P1,
        "temperature_ratio": T2 / T1,
        "density_ratio": rho_ratio,
        "total_pressure_ratio": Pt_ratio,
    }
    return result, M2, T2, P2


def tpg_terminal_normal_shock(gas, M, T, P):
    """TPG terminal normal shock (full velocity is normal)."""
    a = gas.speed_of_sound(T)
    u1 = M * a

    Tt = gas.total_temperature(T, M)
    Pt1 = gas.total_pressure_isentropic(P, T, Tt)

    T2, P2, u2 = tpg_normal_shock_solve(gas, u1, T, P)
    a2 = gas.speed_of_sound(T2)
    M2 = u2 / a2

    Tt2 = gas.total_temperature(T2, M2)
    Pt2 = gas.total_pressure_isentropic(P2, T2, Tt2)
    Pt_ratio = Pt2 / Pt1

    rho_ratio = (P2 / P) * (T / T2)

    return {
        "upstream_mach": M,
        "downstream_mach": M2,
        "pressure_ratio": P2 / P,
        "temperature_ratio": T2 / T,
        "density_ratio": rho_ratio,
        "total_pressure_ratio": Pt_ratio,
    }


# =========================================================================
# Inlet analysis
# =========================================================================

def compute_inlet_cpg(gamma, R, M, T, P, ramp_angles):
    """Compute CPG multi-ramp inlet analysis."""
    oblique_results = []
    overall_Pt = 1.0

    for theta in ramp_angles:
        shock, M, T, P = cpg_oblique_shock(M, theta, gamma, T, P)
        oblique_results.append(shock)
        overall_Pt *= shock["total_pressure_ratio"]

    # Terminal normal shock
    P_r, T_r, rho_r, Mn2, Pt_r = cpg_normal_shock(M, gamma)
    terminal = {
        "upstream_mach": M,
        "downstream_mach": Mn2,
        "pressure_ratio": P_r,
        "temperature_ratio": T_r,
        "density_ratio": rho_r,
        "total_pressure_ratio": Pt_r,
    }
    overall_Pt *= Pt_r

    return {
        "oblique_shocks": oblique_results,
        "terminal_normal_shock": terminal,
        "overall_total_pressure_recovery": overall_Pt,
    }


def compute_inlet_tpg(gas, M, T, P, ramp_angles):
    """Compute TPG multi-ramp inlet analysis."""
    oblique_results = []
    overall_Pt = 1.0

    for theta in ramp_angles:
        shock, M, T, P = tpg_oblique_shock(gas, M, theta, T, P)
        oblique_results.append(shock)
        overall_Pt *= shock["total_pressure_ratio"]

    terminal = tpg_terminal_normal_shock(gas, M, T, P)
    overall_Pt *= terminal["total_pressure_ratio"]

    return {
        "oblique_shocks": oblique_results,
        "terminal_normal_shock": terminal,
        "overall_total_pressure_recovery": overall_Pt,
    }


def optimize_inlet_cpg(gamma, R, M_inf, T_inf, P_inf, num_ramps, total_defl):
    """Optimize ramp angles for maximum total pressure recovery (CPG)."""

    def neg_recovery(x):
        """x: first (num_ramps-1) fractional angles; last inferred."""
        fracs = list(x) + [1.0 - sum(x)]
        if any(f <= 0.01 for f in fracs):
            return 0.0  # infeasible → bad recovery
        angles = [f * total_defl for f in fracs]
        try:
            result = compute_inlet_cpg(gamma, R, M_inf, T_inf, P_inf, angles)
            return -result["overall_total_pressure_recovery"]
        except Exception:
            return 0.0

    x0 = np.ones(num_ramps - 1) / num_ramps
    bounds = [(0.02, 0.98)] * (num_ramps - 1)
    constraints = [{"type": "ineq", "fun": lambda x: 1.0 - sum(x) - 0.02}]

    res = minimize(
        neg_recovery, x0, method="SLSQP", bounds=bounds, constraints=constraints,
        options={"ftol": 1e-10, "maxiter": 200},
    )

    opt_fracs = list(res.x) + [1.0 - sum(res.x)]
    opt_angles = [f * total_defl for f in opt_fracs]

    result = compute_inlet_cpg(gamma, R, M_inf, T_inf, P_inf, opt_angles)
    result["optimized_ramp_angles_deg"] = opt_angles
    return result


# =========================================================================
# Main driver
# =========================================================================

def analyze_case(case, gas_data):
    model = case["gas_model"]
    fs = case["freestream"]
    M = fs["mach"]
    T = fs["temperature_K"]
    P = fs["pressure_Pa"]

    if case.get("optimize", False):
        gamma = case["gamma"]
        R = case.get("R", 287.058)
        num_ramps = case["num_ramps"]
        total_defl = case["total_deflection_deg"]
        return optimize_inlet_cpg(gamma, R, M, T, P, num_ramps, total_defl)

    if model == "cpg":
        gamma = case["gamma"]
        R = case.get("R", 287.058)
        return compute_inlet_cpg(gamma, R, M, T, P, case["ramp_angles_deg"])
    elif model == "tpg":
        gas = TPGModel(gas_data, case.get("gas_species", "air"))
        return compute_inlet_tpg(gas, M, T, P, case["ramp_angles_deg"])
    else:
        raise ValueError(f"Unknown gas model: {model}")


def main():
    with open("/app/inlet_config.json") as f:
        config = json.load(f)

    with open("/app/gas_data.json") as f:
        gas_data = json.load(f)

    results = {}
    for case in config["cases"]:
        name = case["name"]
        print(f"Analyzing {name}...")
        try:
            results[name] = analyze_case(case, gas_data)
            rec = results[name]["overall_total_pressure_recovery"]
            print(f"  Total pressure recovery: {rec:.6f}")
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            results[name] = {"error": str(e)}

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
