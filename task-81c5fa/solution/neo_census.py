#!/usr/bin/env python3
"""
NEO Orbit Census — compute osculating orbital elements for 5 near-Earth
asteroids from JPL Horizons heliocentric state vectors.
"""

import json
import math
import re
import sys
import time
import urllib.request
import urllib.parse

# ---------- Physical constants ----------
GM_SUN = 1.32712440018e11   # km^3/s^2
AU_KM = 1.495978707e8       # km per AU

EPOCH_STR = '2024-Jun-15 00:00'
EPOCH_JD = 2460477.5
ASTEROIDS = [433, 1566, 3200, 25143, 101955]
JUPITER_ID = '599'


# ---------- Horizons API ----------

def horizons_query(extra_params, retries=5):
    """Query the Horizons API. Returns the text result string."""
    params = {
        'format': 'json',
        'OBJ_DATA': "'NO'",
        'MAKE_EPHEM': "'YES'",
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
            raise RuntimeError(f"No $$SOE: {result[:400]}")
        except Exception as exc:
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
            else:
                raise RuntimeError(
                    f"Horizons query failed after {retries} attempts: {exc}")


def find_body_cmd(body_id):
    """Determine the correct COMMAND string for a body."""
    test_base = {
        'EPHEM_TYPE': 'VECTORS', 'CENTER': '@10',
        'START_TIME': EPOCH_STR, 'STOP_TIME': '2024-Jun-15 01:00',
        'STEP_SIZE': '1 h', 'REF_PLANE': 'ECLIPTIC', 'REF_SYSTEM': 'ICRF',
        'VEC_TABLE': '2', 'VEC_LABELS': 'YES', 'OUT_UNITS': 'KM-S',
    }
    for cmd in [str(body_id), f'DES={body_id};', f'{body_id};']:
        try:
            p = dict(test_base)
            p['COMMAND'] = cmd
            horizons_query(p, retries=2)
            return cmd
        except Exception:
            time.sleep(1)
            continue
    raise RuntimeError(f"Cannot resolve body {body_id} in Horizons")


def query_heliocentric_vectors(cmd):
    """Query heliocentric state vectors at the epoch."""
    return horizons_query({
        'COMMAND': cmd,
        'EPHEM_TYPE': 'VECTORS',
        'CENTER': '@10',
        'START_TIME': EPOCH_STR,
        'STOP_TIME': '2024-Jun-15 01:00',
        'STEP_SIZE': '1 h',
        'REF_PLANE': 'ECLIPTIC',
        'REF_SYSTEM': 'ICRF',
        'VEC_TABLE': '2',
        'VEC_LABELS': 'YES',
        'CSV_FORMAT': 'NO',
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


# ---------- Vector math ----------

def vmag(x, y, z):
    return math.sqrt(x * x + y * y + z * z)


def cross(a, b):
    return (a[1]*b[2] - a[2]*b[1],
            a[2]*b[0] - a[0]*b[2],
            a[0]*b[1] - a[1]*b[0])


def dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def scale(s, v):
    return (s*v[0], s*v[1], s*v[2])


def vsub(a, b):
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])


# ---------- Orbital mechanics ----------

def state_to_elements(state):
    """Convert heliocentric state vector to Keplerian elements.
    Returns: (a_au, ecc, inc_deg, node_deg, argp_deg)
    """
    _, x, y, z, vx, vy, vz = state
    r_vec = (x, y, z)
    v_vec = (vx, vy, vz)
    r = vmag(x, y, z)
    v = vmag(vx, vy, vz)

    # Specific orbital energy -> semi-major axis
    eps = v * v / 2.0 - GM_SUN / r
    a_km = -GM_SUN / (2.0 * eps)
    a_au = a_km / AU_KM

    # Angular momentum vector
    h_vec = cross(r_vec, v_vec)
    h = vmag(*h_vec)

    # Eccentricity vector: e_vec = (v x h) / mu - r_hat
    v_cross_h = cross(v_vec, h_vec)
    e_vec = (v_cross_h[0] / GM_SUN - x / r,
             v_cross_h[1] / GM_SUN - y / r,
             v_cross_h[2] / GM_SUN - z / r)
    ecc = vmag(*e_vec)

    # Inclination from angular momentum z-component
    inc = math.acos(max(-1.0, min(1.0, h_vec[2] / h)))
    inc_deg = math.degrees(inc)

    # Node vector: n = k_hat x h = (-h_y, h_x, 0) in ecliptic coords
    n_vec = (-h_vec[1], h_vec[0], 0.0)
    n = vmag(*n_vec)

    # Longitude of ascending node
    if n > 1e-10:
        cos_node = max(-1.0, min(1.0, n_vec[0] / n))
        node = math.acos(cos_node)
        if n_vec[1] < 0:
            node = 2.0 * math.pi - node
    else:
        node = 0.0
    node_deg = math.degrees(node)

    # Argument of perihelion
    if n > 1e-10 and ecc > 1e-10:
        cos_argp = max(-1.0, min(1.0, dot(n_vec, e_vec) / (n * ecc)))
        argp = math.acos(cos_argp)
        if e_vec[2] < 0:
            argp = 2.0 * math.pi - argp
    else:
        argp = 0.0
    argp_deg = math.degrees(argp)

    return a_au, ecc, inc_deg, node_deg, argp_deg


def compute_tisserand(a_au, ecc, inc_deg, a_j_au):
    """Tisserand parameter relative to Jupiter."""
    i_rad = math.radians(inc_deg)
    return a_j_au / a_au + 2.0 * math.cos(i_rad) * math.sqrt(
        a_au / a_j_au * (1.0 - ecc * ecc))


def classify_neo(a_au, q_au, Q_au):
    """Classify NEO dynamical class from osculating elements."""
    if a_au < 1.0 and Q_au < 0.983:
        return "Atira"
    elif a_au < 1.0 and Q_au >= 0.983:
        return "Aten"
    elif a_au >= 1.0 and q_au < 1.017:
        return "Apollo"
    elif q_au >= 1.017 and q_au < 1.3:
        return "Amor"
    else:
        return "Other"


# ---------- Main ----------

def main():
    print("=== NEO Orbit Census ===\n")

    # --- Resolve body commands ---
    print("[1] Resolving body identifiers...")
    body_cmds = {}
    for body_id in [JUPITER_ID] + [str(a) for a in ASTEROIDS]:
        cmd = find_body_cmd(body_id)
        body_cmds[body_id] = cmd
        print(f"    {body_id} -> COMMAND='{cmd}'")
        time.sleep(1)

    # --- Query Jupiter ---
    print("\n[2] Querying Jupiter state vectors...")
    time.sleep(1.5)
    jup_text = query_heliocentric_vectors(body_cmds[JUPITER_ID])
    jup_data = parse_vectors(jup_text)
    a_j, _, _, _, _ = state_to_elements(jup_data[0])
    print(f"    Jupiter SMA = {a_j:.6f} AU")

    # --- Query and process each asteroid ---
    asteroid_results = {}
    positions = {}
    for idx, ast_id in enumerate(ASTEROIDS):
        aid = str(ast_id)
        print(f"\n[{idx + 3}] Processing asteroid {aid}...")
        time.sleep(2)
        text = query_heliocentric_vectors(body_cmds[aid])
        data = parse_vectors(text)
        state = data[0]

        # Store position for distance computation
        positions[ast_id] = (state[1], state[2], state[3])

        # Compute orbital elements
        a, e, i, node, argp = state_to_elements(state)
        q = a * (1.0 - e)
        Q = a * (1.0 + e)
        tj = compute_tisserand(a, e, i, a_j)
        cls = classify_neo(a, q, Q)

        asteroid_results[aid] = {
            "sma_au": round(a, 8),
            "ecc": round(e, 8),
            "inc_deg": round(i, 6),
            "node_deg": round(node, 6),
            "argp_deg": round(argp, 6),
            "perihelion_au": round(q, 8),
            "aphelion_au": round(Q, 8),
            "tisserand_jupiter": round(tj, 8),
            "neo_class": cls,
        }
        print(f"    a={a:.4f} AU, e={e:.4f}, i={i:.2f}°")
        print(f"    T_J={tj:.4f}, class={cls}")

    # --- Tisserand ranking ---
    ranking = sorted(ASTEROIDS,
                     key=lambda x: asteroid_results[str(x)]['tisserand_jupiter'])
    print(f"\nTisserand ranking (ascending T_J): {ranking}")

    # --- Closest pair ---
    min_dist = float('inf')
    closest = None
    for i_idx in range(len(ASTEROIDS)):
        for j_idx in range(i_idx + 1, len(ASTEROIDS)):
            a1, a2 = ASTEROIDS[i_idx], ASTEROIDS[j_idx]
            p1, p2 = positions[a1], positions[a2]
            d = vmag(p1[0] - p2[0], p1[1] - p2[1], p1[2] - p2[2])
            if d < min_dist:
                min_dist = d
                closest = (min(a1, a2), max(a1, a2))
    print(f"Closest pair: {closest[0]}-{closest[1]}, distance = {min_dist:.2f} km")

    # --- Write output ---
    results = {
        "epoch_jd_tdb": EPOCH_JD,
        "jupiter_sma_au": round(a_j, 8),
        "asteroids": asteroid_results,
        "tisserand_ranking": ranking,
        "closest_pair": list(closest),
        "closest_pair_distance_km": round(min_dist, 2),
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n=== Results written to /app/results.json ===")
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
