#!/usr/bin/env python3
"""
Earth-Mars transfer trajectory design for the 2033 launch window.

Queries JPL Horizons for ephemeris data, solves Lambert's boundary-value
problem across a departure/arrival grid, and finds the minimum-delta-v
Type I transfer.
"""

import json
import math
import sys
import time

import numpy as np
import requests

# ── Physical constants ──
MU_SUN = 1.32712440041279419e11   # km^3/s^2
MU_EARTH = 3.986004418e5          # km^3/s^2
MU_MARS = 4.282837e4              # km^3/s^2
R_EARTH = 6371.0                  # km
R_MARS = 3389.5                   # km
R_PARK_EARTH = R_EARTH + 200.0    # 200 km LEO
R_PARK_MARS = R_MARS + 300.0      # 300 km LMO
AU_KM = 149597870.7


# ── Time utilities ──

def date_to_jd(y, m, d):
    """Calendar date to Julian Date (noon UT)."""
    if m <= 2:
        y -= 1
        m += 12
    A = int(y / 100)
    B = 2 - A + int(A / 4)
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + B - 1524.5


def jd_to_cal(jd):
    """Julian Date to YYYY-MM-DD string."""
    jd2 = jd + 0.5
    Z = int(jd2)
    F = jd2 - Z
    if Z < 2299161:
        A = Z
    else:
        alpha = int((Z - 1867216.25) / 36524.25)
        A = Z + 1 + alpha - int(alpha / 4)
    B = A + 1524
    C = int((B - 122.1) / 365.25)
    D = int(365.25 * C)
    E = int((B - D) / 30.6001)
    day = B - D - int(30.6001 * E) + F
    month = E - 1 if E < 14 else E - 13
    year = C - 4716 if month > 2 else C - 4715
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


# ── Horizons API ──

