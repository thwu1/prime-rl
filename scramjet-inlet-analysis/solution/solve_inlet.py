#!/usr/bin/env python3
"""
Supersonic multi-ramp inlet oblique shock analyzer.

Reads /app/inlet_config.json and writes computed results to /app/results.json.
Implements CPG and TPG oblique shock relations, multi-ramp chaining, and
optimization for maximum total pressure recovery.

"""

import json
import math
from scipy.optimize import brentq, minimize_scalar


# =========================================================================
# Core CPG (Calorically Perfect Gas) functions
# =========================================================================

def theta_beta_mach(beta_rad, M, gamma):
    """Compute deflection angle theta (rad) from shock angle beta (rad)."""
    sb = math.sin(beta_rad)
    cb = math.cos(beta_rad)
    M2sb2 = M ** 2 * sb ** 2
    if M2sb2 <= 1.0:
        return 0.0
    num = 2.0 * (cb / sb) * (M2sb2 - 1.0)
    den = M ** 2 * (gamma + math.cos(2 * beta_rad)) + 2.0
    if abs(den) < 1e-30:
        return 0.0
    return math.atan(num / den)


def find_beta_max(M, gamma):
    """Find shock angle (rad) at maximum deflection."""
    mu = math.asin(1.0 / M)
    res = minimize_scalar(
        lambda b: -theta_beta_mach(b, M, gamma),
        bounds=(mu + 1e-8, math.pi / 2 - 1e-8),
        method="bounded",
    )
    return res.x


def solve_beta(M, theta_deg, gamma, weak=True):
    """Solve for shock angle beta (deg) given M and deflection theta (deg)."""
    theta_rad = math.radians(theta_deg)
    if theta_deg < 1e-10:
        return 90.0

    mu = math.asin(1.0 / M)
    beta_max = find_beta_max(M, gamma)
    theta_max = theta_beta_mach(beta_max, M, gamma)

    if theta_rad > theta_max + 1e-10:
        raise ValueError(
            f"Detached shock: theta={theta_deg:.2f} > theta_max={math.degrees(theta_max):.2f}"
        )

    def residual(b):
        return theta_beta_mach(b, M, gamma) - theta_rad

    if weak:
        beta = brentq(residual, mu + 1e-8, beta_max - 1e-10)
    else:
        beta = brentq(residual, beta_max + 1e-10, math.pi / 2 - 1e-8)

    return math.degrees(beta)


def normal_shock_props(M1n, gamma):
    """All properties across a normal shock at normal Mach M1n.

    Returns: (M2n, p_ratio, rho_ratio, T_ratio, p0_ratio)
    """
    M1n2 = M1n ** 2
    gp1 = gamma + 1.0
    gm1 = gamma - 1.0

    M2n2 = (M1n2 + 2.0 / gm1) / (2.0 * gamma / gm1 * M1n2 - 1.0)
    M2n = math.sqrt(max(M2n2, 0.0))

    p_ratio = 1.0 + 2.0 * gamma / gp1 * (M1n2 - 1.0)
    rho_ratio = gp1 * M1n2 / (gm1 * M1n2 + 2.0)
    T_ratio = p_ratio / rho_ratio

    # Total pressure ratio (Rayleigh Pitot tube formula)
    t1 = (gp1 * M1n2 / (gm1 * M1n2 + 2.0)) ** (gamma / gm1)
    t2 = (gp1 / (2.0 * gamma * M1n2 - gm1)) ** (1.0 / gm1)
    p0_ratio = t1 * t2

    return M2n, p_ratio, rho_ratio, T_ratio, p0_ratio


# =========================================================================
# CPG case solvers
# =========================================================================

def solve_oblique(M1, theta_deg, gamma, weak=True):
    beta_deg = solve_beta(M1, theta_deg, gamma, weak)
    beta_rad = math.radians(beta_deg)
    theta_rad = math.radians(theta_deg)

    M1n = M1 * math.sin(beta_rad)
    M2n, p_ratio, rho_ratio, T_ratio, p0_ratio = normal_shock_props(M1n, gamma)

    sinbt = math.sin(beta_rad - theta_rad)
    M2 = M2n / sinbt if sinbt > 1e-10 else M2n

    return {
        "beta_deg": beta_deg,
        "M2": M2,
        "p2_p1": p_ratio,
        "T2_T1": T_ratio,
        "rho2_rho1": rho_ratio,
        "p02_p01": p0_ratio,
    }


def solve_normal(M1, gamma):
    M2n, p_ratio, rho_ratio, T_ratio, p0_ratio = normal_shock_props(M1, gamma)
    return {
        "beta_deg": 90.0,
        "M2": M2n,
        "p2_p1": p_ratio,
        "T2_T1": T_ratio,
        "rho2_rho1": rho_ratio,
        "p02_p01": p0_ratio,
    }


