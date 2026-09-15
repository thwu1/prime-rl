#!/usr/bin/env python3
"""
NEO Encounter Cross-Validation Pipeline

Diagnoses the flawed preliminary analysis at /app/preliminary_analysis.json,
then independently computes correct encounter dynamics from JPL data sources.

Diagnosis of preliminary_analysis.json:
- All distances are ~1 AU because the pipeline reported the NEO's heliocentric
  distance (distance from the Sun) instead of the geocentric close approach
  distance (distance from Earth). The metadata confirms center="Sun (code 10)".
- Velocities are heliocentric orbital speeds, not Earth-relative velocities.
- v_inf values are nearly identical to velocity because at 1 AU the Earth's
  gravitational escape velocity correction is negligible.
- Vis-viva residuals are large because of incorrect GM_Sun or wrong distance/velocity.
- Deflection angles are near-zero because deflection is negligible at 1 AU.
- Contains 7 entries instead of the required 5.
- Includes "2020 QG" which is not a 2024 designation.

Fix: Query the CAD API for the actual closest approaches, then use Horizons
with heliocentric state vectors for BOTH the NEO and Earth, computing the
geocentric relative state via vector subtraction.
"""

import json
import math
import re
import sys
import time
from datetime import datetime, timedelta

import requests

# --------------- Physical constants ---------------
AU_KM = 149597870.700
GM_SUN = 1.32712440018e11   # km^3/s^2
GM_EARTH = 398600.4418      # km^3/s^2
A_JUPITER_AU = 5.2038       # AU

HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
CAD_URL = "https://ssd-api.jpl.nasa.gov/cad.api"


# --------------- Utility functions ---------------

def jd_to_datetime(jd):
    """Convert Julian Date (TDB) to Python datetime."""
    j2000_jd = 2451545.0
    j2000_dt = datetime(2000, 1, 1, 12, 0, 0)
    return j2000_dt + timedelta(days=(jd - j2000_jd))


def jd_to_horizons_time(jd):
    """Convert JD to a Horizons-compatible calendar string."""
    dt = jd_to_datetime(jd)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def vec_sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def vec_mag(v):
    return math.sqrt(sum(x * x for x in v))


# --------------- CAD API ---------------

