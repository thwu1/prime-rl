#!/usr/bin/env python3
"""
Thermally Perfect Gas (TPG) Compressible Flow Solver

Computes oblique shock wave properties for thermally perfect gases using
NASA 7-coefficient polynomial Cp(T) representations. Based on the methodology
described in NASA CR-4749 by Kenneth E. Tatum (1996).

"""

import json
import math
import os
import sys
from scipy.optimize import brentq, minimize_scalar


class TPGMixture:
    """Thermally perfect gas mixture using NASA 7-coefficient polynomials."""

    def __init__(self, data):
        self.R_universal = data["R_universal_J_per_kmol_K"]
        self.species_list = []
        for name, sp in data["species"].items():
            self.species_list.append({
                "name": name,
                "Xi": sp["mole_fraction"],
                "M": sp["molar_mass_kg_per_kmol"],
                "ranges": sp["thermo"]["ranges"],
            })
        self.M_mix = sum(sp["Xi"] * sp["M"] for sp in self.species_list)
        self.R = self.R_universal / self.M_mix  # J/(kg*K)

    def _get_coeffs(self, sp, T):
        for r in sp["ranges"]:
            if r["T_min_K"] <= T <= r["T_max_K"]:
                return r["coeffs"]
        # Extrapolate: use nearest range
        if T < sp["ranges"][0]["T_min_K"]:
            return sp["ranges"][0]["coeffs"]
        return sp["ranges"][-1]["coeffs"]

    def cp_over_R(self, T):
        """Mixture Cp / R_universal = sum(Xi * Cp_i/R_univ)."""
        total = 0.0
        for sp in self.species_list:
            a = self._get_coeffs(sp, T)
            cp_i = a[0] + a[1]*T + a[2]*T**2 + a[3]*T**3 + a[4]*T**4
            total += sp["Xi"] * cp_i
        return total

    def cp(self, T):
        """Cp [J/(kg*K)] for the mixture."""
        return self.cp_over_R(T) * self.R

    def h(self, T):
        """Specific enthalpy [J/kg] from NASA polynomial."""
        total = 0.0
        for sp in self.species_list:
            a = self._get_coeffs(sp, T)
            h_i = (a[0]*T + a[1]*T**2/2.0 + a[2]*T**3/3.0
                   + a[3]*T**4/4.0 + a[4]*T**5/5.0 + a[5])
            total += sp["Xi"] * h_i
        return total * self.R

    def phi(self, T):
        """Entropy function phi [J/(kg*K)] = R_mix * sum(Xi * S_i/R_univ)."""
        total = 0.0
        for sp in self.species_list:
            a = self._get_coeffs(sp, T)
            s_i = (a[0]*math.log(T) + a[1]*T + a[2]*T**2/2.0
                   + a[3]*T**3/3.0 + a[4]*T**4/4.0 + a[6])
            total += sp["Xi"] * s_i
        return total * self.R

    def gamma(self, T):
        """Effective ratio of specific heats."""
        cp_R = self.cp_over_R(T)
        return cp_R / (cp_R - 1.0)

    def sound_speed(self, T):
        """Speed of sound [m/s]."""
        return math.sqrt(self.gamma(T) * self.R * T)


