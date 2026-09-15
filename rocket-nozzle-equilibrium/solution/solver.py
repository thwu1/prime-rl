#!/usr/bin/env python3
"""
Chemical equilibrium rocket nozzle performance solver.

Implements Gibbs free energy minimization for ideal gas mixtures with
isentropic nozzle expansion under shifting (equilibrium) composition.
Verifiable against NASA RP-1311 Example 8 (LOX/LH2).
"""

import json
import sys
import numpy as np
from scipy.optimize import minimize, brentq, minimize_scalar

R_U = 8314.46    # J/(kmol·K)
P_REF = 101325.0 # Pa (1 atm standard state)


def load_json(path):
    with open(path) as f:
        return json.load(f)


# ── NASA 7-coefficient thermodynamic functions ──

def _coeffs(sp_data, T):
    T_mid = sp_data["T_ranges"][1]
    return np.array(sp_data["low_coeffs"] if T <= T_mid else sp_data["high_coeffs"])

def cp_R(a, T):
    return a[0] + a[1]*T + a[2]*T**2 + a[3]*T**3 + a[4]*T**4

def h_RT(a, T):
    return a[0] + a[1]*T/2.0 + a[2]*T**2/3.0 + a[3]*T**3/4.0 + a[4]*T**4/5.0 + a[5]/T

def s_R(a, T):
    return a[0]*np.log(T) + a[1]*T + a[2]*T**2/2.0 + a[3]*T**3/3.0 + a[4]*T**4/4.0 + a[6]

def g_RT(a, T):
    return h_RT(a, T) - s_R(a, T)


