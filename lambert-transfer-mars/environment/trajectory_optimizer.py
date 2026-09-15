#!/usr/bin/env python3
"""
Earth-Mars Transfer Orbit Optimizer
Finds the minimum-C3 Type-I transfer orbit for the 2026-2027 launch window
using JPL Horizons ephemeris data and a universal-variable Lambert solver.
"""

import json
import math
import re
import sys
import time
import urllib.request

MU_SUN = 1.32712440018e11  # km^3/s^2


# ---------------------------------------------------------------------------
# Vector helpers (pure Python, no external dependencies)
# ---------------------------------------------------------------------------

def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def vnorm(a):
    return math.sqrt(dot(a, a))


def vsub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


# ---------------------------------------------------------------------------
# Stumpff functions for universal variable formulation
# ---------------------------------------------------------------------------

def stumpff_c(z):
    if z > 1e-6:
        return (1.0 - math.cos(math.sqrt(z))) / z
    elif z < -1e-6:
        return (math.cosh(math.sqrt(-z)) - 1.0) / (-z)
    return 0.5 - z / 24.0 + z * z / 720.0


def stumpff_s(z):
    if z > 1e-6:
        sz = math.sqrt(z)
        return (sz - math.sin(sz)) / (sz ** 3)
    elif z < -1e-6:
        sz = math.sqrt(-z)
        return (math.sinh(sz) - sz) / (sz ** 3)
    return 1.0 / 6.0 - z / 120.0 + z * z / 5040.0


# ---------------------------------------------------------------------------
# Lambert solver — universal variable method
# ---------------------------------------------------------------------------

def lambert_solve(r1_vec, r2_vec, tof, mu=MU_SUN):
    """
    Solve Lambert's problem using the universal variable method.
    Returns transfer velocities (v1, v2) and transfer angle for the
    prograde short-way (Type-I) arc.
    """
    r1 = vnorm(r1_vec)
    r2 = vnorm(r2_vec)

    cos_dtheta = max(-1.0, min(1.0, dot(r1_vec, r2_vec) / (r1 * r2)))

    # Determine prograde vs retrograde from orbit normal direction
    cx = cross(r1_vec, r2_vec)
    if cx[1] >= 0:
        dtheta = math.acos(cos_dtheta)
    else:
        dtheta = 2.0 * math.pi - math.acos(cos_dtheta)

    # Only accept short-way (Type-I) transfers
    if dtheta > math.pi:
        raise ValueError("Type-II transfer")

    sin_dtheta = math.sin(dtheta)
    if abs(sin_dtheta) < 1e-12:
        raise ValueError("Degenerate geometry")

    A = sin_dtheta * math.sqrt(r1 * r2 / (1.0 - cos_dtheta))
    if abs(A) < 1e-14:
        raise ValueError("A ~ 0")

    sqrt_mu = math.sqrt(mu)

    def tof_residual(z):
        C = stumpff_c(z)
        S = stumpff_s(z)
        if C <= 0:
            return None, None
        y = r1 + r2 + A * (z * S - 1.0) / math.sqrt(C)
        if y < 0:
            return None, y
        F = (y / C) ** 1.5 * S + A * math.sqrt(y) - sqrt_mu * tof
        return F, y

    # Newton-Raphson iteration on the universal variable z
    z = 0.0
    for _ in range(300):
        F, y = tof_residual(z)
        if F is None or y is None or y < 0:
            z += 0.5
            continue
        if abs(F) < 1e-8:
            break
        h = max(abs(z) * 1e-7, 1e-7)
        Fp, _ = tof_residual(z + h)
        Fm, _ = tof_residual(z - h)
        if Fp is None or Fm is None:
            z += 0.5
            continue
        dFdz = (Fp - Fm) / (2.0 * h)
        if abs(dFdz) < 1e-30:
            z += 0.5
            continue
        z_new = z - F / dFdz
        z_new = max(-4.0 * math.pi ** 2, min(40.0 * math.pi ** 2, z_new))
        _, y_new = tof_residual(z_new)
        retries = 0
        while (y_new is None or y_new < 0) and retries < 20:
            z_new = (z + z_new) / 2.0
            _, y_new = tof_residual(z_new)
            retries += 1
        z = z_new
    else:
        raise ValueError("Lambert solver did not converge")

    # Compute Lagrange coefficients
    C = stumpff_c(z)
    S = stumpff_s(z)
    y = r1 + r2 + A * (z * S - 1.0) / math.sqrt(C)

    f = 1.0 - y / r1
    g = A * math.sqrt(y / mu)
    gdot = 1.0 - y / r2

    v1 = [(r2_vec[i] - f * r1_vec[i]) / g for i in range(3)]
    v2 = [(gdot * r2_vec[i] - r1_vec[i]) / g for i in range(3)]

    return v1, v2, dtheta


