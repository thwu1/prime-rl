#!/usr/bin/env python3
"""
H2/O2 Chemical Equilibrium Combustion and Rocket Nozzle Performance Solver.
Uses compiled Fortran module for thermodynamic property evaluation via ctypes.
"""

import json
import math
import os
import subprocess
import ctypes as ct
import numpy as np
from scipy.optimize import minimize, brentq, minimize_scalar

R_UNIV = 8.314462618  # Universal gas constant, J/(mol*K)


# ---------------------------------------------------------------------------
# Compile and load Fortran thermo library
# ---------------------------------------------------------------------------

def compile_fortran():
    """Compile thermo_eval.f90 to a position-independent shared library."""
    src = "/app/thermo_eval.f90"
    lib_path = "/app/libthermo_eval.so"
    if not os.path.exists(lib_path):
        subprocess.run([
            "gfortran", "-shared", "-fPIC", "-O2",
            src, "-o", lib_path
        ], check=True, capture_output=True)
    return lib_path


def load_thermo_lib(lib_path):
    """Load compiled library and configure function signatures."""
    lib = ct.CDLL(lib_path)
    _dp = ct.POINTER(ct.c_double)
    _d = ct.c_double

    for name in ["thermo_cp_over_r", "thermo_h_over_rt",
                  "thermo_s_over_r", "thermo_g_over_rt"]:
        func = getattr(lib, name)
        func.restype = _d
        func.argtypes = [_dp, _d, _d, _d]

    lib.thermo_eval_all.restype = None
    lib.thermo_eval_all.argtypes = [_dp, _d, _d, _d, _dp, _dp, _dp, _dp]

    return lib


_LIB_PATH = compile_fortran()
_LIB = load_thermo_lib(_LIB_PATH)


# ---------------------------------------------------------------------------
# Fortran-backed thermodynamic property evaluation
# ---------------------------------------------------------------------------

def _get_interval(sp, T):
    """Return the coefficient interval covering temperature T."""
    intervals = sp["intervals"]
    for iv in intervals:
        if iv["t_low"] <= T <= iv["t_high"]:
            return iv
    if T < intervals[0]["t_low"]:
        return intervals[0]
    return intervals[-1]


def _make_coeff_arr(iv):
    """Create ctypes c_double array from interval coefficients."""
    return (ct.c_double * 7)(*iv["coeffs"])


def cp_over_R(sp, T):
    iv = _get_interval(sp, T)
    a = _make_coeff_arr(iv)
    return _LIB.thermo_cp_over_r(a, iv["b1"], iv["b2"], T)


def h_over_RT(sp, T):
    iv = _get_interval(sp, T)
    a = _make_coeff_arr(iv)
    return _LIB.thermo_h_over_rt(a, iv["b1"], iv["b2"], T)


def s_over_R(sp, T):
    iv = _get_interval(sp, T)
    a = _make_coeff_arr(iv)
    return _LIB.thermo_s_over_r(a, iv["b1"], iv["b2"], T)


def g_over_RT(sp, T):
    iv = _get_interval(sp, T)
    a = _make_coeff_arr(iv)
    return _LIB.thermo_g_over_rt(a, iv["b1"], iv["b2"], T)


# ---------------------------------------------------------------------------
# NASA thermo database parser (RP-1311 fixed-width format)
# ---------------------------------------------------------------------------

def parse_thermo(filepath):
    """Parse NASA 7-coefficient thermodynamic database."""
    with open(filepath) as f:
        raw = f.read()
    lines = raw.split("\n")
    species = {}
    i = 0

    while i < len(lines):
        if lines[i].strip().lower() == "thermo":
            i += 2
            break
        i += 1

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.lower() == "end":
            i += 1
            continue

        name = line[:18].strip()
        if not name:
            i += 1
            continue
        i += 1
        if i >= len(lines):
            break

        ml = lines[i]
        num_iv = int(ml[:2].strip() or "0")

        elements = {}
        for k in range(5):
            off = 10 + k * 8
            sym = ml[off:off + 2].strip()
            try:
                cnt = float(ml[off + 2:off + 8])
            except (ValueError, IndexError):
                cnt = 0.0
            if sym and cnt > 0 and sym[0].isalpha():
                elements[sym] = cnt

        try:
            mw = float(ml[52:65])
        except (ValueError, IndexError):
            mw = 0.0
        try:
            hf = float(ml[65:80])
        except (ValueError, IndexError):
            hf = 0.0

        i += 1
        intervals = []
        for _ in range(num_iv):
            if i >= len(lines):
                break

            tl = lines[i]
            t_low = float(tl[:11].strip())
            th_str = tl[11:22].strip()
            try:
                t_high = float(th_str)
            except ValueError:
                t_high = float(th_str[:-1])
            i += 1

            cl1 = lines[i]
            a = []
            for k in range(5):
                s = cl1[k * 16:(k + 1) * 16].replace("D", "E").replace("d", "e").strip()
                a.append(float(s))
            i += 1

            cl2 = lines[i]
            a.append(float(cl2[0:16].replace("D", "E").replace("d", "e").strip()))
            a.append(float(cl2[16:32].replace("D", "E").replace("d", "e").strip()))
            b1 = float(cl2[48:64].replace("D", "E").replace("d", "e").strip())
            b2 = float(cl2[64:80].replace("D", "E").replace("d", "e").strip())
            i += 1

            intervals.append({
                "t_low": t_low, "t_high": t_high,
                "coeffs": a, "b1": b1, "b2": b2,
            })

        species[name] = {
            "name": name, "elements": elements,
            "mw": mw, "hf": hf, "intervals": intervals,
        }

    return species


