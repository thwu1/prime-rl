#!/usr/bin/env python3
"""Self-contained astrodynamics library.

All units: km, km/s, seconds, radians.
No external astrodynamics packages — only numpy and scipy.
"""
import numpy as np
from datetime import datetime
from scipy.integrate import solve_ivp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rotation_matrix(angle, axis):
    """Standard CCW rotation matrix around axis (0=x, 2=z)."""
    c, s = np.cos(angle), np.sin(angle)
    if axis == 0:
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=float)
    elif axis == 2:
        return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=float)
    raise ValueError(f"Unsupported axis {axis}")


def _hyp2f1b(x, tol=1e-15, maxiter=200):
    """Gauss hypergeometric 2F1(3, 1, 5/2, x) via power series."""
    result = 1.0
    term = 1.0
    for n in range(maxiter):
        term *= (2 * n + 6) / (2 * n + 5) * x
        result += term
        if abs(term) < tol * max(abs(result), 1.0):
            break
    return result


# ---------------------------------------------------------------------------
# State vector <-> Classical orbital elements
# ---------------------------------------------------------------------------

def rv2coe(mu, r, v):
    """State vector to classical orbital elements.

    Returns (p, ecc, inc, raan, argp, nu).
    """
    r = np.asarray(r, dtype=float)
    v = np.asarray(v, dtype=float)

    h = np.cross(r, v)
    n = np.cross([0.0, 0.0, 1.0], h)

    r_mag = np.linalg.norm(r)
    v_sq = np.dot(v, v)
    h_mag = np.linalg.norm(h)

    e_vec = ((v_sq - mu / r_mag) * r - np.dot(r, v) * v) / mu
    ecc = np.linalg.norm(e_vec)
    p = h_mag ** 2 / mu
    inc = np.arccos(np.clip(h[2] / h_mag, -1.0, 1.0))

    tol = 1e-8
    circular = ecc < tol
    equatorial = abs(inc) < tol

    if equatorial and not circular:
        raan = 0.0
        argp = np.arctan2(e_vec[1], e_vec[0]) % (2 * np.pi)
        nu = np.arctan2(
            np.dot(h, np.cross(e_vec, r)) / h_mag, np.dot(r, e_vec)
        )
    elif not equatorial and circular:
        raan = np.arctan2(n[1], n[0]) % (2 * np.pi)
        argp = 0.0
        nu = np.arctan2(
            np.dot(r, np.cross(h, n)) / h_mag, np.dot(r, n)
        )
    elif equatorial and circular:
        raan = 0.0
        argp = 0.0
        nu = np.arctan2(r[1], r[0]) % (2 * np.pi)
    else:
        a = p / (1 - ecc ** 2)
        ka = mu * a
        if a > 0:
            e_se = np.dot(r, v) / np.sqrt(ka)
            e_ce = r_mag * v_sq / mu - 1
            E = np.arctan2(e_se, e_ce)
            nu = 2 * np.arctan2(
                np.sqrt(1 + ecc) * np.sin(E / 2),
                np.sqrt(1 - ecc) * np.cos(E / 2),
            )
        else:
            e_sh = np.dot(r, v) / np.sqrt(-ka)
            e_ch = r_mag * v_sq / mu - 1
            F = np.log((e_ch + e_sh) / (e_ch - e_sh)) / 2
            nu = 2 * np.arctan(
                np.sqrt((ecc + 1) / (ecc - 1)) * np.tanh(F / 2)
            )
        raan = np.arctan2(n[1], n[0]) % (2 * np.pi)
        px = np.dot(r, n)
        py = np.dot(r, np.cross(h, n)) / h_mag
        argp = (np.arctan2(py, px) - nu) % (2 * np.pi)

    nu = (nu + np.pi) % (2 * np.pi) - np.pi
    return p, ecc, inc, raan, argp, nu


def coe2rv(mu, p, ecc, inc, raan, argp, nu):
    """Classical orbital elements to state vector.

    Returns (r_array, v_array).
    """
    r_mag = p / (1 + ecc * np.cos(nu))
    r_pf = r_mag * np.array([np.cos(nu), np.sin(nu), 0.0])
    v_pf = np.sqrt(mu / p) * np.array([-np.sin(nu), ecc + np.cos(nu), 0.0])

    Q = (
        _rotation_matrix(raan, 2)
        @ _rotation_matrix(inc, 0)
        @ _rotation_matrix(argp, 2)
    )
    return Q @ r_pf, Q @ v_pf