def get_cad_closest(n=5):
    """Return the *n* closest distinct NEO approaches to Earth in 2024."""
    params = {
        "date-min": "2024-01-01",
        "date-max": "2024-12-31",
        "dist-max": "0.01",
        "sort": "dist",
    }
    resp = requests.get(CAD_URL, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    fields = data["fields"]
    idx = {f: fields.index(f) for f in fields}

    encounters = []
    seen = set()
    for row in data["data"]:
        des = row[idx["des"]]
        if des in seen:
            continue
        seen.add(des)
        encounters.append({
            "designation": des,
            "jd": float(row[idx["jd"]]),
            "dist_au": float(row[idx["dist"]]),
            "v_rel_kms": float(row[idx["v_rel"]]),
            "v_inf_kms": float(row[idx["v_inf"]]),
        })
        if len(encounters) >= n:
            break
    return encounters


# --------------- Horizons API ---------------

def horizons_request(params, max_retries=4):
    """Issue a single Horizons GET with retry + rate-limit back-off."""
    params["format"] = "json"
    for attempt in range(max_retries):
        time.sleep(2.0)                       # respect 1-at-a-time policy
        try:
            resp = requests.get(HORIZONS_URL, params=params, timeout=120)
            resp.raise_for_status()
            body = resp.json()
            if "error" in body:
                raise ValueError(f"Horizons error: {body['error']}")
            return body["result"]
        except Exception as exc:
            print(f"  [attempt {attempt+1}/{max_retries}] {exc}",
                  file=sys.stderr)
            if attempt < max_retries - 1:
                time.sleep(4 * (attempt + 1))
    return None


def _horizons_time_params(jd):
    """Build START_TIME / STOP_TIME / STEP_SIZE for a single-epoch query."""
    dt = jd_to_datetime(jd)
    start = dt.strftime("%Y-%m-%d %H:%M:%S")
    stop = (dt + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "START_TIME": f"'{start}'",
        "STOP_TIME":  f"'{stop}'",
        "STEP_SIZE":  "'60 min'",
    }


def parse_vectors(text):
    """Extract the first (X,Y,Z,VX,VY,VZ) record from Horizons text."""
    soe = text.find("$$SOE")
    eoe = text.find("$$EOE")
    if soe < 0 or eoe < 0:
        raise ValueError("Missing $$SOE/$$EOE in Horizons output")
    block = text[soe + 5 : eoe]

    def val(label):
        m = re.search(rf'\b{label}\s*=\s*([^\s]+)', block)
        if not m:
            raise ValueError(f"Label '{label}' not found in vector block")
        return float(m.group(1))

    pos = [val("X"), val("Y"), val("Z")]
    vel = [val("VX"), val("VY"), val("VZ")]
    return pos, vel


def parse_elements(text):
    """Extract EC, A (km), IN (deg) from Horizons ELEMENTS text."""
    soe = text.find("$$SOE")
    eoe = text.find("$$EOE")
    if soe < 0 or eoe < 0:
        raise ValueError("Missing $$SOE/$$EOE in Horizons output")
    block = text[soe + 5 : eoe]

    def val(label):
        m = re.search(rf'\b{label}\s*=\s*([^\s]+)', block)
        if not m:
            raise ValueError(f"Label '{label}' not found in elements block")
        return float(m.group(1))

    ec = val("EC")
    a_km = val("A")
    in_deg = val("IN")
    return ec, a_km, in_deg


def get_state_vectors(command, jd):
    """Heliocentric ecliptic-J2000 state vectors (km, km/s)."""
    params = {
        "COMMAND":     f"'{command}'",
        "OBJ_DATA":    "'NO'",
        "MAKE_EPHEM":  "'YES'",
        "EPHEM_TYPE":  "'VECTORS'",
        "CENTER":      "'500@10'",
        "VEC_TABLE":   "'2'",
        "VEC_LABELS":  "'YES'",
        "OUT_UNITS":   "'KM-S'",
        "REF_PLANE":   "'ECLIPTIC'",
        "REF_SYSTEM":  "'J2000'",
        "CSV_FORMAT":  "'NO'",
    }
    params.update(_horizons_time_params(jd))
    text = horizons_request(params)
    if text is None:
        return None, None
    return parse_vectors(text)


def get_orbital_elements(command, jd):
    """Heliocentric osculating elements (ec, a_km, inc_deg)."""
    params = {
        "COMMAND":     f"'{command}'",
        "OBJ_DATA":    "'NO'",
        "MAKE_EPHEM":  "'YES'",
        "EPHEM_TYPE":  "'ELEMENTS'",
        "CENTER":      "'500@10'",
        "OUT_UNITS":   "'KM-S'",
        "REF_PLANE":   "'ECLIPTIC'",
        "REF_SYSTEM":  "'J2000'",
        "CSV_FORMAT":  "'NO'",
    }
    params.update(_horizons_time_params(jd))
    text = horizons_request(params)
    if text is None:
        return None, None, None
    return parse_elements(text)


# --------------- Encounter analysis ---------------

def analyse_encounter(cad):
    """Full encounter analysis for one CAD record.  Returns dict or None."""
    des = cad["designation"]
    jd  = cad["jd"]
    print(f"  Analysing {des}  (JD {jd:.6f}) ...")

    neo_cmd = f"DES={des};"

    try:
        r_neo, v_neo = get_state_vectors(neo_cmd, jd)
        if r_neo is None:
            raise RuntimeError("NEO vector query failed")

        r_ear, v_ear = get_state_vectors("399", jd)
        if r_ear is None:
            raise RuntimeError("Earth vector query failed")

        ec, a_km, in_deg = get_orbital_elements(neo_cmd, jd)
        if ec is None:
            raise RuntimeError("NEO element query failed")
    except Exception as exc:
        print(f"    SKIP {des}: {exc}", file=sys.stderr)
        return None

    # ---- relative geometry (geocentric) ----
    r_rel = vec_sub(r_neo, r_ear)
    v_rel = vec_sub(v_neo, v_ear)
    dist_km = vec_mag(r_rel)
    dist_au = dist_km / AU_KM
    v_rel_mag = vec_mag(v_rel)          # km/s

    # ---- hyperbolic excess velocity ----
    v_inf_sq = v_rel_mag ** 2 - 2.0 * GM_EARTH / dist_km
    v_inf = math.sqrt(max(0.0, v_inf_sq))

    # ---- deflection angle ----
    if v_inf > 0:
        e_hyp = 1.0 + dist_km * v_inf ** 2 / GM_EARTH
        deflection_deg = math.degrees(2.0 * math.asin(1.0 / e_hyp))
    else:
        deflection_deg = 180.0

    # ---- vis-viva check ----
    r_helio = vec_mag(r_neo)
    v_helio = vec_mag(v_neo)
    vv_lhs = v_helio ** 2
    vv_rhs = GM_SUN * (2.0 / r_helio - 1.0 / a_km)
    vis_viva_residual = abs(vv_lhs - vv_rhs) / abs(vv_lhs) if vv_lhs else 0.0

    # ---- Tisserand parameter ----
    a_au = a_km / AU_KM
    in_rad = math.radians(in_deg)
    t_j = (A_JUPITER_AU / a_au
           + 2.0 * math.cos(in_rad)
           * math.sqrt(a_au / A_JUPITER_AU * (1.0 - ec ** 2)))

    print(f"    dist  cad={cad['dist_au']:.6e}  comp={dist_au:.6e} AU")
    print(f"    vrel  cad={cad['v_rel_kms']:.4f}  comp={v_rel_mag:.4f} km/s")
    print(f"    vinf  cad={cad['v_inf_kms']:.4f}  comp={v_inf:.4f} km/s")
    print(f"    vis-viva residual = {vis_viva_residual:.4e}")
    print(f"    T_J = {t_j:.4f}   deflection = {deflection_deg:.3f} deg")

    return {
        "designation":       des,
        "close_approach_jd": jd,
        "cad_dist_au":       cad["dist_au"],
        "computed_dist_au":  dist_au,
        "cad_v_rel_kms":     cad["v_rel_kms"],
        "computed_v_rel_kms": v_rel_mag,
        "cad_v_inf_kms":     cad["v_inf_kms"],
        "computed_v_inf_kms": v_inf,
        "vis_viva_residual": vis_viva_residual,
        "tisserand_jupiter": t_j,
        "deflection_angle_deg": deflection_deg,
    }


# --------------- Main ---------------

def main():
    print("=== Diagnosing preliminary analysis ===")
    try:
        with open("/app/preliminary_analysis.json") as f:
            prelim = json.load(f)
        meta = prelim.get("metadata", {})
        print(f"  Pipeline center: {meta.get('center', 'unknown')}")
        print(f"  Number of entries: {len(prelim.get('neo_encounters', []))}")
        dists = [e.get("dist_au", 0) for e in prelim.get("neo_encounters", [])]
        print(f"  Distance range: {min(dists):.4f} - {max(dists):.4f} AU")
        print("  DIAGNOSIS: All distances ~1 AU indicate heliocentric distances,")
        print("  not geocentric close approach distances. Pipeline used Sun as center")
        print("  and reported |r_neo| instead of |r_neo - r_earth|.")
        print()
    except Exception as exc:
        print(f"  Could not read preliminary analysis: {exc}")

    print("=== Querying CAD API for actual closest approaches in 2024 ===")
    cad_entries = get_cad_closest(n=12)      # fetch extras as fall-back
    print(f"  Retrieved {len(cad_entries)} candidate encounters")

    results = []
    for entry in cad_entries:
        if len(results) >= 5:
            break
        rec = analyse_encounter(entry)
        if rec is not None:
            results.append(rec)

    if len(results) < 5:
        print(f"WARNING: only {len(results)} encounters succeeded", file=sys.stderr)

    with open("/app/results.json", "w") as fh:
        json.dump({"neo_encounters": results}, fh, indent=2)

    print(f"\nWrote {len(results)} encounters to /app/results.json")


if __name__ == "__main__":
    main()