# ---------------------------------------------------------------------------
# TP equilibrium solver (Gibbs minimization via SLSQP)
# ---------------------------------------------------------------------------

def solve_tp(sp_names, sp_db, T, P, b_elem, n_hint=None):
    """
    Minimise mixture Gibbs energy at given T, P subject to element balance.
    """
    NS = len(sp_names)
    el_names = sorted(b_elem.keys())
    NE = len(el_names)
    b = np.array([b_elem[e] for e in el_names])

    A = np.zeros((NE, NS))
    for j, spn in enumerate(sp_names):
        for ii, e in enumerate(el_names):
            A[ii, j] = sp_db[spn]["elements"].get(e, 0.0)

    g0 = np.array([g_over_RT(sp_db[spn], T) for spn in sp_names])
    lnP = math.log(max(P, 1e-30))

    def _safe_exp(y):
        return np.exp(np.clip(y, -500, 500))

    def obj(y):
        n = _safe_exp(y)
        nt = n.sum()
        if nt <= 0 or not np.isfinite(nt):
            return 1e30
        return float(np.dot(n, g0 + y - math.log(nt) + lnP))

    def grad(y):
        n = _safe_exp(y)
        nt = n.sum()
        if nt <= 0 or not np.isfinite(nt):
            return np.zeros_like(y)
        g = n * (g0 + y - math.log(nt) + lnP)
        return np.where(np.isfinite(g), g, 0.0)

    def ceq(y):
        return A @ _safe_exp(y) - b

    def ceq_jac(y):
        n = _safe_exp(y)
        return A * n[np.newaxis, :]

    if n_hint is not None and len(n_hint) == NS:
        n0 = np.maximum(n_hint, 1e-25)
    else:
        n0 = _initial_guess(sp_names, sp_db, b_elem)

    y0 = np.log(np.maximum(n0, 1e-30))

    res = minimize(obj, y0, jac=grad, method="SLSQP",
                   constraints=[{"type": "eq", "fun": ceq, "jac": ceq_jac}],
                   options={"maxiter": 3000, "ftol": 1e-16})

    n_eq = _safe_exp(res.x)
    n_eq = _project_element_balance(n_eq, A, b)
    n_tot = n_eq.sum()
    x = n_eq / n_tot
    return n_eq, x, n_tot


def _initial_guess(sp_names, sp_db, b_elem):
    NS = len(sp_names)
    n0 = np.full(NS, 1e-8)
    h_avail = b_elem.get("H", 0.0)
    o_avail = b_elem.get("O", 0.0)

    if "H2O" in sp_names:
        idx = sp_names.index("H2O")
        n_h2o = min(h_avail / 2.0, o_avail) * 0.80
        n0[idx] = max(n_h2o, 1e-8)
        h_rem = h_avail - 2.0 * n0[idx]
        o_rem = o_avail - n0[idx]
    else:
        h_rem, o_rem = h_avail, o_avail

    if "H2" in sp_names and h_rem > 1e-10:
        n0[sp_names.index("H2")] = h_rem / 2.0
    if "O2" in sp_names and o_rem > 1e-10:
        n0[sp_names.index("O2")] = o_rem / 2.0
    return n0


def _project_element_balance(n, A, b):
    r = A @ n - b
    if np.linalg.norm(r) < 1e-12 * np.linalg.norm(b):
        return n
    AAT = A @ (A.T * n[:, np.newaxis])
    try:
        lam = np.linalg.solve(AAT, r)
        dn = n * (A.T @ lam)
        n_new = n - dn
        n_new = np.maximum(n_new, 1e-30)
        return n_new
    except np.linalg.LinAlgError:
        return n