def solve_max_deflection(M, gamma):
    beta_max = find_beta_max(M, gamma)
    theta_max = theta_beta_mach(beta_max, M, gamma)
    return {
        "theta_max_deg": math.degrees(theta_max),
        "beta_at_max_deg": math.degrees(beta_max),
    }


def solve_multi_ramp(M1, theta_degs, gamma):
    shocks = []
    M_current = M1
    total_p0 = 1.0

    for theta in theta_degs:
        result = solve_oblique(M_current, theta, gamma, weak=True)
        result["M1"] = M_current
        result["T2_T1"] = result["T2_T1"]
        shocks.append(result)
        total_p0 *= result["p02_p01"]
        M_current = result["M2"]

    return {
        "shocks": shocks,
        "total_p0_recovery": total_p0,
        "final_M": M_current,
    }


def solve_optimize_equal_ramps(M1, n_ramps, gamma):
    """Find optimal equal-angle ramp configuration including terminal normal shock.

    The total pressure recovery is the product of all oblique shock p0 ratios
    times the terminal normal shock p0 ratio at the final (post-oblique) Mach.
    """
    def total_recovery_with_terminal(theta_deg):
        try:
            r = solve_multi_ramp(M1, [theta_deg] * n_ramps, gamma)
            final_M = r["final_M"]
            if final_M > 1.0:
                _, _, _, _, p0_ns = normal_shock_props(final_M, gamma)
                return r["total_p0_recovery"] * p0_ns
            else:
                return r["total_p0_recovery"]
        except (ValueError, ZeroDivisionError):
            return 0.0

    def neg_recovery(theta_deg):
        return -total_recovery_with_terminal(theta_deg)

    theta_max_info = solve_max_deflection(M1, gamma)
    theta_upper = min(theta_max_info["theta_max_deg"] * 0.85, 30.0)

    res = minimize_scalar(
        neg_recovery, bounds=(1.0, theta_upper), method="bounded",
        options={"xatol": 1e-5},
    )
    optimal_theta = res.x
    multi = solve_multi_ramp(M1, [optimal_theta] * n_ramps, gamma)

    if multi["final_M"] > 1.0:
        _, _, _, _, p0_ns = normal_shock_props(multi["final_M"], gamma)
        total_p0 = multi["total_p0_recovery"] * p0_ns
    else:
        total_p0 = multi["total_p0_recovery"]

    return {
        "optimal_theta_deg": optimal_theta,
        "total_p0_recovery": total_p0,
        "final_M": multi["final_M"],
        "shocks": multi["shocks"],
    }


# =========================================================================
# TPG (Thermally Perfect Gas) functions
# =========================================================================

def cp_eval(T, coeffs):
    """Cp(T) = c0 + c1*T + c2*T^2 + c3*T^3."""
    return sum(c * T ** i for i, c in enumerate(coeffs))


def h_eval(T, coeffs):
    """Enthalpy h(T) = integral of Cp from 0 to T."""
    return sum(c * T ** (i + 1) / (i + 1) for i, c in enumerate(coeffs))


def s_integral(T, coeffs):
    """Entropy integral: integral of Cp/T dT = c0*ln(T) + c1*T + c2*T^2/2 + ..."""
    result = coeffs[0] * math.log(T)
    for i in range(1, len(coeffs)):
        result += coeffs[i] * T ** i / i
    return result


def solve_tpg_normal_shock(rho1, V1n, p1, T1, cp_coeffs, R_gas):
    """Solve normal shock conservation equations for TPG.

    Parameterises by density ratio rho2/rho1 and uses energy residual.
    """
    h1 = h_eval(T1, cp_coeffs)
    mass_flux = rho1 * V1n          # rho1 * V1n = rho2 * V2n
    mom_flux = p1 + rho1 * V1n ** 2  # p1 + rho1*V1n^2 = p2 + rho2*V2n^2
    total_h = h1 + V1n ** 2 / 2.0    # h1 + V1n^2/2 = h2 + V2n^2/2

    def energy_residual(rho2):
        V2n = mass_flux / rho2
        p2 = mom_flux - rho2 * V2n ** 2
        if p2 <= 0:
            return 1e12
        T2 = p2 / (rho2 * R_gas)
        if T2 <= 0:
            return 1e12
        h2 = h_eval(T2, cp_coeffs)
        return (h2 + V2n ** 2 / 2.0) - total_h

    # Bounds: rho2 > rho1 (compression) and below strong-shock limit
    cp1 = cp_eval(T1, cp_coeffs)
    gamma1 = cp1 / (cp1 - R_gas)
    rho_max = rho1 * (gamma1 + 1) / (gamma1 - 1) * 2.0  # generous upper bound

    rho2 = brentq(energy_residual, rho1 * 1.0001, rho_max, xtol=1e-10)

    V2n = mass_flux / rho2
    p2 = mom_flux - rho2 * V2n ** 2
    T2 = p2 / (rho2 * R_gas)

    # Total pressure ratio from entropy change: p02/p01 = exp(-ds/R)
    ds = s_integral(T2, cp_coeffs) - s_integral(T1, cp_coeffs) - R_gas * math.log(p2 / p1)
    p0_ratio = math.exp(-ds / R_gas)

    return {
        "T2": T2,
        "p2": p2,
        "rho2": rho2,
        "V2n": V2n,
        "rho_ratio": rho2 / rho1,
        "p0_ratio": p0_ratio,
    }