class RocketSolver:
    def __init__(self, thermo, problem):
        self.thermo = thermo
        self.problem = problem
        self.species = list(thermo["species"].keys())
        self.elements = thermo["elements"]
        self.n_sp = len(self.species)
        self.n_el = len(self.elements)
        self.sp_data = [thermo["species"][sp] for sp in self.species]

        # Element composition matrix  (n_el x n_sp)
        self.A = np.zeros((self.n_el, self.n_sp))
        for i, sp in enumerate(self.species):
            for j, el in enumerate(self.elements):
                self.A[j, i] = thermo["species"][sp]["elements"].get(el, 0)

        self._setup_mixture()

    # ── mixture bookkeeping ──

    def _setup_mixture(self):
        p = self.problem
        of = p["of_ratio"]
        fuel, oxid = p["fuel"], p["oxidizer"]
        mf = 1.0 / (1.0 + of)   # fuel mass fraction
        mo = of  / (1.0 + of)   # oxidizer mass fraction

        self.b = np.zeros(self.n_el)
        for j, el in enumerate(self.elements):
            self.b[j] = (mf * fuel["composition"].get(el, 0) / fuel["molecular_weight"]
                       + mo * oxid["composition"].get(el, 0) / oxid["molecular_weight"])

        self.h0 = (mf * fuel["enthalpy_J_per_kmol"] / fuel["molecular_weight"]
                 + mo * oxid["enthalpy_J_per_kmol"] / oxid["molecular_weight"])

        self.P_c = p["chamber_pressure_bar"] * 1e5  # Pa

    # ── thermodynamic property helpers ──

    def _g0_vec(self, T):
        return np.array([g_RT(_coeffs(sd, T), T) for sd in self.sp_data])

    def _h_vec(self, T):
        return np.array([h_RT(_coeffs(sd, T), T) for sd in self.sp_data])

    def _cp_vec(self, T):
        return np.array([cp_R(_coeffs(sd, T), T) for sd in self.sp_data])

    def _s_vec(self, T):
        return np.array([s_R(_coeffs(sd, T), T) for sd in self.sp_data])

    def mix_h(self, n, T):
        """Specific enthalpy  J/kg."""
        return float(R_U * T * np.dot(n, self._h_vec(T)))

    def mix_s(self, n, T, P):
        """Specific entropy  J/(kg·K)."""
        N = np.sum(n)
        x = n / N
        s0 = self._s_vec(T)
        lnP = np.log(P / P_REF)
        s = 0.0
        for i in range(self.n_sp):
            if n[i] > 1e-25:
                s += n[i] * R_U * (s0[i] - np.log(x[i]) - lnP)
        return float(s)

    def mix_cp(self, n, T):
        """Frozen Cp  J/(kg·K)."""
        return float(R_U * np.dot(n, self._cp_vec(T)))

    def mix_rho(self, n, T, P):
        """Density  kg/m³."""
        return P / (np.sum(n) * R_U * T)

    # ── equilibrium solver ──

    def _initial_n(self, T):
        """Heuristic initial mole numbers (kmol/kg)."""
        idx = {s: i for i, s in enumerate(self.species)}
        bH, bO = self.b[0], self.b[1]
        n0 = np.full(self.n_sp, 1e-10)
        if T > 2500:
            n0[idx["H2O"]] = min(bH / 2, bO) * 0.85
            used_H = 2 * n0[idx["H2O"]]
            n0[idx["H2"]]  = max((bH - used_H) / 2, 1e-10) * 0.9
            n0[idx["OH"]]  = min(bH, bO) * 0.03
            n0[idx["H"]]   = bH * 0.02
            n0[idx["O"]]   = bO * 0.004
            n0[idx["O2"]]  = bO * 0.004
        else:
            n0[idx["H2O"]] = min(bH / 2, bO) * 0.995
            used_H = 2 * n0[idx["H2O"]]
            n0[idx["H2"]]  = max((bH - used_H) / 2, 1e-10)
        return np.maximum(n0, 1e-15)

    def equilibrium(self, T, P, n_prev=None):
        """Min-G equilibrium at fixed T, P.  Returns (n, x)."""
        g0 = self._g0_vec(T)
        C  = np.log(P / P_REF)

        def obj(n):
            n = np.maximum(n, 1e-30)
            N = np.sum(n)
            return float(np.sum(n * (g0 + np.log(n / N) + C)))

        def jac(n):
            n = np.maximum(n, 1e-30)
            N = np.sum(n)
            return g0 + np.log(n / N) + C

        cons = [{"type": "eq",
                 "fun": lambda n: self.A @ n - self.b,
                 "jac": lambda n: self.A}]
        bnd = [(1e-20, None)] * self.n_sp

        n0 = n_prev if n_prev is not None else self._initial_n(T)
        n0 = np.maximum(n0, 1e-15)

        res = minimize(obj, n0, jac=jac, method="SLSQP",
                       constraints=cons, bounds=bnd,
                       options={"maxiter": 800, "ftol": 1e-15})

        if not res.success:
            # retry with fresh guess
            n0 = self._initial_n(T)
            res = minimize(obj, n0, jac=jac, method="SLSQP",
                           constraints=cons, bounds=bnd,
                           options={"maxiter": 1200, "ftol": 1e-14})

        n = np.maximum(res.x, 0.0)
        N = np.sum(n)
        return n, n / N

    # ── chamber (HP) solve ──

    def solve_chamber(self):
        cache = [None]

        def resid(T):
            n, _ = self.equilibrium(T, self.P_c, cache[0])
            cache[0] = n
            return self.mix_h(n, T) - self.h0

        T_c = brentq(resid, 1500, 5500, xtol=0.05, rtol=1e-9)
        n_c, x_c = self.equilibrium(T_c, self.P_c, cache[0])
        return T_c, n_c, x_c

    # ── isentropic helpers ──

    def _T_at_PS(self, P, S_target, T_lo, T_hi, n_hint=None):
        """Temperature on the isentrope at pressure P."""
        cache = [n_hint]

        def resid(T):
            n, _ = self.equilibrium(T, P, cache[0])
            cache[0] = n
            return self.mix_s(n, T, P) - S_target

        T = brentq(resid, T_lo, T_hi, xtol=0.1, rtol=1e-8)
        n, x = self.equilibrium(T, P, cache[0])
        return T, n, x

    # ── throat ──

    def find_throat(self, T_c, h0, S_c):
        def neg_rho_v(logP):
            P = np.exp(logP)
            try:
                T, n, _ = self._T_at_PS(P, S_c, 600, T_c - 10)
                dh = h0 - self.mix_h(n, T)
                if dh <= 0:
                    return 0.0
                v   = np.sqrt(2.0 * dh)
                rho = self.mix_rho(n, T, P)
                return -(rho * v)
            except Exception:
                return 0.0

        res = minimize_scalar(neg_rho_v,
                              bounds=(np.log(self.P_c * 0.05),
                                      np.log(self.P_c * 0.98)),
                              method="bounded",
                              options={"xatol": 1e-4, "maxiter": 200})
        P_t = np.exp(res.x)
        T_t, n_t, x_t = self._T_at_PS(P_t, S_c, 600, T_c - 10)
        h_t  = self.mix_h(n_t, T_t)
        v_t  = np.sqrt(2.0 * (h0 - h_t))
        rho_t = self.mix_rho(n_t, T_t, P_t)
        return P_t, T_t, n_t, x_t, v_t, rho_t

    # ── exit at given area ratio ──

    def find_exit(self, ar_target, T_c, h0, S_c, rho_t, v_t):
        rv_t = rho_t * v_t

        def resid(logP):
            P = np.exp(logP)
            try:
                T, n, _ = self._T_at_PS(P, S_c, 250, T_c - 10)
                dh = h0 - self.mix_h(n, T)
                if dh <= 0:
                    return -ar_target
                v   = np.sqrt(2.0 * dh)
                rho = self.mix_rho(n, T, P)
                return rv_t / (rho * v) - ar_target
            except Exception:
                return -ar_target

        logP_lo = np.log(50.0)                  # ~0.5 mbar
        logP_hi = np.log(self.P_c * 0.45)       # well below throat

        logP_e = brentq(resid, logP_lo, logP_hi, xtol=0.005, rtol=1e-7)
        P_e = np.exp(logP_e)
        T_e, n_e, x_e = self._T_at_PS(P_e, S_c, 250, T_c - 10)
        h_e   = self.mix_h(n_e, T_e)
        v_e   = np.sqrt(2.0 * (h0 - h_e))
        rho_e = self.mix_rho(n_e, T_e, P_e)
        return P_e, T_e, n_e, x_e, v_e, rho_e

    # ── performance metrics ──

    def frozen_mach(self, n, T, v):
        N   = np.sum(n)
        cp  = self.mix_cp(n, T)
        cv  = cp - N * R_U
        gam = cp / cv
        a   = np.sqrt(gam * N * R_U * T)
        return v / a

    # ── main driver ──

    def solve(self):
        print("Solving chamber HP equilibrium …")
        T_c, n_c, x_c = self.solve_chamber()
        h_c = self.mix_h(n_c, T_c)
        S_c = self.mix_s(n_c, T_c, self.P_c)
        print(f"  T_chamber = {T_c:.2f} K   h0 = {self.h0:.1f} J/kg   h_c = {h_c:.1f} J/kg")

        print("Finding throat …")
        P_t, T_t, n_t, x_t, v_t, rho_t = self.find_throat(T_c, self.h0, S_c)
        c_star = self.P_c / (rho_t * v_t)
        print(f"  T_throat = {T_t:.2f} K   P = {P_t/1e5:.3f} bar   v = {v_t:.1f} m/s   c* = {c_star:.1f} m/s")

        results = {
            "chamber": {
                "temperature_K": round(T_c, 2),
                "pressure_bar": round(self.P_c / 1e5, 4),
                "mole_fractions": {sp: round(float(x_c[i]), 5)
                                   for i, sp in enumerate(self.species)}
            },
            "throat": {
                "temperature_K": round(T_t, 2),
                "pressure_bar": round(P_t / 1e5, 4),
                "velocity_m_per_s": round(v_t, 1)
            },
            "c_star_m_per_s": round(c_star, 1),
            "exit_conditions": []
        }

        for ar in self.problem["exit_area_ratios"]:
            print(f"Solving exit at Ae/At = {ar} …")
            P_e, T_e, n_e, x_e, v_e, rho_e = self.find_exit(
                ar, T_c, self.h0, S_c, rho_t, v_t)

            Isp  = v_e
            CF   = Isp / c_star
            Ivac = v_e + P_e / (rho_e * v_e)
            Mach = self.frozen_mach(n_e, T_e, v_e)

            print(f"  T={T_e:.1f} K  P={P_e/1e5:.5f} bar  Isp={Isp:.1f}  CF={CF:.4f}  Ivac={Ivac:.1f}  M={Mach:.3f}")

            results["exit_conditions"].append({
                "area_ratio": ar,
                "temperature_K": round(T_e, 2),
                "pressure_bar": round(P_e / 1e5, 5),
                "mach_number": round(Mach, 3),
                "isp_m_per_s": round(Isp, 1),
                "ivac_m_per_s": round(Ivac, 1),
                "cf": round(CF, 4)
            })

        return results


def main():
    thermo  = load_json("/app/thermo_data.json")
    problem = load_json("/app/problem.json")
    solver  = RocketSolver(thermo, problem)
    results = solver.solve()

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