# ---------------------------------------------------------------------------
# Cowell propagation
# ---------------------------------------------------------------------------

def propagate_cowell(mu, r0, v0, tof, perturbation=None, rtol=1e-12):
    """Cowell formulation numerical propagation.

    Returns (rf, vf).
    """
    r0 = np.asarray(r0, dtype=float)
    v0 = np.asarray(v0, dtype=float)
    y0 = np.concatenate([r0, v0])

    def eom(t, y):
        rv = y[:3]
        vv = y[3:]
        r_mag = np.linalg.norm(rv)
        a_grav = -mu / r_mag ** 3 * rv
        if perturbation is not None:
            a_pert = np.asarray(perturbation(t, y, mu), dtype=float)
            return np.concatenate([vv, a_grav + a_pert])
        return np.concatenate([vv, a_grav])

    sol = solve_ivp(
        eom,
        [0.0, tof],
        y0,
        method="DOP853",
        rtol=rtol,
        atol=rtol * 1e-3,
        dense_output=False,
    )
    if not sol.success:
        raise RuntimeError(f"Integration failed: {sol.message}")

    return sol.y[:3, -1].copy(), sol.y[3:, -1].copy()


# ---------------------------------------------------------------------------
# Lambert solver (Izzo algorithm internals)
# ---------------------------------------------------------------------------

def _compute_y(x, ll):
    return np.sqrt(1 - ll ** 2 * (1 - x ** 2))


def _compute_psi(x, y, ll):
    if -1 <= x < 1:
        return np.arccos(np.clip(x * y + ll * (1 - x ** 2), -1.0, 1.0))
    elif x > 1:
        return np.arcsinh((y - x * ll) * np.sqrt(x ** 2 - 1))
    return 0.0


def _tof_equation_y(x, y, T0, ll, M):
    if M == 0 and np.sqrt(0.6) < x < np.sqrt(1.4):
        eta = y - ll * x
        S_1 = (1 - ll - x * eta) * 0.5
        Q = 4.0 / 3.0 * _hyp2f1b(S_1)
        T_ = (eta ** 3 * Q + 4 * ll * eta) * 0.5
    else:
        psi = _compute_psi(x, y, ll)
        T_ = (
            (psi + M * np.pi) / np.sqrt(np.abs(1 - x ** 2)) - x + ll * y
        ) / (1 - x ** 2)
    return T_ - T0


def _tof_equation(x, T0, ll, M):
    return _tof_equation_y(x, _compute_y(x, ll), T0, ll, M)


def _tof_equation_p(x, y, T, ll):
    return (3 * T * x - 2 + 2 * ll ** 3 * x / y) / (1 - x ** 2)


def _tof_equation_p2(x, y, T, dT, ll):
    return (
        3 * T + 5 * x * dT + 2 * (1 - ll ** 2) * ll ** 3 / y ** 3
    ) / (1 - x ** 2)


def _tof_equation_p3(x, y, _, dT, ddT, ll):
    return (
        7 * x * ddT + 8 * dT - 6 * (1 - ll ** 2) * ll ** 5 * x / y ** 5
    ) / (1 - x ** 2)


def _compute_T_min(ll, M, numiter, rtol):
    if ll == 1:
        x_T_min = 0.0
        T_min = _tof_equation(x_T_min, 0.0, ll, M)
    else:
        if M == 0:
            x_T_min = np.inf
            T_min = 0.0
        else:
            x_i = 0.1
            T_i = _tof_equation(x_i, 0.0, ll, M)
            x_T_min = _halley(x_i, T_i, ll, rtol, numiter)
            T_min = _tof_equation(x_T_min, 0.0, ll, M)
    return x_T_min, T_min