# ---------------------------------------------------------------------------
# JPL Horizons API interface
# ---------------------------------------------------------------------------

def query_horizons(body_id, start_date, stop_date, step_size="5d"):
    """Query JPL Horizons for heliocentric ecliptic J2000 state vectors."""
    url = (
        "https://ssd.jpl.nasa.gov/api/horizons.api"
        "?format=text"
        f"&COMMAND=%27{body_id}%27"
        "&OBJ_DATA=NO"
        "&MAKE_EPHEM=YES"
        "&EPHEM_TYPE=VECTORS"
        "&CENTER=%27500@10%27"
        "&REF_PLANE=ECLIPTIC"
        "&OUT_UNITS=KM-S"
        "&VEC_TABLE=2"
        "&VEC_LABELS=YES"
        "&CSV_FORMAT=NO"
        "&VEC_CORR=LT"
        f"&START_TIME=%27{start_date}%27"
        f"&STOP_TIME=%27{stop_date}%27"
        f"&STEP_SIZE=%27{step_size}%27"
    )

    for attempt in range(5):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=120) as resp:
                text = resp.read().decode("utf-8")
            return parse_horizons_vectors(text)
        except Exception as e:
            print(f"  API attempt {attempt + 1} failed: {e}", file=sys.stderr)
            if attempt < 4:
                time.sleep(3 * (attempt + 1))
            else:
                raise


def parse_horizons_vectors(text):
    """Parse Horizons text output into list of state dicts."""
    soe = text.find("$$SOE")
    eoe = text.find("$$EOE")
    if soe < 0 or eoe < 0:
        raise ValueError(
            "Missing $$SOE/$$EOE markers in Horizons output"
        )

    data = text[soe + 5 : eoe]

    jd_pat = re.compile(r"(\d+\.\d+)\s*=\s*A\.D\.")
    x_pat = re.compile(
        r"X\s*=\s*([+-]?\d+\.\d+[Ee][+-]?\d+)\s+"
        r"Y\s*=\s*([+-]?\d+\.\d+[Ee][+-]?\d+)\s+"
        r"Z\s*=\s*([+-]?\d+\.\d+[Ee][+-]?\d+)"
    )
    v_pat = re.compile(
        r"VX\s*=\s*([+-]?\d+\.\d+[Ee][+-]?\d+)\s+"
        r"VY\s*=\s*([+-]?\d+\.\d+[Ee][+-]?\d+)\s+"
        r"VZ\s*=\s*([+-]?\d+\.\d+[Ee][+-]?\d+)"
    )

    states = []
    cur_jd = None
    cur_pos = None
    cur_vel = None

    for line in data.split("\n"):
        jm = jd_pat.search(line)
        if jm:
            if cur_jd is not None and cur_pos and cur_vel:
                states.append({"jd": cur_jd, "pos": cur_pos, "vel": cur_vel})
            cur_jd = float(jm.group(1))
            cur_pos = None
            cur_vel = None
            continue

        xm = x_pat.search(line)
        if xm:
            cur_pos = [float(xm.group(i)) for i in range(1, 4)]
            continue

        vm = v_pat.search(line)
        if vm:
            cur_vel = [float(vm.group(i)) for i in range(1, 4)]

    if cur_jd is not None and cur_pos and cur_vel:
        states.append({"jd": cur_jd, "pos": cur_pos, "vel": cur_vel})

    return states


