"""
Span-Wagner multiparameter Helmholtz equation of state for CO2.
Reference: Span & Wagner, J. Phys. Chem. Ref. Data 25(6), 1509-1596 (1996).
"""

import json
import math

with open("/app/co2_coefficients.json") as _f:
    _C = json.load(_f)

R = _C["gas_constant"]          # 8.31451 J/(mol*K)
M = _C["molar_mass"]            # 0.0440098 kg/mol
Tc = _C["reducing_T"]           # 304.1282 K
rhoc = _C["reducing_rhomolar"]  # 10624.9063 mol/m^3
Pc = _C["critical_p"]           # 7377300.0 Pa


# ===== Ideal-gas Helmholtz energy and derivatives =====

def _alpha0(tau, delta):
    """Returns (alpha0, d_alpha0/d_tau, d2_alpha0/d_tau2)."""
    a0 = 0.0
    a0_t = 0.0
    a0_tt = 0.0
    for term in _C["alpha0"]:
        typ = term["type"]
        if typ == "IdealGasHelmholtzLead":
            a0 += math.log(delta) + term["a1"] + term["a2"] * tau
            a0_t += term["a2"]
        elif typ == "IdealGasHelmholtzLogTau":
            a = term["a"]
            a0 += a * math.log(tau)
            a0_t += a / tau
            a0_tt -= a / (tau * tau)
        elif typ == "IdealGasHelmholtzPlanckEinstein":
            for ni, ti in zip(term["n"], term["t"]):
                x = ti * tau
                if x > 500:
                    a0 += ni * x
                    a0_t += ni * ti
                    continue
                ex = math.exp(x)
                em = 1.0 / ex  # exp(-x)
                a0 += ni * math.log(1.0 - em)
                a0_t += ni * ti * em / (1.0 - em)
                a0_tt -= ni * ti * ti * ex / (ex - 1.0) ** 2
        elif typ == "IdealGasHelmholtzEnthalpyEntropyOffset":
            a0 += term["a1"] + term["a2"] * tau
            a0_t += term["a2"]
    return a0, a0_t, a0_tt


# ===== Residual Helmholtz energy and derivatives =====