def solve_tpg_oblique(M1, theta_deg, T1, p1, cp_coeffs, R_gas):
    """Solve oblique shock with thermally perfect gas model."""
    rho1 = p1 / (R_gas * T1)
    cp1 = cp_eval(T1, cp_coeffs)
    gamma1 = cp1 / (cp1 - R_gas)
    a1 = math.sqrt(gamma1 * R_gas * T1)
    V1 = M1 * a1

    mu_deg = math.degrees(math.asin(1.0 / M1))

    def compute_theta(beta_deg):
        """Compute actual deflection angle for given shock angle using TPG."""
        beta_rad = math.radians(beta_deg)
        V1n = V1 * math.sin(beta_rad)
        V1t = V1 * math.cos(beta_rad)
        ns = solve_tpg_normal_shock(rho1, V1n, p1, T1, cp_coeffs, R_gas)
        V2n = ns["V2n"]
        return beta_deg - math.degrees(math.atan2(V2n, V1t))

    def residual(beta_deg):
        try:
            return compute_theta(beta_deg) - theta_deg
        except Exception:
            return float("nan")

    # Scan for bracket (weak solution: first negative-to-positive crossing)
    n_scan = 500
    beta_lo = mu_deg + 0.3
    beta_hi = 85.0
    step = (beta_hi - beta_lo) / n_scan

    bracket_a, bracket_b = None, None
    prev_r = residual(beta_lo)
    for k in range(1, n_scan + 1):
        b = beta_lo + k * step
        r = residual(b)
        if math.isnan(prev_r) or math.isnan(r):
            prev_r = r
            continue
        if prev_r <= 0 and r > 0:
            bracket_a = b - step
            bracket_b = b
            break
        prev_r = r

    if bracket_a is None:
        raise ValueError("No weak TPG shock solution found")

    beta_result = brentq(residual, bracket_a, bracket_b, xtol=1e-8)

    # Full solution at converged beta
    beta_rad = math.radians(beta_result)
    V1n = V1 * math.sin(beta_rad)
    V1t = V1 * math.cos(beta_rad)
    ns = solve_tpg_normal_shock(rho1, V1n, p1, T1, cp_coeffs, R_gas)

    V2n = ns["V2n"]
    V2 = math.sqrt(V2n ** 2 + V1t ** 2)

    T2 = ns["T2"]
    cp2 = cp_eval(T2, cp_coeffs)
    gamma2 = cp2 / (cp2 - R_gas)
    a2 = math.sqrt(gamma2 * R_gas * T2)
    M2 = V2 / a2

    return {
        "beta_deg": beta_result,
        "M2": M2,
        "T2_K": T2,
        "p2_Pa": ns["p2"],
        "rho2_rho1": ns["rho_ratio"],
        "p02_p01": ns["p0_ratio"],
    }


# =========================================================================
# Main driver
# =========================================================================

def main():
    with open("/app/inlet_config.json") as f:
        config = json.load(f)

    output_cases = []

    for case in config["cases"]:
        cid = case["id"]
        ctype = case["type"]
        result = {"id": cid}

        if ctype == "single_oblique":
            weak = case.get("shock_type", "weak") == "weak"
            r = solve_oblique(case["M1"], case["theta_deg"], case["gamma"], weak=weak)
            result.update(r)

        elif ctype == "normal_shock":
            r = solve_normal(case["M1"], case["gamma"])
            result.update(r)

        elif ctype == "max_deflection":
            r = solve_max_deflection(case["M1"], case["gamma"])
            result.update(r)

        elif ctype == "multi_ramp":
            r = solve_multi_ramp(case["M1"], case["theta_degs"], case["gamma"])
            result.update(r)

        elif ctype == "optimize_equal_ramps":
            r = solve_optimize_equal_ramps(case["M1"], case["n_ramps"], case["gamma"])
            result.update(r)

        elif ctype == "single_oblique_tpg":
            r = solve_tpg_oblique(
                case["M1"], case["theta_deg"],
                case["T1_K"], case["p1_Pa"],
                case["cp_poly"], case["R_gas"],
            )
            result.update(r)

        output_cases.append(result)

    with open("/app/results.json", "w") as f:
        json.dump({"cases": output_cases}, f, indent=2)

    print(f"Wrote {len(output_cases)} cases to /app/results.json")


if __name__ == "__main__":
    main()