# ---------------------------------------------------------------------------
# Mixture property helpers
# ---------------------------------------------------------------------------

def mix_h(sp_names, sp_db, T, n):
    return sum(n[j] * h_over_RT(sp_db[spn], T)
               for j, spn in enumerate(sp_names)) * R_UNIV * T


def mix_s(sp_names, sp_db, T, P, n, x):
    s = 0.0
    lnP = math.log(max(P, 1e-30))
    for j, spn in enumerate(sp_names):
        xj = max(x[j], 1e-30)
        s += n[j] * (s_over_R(sp_db[spn], T) - math.log(xj) - lnP)
    return s * R_UNIV


def mix_mw(x, sp_names, sp_db):
    return sum(x[j] * sp_db[spn]["mw"] for j, spn in enumerate(sp_names))


# ---------------------------------------------------------------------------
# HP solver (assigned enthalpy and pressure)
# ---------------------------------------------------------------------------

def solve_hp(sp_names, sp_db, P, h_target, b_elem, T_lo=1500, T_hi=4500):
    def residual(T):
        n, x, nt = solve_tp(sp_names, sp_db, T, P, b_elem)
        return mix_h(sp_names, sp_db, T, n) - h_target

    T_c = brentq(residual, T_lo, T_hi, xtol=0.05, rtol=1e-9)
    n, x, nt = solve_tp(sp_names, sp_db, T_c, P, b_elem)
    return T_c, n, x, nt


# ---------------------------------------------------------------------------
# SP solver (assigned entropy and pressure)
# ---------------------------------------------------------------------------

def solve_sp(sp_names, sp_db, P, s_target, b_elem, T_lo=500, T_hi=4500,
             n_hint=None):
    def residual(T):
        try:
            n, x, nt = solve_tp(sp_names, sp_db, T, P, b_elem, n_hint=n_hint)
            s = mix_s(sp_names, sp_db, T, P, n, x)
            if not math.isfinite(s):
                return float('nan')
            return s - s_target
        except Exception:
            return float('nan')

    r_lo = residual(T_lo)
    r_hi = residual(T_hi)

    while (not math.isfinite(r_hi)) and T_hi > T_lo + 100:
        T_hi *= 0.8
        r_hi = residual(T_hi)

    while (not math.isfinite(r_lo)) and T_lo < T_hi - 100:
        T_lo *= 1.2
        r_lo = residual(T_lo)

    T = brentq(residual, T_lo, T_hi, xtol=0.05, rtol=1e-9)
    n, x, nt = solve_tp(sp_names, sp_db, T, P, b_elem, n_hint=n_hint)
    return T, n, x, nt


# ---------------------------------------------------------------------------
# Nozzle station computation
# ---------------------------------------------------------------------------

def station_props(sp_names, sp_db, P, s_c, h_c, b_elem,
                  T_lo=500, T_hi=5000, n_hint=None):
    T, n, x, nt = solve_sp(sp_names, sp_db, P, s_c, b_elem,
                            T_lo=T_lo, T_hi=T_hi, n_hint=n_hint)
    h = mix_h(sp_names, sp_db, T, n)
    mw = mix_mw(x, sp_names, sp_db)
    rho = P * 1e5 * mw * 1e-3 / (R_UNIV * T)
    dh = h_c - h
    if dh <= 0:
        v = 0.0
    else:
        v = math.sqrt(2.0 * dh * 1000.0)
    return T, rho, v, h, n, x, nt, mw


def find_throat(sp_names, sp_db, P_c, s_c, h_c, b_elem):
    def neg_flux(P):
        try:
            T, rho, v, *_ = station_props(sp_names, sp_db, P, s_c, h_c,
                                          b_elem, T_hi=4500)
            return -(rho * v)
        except Exception:
            return 0.0

    Ps = np.linspace(P_c * 0.3, P_c * 0.8, 30)
    fluxes = np.array([neg_flux(p) for p in Ps])
    best_idx = int(np.argmin(fluxes))
    P_lo = Ps[max(best_idx - 2, 0)]
    P_hi = Ps[min(best_idx + 2, len(Ps) - 1)]

    res = minimize_scalar(neg_flux, bounds=(P_lo, P_hi), method="bounded",
                          options={"xatol": 0.005})
    P_t = res.x

    T_t, rho_t, v_t, h_t, n_t, x_t, nt_t, mw_t = station_props(
        sp_names, sp_db, P_t, s_c, h_c, b_elem, T_hi=4500)
    return P_t, T_t, rho_t, v_t, h_t, n_t, x_t, nt_t, mw_t