class ShockSolver:
    """Solver for normal and oblique shock waves in TPG."""

    def __init__(self, gas):
        self.gas = gas

    def find_static_T(self, M, Tt):
        """
        Find static temperature from isentropic energy equation:
        h(Tt) = h(T1) + 0.5 * M^2 * gamma(T1) * R * T1
        """
        g = self.gas
        h_total = g.h(Tt)

        def f(T):
            return h_total - g.h(T) - 0.5 * M**2 * g.gamma(T) * g.R * T

        # CPG estimate for bracketing
        gamma_est = g.gamma(Tt)
        T_cpg = Tt / (1.0 + (gamma_est - 1.0) / 2.0 * M**2)
        T_lo = max(T_cpg * 0.3, 50.0)
        T_hi = Tt - 0.01

        # Ensure sign change
        f_lo, f_hi = f(T_lo), f(T_hi)
        if f_lo * f_hi > 0:
            T_lo = max(10.0, T_lo * 0.1)

        return brentq(f, T_lo, T_hi, xtol=1e-10, rtol=1e-13)

    def normal_shock(self, M1n, T1):
        """
        Solve normal shock for TPG.

        Given upstream normal Mach M1n and static temperature T1,
        returns downstream properties as ratios.
        """
        g = self.gas
        if M1n <= 1.0:
            return None

        a1 = g.sound_speed(T1)
        u1 = M1n * a1
        h1 = g.h(T1)
        ht = h1 + 0.5 * u1**2

        # Normalized pressure P1 = 1
        P1 = 1.0
        rho1 = P1 / (g.R * T1)
        F = rho1 * u1          # mass flux
        Q = P1 + rho1 * u1**2  # momentum flux

        # Find T2_max where h(T2_max) = ht (all KE converted to enthalpy)
        T_search = T1 * 2.0
        while g.h(T_search) < ht:
            T_search *= 2.0
            if T_search > 50000:
                break

        def h_residual(T):
            return g.h(T) - ht

        T2_max = brentq(h_residual, T1, T_search, xtol=1e-10)

        def momentum_f(T2):
            h2 = g.h(T2)
            ke2 = ht - h2
            if ke2 <= 1e-30:
                return 1e20
            u2 = math.sqrt(2.0 * ke2)
            rho2 = F / u2
            P2 = rho2 * g.R * T2
            return P2 + rho2 * u2**2 - Q

        T2_lo = T1 * 1.00001
        T2_hi = T1 + 0.99 * (T2_max - T1)

        # Verify bracket
        f_lo = momentum_f(T2_lo)
        f_hi = momentum_f(T2_hi)
        if f_lo * f_hi > 0:
            # Scan for sign change
            n_pts = 500
            dT = (T2_hi - T2_lo) / n_pts
            for i in range(n_pts):
                T_test = T2_lo + i * dT
                if momentum_f(T_test) * f_lo < 0:
                    T2_hi = T_test
                    break

        T2 = brentq(momentum_f, T2_lo, T2_hi, xtol=1e-10, rtol=1e-13)

        h2 = g.h(T2)
        u2 = math.sqrt(2.0 * (ht - h2))
        rho2 = F / u2
        P2 = rho2 * g.R * T2
        M2 = u2 / g.sound_speed(T2)

        # Total pressure ratio via entropy
        phi1 = g.phi(T1)
        phi2 = g.phi(T2)
        Pt2_Pt1 = (P2 / P1) * math.exp((phi1 - phi2) / g.R)

        return {
            "M2": M2,
            "P2_P1": P2 / P1,
            "T2_T1": T2 / T1,
            "rho2_rho1": rho2 / rho1,
            "Pt2_Pt1": Pt2_Pt1,
            "T2": T2,
        }

    def oblique_theta(self, M1, T1, beta_rad):
        """Compute deflection angle for given shock wave angle beta."""
        g = self.gas
        M1n = M1 * math.sin(beta_rad)
        if M1n <= 1.0:
            return 0.0

        V1 = M1 * g.sound_speed(T1)
        u1n = V1 * math.sin(beta_rad)
        ut = V1 * math.cos(beta_rad)

        ns = self.normal_shock(M1n, T1)
        if ns is None:
            return 0.0

        u2n = u1n / ns["rho2_rho1"]

        # Deflection angle from geometry
        theta = math.atan2(ut * (u1n - u2n), ut**2 + u1n * u2n)
        return theta

    def oblique_shock_at_beta(self, M1, T1, beta_deg):
        """Full oblique shock solution at a given shock angle beta."""
        g = self.gas
        beta = math.radians(beta_deg)
        M1n = M1 * math.sin(beta)
        if M1n <= 1.0:
            return None

        V1 = M1 * g.sound_speed(T1)
        u1n = V1 * math.sin(beta)
        ut = V1 * math.cos(beta)

        ns = self.normal_shock(M1n, T1)
        if ns is None:
            return None

        u2n = u1n / ns["rho2_rho1"]
        T2 = ns["T2"]
        V2 = math.sqrt(u2n**2 + ut**2)
        M2 = V2 / g.sound_speed(T2)

        theta = math.atan2(ut * (u1n - u2n), ut**2 + u1n * u2n)

        return {
            "beta_deg": beta_deg,
            "theta_deg": math.degrees(theta),
            "M2": M2,
            "P2_P1": ns["P2_P1"],
            "T2_T1": ns["T2_T1"],
            "rho2_rho1": ns["rho2_rho1"],
            "Pt2_Pt1": ns["Pt2_Pt1"],
        }

    def find_detachment(self, M1, T1):
        """Find maximum deflection angle (detachment condition)."""
        mu = math.asin(1.0 / M1)

        def neg_theta(beta_rad):
            return -self.oblique_theta(M1, T1, beta_rad)

        res = minimize_scalar(
            neg_theta,
            bounds=(mu + 0.005, math.pi / 2 - 0.005),
            method="bounded",
            options={"xatol": 1e-8},
        )
        theta_max = -res.fun
        beta_detach = res.x
        return math.degrees(theta_max), beta_detach

    def find_beta_for_theta(self, M1, T1, theta_deg, shock_type="weak"):
        """Find shock angle beta for a given deflection angle theta."""
        theta_target = math.radians(theta_deg)
        mu = math.asin(1.0 / M1)
        theta_max_deg, beta_detach = self.find_detachment(M1, T1)

        if theta_deg >= theta_max_deg:
            return None  # detached shock

        def f(beta_rad):
            return self.oblique_theta(M1, T1, beta_rad) - theta_target

        if shock_type == "weak":
            beta_lo = mu + 0.001
            beta_hi = beta_detach - 0.0001
        else:
            beta_lo = beta_detach + 0.0001
            beta_hi = math.pi / 2 - 0.001

        # Check bracket validity
        f_lo = f(beta_lo)
        f_hi = f(beta_hi)
        if f_lo * f_hi > 0:
            return None

        beta_sol = brentq(f, beta_lo, beta_hi, xtol=1e-10, rtol=1e-12)
        return self.oblique_shock_at_beta(M1, T1, math.degrees(beta_sol))

    def solve_condition(self, M1, Tt, theta_deg):
        """Solve a complete flight condition."""
        g = self.gas

        T1 = self.find_static_T(M1, Tt)
        gamma_eff = g.gamma(T1)

        ns = self.normal_shock(M1, T1)

        weak = self.find_beta_for_theta(M1, T1, theta_deg, "weak")
        strong = self.find_beta_for_theta(M1, T1, theta_deg, "strong")

        theta_max_deg, _ = self.find_detachment(M1, T1)

        result = {
            "freestream": {
                "T_static_K": round(T1, 6),
                "gamma_effective": round(gamma_eff, 6),
            },
            "normal_shock": {
                "M2": round(ns["M2"], 6),
                "P2_P1": round(ns["P2_P1"], 6),
                "T2_T1": round(ns["T2_T1"], 6),
                "rho2_rho1": round(ns["rho2_rho1"], 6),
                "Pt2_Pt1": round(ns["Pt2_Pt1"], 6),
            },
            "detachment_angle_deg": round(theta_max_deg, 4),
        }

        if weak is not None:
            result["weak_shock"] = {
                "beta_deg": round(weak["beta_deg"], 4),
                "M2": round(weak["M2"], 6),
                "P2_P1": round(weak["P2_P1"], 6),
                "T2_T1": round(weak["T2_T1"], 6),
                "rho2_rho1": round(weak["rho2_rho1"], 6),
                "Pt2_Pt1": round(weak["Pt2_Pt1"], 6),
            }

        if strong is not None:
            result["strong_shock"] = {
                "beta_deg": round(strong["beta_deg"], 4),
                "M2": round(strong["M2"], 6),
                "P2_P1": round(strong["P2_P1"], 6),
                "T2_T1": round(strong["T2_T1"], 6),
                "rho2_rho1": round(strong["rho2_rho1"], 6),
                "Pt2_Pt1": round(strong["Pt2_Pt1"], 6),
            }

        return result


def main():
    with open("/app/data/species.json") as f:
        species_data = json.load(f)
    with open("/app/data/conditions.json") as f:
        conditions_data = json.load(f)

    gas = TPGMixture(species_data)
    solver = ShockSolver(gas)

    results = {}
    for cond in conditions_data["conditions"]:
        cid = cond["id"]
        M1 = cond["mach"]
        Tt = cond["total_temperature_K"]
        theta = cond["deflection_angle_deg"]

        print(f"Solving {cid}: M={M1}, Tt={Tt}K, theta={theta}deg")
        result = solver.solve_condition(M1, Tt, theta)
        results[cid] = result
        print(f"  T1={result['freestream']['T_static_K']:.2f}K, "
              f"gamma={result['freestream']['gamma_effective']:.4f}, "
              f"detach={result['detachment_angle_deg']:.2f}deg")

    os.makedirs("/app/results", exist_ok=True)
    with open("/app/results/flow_tables.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results/flow_tables.json")


if __name__ == "__main__":
    main()
