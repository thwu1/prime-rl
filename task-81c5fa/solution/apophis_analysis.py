#!/usr/bin/env python3
"""
Apophis 2029 Earth Encounter Analysis

Queries the JPL Horizons API to analyze asteroid 99942 Apophis's close
flyby of Earth in April 2029.  Determines closest approach parameters,
models the hyperbolic encounter, computes pre/post orbital element
changes, and determines NEO class transition.
"""

import json
import math
import re
import sys
import time
import urllib.request
import urllib.parse

# ---------- Physical constants ----------
GM_EARTH = 398600.4418        # km^3/s^2
GM_SUN   = 1.32712440018e11   # km^3/s^2
AU_KM    = 1.495978707e8      # km per AU
GEO_R    = 42164.0            # geostationary orbit radius, km


# ---------- Horizons API ----------

def horizons_query(extra_params, retries=5):
    """Query the Horizons API. Returns the text result string."""
    params = {
        'format': 'json',
        'OBJ_DATA': "'NO'",
        'MAKE_EPHEM': "'YES'",
        'VEC_LABELS': "'YES'",
        'CSV_FORMAT': "'NO'",
    }
    for k, v in extra_params.items():
        if k == 'format':
            params[k] = v
        else:
            params[k] = f"'{v}'"

    url = ('https://ssd.jpl.nasa.gov/api/horizons.api?'
           + urllib.parse.urlencode(params, quote_via=urllib.parse.quote))

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                raw = resp.read().decode()
            data = json.loads(raw)
            result = data.get('result', '')
            if '$$SOE' in result:
                return result
            raise RuntimeError(f"No $$SOE in response: {result[:400]}")
        except Exception as exc:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
            else:
                raise RuntimeError(
                    f"Horizons query failed after {retries} attempts: {exc}")


def find_apophis_cmd():
    """Determine the correct COMMAND string for Apophis."""
    test_params_base = {
        'EPHEM_TYPE': 'VECTORS',
        'CENTER': '@399',
        'START_TIME': '2029-Apr-13 00:00',
        'STOP_TIME': '2029-Apr-13 01:00',
        'STEP_SIZE': '1 h',
        'REF_PLANE': 'ECLIPTIC',
        'REF_SYSTEM': 'ICRF',
        'VEC_TABLE': '2',
        'OUT_UNITS': 'KM-S',
    }
    for cmd in ['99942', 'DES=99942;', 'Apophis;', '2099942']:
        try:
            p = dict(test_params_base)
            p['COMMAND'] = cmd
            horizons_query(p, retries=2)
            print(f"  Using COMMAND='{cmd}' for Apophis")
            return cmd
        except Exception:
            continue
    raise RuntimeError("Cannot find Apophis in Horizons")


def geocentric_vectors(cmd, start, stop, step):
    """Query geocentric (Earth-centered) VECTORS for Apophis."""
    return horizons_query({
        'COMMAND': cmd,
        'EPHEM_TYPE': 'VECTORS',
        'CENTER': '@399',
        'START_TIME': start,
        'STOP_TIME': stop,
        'STEP_SIZE': step,
        'REF_PLANE': 'ECLIPTIC',
        'REF_SYSTEM': 'ICRF',
        'VEC_TABLE': '2',
        'OUT_UNITS': 'KM-S',
    })


def heliocentric_vectors(cmd, start, stop, step='1 d'):
    """Query heliocentric (Sun-centered) VECTORS for Apophis."""
    return horizons_query({
        'COMMAND': cmd,
        'EPHEM_TYPE': 'VECTORS',
        'CENTER': '@10',
        'START_TIME': start,
        'STOP_TIME': stop,
        'STEP_SIZE': step,
        'REF_PLANE': 'ECLIPTIC',
        'REF_SYSTEM': 'ICRF',
        'VEC_TABLE': '2',
        'OUT_UNITS': 'KM-S',
    })


# ---------- Parsing ----------

_NUM = r'([\-+]?[\d.]+(?:[Ee][\-+]?\d+)?)'