def find_exit(sp_names, sp_db, s_c, h_c, b_elem, rho_t_v_t, area_ratio, P_t):
    target_flux = rho_t_v_t / area_ratio

    def residual(P):
        try:
            _, rho, v, *_ = station_props(sp_names, sp_db, P, s_c, h_c,
                                          b_elem, T_lo=400, T_hi=4000)
            return rho * v - target_flux
        except Exception:
            return -target_flux

    P_lo = 0.01
    for trial in [P_t * 0.001, P_t * 0.01, P_t * 0.05]:
        try:
            _, rho, v, *_ = station_props(sp_names, sp_db, trial, s_c, h_c,
                                          b_elem, T_lo=400, T_hi=4000)
            if rho * v < target_flux:
                P_lo = trial
                break
        except Exception:
            continue

    P_e = brentq(residual, P_lo, P_t * 0.98, xtol=0.0005, rtol=1e-8)
    T_e, rho_e, v_e, h_e, n_e, x_e, nt_e, mw_e = station_props(
        sp_names, sp_db, P_e, s_c, h_c, b_elem, T_lo=400, T_hi=4000)
    return P_e, T_e, rho_e, v_e, h_e


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with open("/app/problem.json") as f:
        prob = json.load(f)

    sp_db = parse_thermo(prob["thermo_database"])

    fuel = prob["propellants"]["fuel"]
    ox = prob["propellants"]["oxidizer"]
    of_ratio = prob["propellants"]["of_ratio"]
    P_c = prob["chamber_pressure_bar"]
    sp_names = prob["product_species"]
    area_ratios = prob["supersonic_area_ratios"]

    f_frac = 1.0 / (1.0 + of_ratio)
    o_frac = of_ratio / (1.0 + of_ratio)

    b_elem = {}
    for el, cnt in fuel["formula"].items():
        b_elem[el] = b_elem.get(el, 0.0) + cnt * f_frac / fuel["molecular_weight"]
    for el, cnt in ox["formula"].items():
        b_elem[el] = b_elem.get(el, 0.0) + cnt * o_frac / ox["molecular_weight"]

    h_c = (f_frac * fuel["hf_j_per_mol"] / fuel["molecular_weight"]
           + o_frac * ox["hf_j_per_mol"] / ox["molecular_weight"])

    print(f"Element amounts: {b_elem}")
    print(f"Chamber enthalpy target: {h_c:.4f} J/g")

    T_c, n_c, x_c, nt_c = solve_hp(sp_names, sp_db, P_c, h_c, b_elem)
    mw_c = mix_mw(x_c, sp_names, sp_db)
    s_c = mix_s(sp_names, sp_db, T_c, P_c, n_c, x_c)

    print(f"\n=== Chamber ===")
    print(f"T = {T_c:.3f} K, MW = {mw_c:.3f}")
    for j, sp in enumerate(sp_names):
        if x_c[j] > 1e-8:
            print(f"  x({sp}) = {x_c[j]:.6g}")

    P_t, T_t, rho_t, v_t, h_t, n_t, x_t, nt_t, mw_t = find_throat(
        sp_names, sp_db, P_c, s_c, h_c, b_elem)
    c_star = P_c * 1e5 / (rho_t * v_t)

    print(f"\n=== Throat ===")
    print(f"T = {T_t:.3f} K, P = {P_t:.4f} bar, c* = {c_star:.2f} m/s")

    rho_t_v_t = rho_t * v_t
    exit_conditions = []
    for ar in area_ratios:
        P_e, T_e, rho_e, v_e, h_e = find_exit(
            sp_names, sp_db, s_c, h_c, b_elem, rho_t_v_t, ar, P_t)
        isp_vac = v_e + P_e * 1e5 / (rho_e * v_e)

        print(f"\n=== Exit Ae/At = {ar} ===")
        print(f"T = {T_e:.3f} K, P = {P_e:.4f} bar, Isp_vac = {isp_vac:.3f} m/s")

        exit_conditions.append({
            "area_ratio": ar,
            "isp_vacuum_m_per_s": round(isp_vac, 3),
        })

    results = {
        "chamber": {
            "temperature_k": round(T_c, 3),
            "pressure_bar": P_c,
            "molecular_weight": round(mw_c, 3),
            "mole_fractions": {sp: float(f"{x_c[j]:.7g}")
                               for j, sp in enumerate(sp_names)},
        },
        "throat": {
            "temperature_k": round(T_t, 3),
            "pressure_bar": round(P_t, 3),
        },
        "performance": {
            "c_star_m_per_s": round(c_star, 2),
            "exit_conditions": exit_conditions,
        },
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
