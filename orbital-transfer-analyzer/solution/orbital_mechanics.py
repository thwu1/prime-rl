"""
Corrected orbital mechanics computation library.
Fixes bugs in coe_rotation_matrix and Lambert f-coefficient.
Implements j2_correction, plane_change_dv, and mission_budget.

All internal units: km, km/s, seconds, radians.
"""

import math
import numpy as np


# ---------------------------------------------------------------------------
# Stumpff functions
# ---------------------------------------------------------------------------

def stumpff_c2(psi):
    """Stumpff function c2(psi)."""
    if psi > 1e-6:
        return (1.0 - math.cos(math.sqrt(psi))) / psi
    elif psi < -1e-6:
        return (math.cosh(math.sqrt(-psi)) - 1.0) / (-psi)
    else:
        return 1.0 / 2.0


def stumpff_c3(psi):
    """Stumpff function c3(psi)."""
    if psi > 1e-6:
        sp = math.sqrt(psi)
        return (sp - math.sin(sp)) / (psi * sp)
    elif psi < -1e-6:
        sp = math.sqrt(-psi)
        return (math.sinh(sp) - sp) / ((-psi) * sp)
    else:
        return 1.0 / 6.0


# ---------------------------------------------------------------------------
# Anomaly conversions
# ---------------------------------------------------------------------------

def E_to_nu(E, ecc):
    """True anomaly from eccentric anomaly (elliptic orbits)."""
    return 2.0 * math.atan2(
        math.sqrt(1.0 + ecc) * math.sin(E / 2.0),
        math.sqrt(1.0 - ecc) * math.cos(E / 2.0),
    )


def F_to_nu(F, ecc):
    """True anomaly from hyperbolic anomaly."""
    return 2.0 * math.atan(
        math.sqrt((ecc + 1.0) / (ecc - 1.0)) * math.tanh(F / 2.0)
    )


# ---------------------------------------------------------------------------
# Rotation matrices
# ---------------------------------------------------------------------------

def rotation_matrix(angle, axis):
    """Rotation matrix about a principal axis (0=x, 2=z)."""
    c = math.cos(angle)
    s = math.sin(angle)
    if axis == 0:
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=float)
    elif axis == 2:
        return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=float)
    else:
        raise ValueError(f"Unsupported axis: {axis}")


def coe_rotation_matrix(inc, raan, argp):
    """Rotation matrix from perifocal (PQW) to inertial (IJK) frame.

    Composes 3-1-3 Euler rotations: R3(raan) @ R1(inc) @ R3(argp).
    """
    r = rotation_matrix(raan, 2)
    r = r @ rotation_matrix(inc, 0)
    r = r @ rotation_matrix(argp, 2)
    return r


# ---------------------------------------------------------------------------
# State vector <-> Classical orbital elements
# ---------------------------------------------------------------------------

def rv2coe(k, r, v, tol=1e-8):
    """Convert position/velocity state vectors to classical orbital elements."""
    r = np.asarray(r, dtype=float)
    v = np.asarray(v, dtype=float)

    h = np.cross(r, v)
    n = np.cross(np.array([0.0, 0.0, 1.0]), h)

    r_norm = np.linalg.norm(r)
    v_sq = np.dot(v, v)
    h_norm = np.linalg.norm(h)

    e_vec = ((v_sq - k / r_norm) * r - np.dot(r, v) * v) / k
    ecc = np.linalg.norm(e_vec)

    p = h_norm ** 2 / k
    inc = math.acos(np.clip(h[2] / h_norm, -1.0, 1.0))

    circular = ecc < tol
    equatorial = abs(inc) < tol

    if equatorial and not circular:
        raan = 0.0
        argp = math.atan2(e_vec[1], e_vec[0]) % (2 * math.pi)
        nu = math.atan2(
            np.dot(h, np.cross(e_vec, r)) / h_norm, np.dot(r, e_vec)
        )
    elif not equatorial and circular:
        raan = math.atan2(n[1], n[0]) % (2 * math.pi)
        argp = 0.0
        nu = math.atan2(
            np.dot(r, np.cross(h, n)) / h_norm, np.dot(r, n)
        )
    elif equatorial and circular:
        raan = 0.0
        argp = 0.0
        nu = math.atan2(r[1], r[0]) % (2 * math.pi)
    else:
        a = p / (1.0 - ecc ** 2)
        ka = k * a
        if a > 0:
            e_se = np.dot(r, v) / math.sqrt(ka)
            e_ce = r_norm * v_sq / k - 1.0
            E = math.atan2(e_se, e_ce)
            nu = E_to_nu(E, ecc)
        else:
            e_sh = np.dot(r, v) / math.sqrt(-ka)
            e_ch = r_norm * v_sq / k - 1.0
            F = math.log((e_ch + e_sh) / (e_ch - e_sh)) / 2.0
            nu = F_to_nu(F, ecc)

        raan = math.atan2(n[1], n[0]) % (2 * math.pi)
        px = np.dot(r, n)
        py = np.dot(r, np.cross(h, n)) / h_norm
        argp = (math.atan2(py, px) - nu) % (2 * math.pi)

    nu = (nu + math.pi) % (2 * math.pi) - math.pi

    return p, ecc, inc, raan, argp, nu