def parse_vectors(text):
    """Parse VECTORS output -> list of (jd, x, y, z, vx, vy, vz)."""
    block = text[text.index('$$SOE') + 5: text.index('$$EOE')].strip()
    results = []
    lines = block.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if '=' in line and 'A.D.' in line:
            jd = float(line.split('=')[0].strip())
            i += 1
            pos = lines[i].strip()
            x = float(re.search(r'X\s*=\s*' + _NUM, pos).group(1))
            y = float(re.search(r'Y\s*=\s*' + _NUM, pos).group(1))
            z = float(re.search(r'Z\s*=\s*' + _NUM, pos).group(1))
            i += 1
            vel = lines[i].strip()
            vx = float(re.search(r'VX\s*=\s*' + _NUM, vel).group(1))
            vy = float(re.search(r'VY\s*=\s*' + _NUM, vel).group(1))
            vz = float(re.search(r'VZ\s*=\s*' + _NUM, vel).group(1))
            results.append((jd, x, y, z, vx, vy, vz))
        i += 1
    return results


# ---------- Math helpers ----------

def vmag(x, y, z):
    return math.sqrt(x * x + y * y + z * z)


# ---------- Orbital mechanics ----------

def heliocentric_elements(state):
    """Compute (a_au, ecc) from a heliocentric state vector tuple.

    Uses vis-viva for semi-major axis and the orbit equation for
    eccentricity.
    """
    _, x, y, z, vx, vy, vz = state
    r = vmag(x, y, z)
    v = vmag(vx, vy, vz)
    # Specific orbital energy -> semi-major axis
    eps = v * v / 2.0 - GM_SUN / r
    a_km = -GM_SUN / (2.0 * eps)
    # Angular momentum magnitude
    hx = y * vz - z * vy
    hy = z * vx - x * vz
    hz = x * vy - y * vx
    h = vmag(hx, hy, hz)
    # Eccentricity from orbit equation: e^2 = 1 + 2*eps*h^2/mu^2
    ecc = math.sqrt(max(0.0, 1.0 + 2.0 * eps * h * h / (GM_SUN * GM_SUN)))
    return a_km / AU_KM, ecc


def classify_neo(a_au, ecc):
    """Classify NEO dynamical class from osculating elements."""
    q = a_au * (1.0 - ecc)
    big_q = a_au * (1.0 + ecc)
    if a_au < 1.0 and big_q < 0.983:
        return "Atira"
    elif a_au < 1.0 and big_q >= 0.983:
        return "Aten"
    elif a_au >= 1.0 and q < 1.017:
        return "Apollo"
    elif q >= 1.017 and q < 1.3:
        return "Amor"
    return "Other"


def orbital_period_days(a_au):
    """Orbital period in days from semi-major axis in AU (Kepler III)."""
    a_km = a_au * AU_KM
    return 2.0 * math.pi * math.sqrt(a_km ** 3 / GM_SUN) / 86400.0


# ---------- Main pipeline ----------