def _alphar(tau, delta):
    """Returns (ar, ar_d, ar_t, ar_dd, ar_tt, ar_dt).
    Subscripts: _d = d/d(delta), _t = d/d(tau).
    """
    ar = 0.0
    ar_d = 0.0
    ar_t = 0.0
    ar_dd = 0.0
    ar_tt = 0.0
    ar_dt = 0.0

    for term in _C["alphar"]:
        typ = term["type"]

        if typ == "ResidualHelmholtzPower":
            ns = term["n"]
            ds = term["d"]
            ts = term["t"]
            ls = term["l"]
            for i in range(len(ns)):
                ni, di, ti, li = ns[i], ds[i], ts[i], ls[i]
                dd = delta ** di
                tt = tau ** ti if ti != 0 else 1.0
                dtt = ti * tau ** (ti - 1) if ti != 0 else 0.0
                ddtt = ti * (ti - 1) * tau ** (ti - 2) if (ti != 0 and ti != 1) else 0.0

                if li == 0:
                    phi = ni * dd * tt
                    ar += phi
                    ar_d += ni * di * delta ** (di - 1) * tt
                    ar_t += ni * dd * dtt
                    ar_dd += ni * di * (di - 1) * delta ** (di - 2) * tt
                    ar_tt += ni * dd * ddtt
                    ar_dt += ni * di * delta ** (di - 1) * dtt
                else:
                    dl = delta ** li
                    edl = math.exp(-dl)
                    phi = ni * dd * tt * edl
                    ar += phi
                    f1 = di - li * dl
                    ar_d += ni * tt * delta ** (di - 1) * edl * f1
                    ar_t += ni * dd * edl * dtt
                    f2 = di - 1 - li * dl
                    ar_dd += ni * tt * delta ** (di - 2) * edl * (f1 * f2 - li * li * dl)
                    ar_tt += ni * dd * edl * ddtt
                    ar_dt += ni * delta ** (di - 1) * edl * f1 * dtt

        elif typ == "ResidualHelmholtzGaussian":
            ns = term["n"]
            ds = term["d"]
            ts = term["t"]
            etas = term["eta"]
            epss = term["epsilon"]
            betas = term["beta"]
            gammas = term["gamma"]
            for i in range(len(ns)):
                ni = ns[i]
                di, ti = ds[i], ts[i]
                eta_i, eps_i = etas[i], epss[i]
                beta_i, gamma_i = betas[i], gammas[i]

                dd = delta ** di
                tt = tau ** ti if ti != 0 else 1.0

                de = delta - eps_i
                tg = tau - gamma_i
                ev = math.exp(-eta_i * de * de - beta_i * tg * tg)
                phi = ni * dd * tt * ev

                F = di / delta - 2.0 * eta_i * de
                G = (ti / tau if ti != 0 else 0.0) - 2.0 * beta_i * tg

                ar += phi
                ar_d += phi * F
                ar_t += phi * G
                ar_dd += phi * (F * F - di / (delta * delta) - 2.0 * eta_i)
                ar_tt += phi * (G * G - (ti / (tau * tau) if ti != 0 else 0.0) - 2.0 * beta_i)
                ar_dt += phi * F * G

        elif typ == "ResidualHelmholtzNonAnalytic":
            ns = term["n"]
            As = term["A"]
            Bs = term["B"]
            Cs = term["C"]
            Ds = term["D"]
            a_s = term["a"]
            b_s = term["b"]
            betas = term["beta"]
            for i in range(len(ns)):
                ni = ns[i]
                Ai, Bi, Ci, Di = As[i], Bs[i], Cs[i], Ds[i]
                ai, bi, beta_i = a_s[i], b_s[i], betas[i]

                dm = delta - 1.0
                tm = tau - 1.0
                dm2 = dm * dm

                # psi and its derivatives
                psi = math.exp(-Ci * dm2 - Di * tm * tm)
                dpsi_dd = -2.0 * Ci * dm * psi
                dpsi_dt = -2.0 * Di * tm * psi
                d2psi_dd2 = (4.0 * Ci * Ci * dm2 - 2.0 * Ci) * psi
                d2psi_dt2 = (4.0 * Di * Di * tm * tm - 2.0 * Di) * psi
                d2psi_ddt = 4.0 * Ci * Di * dm * tm * psi

                # theta, Delta, and their derivatives
                adm = abs(dm)
                if adm > 1e-15:
                    p_half_beta = 1.0 / (2.0 * beta_i)
                    dm2_phb = dm2 ** p_half_beta  # ((delta-1)^2)^{1/(2*beta)}
                    theta = -tm + Ai * dm2_phb

                    dm2_a = dm2 ** ai
                    Delta = theta * theta + Bi * dm2_a

                    # dtheta/d_delta = A/(beta) * dm * dm2^{1/(2*beta)-1}
                    dtheta_dd = Ai / beta_i * dm * dm2 ** (p_half_beta - 1.0)

                    # d2theta/d_delta2 = A/beta * (1/beta - 1) * dm2^{1/(2*beta)-1}
                    d2theta_dd2 = Ai / beta_i * (1.0 / beta_i - 1.0) * dm2 ** (p_half_beta - 1.0)

                    # dDelta/d_delta
                    dDelta_dd = 2.0 * theta * dtheta_dd + 2.0 * ai * Bi * dm * dm2 ** (ai - 1.0)

                    # d2Delta/d_delta2
                    d2Delta_dd2 = (2.0 * (dtheta_dd * dtheta_dd + theta * d2theta_dd2)
                                   + 2.0 * ai * Bi * (2.0 * ai - 1.0) * dm2 ** (ai - 1.0))
                else:
                    theta = -tm
                    Delta = theta * theta
                    dtheta_dd = 0.0
                    d2theta_dd2 = 0.0
                    dDelta_dd = 0.0
                    d2Delta_dd2 = 2.0

                # Delta^b and derivatives
                if Delta > 1e-50:
                    Db = Delta ** bi
                    Dbm1 = Delta ** (bi - 1.0)
                    Dbm2 = Delta ** (bi - 2.0) if abs(bi - 1.0) > 1e-12 else 1.0 / Delta

                    dDb_dd = bi * Dbm1 * dDelta_dd
                    dDb_dt = bi * Dbm1 * (-2.0 * theta)

                    d2Db_dd2 = bi * ((bi - 1.0) * Dbm2 * dDelta_dd ** 2 + Dbm1 * d2Delta_dd2)
                    d2Db_dt2 = bi * (4.0 * (bi - 1.0) * Dbm2 * theta * theta + 2.0 * Dbm1)
                    d2Db_ddt = bi * ((bi - 1.0) * Dbm2 * dDelta_dd * (-2.0 * theta)
                                     + Dbm1 * (-2.0 * dtheta_dd))
                else:
                    Db = 0.0
                    dDb_dd = 0.0
                    dDb_dt = 0.0
                    d2Db_dd2 = 0.0
                    d2Db_dt2 = 0.0
                    d2Db_ddt = 0.0

                # Contributions to alphar and derivatives
                ar += ni * Db * delta * psi

                ar_d += ni * (dDb_dd * delta * psi
                              + Db * (psi + delta * dpsi_dd))

                ar_t += ni * delta * (dDb_dt * psi + Db * dpsi_dt)

                ar_dd += ni * (d2Db_dd2 * delta * psi
                               + 2.0 * dDb_dd * (psi + delta * dpsi_dd)
                               + Db * (2.0 * dpsi_dd + delta * d2psi_dd2))

                ar_tt += ni * delta * (d2Db_dt2 * psi
                                       + 2.0 * dDb_dt * dpsi_dt
                                       + Db * d2psi_dt2)

                ar_dt += ni * (Db * (dpsi_dt + delta * d2psi_ddt)
                               + delta * dDb_dd * dpsi_dt
                               + dDb_dt * (psi + delta * dpsi_dd)
                               + d2Db_ddt * delta * psi)

    return ar, ar_d, ar_t, ar_dd, ar_tt, ar_dt