def _initial_guess(T, ll, M, lowpath):
    if M == 0:
        T_0 = np.arccos(ll) + ll * np.sqrt(1 - ll ** 2) + M * np.pi
        T_1 = 2 * (1 - ll ** 3) / 3
        if T >= T_0:
            return (T_0 / T) ** (2.0 / 3.0) - 1
        elif T < T_1:
            return 5.0 / 2.0 * T_1 / T * (T_1 - T) / (1 - ll ** 5) + 1
        else:
            return (
                np.exp(np.log(2) * np.log(T / T_0) / np.log(T_1 / T_0)) - 1
            )
    else:
        x_0l = (((M * np.pi + np.pi) / (8 * T)) ** (2.0 / 3.0) - 1) / (
            ((M * np.pi + np.pi) / (8 * T)) ** (2.0 / 3.0) + 1
        )
        x_0r = (((8 * T) / (M * np.pi)) ** (2.0 / 3.0) - 1) / (
            ((8 * T) / (M * np.pi)) ** (2.0 / 3.0) + 1
        )
        return max(x_0l, x_0r) if lowpath else min(x_0l, x_0r)


def _halley(p0, T0, ll, tol, maxiter):
    for _ in range(maxiter):
        y = _compute_y(p0, ll)
        fder = _tof_equation_p(p0, y, T0, ll)
        fder2 = _tof_equation_p2(p0, y, T0, fder, ll)
        if fder2 == 0:
            raise RuntimeError("Halley: zero second derivative")
        fder3 = _tof_equation_p3(p0, y, T0, fder, fder2, ll)
        p = p0 - 2 * fder * fder2 / (2 * fder2 ** 2 - fder * fder3)
        if abs(p - p0) < tol:
            return p
        p0 = p
    raise RuntimeError("Halley: failed to converge")


def _householder(p0, T0, ll, M, tol, maxiter):
    for _ in range(maxiter):
        y = _compute_y(p0, ll)
        fval = _tof_equation_y(p0, y, T0, ll, M)
        T = fval + T0
        fder = _tof_equation_p(p0, y, T, ll)
        fder2 = _tof_equation_p2(p0, y, T, fder, ll)
        fder3 = _tof_equation_p3(p0, y, T, fder, fder2, ll)
        p = p0 - fval * (
            (fder ** 2 - fval * fder2 / 2)
            / (fder * (fder ** 2 - fval * fder2) + fder3 * fval ** 2 / 6)
        )
        if abs(p - p0) < tol:
            return p
        p0 = p
    raise RuntimeError("Householder: failed to converge")


def _find_xy(ll, T, M, numiter, lowpath, rtol):
    assert abs(ll) < 1
    assert T > 0

    M_max = int(np.floor(T / np.pi))
    T_00 = np.arccos(ll) + ll * np.sqrt(1 - ll ** 2)

    if T < T_00 + M_max * np.pi and M_max > 0:
        _, T_min = _compute_T_min(ll, M_max, numiter, rtol)
        if T < T_min:
            M_max -= 1

    if M > M_max:
        raise ValueError("No feasible solution, try lower M")

    x_0 = _initial_guess(T, ll, M, lowpath)
    x = _householder(x_0, T, ll, M, rtol, numiter)
    y = _compute_y(x, ll)
    return x, y


# ---------------------------------------------------------------------------
# Lambert solver (public)
# ---------------------------------------------------------------------------