def main():
    print("=== Apophis 2029 Flyby Analysis ===\n")

    # --- Determine COMMAND format ---
    print("[1/5] Resolving Apophis identifier in Horizons...")
    cmd = find_apophis_cmd()

    # --- Coarse search: hourly, April 12-14 ---
    print("[2/5] Querying geocentric vectors (hourly, Apr 12-14 TDB)...")
    time.sleep(1)
    hourly_text = geocentric_vectors(
        cmd, '2029-Apr-12 00:00', '2029-Apr-14 00:00', '1 h')
    hourly = parse_vectors(hourly_text)
    print(f"      {len(hourly)} hourly epochs parsed")

    dists = [(s[0], vmag(s[1], s[2], s[3])) for s in hourly]
    min_i = min(range(len(dists)), key=lambda i: dists[i][1])
    approx_jd = dists[min_i][0]
    print(f"      Approx CA: JD {approx_jd:.4f}, dist {dists[min_i][1]:.0f} km")

    # --- Fine search: 1-minute, ±2 hours ---
    print("[3/5] Refining with 1-minute resolution (±2 h)...")
    time.sleep(1)
    fine_start = f'JD{approx_jd - 2.0 / 24.0}'
    fine_stop = f'JD{approx_jd + 2.0 / 24.0}'
    fine_text = geocentric_vectors(cmd, fine_start, fine_stop, '1 min')
    fine = parse_vectors(fine_text)
    print(f"      {len(fine)} fine epochs parsed")

    fine_dists = [(s[0], vmag(s[1], s[2], s[3])) for s in fine]
    min_fi = min(range(len(fine_dists)), key=lambda i: fine_dists[i][1])
    ca_state = fine[min_fi]

    ca_jd = ca_state[0]
    ca_dist = vmag(ca_state[1], ca_state[2], ca_state[3])
    ca_vrel = vmag(ca_state[4], ca_state[5], ca_state[6])

    print(f"      CA: JD {ca_jd:.6f}")
    print(f"      Distance: {ca_dist:.2f} km")
    print(f"      Relative velocity: {ca_vrel:.4f} km/s")

    # --- Hyperbolic flyby parameters ---
    print("[4/5] Computing hyperbolic flyby parameters...")
    v_inf_sq = ca_vrel ** 2 - 2.0 * GM_EARTH / ca_dist
    if v_inf_sq <= 0:
        print("      WARNING: v_inf^2 <= 0 — adjusting to small positive")
        v_inf_sq = 1e-6
    v_inf = math.sqrt(v_inf_sq)

    e_hyp = 1.0 + ca_dist * v_inf ** 2 / GM_EARTH
    defl_deg = math.degrees(2.0 * math.asin(1.0 / e_hyp))

    inside_geo = ca_dist < GEO_R

    print(f"      v_inf    = {v_inf:.4f} km/s")
    print(f"      e_hyp    = {e_hyp:.4f}")
    print(f"      defl     = {defl_deg:.4f} deg")
    print(f"      inside GEO: {inside_geo}")

    # --- Heliocentric orbital elements before/after ---
    print("[5/5] Computing heliocentric orbital elements (±7 days)...")
    jd_before = ca_jd - 7.0
    jd_after = ca_jd + 7.0

    time.sleep(1)
    before_text = heliocentric_vectors(
        cmd, f'JD{jd_before}', f'JD{jd_before + 0.5}')
    time.sleep(1)
    after_text = heliocentric_vectors(
        cmd, f'JD{jd_after}', f'JD{jd_after + 0.5}')

    before_data = parse_vectors(before_text)
    after_data = parse_vectors(after_text)

    a_before, e_before = heliocentric_elements(before_data[0])
    a_after, e_after = heliocentric_elements(after_data[0])

    p_before = orbital_period_days(a_before)
    p_after = orbital_period_days(a_after)

    cls_before = classify_neo(a_before, e_before)
    cls_after = classify_neo(a_after, e_after)

    print(f"      Before (JD {jd_before:.2f}): a={a_before:.6f} AU, "
          f"e={e_before:.6f}, P={p_before:.2f} d, class={cls_before}")
    print(f"      After  (JD {jd_after:.2f}):  a={a_after:.6f} AU, "
          f"e={e_after:.6f}, P={p_after:.2f} d, class={cls_after}")

    # --- Write results ---
    results = {
        "closest_approach_jd_tdb": round(ca_jd, 6),
        "closest_approach_distance_km": round(ca_dist, 2),
        "relative_velocity_km_s": round(ca_vrel, 6),
        "inside_geostationary": inside_geo,
        "v_infinity_km_s": round(v_inf, 6),
        "hyperbolic_eccentricity": round(e_hyp, 6),
        "deflection_angle_deg": round(defl_deg, 6),
        "semi_major_axis_before_au": round(a_before, 8),
        "semi_major_axis_after_au": round(a_after, 8),
        "eccentricity_before": round(e_before, 8),
        "eccentricity_after": round(e_after, 8),
        "period_before_days": round(p_before, 4),
        "period_after_days": round(p_after, 4),
        "neo_class_before": cls_before,
        "neo_class_after": cls_after,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n=== Results written to /app/results.json ===")
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