def coe2rv(k, p, ecc, inc, raan, argp, nu):
    """Convert classical orbital elements to state vectors."""
    cos_nu = math.cos(nu)
    sin_nu = math.sin(nu)

    r_factor = p / (1.0 + ecc * cos_nu)
    v_factor = math.sqrt(k / p)

    r_pqw = np.array([r_factor * cos_nu, r_factor * sin_nu, 0.0])
    v_pqw = np.array([v_factor * (-sin_nu), v_factor * (ecc + cos_nu), 0.0])

    rm = coe_rotation_matrix(inc, raan, argp)
    r_ijk = rm @ r_pqw
    v_ijk = rm @ v_pqw

    return r_ijk, v_ijk


# ---------------------------------------------------------------------------
# Lambert's problem solver
# ---------------------------------------------------------------------------

def lambert_solve(k, r0, r, tof, prograde=True, numiter=35, rtol=1e-8):
    """Solve Lambert's problem using the universal variable method."""
    r0 = np.asarray(r0, dtype=float)
    r = np.asarray(r, dtype=float)

    r0_norm = np.linalg.norm(r0)
    r_norm = np.linalg.norm(r)
    r0r = r0_norm * r_norm
    r0pr = r0_norm + r_norm

    cos_dnu = np.dot(r0, r) / r0r

    t_m = 1.0 if prograde else -1.0

    A = t_m * math.sqrt(r0r * (1.0 + cos_dnu))

    if abs(A) < 1e-14:
        raise RuntimeError("Cannot compute orbit, phase angle is 180 degrees")

    psi = 0.0
    psi_low = -4.0 * math.pi ** 2
    psi_up = 4.0 * math.pi ** 2

    converged = False
    for _ in range(numiter):
        c2 = stumpff_c2(psi)
        c3 = stumpff_c3(psi)

        y = r0pr + A * (psi * c3 - 1.0) / math.sqrt(c2)

        if A > 0.0:
            while y < 0.0:
                psi_low = psi
                psi = 0.8 * (1.0 / c3) * (
                    1.0 - r0r * math.sqrt(c2) / A
                )
                c2 = stumpff_c2(psi)
                c3 = stumpff_c3(psi)
                y = r0pr + A * (psi * c3 - 1.0) / math.sqrt(c2)

        xi = math.sqrt(y / c2)
        tof_new = (xi ** 3 * c3 + A * math.sqrt(y)) / math.sqrt(k)

        if abs((tof_new - tof) / tof) < rtol:
            converged = True
            break

        if tof_new <= tof:
            psi_low = psi
        else:
            psi_up = psi

        psi = (psi_up + psi_low) / 2.0

    if not converged:
        raise RuntimeError("Lambert solver did not converge")

    f = 1.0 - y / r0_norm
    g = A * math.sqrt(y / k)
    gdot = 1.0 - y / r_norm

    v0 = (r - f * r0) / g
    v_final = (gdot * r - r0) / g

    return v0, v_final


# ---------------------------------------------------------------------------
# Hohmann transfer
# ---------------------------------------------------------------------------

def hohmann(k, r_i, r_f):
    """Compute Hohmann two-impulse transfer between coplanar circular orbits."""
    a_trans = (r_i + r_f) / 2.0

    v_i = math.sqrt(k / r_i)
    v_f = math.sqrt(k / r_f)

    v_trans_a = math.sqrt(2.0 * k / r_i - k / a_trans)
    v_trans_b = math.sqrt(2.0 * k / r_f - k / a_trans)

    dv_a = abs(v_trans_a - v_i)
    dv_b = abs(v_f - v_trans_b)

    t_trans = math.pi * math.sqrt(a_trans ** 3 / k)

    return dv_a, dv_b, t_trans


# ---------------------------------------------------------------------------
# Bielliptic transfer
# ---------------------------------------------------------------------------