def lambert_solve(mu, r1, r2, tof, M=0, prograde=True):
    """Solve Lambert's problem.

    Returns list of (v1, v2) tuples.
    """
    r1 = np.asarray(r1, dtype=float)
    r2 = np.asarray(r2, dtype=float)
    assert tof > 0 and mu > 0

    cross_prod = np.cross(r1, r2)
    if not np.any(cross_prod):
        raise ValueError("Collinear vectors")

    c = r2 - r1
    c_norm = np.linalg.norm(c)
    r1_norm = np.linalg.norm(r1)
    r2_norm = np.linalg.norm(r2)
    s = (r1_norm + r2_norm + c_norm) * 0.5

    i_r1 = r1 / r1_norm
    i_r2 = r2 / r2_norm
    i_h = cross_prod / np.linalg.norm(cross_prod)

    ll = np.sqrt(1 - min(1.0, c_norm / s))

    if i_h[2] < 0:
        ll = -ll
        i_t1 = np.cross(i_r1, i_h)
        i_t2 = np.cross(i_r2, i_h)
    else:
        i_t1 = np.cross(i_h, i_r1)
        i_t2 = np.cross(i_h, i_r2)

    if not prograde:
        ll = -ll
        i_t1 = -i_t1
        i_t2 = -i_t2

    T = np.sqrt(2 * mu / s ** 3) * tof

    gamma = np.sqrt(mu * s / 2)
    rho = (r1_norm - r2_norm) / c_norm
    sigma = np.sqrt(1 - rho ** 2)

    results = []

    def _reconstruct(x, y):
        V_r1 = gamma * ((ll * y - x) - rho * (ll * y + x)) / r1_norm
        V_r2 = -gamma * ((ll * y - x) + rho * (ll * y + x)) / r2_norm
        V_t1 = gamma * sigma * (y + ll * x) / r1_norm
        V_t2 = gamma * sigma * (y + ll * x) / r2_norm
        v1 = V_r1 * i_r1 + V_t1 * i_t1
        v2 = V_r2 * i_r2 + V_t2 * i_t2
        return v1, v2

    if M == 0:
        x, y = _find_xy(ll, T, M, 35, True, 1e-8)
        results.append(_reconstruct(x, y))
    else:
        for lowpath in [True, False]:
            try:
                x, y = _find_xy(ll, T, M, 35, lowpath, 1e-8)
                results.append(_reconstruct(x, y))
            except (ValueError, RuntimeError):
                pass

    return results


# ---------------------------------------------------------------------------
# Hohmann transfer
# ---------------------------------------------------------------------------

def hohmann_transfer(mu, r_i, r_f):
    """Hohmann transfer between coplanar circular orbits.

    Returns (delta_v1, delta_v2, tof).
    """
    v_i = np.sqrt(mu / r_i)
    v_f = np.sqrt(mu / r_f)
    a_t = (r_i + r_f) / 2
    v_t_dep = np.sqrt(mu * (2 / r_i - 1 / a_t))
    v_t_arr = np.sqrt(mu * (2 / r_f - 1 / a_t))
    dv1 = abs(v_t_dep - v_i)
    dv2 = abs(v_f - v_t_arr)
    tof = np.pi * np.sqrt(a_t ** 3 / mu)
    return dv1, dv2, tof


# ---------------------------------------------------------------------------
# J2 perturbation
# ---------------------------------------------------------------------------

def j2_perturbation(t, state, mu, J2, R):
    """J2 oblateness perturbation acceleration [ax, ay, az]."""
    state = np.asarray(state, dtype=float)
    r_vec = state[:3]
    r = np.linalg.norm(r_vec)
    factor = 1.5 * mu * J2 * R ** 2 / r ** 5
    z2_r2 = r_vec[2] ** 2 / r ** 2
    return factor * r_vec * np.array(
        [5 * z2_r2 - 1, 5 * z2_r2 - 1, 5 * z2_r2 - 3]
    )


# ---------------------------------------------------------------------------
# CCSDS OEM parser
# ---------------------------------------------------------------------------

def _iso_to_seconds(iso_str):
    """Convert ISO 8601 datetime string to seconds from a reference."""
    # Handle optional milliseconds
    if '.' in iso_str:
        dt = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%S.%f")
    else:
        dt = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%S")
    ref = datetime(2000, 1, 1)
    return (dt - ref).total_seconds()


def parse_oem(filepath):
    """Parse a CCSDS Orbit Ephemeris Message file.

    Returns list of dicts with keys: epoch_s, x, y, z, vx, vy, vz.
    epoch_s is seconds from the first data epoch.
    """
    entries = []
    in_data = False
    first_epoch = None

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('COMMENT'):
                continue
            if line == 'META_STOP':
                in_data = True
                continue
            if line == 'META_START':
                in_data = False
                continue
            if not in_data:
                continue
            # Skip any header-style lines in data block
            if '=' in line:
                continue
            parts = line.split()
            if len(parts) >= 7:
                epoch_str = parts[0]
                epoch_abs = _iso_to_seconds(epoch_str)
                if first_epoch is None:
                    first_epoch = epoch_abs
                entries.append({
                    "epoch_s": epoch_abs - first_epoch,
                    "x": float(parts[1]),
                    "y": float(parts[2]),
                    "z": float(parts[3]),
                    "vx": float(parts[4]),
                    "vy": float(parts[5]),
                    "vz": float(parts[6]),
                })

    return entries