# ---------------------------------------------------------------------------
# Main optimization
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Earth-Mars Transfer Orbit Optimizer")
    print("=" * 60)

    # Fetch Earth ephemeris for departure window
    print("\nFetching Earth ephemeris...")
    earth_states = query_horizons("3", "2026-Sep-01", "2026-Dec-01")
    print(f"  {len(earth_states)} epochs loaded")
    if not earth_states:
        print("ERROR: No Earth states returned", file=sys.stderr)
        sys.exit(1)

    time.sleep(2)  # respect Horizons rate limit

    # Fetch Mars ephemeris for arrival window
    print("Fetching Mars ephemeris...")
    mars_states = query_horizons("499", "2027-Mar-01", "2027-Sep-01")
    print(f"  {len(mars_states)} epochs loaded")
    if not mars_states:
        print("ERROR: No Mars states returned", file=sys.stderr)
        sys.exit(1)

    # Grid search over all departure-arrival pairs
    print(f"\nSearching {len(earth_states)} x {len(mars_states)} grid...")

    best_c3 = float("inf")
    best = None
    solved = 0
    skipped = 0

    for ei, es in enumerate(earth_states):
        for ms in mars_states:
            tof_days = ms["jd"] - es["jd"]
            if tof_days < 100 or tof_days > 400:
                skipped += 1
                continue

            tof_sec = tof_days * 86400.0

            try:
                v1, v2, dtheta = lambert_solve(
                    es["pos"], ms["pos"], tof_sec, MU_SUN
                )
            except (ValueError, ZeroDivisionError, OverflowError):
                continue

            solved += 1
            v_inf_dep = vsub(v1, es["vel"])
            c3 = dot(v_inf_dep, v_inf_dep)

            if c3 < best_c3:
                best_c3 = c3
                v_inf_arr = vsub(v2, ms["vel"])
                best = {
                    "departure_jd": es["jd"],
                    "arrival_jd": ms["jd"],
                    "c3_km2_s2": c3,
                    "v_inf_dep_km_s": v_inf_dep,
                    "v_inf_arr_km_s": v_inf_arr,
                    "transfer_v1_km_s": v1,
                    "transfer_v2_km_s": v2,
                    "tof_seconds": tof_sec,
                    "earth_pos_km": es["pos"],
                    "earth_vel_km_s": es["vel"],
                    "mars_pos_km": ms["pos"],
                    "mars_vel_km_s": ms["vel"],
                }

        if (ei + 1) % 5 == 0:
            print(
                f"  Progress: {ei + 1}/{len(earth_states)} departure dates "
                f"(solved={solved}, skipped={skipped})"
            )

    print(f"  Evaluated {solved} valid Lambert solutions (skipped {skipped})")

    if best is None:
        print("ERROR: No valid solutions found", file=sys.stderr)
        sys.exit(1)

    print(f"\nOptimal transfer:")
    print(f"  Departure JD: {best['departure_jd']:.1f}")
    print(f"  Arrival JD:   {best['arrival_jd']:.1f}")
    print(f"  TOF:          {best['tof_seconds'] / 86400:.1f} days")
    print(f"  C3:           {best['c3_km2_s2']:.4f} km^2/s^2")
    print(f"  |v_inf_dep|:  {vnorm(best['v_inf_dep_km_s']):.4f} km/s")
    print(f"  |v_inf_arr|:  {vnorm(best['v_inf_arr_km_s']):.4f} km/s")

    with open("/app/results.json", "w") as f:
        json.dump(best, f, indent=2)

    print("\nResults written to /app/results.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