# ===== Thermodynamic property functions =====

def pressure(T, rho):
    """Pressure in Pa from T (K) and rho (mol/m^3)."""
    tau = Tc / T
    delta = rho / rhoc
    _, ar_d, _, _, _, _ = _alphar(tau, delta)
    return rho * R * T * (1.0 + delta * ar_d)


def enthalpy(T, rho):
    """Molar enthalpy in J/mol (IIR reference)."""
    tau = Tc / T
    delta = rho / rhoc
    _, a0_t, _ = _alpha0(tau, delta)
    _, ar_d, ar_t, _, _, _ = _alphar(tau, delta)
    return R * T * (1.0 + tau * (a0_t + ar_t) + delta * ar_d)


def entropy(T, rho):
    """Molar entropy in J/(mol*K) (IIR reference)."""
    tau = Tc / T
    delta = rho / rhoc
    a0, a0_t, _ = _alpha0(tau, delta)
    ar, _, ar_t, _, _, _ = _alphar(tau, delta)
    return R * (tau * (a0_t + ar_t) - a0 - ar)


def cv(T, rho):
    """Molar isochoric heat capacity in J/(mol*K)."""
    tau = Tc / T
    delta = rho / rhoc
    _, _, a0_tt = _alpha0(tau, delta)
    _, _, _, _, ar_tt, _ = _alphar(tau, delta)
    return -R * tau * tau * (a0_tt + ar_tt)


def cp(T, rho):
    """Molar isobaric heat capacity in J/(mol*K)."""
    tau = Tc / T
    delta = rho / rhoc
    _, _, a0_tt = _alpha0(tau, delta)
    _, ar_d, _, ar_dd, ar_tt, ar_dt = _alphar(tau, delta)
    cv_val = -R * tau * tau * (a0_tt + ar_tt)
    num = (1.0 + delta * ar_d - delta * tau * ar_dt) ** 2
    den = 1.0 + 2.0 * delta * ar_d + delta * delta * ar_dd
    return cv_val + R * num / den