def bielliptic(k, r_i, r_b, r_f):
    """Compute bielliptic three-impulse transfer."""
    a_trans1 = (r_i + r_b) / 2.0
    a_trans2 = (r_b + r_f) / 2.0

    v_i = math.sqrt(k / r_i)
    v_f = math.sqrt(k / r_f)

    v_trans1_a = math.sqrt(2.0 * k / r_i - k / a_trans1)
    v_trans1_b = math.sqrt(2.0 * k / r_b - k / a_trans1)
    v_trans2_b = math.sqrt(2.0 * k / r_b - k / a_trans2)
    v_trans2_f = math.sqrt(2.0 * k / r_f - k / a_trans2)

    dv_a = abs(v_trans1_a - v_i)
    dv_b = abs(v_trans2_b - v_trans1_b)
    dv_c = abs(v_f - v_trans2_f)

    t_trans1 = math.pi * math.sqrt(a_trans1 ** 3 / k)
    t_trans2 = math.pi * math.sqrt(a_trans2 ** 3 / k)

    return dv_a, dv_b, dv_c, t_trans1, t_trans2


# ---------------------------------------------------------------------------
# J2 pericenter correction
# ---------------------------------------------------------------------------

def j2_correction(k, R, J2, max_delta_r, a, ecc, inc):
    """Compute pericenter correction maneuver due to J2 perturbation.

    Based on Vallado "Fundamentals of Astrodynamics", p.885.
    """
    p = a * (1.0 - ecc ** 2)
    n = math.sqrt(k / a ** 3)

    # Pericenter drift rate due to J2
    dw = (3.0 * n * R ** 2 * J2) / (4.0 * p ** 2) * (
        4.0 - 5.0 * math.sin(inc) ** 2
    )

    # Maximum allowable argument-of-perigee drift
    delta_w = math.sqrt(
        2.0 * (1.0 + ecc) * max_delta_r / (a * ecc * (1.0 - ecc))
    )

    delta_t = abs(delta_w / dw)
    delta_v = 0.5 * n * a * ecc * abs(delta_w)

    return delta_t, delta_v


# ---------------------------------------------------------------------------
# Plane change maneuver
# ---------------------------------------------------------------------------

def plane_change_dv(k, a, delta_inc):
    """Compute delta-v for a simple inclination change on a circular orbit.

    Parameters
    ----------
    k : float  - Gravitational parameter (km^3/s^2)
    a : float  - Circular orbit radius (km)
    delta_inc : float - Inclination change (radians)

    Returns
    -------
    dv : float - Delta-v magnitude (km/s)
    """
    v = math.sqrt(k / a)
    return 2.0 * v * math.sin(abs(delta_inc) / 2.0)


# ---------------------------------------------------------------------------
# Mission budget: combined Hohmann + plane change
# ---------------------------------------------------------------------------

def mission_budget(k, r_i, r_f, delta_inc):
    """Compute delta-v budget for combined Hohmann + plane change.

    Evaluates two strategies:
    1. Plane change combined with departure burn
    2. Plane change combined with arrival burn

    Uses the velocity-triangle (law of cosines) for combined burns.

    Parameters
    ----------
    k : float  - Gravitational parameter (km^3/s^2)
    r_i : float - Initial circular orbit radius (km)
    r_f : float - Final circular orbit radius (km)
    delta_inc : float - Inclination change (radians)

    Returns
    -------
    dv_depart_total, dv_arrive_total : float
        Total delta-v for each strategy (km/s)
    """
    a_trans = (r_i + r_f) / 2.0

    v_i = math.sqrt(k / r_i)
    v_f = math.sqrt(k / r_f)
    v_trans_a = math.sqrt(2.0 * k / r_i - k / a_trans)
    v_trans_b = math.sqrt(2.0 * k / r_f - k / a_trans)

    cos_di = math.cos(abs(delta_inc))

    # Strategy 1: plane change combined with departure burn
    dv_a_combined = math.sqrt(
        v_trans_a ** 2 + v_i ** 2 - 2.0 * v_trans_a * v_i * cos_di
    )
    dv_b_pure = abs(v_f - v_trans_b)
    dv_depart_total = dv_a_combined + dv_b_pure

    # Strategy 2: plane change combined with arrival burn
    dv_a_pure = abs(v_trans_a - v_i)
    dv_b_combined = math.sqrt(
        v_trans_b ** 2 + v_f ** 2 - 2.0 * v_trans_b * v_f * cos_di
    )
    dv_arrive_total = dv_a_pure + dv_b_combined

    return dv_depart_total, dv_arrive_total