def query_horizons_vectors(body_id, start_date, stop_date, step='5d'):
    """Fetch heliocentric ecliptic J2000 state vectors from Horizons.

    Returns list of dicts with 'jd', 'r' (km), 'v' (km/s).
    """
    url = 'https://ssd.jpl.nasa.gov/api/horizons.api'
    params = {
        'format': 'json',
        'COMMAND': f"'{body_id}'",
        'OBJ_DATA': "'NO'",
        'MAKE_EPHEM': "'YES'",
        'EPHEM_TYPE': "'VECTORS'",
        'CENTER': "'500@10'",
        'START_TIME': f"'{start_date}'",
        'STOP_TIME': f"'{stop_date}'",
        'STEP_SIZE': f"'{step}'",
        'VEC_TABLE': "'2'",
        'REF_PLANE': "'ECLIPTIC'",
        'REF_SYSTEM': "'J2000'",
        'OUT_UNITS': "'KM-S'",
        'CSV_FORMAT': "'YES'",
        'VEC_LABELS': "'NO'",
    }

    for attempt in range(5):
        try:
            resp = requests.get(url, params=params, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:
            if attempt < 4:
                time.sleep(3 * (attempt + 1))
            else:
                raise RuntimeError(f"Horizons query failed: {exc}")

    result = data['result']
    soe = result.index('$$SOE') + len('$$SOE')
    eoe = result.index('$$EOE')
    lines = result[soe:eoe].strip().split('\n')

    states = []
    for line in lines:
        line = line.strip().rstrip(',')
        if not line:
            continue
        parts = [p.strip() for p in line.split(',') if p.strip()]
        if len(parts) < 8:
            continue
        try:
            jd = float(parts[0])
            r = np.array([float(parts[2]), float(parts[3]), float(parts[4])])
            v = np.array([float(parts[5]), float(parts[6]), float(parts[7])])
            states.append({'jd': jd, 'r': r, 'v': v})
        except (ValueError, IndexError):
            continue

    return states


# ── Stumpff functions ──

def stumpff_C(z):
    if z > 1e-6:
        return (1.0 - math.cos(math.sqrt(z))) / z
    elif z < -1e-6:
        return (1.0 - math.cosh(math.sqrt(-z))) / z
    else:
        return 0.5 - z / 24.0 + z ** 2 / 720.0 - z ** 3 / 40320.0


def stumpff_S(z):
    if z > 1e-6:
        sz = math.sqrt(z)
        return (sz - math.sin(sz)) / (z * sz)
    elif z < -1e-6:
        sz = math.sqrt(-z)
        return (math.sinh(sz) - sz) / ((-z) * sz)
    else:
        return 1.0 / 6.0 - z / 120.0 + z ** 2 / 5040.0 - z ** 3 / 362880.0


# ── Lambert solver ──

def lambert_solve(r1_vec, r2_vec, tof_sec, mu, prograde=True):
    """Solve Lambert's problem using universal variables with Stumpff functions.

    Returns (v1, v2) velocity vectors [km/s].
    Raises ValueError on failure.
    """
    r1 = np.linalg.norm(r1_vec)
    r2 = np.linalg.norm(r2_vec)

    cos_dnu = np.dot(r1_vec, r2_vec) / (r1 * r2)
    cos_dnu = float(np.clip(cos_dnu, -1.0, 1.0))

    # Transfer angle direction from z-component of cross product
    cross_z = float(r1_vec[0] * r2_vec[1] - r1_vec[1] * r2_vec[0])

    if prograde:
        dnu = math.acos(cos_dnu) if cross_z >= 0 else 2 * math.pi - math.acos(cos_dnu)
    else:
        dnu = math.acos(cos_dnu) if cross_z < 0 else 2 * math.pi - math.acos(cos_dnu)

    # Only Type I
    if dnu > math.pi:
        raise ValueError("Type II transfer")

    sin_dnu = math.sin(dnu)
    if abs(sin_dnu) < 1e-12:
        raise ValueError("Degenerate 0/180 degree transfer")

    A = sin_dnu * math.sqrt(r1 * r2 / (1.0 - cos_dnu))
    if abs(A) < 1e-14:
        raise ValueError("Degenerate geometry")

    # Newton-Raphson iteration for z
    z = 0.0
    converged = False

    for iteration in range(1000):
        C = stumpff_C(z)
        S = stumpff_S(z)
        if C <= 0:
            z += 0.5
            continue

        y = r1 + r2 + A * (z * S - 1.0) / math.sqrt(C)
        if y < 0:
            z += 0.5
            continue

        chi = math.sqrt(y / C)
        F = chi ** 3 * S + A * math.sqrt(y) - math.sqrt(mu) * tof_sec

        if abs(F) < 1e-8:
            converged = True
            break

        # Numerical derivative
        h = max(1e-7, abs(z) * 1e-7)
        C_p = stumpff_C(z + h)
        S_p = stumpff_S(z + h)
        C_m = stumpff_C(z - h)
        S_m = stumpff_S(z - h)

        Fp = Fm = None
        if C_p > 0 and C_m > 0:
            yp = r1 + r2 + A * ((z + h) * S_p - 1.0) / math.sqrt(C_p)
            ym = r1 + r2 + A * ((z - h) * S_m - 1.0) / math.sqrt(C_m)
            if yp > 0 and ym > 0:
                chip = math.sqrt(yp / C_p)
                chim = math.sqrt(ym / C_m)
                Fp = chip ** 3 * S_p + A * math.sqrt(yp) - math.sqrt(mu) * tof_sec
                Fm = chim ** 3 * S_m + A * math.sqrt(ym) - math.sqrt(mu) * tof_sec

        if Fp is not None and Fm is not None:
            dFdz = (Fp - Fm) / (2 * h)
            if abs(dFdz) > 1e-14:
                step = F / dFdz
                if abs(step) > 10.0:
                    step = 10.0 * (1 if step > 0 else -1)
                z -= step
            else:
                z += 0.1
        else:
            z += 0.5

    if not converged:
        raise ValueError("Lambert solver did not converge")

    # Final Lagrange coefficients
    C = stumpff_C(z)
    S = stumpff_S(z)
    y = r1 + r2 + A * (z * S - 1.0) / math.sqrt(C)

    f = 1.0 - y / r1
    g = A * math.sqrt(y / mu)
    gdot = 1.0 - y / r2

    v1 = (r2_vec - f * r1_vec) / g
    v2 = (gdot * r2_vec - r1_vec) / g

    return v1, v2


# ── Orbital elements ──

def state_to_elements(r_vec, v_vec, mu):
    """State vector to Keplerian elements."""
    r = np.linalg.norm(r_vec)
    v = np.linalg.norm(v_vec)

    h_vec = np.cross(r_vec, v_vec)
    h = np.linalg.norm(h_vec)

    n_vec = np.cross(np.array([0.0, 0.0, 1.0]), h_vec)
    n = np.linalg.norm(n_vec)

    e_vec = ((v ** 2 - mu / r) * r_vec - np.dot(r_vec, v_vec) * v_vec) / mu
    e = np.linalg.norm(e_vec)

    energy = v ** 2 / 2 - mu / r
    a = -mu / (2 * energy) if abs(1.0 - e) > 1e-10 else float('inf')

    inc = math.acos(np.clip(h_vec[2] / h, -1, 1))

    if n > 1e-10:
        raan = math.acos(np.clip(n_vec[0] / n, -1, 1))
        if n_vec[1] < 0:
            raan = 2 * math.pi - raan
    else:
        raan = 0.0

    if n > 1e-10 and e > 1e-10:
        argp = math.acos(np.clip(np.dot(n_vec, e_vec) / (n * e), -1, 1))
        if e_vec[2] < 0:
            argp = 2 * math.pi - argp
    else:
        argp = 0.0

    return {
        'a': a,
        'e': e,
        'i': math.degrees(inc),
        'raan': math.degrees(raan),
        'argp': math.degrees(argp),
    }


# ── Delta-v ──

def dv_from_parking(vinf, mu_body, r_park):
    """Delta-v for hyperbolic departure from / capture into circular orbit."""
    v_circ = math.sqrt(mu_body / r_park)
    v_hyp = math.sqrt(vinf ** 2 + 2 * mu_body / r_park)
    return v_hyp - v_circ


# ── Main ──

def main():
    print("=" * 60)
    print("Earth-Mars Transfer Trajectory Design — 2033 Window")
    print("=" * 60)

    step = '5d'

    # Query Horizons
    print("\n[1/4] Querying Earth ephemeris...")
    earth = query_horizons_vectors('399', '2033-04-01', '2033-09-30', step)
    print(f"      {len(earth)} Earth states")

    time.sleep(1)

    print("[2/4] Querying Mars ephemeris...")
    mars = query_horizons_vectors('499', '2033-08-01', '2034-07-31', step)
    print(f"      {len(mars)} Mars states")

    if not earth or not mars:
        print("ERROR: empty ephemeris data")
        sys.exit(1)

    earth_by_jd = {s['jd']: s for s in earth}
    mars_by_jd = {s['jd']: s for s in mars}
    dep_jds = sorted(earth_by_jd.keys())
    arr_jds = sorted(mars_by_jd.keys())

    TOF_MIN = 120.0
    TOF_MAX = 400.0

    print(f"\n[3/4] Grid search: {len(dep_jds)} dep × {len(arr_jds)} arr")
    print(f"      TOF range: {TOF_MIN}–{TOF_MAX} days")

    results = []
    n_failed = 0

    for dep_jd in dep_jds:
        e_state = earth_by_jd[dep_jd]
        r1 = e_state['r']
        v_earth = e_state['v']

        for arr_jd in arr_jds:
            tof_days = arr_jd - dep_jd
            if tof_days < TOF_MIN or tof_days > TOF_MAX:
                continue

            m_state = mars_by_jd[arr_jd]
            r2 = m_state['r']
            v_mars = m_state['v']

            tof_sec = tof_days * 86400.0

            try:
                v1, v2 = lambert_solve(r1, r2, tof_sec, MU_SUN, prograde=True)
            except ValueError:
                n_failed += 1
                continue

            vinf_dep_vec = v1 - v_earth
            vinf_arr_vec = v2 - v_mars
            vinf_dep = float(np.linalg.norm(vinf_dep_vec))
            vinf_arr = float(np.linalg.norm(vinf_arr_vec))

            c3 = vinf_dep ** 2
            dv_dep = dv_from_parking(vinf_dep, MU_EARTH, R_PARK_EARTH)
            dv_arr = dv_from_parking(vinf_arr, MU_MARS, R_PARK_MARS)
            dv_total = dv_dep + dv_arr

            results.append({
                'dep_jd': dep_jd, 'arr_jd': arr_jd,
                'tof_days': tof_days, 'c3': c3,
                'vinf_dep': vinf_dep, 'vinf_arr': vinf_arr,
                'dv_dep': dv_dep, 'dv_arr': dv_arr, 'dv_total': dv_total,
                'r1': r1.tolist(), 'v1': v1.tolist(),
                'r2': r2.tolist(), 'v2': v2.tolist(),
                'v_earth': v_earth.tolist(), 'v_mars': v_mars.tolist(),
            })

    if not results:
        print("ERROR: no valid trajectories found")
        sys.exit(1)

    results.sort(key=lambda x: x['dv_total'])
    optimal = results[0]
    top5 = results[:5]

    print(f"\n      {len(results)} converged, {n_failed} failed")
    print(f"\n[4/4] Optimal trajectory:")
    print(f"      Departure: JD {optimal['dep_jd']:.1f} ({jd_to_cal(optimal['dep_jd'])})")
    print(f"      Arrival:   JD {optimal['arr_jd']:.1f} ({jd_to_cal(optimal['arr_jd'])})")
    print(f"      TOF:       {optimal['tof_days']:.1f} days")
    print(f"      C3:        {optimal['c3']:.3f} km²/s²")
    print(f"      Δv_dep:    {optimal['dv_dep']:.4f} km/s")
    print(f"      Δv_arr:    {optimal['dv_arr']:.4f} km/s")
    print(f"      Δv_total:  {optimal['dv_total']:.4f} km/s")

    # Build output
    def fmt(res):
        elems = state_to_elements(np.array(res['r1']),
                                  np.array(res['v1']), MU_SUN)
        return {
            'departure_date_jd': res['dep_jd'],
            'arrival_date_jd': res['arr_jd'],
            'departure_date_cal': jd_to_cal(res['dep_jd']),
            'arrival_date_cal': jd_to_cal(res['arr_jd']),
            'tof_days': res['tof_days'],
            'c3_km2s2': res['c3'],
            'vinf_dep_kms': res['vinf_dep'],
            'vinf_arr_kms': res['vinf_arr'],
            'dv_dep_kms': res['dv_dep'],
            'dv_arr_kms': res['dv_arr'],
            'dv_total_kms': res['dv_total'],
            'transfer_a_km': elems['a'],
            'transfer_e': elems['e'],
            'transfer_i_deg': elems['i'],
            'transfer_raan_deg': elems['raan'],
            'transfer_argp_deg': elems['argp'],
            'r1_km': res['r1'],
            'v1_kms': res['v1'],
            'r2_km': res['r2'],
            'v2_kms': res['v2'],
            'v_earth_kms': res['v_earth'],
            'v_mars_kms': res['v_mars'],
        }

    output = {
        'optimal': fmt(optimal),
        'top5': [fmt(r) for r in top5],
        'search_grid': {
            'dep_start_jd': dep_jds[0],
            'dep_end_jd': dep_jds[-1],
            'arr_start_jd': arr_jds[0],
            'arr_end_jd': arr_jds[-1],
            'dep_step_days': 5,
            'arr_step_days': 5,
            'n_dep': len(dep_jds),
            'n_arr': len(arr_jds),
            'n_converged': len(results),
        },
        'constants': {
            'mu_sun_km3s2': MU_SUN,
            'mu_earth_km3s2': MU_EARTH,
            'mu_mars_km3s2': MU_MARS,
            'r_park_earth_km': R_PARK_EARTH,
            'r_park_mars_km': R_PARK_MARS,
        },
    }

    with open('/app/trajectory.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nResults written to /app/trajectory.json")


if __name__ == '__main__':
    main()