def speed_of_sound(T, rho):
    """Speed of sound in m/s."""
    tau = Tc / T
    delta = rho / rhoc
    _, _, a0_tt = _alpha0(tau, delta)
    _, ar_d, _, ar_dd, ar_tt, ar_dt = _alphar(tau, delta)
    mech = 1.0 + 2.0 * delta * ar_d + delta * delta * ar_dd
    num_sq = (1.0 + delta * ar_d - delta * tau * ar_dt) ** 2
    cv_term = tau * tau * (a0_tt + ar_tt)  # negative
    w2 = R * T / M * (mech - num_sq / cv_term)
    return math.sqrt(max(w2, 0.0))


# ===== Density solver =====

def density(T, P, phase="supercritical"):
    """Molar density in mol/m^3 from T (K), P (Pa), and phase hint."""
    # Initial guess
    if phase == "vapor":
        rho = P / (R * T)  # ideal gas
    elif phase == "liquid":
        rho = rhoc * 2.5
    else:  # supercritical
        rho_ig = P / (R * T)
        rho = max(rho_ig, rhoc * 0.5)

    # Newton-Raphson
    for _ in range(200):
        tau = Tc / T
        delta = rho / rhoc
        _, ar_d, _, ar_dd, _, _ = _alphar(tau, delta)
        P_calc = rho * R * T * (1.0 + delta * ar_d)
        dP_drho = R * T * (1.0 + 2.0 * delta * ar_d + delta * delta * ar_dd)
        if abs(dP_drho) < 1e-30:
            break
        drho = (P - P_calc) / dP_drho
        rho += drho
        if rho < 1e-6:
            rho = 1e-6
        if abs(drho) < abs(rho) * 1e-12:
            break
    return rho


# ===== Saturation solver =====

def _ln_fugacity_coeff(tau, delta):
    """ln(phi) = alphar + delta*d_alphar/d_delta - ln(Z) where Z=1+delta*ar_d."""
    ar, ar_d, _, _, _, _ = _alphar(tau, delta)
    Z = 1.0 + delta * ar_d
    if Z <= 0:
        return 1e10  # unphysical
    return ar + delta * ar_d - math.log(Z)


def saturation_densities(T):
    """Returns (rho_liquid, rho_vapor) in mol/m^3 at saturation.
    Uses pressure iteration with fugacity matching.
    """
    tau = Tc / T
    Tr = T / Tc

    # Lee-Kesler initial P estimate
    omega = _C["acentric"]
    f0 = 5.92714 - 6.09648 / Tr - 1.28862 * math.log(Tr) + 0.169347 * Tr ** 6
    f1 = 15.2518 - 15.6875 / Tr - 13.4721 * math.log(Tr) + 0.43577 * Tr ** 6
    P = Pc * math.exp(f0 + omega * f1)
    P = max(P, 100.0)
    P = min(P, Pc * 0.999)

    rho_l = rhoc * 2.5
    rho_v = P / (R * T)

    for iteration in range(200):
        # Find liquid density at P
        rho_l = density(T, P, "liquid")
        # Find vapor density at P
        rho_v = density(T, P, "vapor")

        delta_l = rho_l / rhoc
        delta_v = rho_v / rhoc

        # Check densities are on correct sides
        if delta_l < 1.05 or delta_v > 0.95:
            # Too close to critical or wrong root
            if delta_l < 1.05:
                rho_l = rhoc * 2.0
                delta_l = 2.0
            if delta_v > 0.95:
                rho_v = P / (R * T) * 0.5
                delta_v = rho_v / rhoc

        ln_phi_l = _ln_fugacity_coeff(tau, delta_l)
        ln_phi_v = _ln_fugacity_coeff(tau, delta_v)

        diff = ln_phi_l - ln_phi_v
        if abs(diff) < 1e-10:
            break

        # Successive substitution: P_new = P * exp(diff)
        # Damped for stability
        factor = math.exp(max(min(diff, 0.3), -0.3))
        P *= factor

        P = max(P, 100.0)
        P = min(P, Pc * 0.999)

    return rho_l, rho_v


def saturation_pressure(T):
    """Saturation pressure in Pa."""
    rho_l, rho_v = saturation_densities(T)
    P_l = pressure(T, rho_l)
    P_v = pressure(T, rho_v)
    return 0.5 * (P_l + P_v)
