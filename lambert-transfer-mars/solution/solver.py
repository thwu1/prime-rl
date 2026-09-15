#!/usr/bin/env python3
"""

Corrected Earth-Mars Transfer Orbit Optimizer with Mission Evaluation.

Fixes three domain-specific bugs in /app/trajectory_optimizer.py:
1. Body ID: '3' (Earth-Moon barycenter) -> '399' (Earth geocenter)
2. Prograde check: cx[1] (Y-component) -> cx[2] (Z-component) for ecliptic frame
3. Aberration: VEC_CORR=LT (light-time) -> VEC_CORR=NONE (geometric)

Uses 1-day grid resolution for local optimality.
Performs mission trade-study: C3-optimal vs arrival-v_inf-optimal comparison,
launch/arrival window characterization, and quantitative recommendation.
"""

import json
import math
import re
import sys
import time
import urllib.request

MU_SUN = 1.32712440018e11  # km^3/s^2


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


def lambert_solve(r1_vec, r2_vec, tof, mu=MU_SUN, reject_type_2=True):
    """
    Solve Lambert's problem for a prograde transfer arc.
    When reject_type_2=True (default), only Type-I (short-way, dtheta < pi)
    solutions are returned. When False, Type-II (long-way) is also allowed.
    """
    r1 = vnorm(r1_vec)
    r2 = vnorm(r2_vec)

    cos_dtheta = max(-1.0, min(1.0, dot(r1_vec, r2_vec) / (r1 * r2)))

    cx = cross(r1_vec, r2_vec)
    # FIX: Use Z-component (cx[2]) for ecliptic frame prograde determination
    if cx[2] >= 0:
        dtheta = math.acos(cos_dtheta)
    else:
        dtheta = 2.0 * math.pi - math.acos(cos_dtheta)

    if dtheta > math.pi and reject_type_2:
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

    C = stumpff_c(z)
    S = stumpff_s(z)
    y = r1 + r2 + A * (z * S - 1.0) / math.sqrt(C)

    f = 1.0 - y / r1
    g = A * math.sqrt(y / mu)
    gdot = 1.0 - y / r2

    v1 = [(r2_vec[i] - f * r1_vec[i]) / g for i in range(3)]
    v2 = [(gdot * r2_vec[i] - r1_vec[i]) / g for i in range(3)]

    return v1, v2, dtheta


def query_horizons(body_id, start_date, stop_date, step_size="1d"):
    """Query JPL Horizons for heliocentric ecliptic J2000 geometric state vectors."""
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
        # FIX: Use NONE for geometric positions (was LT)
        "&VEC_CORR=NONE"
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
    soe = text.find("$$SOE")
    eoe = text.find("$$EOE")
    if soe < 0 or eoe < 0:
        raise ValueError("Missing $$SOE/$$EOE markers")

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


def find_contiguous_window(jd_list, optimal_jd):
    """Find contiguous range of JDs (1-day spacing) around optimal_jd."""
    if not jd_list:
        return optimal_jd, optimal_jd
    jds = sorted(jd_list)
    opt_idx = min(range(len(jds)), key=lambda i: abs(jds[i] - optimal_jd))
    left = opt_idx
    while left > 0 and (jds[left] - jds[left - 1]) < 1.5:
        left -= 1
    right = opt_idx
    while right < len(jds) - 1 and (jds[right + 1] - jds[right]) < 1.5:
        right += 1
    return jds[left], jds[right]


def main():
    print("=" * 60)
    print("Corrected Earth-Mars Transfer Optimizer + Evaluation")
    print("=" * 60)

    # FIX: Use body 399 (Earth geocenter) instead of 3 (Earth-Moon barycenter)
    print("\nFetching Earth ephemeris (body 399, geometric, 1-day grid)...")
    earth_states = query_horizons("399", "2026-Sep-01", "2026-Dec-01", step_size="1d")
    print(f"  {len(earth_states)} epochs loaded")
    if not earth_states:
        print("ERROR: No Earth states returned", file=sys.stderr)
        sys.exit(1)

    time.sleep(2)

    print("Fetching Mars ephemeris (body 499, geometric, 1-day grid)...")
    mars_states = query_horizons("499", "2027-Mar-01", "2027-Sep-01", step_size="1d")
    print(f"  {len(mars_states)} epochs loaded")
    if not mars_states:
        print("ERROR: No Mars states returned", file=sys.stderr)
        sys.exit(1)

    # ===================================================================
    # Phase 1: Find C3-optimal transfer (Type-I only)
    # ===================================================================
    print(f"\nSearching {len(earth_states)} x {len(mars_states)} grid for C3 minimum...")

    best_c3 = float("inf")
    best = None
    solved = 0

    # Also track arrival-v_inf-optimal simultaneously
    best_vinf_arr_mag = float("inf")
    arr_opt = None

    for ei, es in enumerate(earth_states):
        for ms in mars_states:
            tof_days = ms["jd"] - es["jd"]
            if tof_days < 100 or tof_days > 400:
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
            v_inf_arr = vsub(v2, ms["vel"])
            vinf_arr_mag = vnorm(v_inf_arr)

            # Track C3 minimum
            if c3 < best_c3:
                best_c3 = c3
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

            # Track arrival v_inf minimum
            if vinf_arr_mag < best_vinf_arr_mag:
                best_vinf_arr_mag = vinf_arr_mag
                arr_opt = {
                    "departure_jd": es["jd"],
                    "arrival_jd": ms["jd"],
                    "c3_km2_s2": c3,
                    "v_inf_arr_mag_km_s": vinf_arr_mag,
                    "tof_days": tof_days,
                }

        if (ei + 1) % 15 == 0:
            print(f"  Progress: {ei + 1}/{len(earth_states)} departure dates")

    print(f"  Evaluated {solved} valid Lambert solutions")

    if best is None:
        print("ERROR: No valid solutions found", file=sys.stderr)
        sys.exit(1)

    print(f"\nC3-optimal transfer:")
    print(f"  Departure JD: {best['departure_jd']:.1f}")
    print(f"  Arrival JD:   {best['arrival_jd']:.1f}")
    print(f"  TOF:          {best['tof_seconds'] / 86400:.1f} days")
    print(f"  C3:           {best['c3_km2_s2']:.4f} km^2/s^2")
    print(f"  |v_inf_dep|:  {vnorm(best['v_inf_dep_km_s']):.4f} km/s")
    print(f"  |v_inf_arr|:  {vnorm(best['v_inf_arr_km_s']):.4f} km/s")

    with open("/app/results.json", "w") as f:
        json.dump(best, f, indent=2)
    print("Results written to /app/results.json")

    # ===================================================================
    # Phase 2: Write diagnosis
    # ===================================================================
    diagnosis = {
        "bugs_found": [
            {
                "location": "main(), Earth ephemeris query: query_horizons('3', ...)",
                "description": (
                    "Uses JPL body ID '3' which is the Earth-Moon barycenter (EMB), "
                    "not Earth itself. The correct body ID for Earth's geocenter is '399'. "
                    "The EMB is offset from Earth by up to ~4,700 km due to the Moon's "
                    "gravitational influence on the system center of mass."
                ),
                "impact": (
                    "Earth departure positions and velocities are for the EMB, not Earth, "
                    "introducing ~4,700 km position error in the Lambert boundary conditions "
                    "and slight velocity errors, yielding incorrect transfer orbit parameters."
                ),
                "fix": "Change body ID from '3' to '399' in the Earth query call."
            },
            {
                "location": "lambert_solve(), prograde direction check: if cx[1] >= 0",
                "description": (
                    "Uses the Y-component (index 1) of the cross product r1 x r2 to "
                    "determine whether the transfer arc is prograde or retrograde. "
                    "In ecliptic coordinates, the orbit normal for prograde motion "
                    "points along the positive Z-axis (ecliptic north pole), so the "
                    "Z-component (index 2) must be checked instead."
                ),
                "impact": (
                    "For orbits near the ecliptic plane, the Y-component of r1 x r2 is "
                    "small and its sign is unreliable for determining orbit direction. "
                    "This causes many valid prograde (Type-I) transfers to be incorrectly "
                    "classified as retrograde and rejected, preventing the optimizer "
                    "from finding the true minimum-C3 solution."
                ),
                "fix": "Change cx[1] to cx[2] in the prograde/retrograde conditional."
            },
            {
                "location": "query_horizons(), URL parameter: VEC_CORR=LT",
                "description": (
                    "Uses light-time corrected positions (VEC_CORR=LT) instead of "
                    "geometric positions (VEC_CORR=NONE). Light-time correction returns "
                    "the position where the body was when light left it to reach the "
                    "coordinate origin, not where the body actually is at the coordinate "
                    "time. For Lambert's two-point boundary value problem, geometric "
                    "(instantaneous) positions are required."
                ),
                "impact": (
                    "Mars positions are shifted by light-travel-time effects — up to "
                    "~25,000 km depending on the Earth-Mars distance — causing systematic "
                    "errors in the Lambert boundary conditions and incorrect transfer "
                    "orbit solutions."
                ),
                "fix": "Change VEC_CORR=LT to VEC_CORR=NONE for geometric positions."
            }
        ],
        "num_bugs_fixed": 3
    }

    with open("/app/diagnosis.json", "w") as f:
        json.dump(diagnosis, f, indent=2)
    print("Diagnosis written to /app/diagnosis.json")

    # ===================================================================
    # Phase 3: Mission evaluation — trade study
    # ===================================================================
    print("\n" + "=" * 60)
    print("Mission Trade-Study Evaluation")
    print("=" * 60)

    print(f"\nArrival-optimal transfer:")
    print(f"  Departure JD: {arr_opt['departure_jd']:.1f}")
    print(f"  Arrival JD:   {arr_opt['arrival_jd']:.1f}")
    print(f"  TOF:          {arr_opt['tof_days']:.1f} days")
    print(f"  C3:           {arr_opt['c3_km2_s2']:.4f} km^2/s^2")
    print(f"  |v_inf_arr|:  {arr_opt['v_inf_arr_mag_km_s']:.4f} km/s")

    # --- Launch window (fix arrival at C3-optimal, sweep departure) ---
    # Allow Type-II Lambert solutions in window computation since the
    # transfer angle near the optimal can cross pi, and excluding Type-II
    # would artificially narrow the window.
    print("\nComputing launch window...")
    opt_arr_jd = best["arrival_jd"]
    mars_at_opt_arr = min(mars_states, key=lambda s: abs(s["jd"] - opt_arr_jd))
    c3_threshold = best["c3_km2_s2"] + 2.0

    dep_sub_threshold = []
    for es in sorted(earth_states, key=lambda s: s["jd"]):
        tof_days = opt_arr_jd - es["jd"]
        if tof_days < 100 or tof_days > 400:
            continue
        tof_sec = tof_days * 86400.0
        try:
            v1, _, _ = lambert_solve(
                es["pos"], mars_at_opt_arr["pos"], tof_sec, MU_SUN,
                reject_type_2=False
            )
        except (ValueError, ZeroDivisionError, OverflowError):
            continue
        v_inf = vsub(v1, es["vel"])
        c3 = dot(v_inf, v_inf)
        if c3 < c3_threshold:
            dep_sub_threshold.append(es["jd"])

    dep_earliest, dep_latest = find_contiguous_window(
        dep_sub_threshold, best["departure_jd"]
    )

    launch_window = {
        "optimal_arrival_jd": opt_arr_jd,
        "earliest_departure_jd": dep_earliest,
        "latest_departure_jd": dep_latest,
        "window_width_days": dep_latest - dep_earliest,
        "c3_threshold_km2_s2": c3_threshold,
    }
    print(f"  Width: {launch_window['window_width_days']:.0f} days "
          f"[JD {dep_earliest:.1f}, {dep_latest:.1f}]")

    # --- Arrival window (fix departure at C3-optimal, sweep arrival) ---
    print("Computing arrival window...")
    opt_dep_jd = best["departure_jd"]
    earth_at_opt_dep = min(earth_states, key=lambda s: abs(s["jd"] - opt_dep_jd))

    arr_sub_threshold = []
    for ms in sorted(mars_states, key=lambda s: s["jd"]):
        tof_days = ms["jd"] - opt_dep_jd
        if tof_days < 100 or tof_days > 400:
            continue
        tof_sec = tof_days * 86400.0
        try:
            v1, _, _ = lambert_solve(
                earth_at_opt_dep["pos"], ms["pos"], tof_sec, MU_SUN,
                reject_type_2=False
            )
        except (ValueError, ZeroDivisionError, OverflowError):
            continue
        v_inf = vsub(v1, earth_at_opt_dep["vel"])
        c3 = dot(v_inf, v_inf)
        if c3 < c3_threshold:
            arr_sub_threshold.append(ms["jd"])

    arr_earliest, arr_latest = find_contiguous_window(
        arr_sub_threshold, best["arrival_jd"]
    )

    arrival_window = {
        "optimal_departure_jd": opt_dep_jd,
        "earliest_arrival_jd": arr_earliest,
        "latest_arrival_jd": arr_latest,
        "window_width_days": arr_latest - arr_earliest,
        "c3_threshold_km2_s2": c3_threshold,
    }
    print(f"  Width: {arrival_window['window_width_days']:.0f} days "
          f"[JD {arr_earliest:.1f}, {arr_latest:.1f}]")

    # --- Comparison ---
    c3_opt_vinf_arr = vnorm(best["v_inf_arr_km_s"])
    c3_penalty = arr_opt["c3_km2_s2"] - best["c3_km2_s2"]
    vinf_savings = c3_opt_vinf_arr - arr_opt["v_inf_arr_mag_km_s"]

    comparison = {
        "c3_optimal_c3": best["c3_km2_s2"],
        "c3_optimal_vinf_arr": c3_opt_vinf_arr,
        "c3_optimal_tof_days": best["tof_seconds"] / 86400.0,
        "arr_optimal_c3": arr_opt["c3_km2_s2"],
        "arr_optimal_vinf_arr": arr_opt["v_inf_arr_mag_km_s"],
        "arr_optimal_tof_days": arr_opt["tof_days"],
        "c3_penalty_for_arr_optimal": c3_penalty,
        "vinf_savings_for_arr_optimal": vinf_savings,
    }

    print(f"\nComparison:")
    print(f"  C3-optimal:      C3={best['c3_km2_s2']:.2f}, "
          f"v_inf_arr={c3_opt_vinf_arr:.2f}, "
          f"TOF={best['tof_seconds']/86400:.0f}d")
    print(f"  Arrival-optimal: C3={arr_opt['c3_km2_s2']:.2f}, "
          f"v_inf_arr={arr_opt['v_inf_arr_mag_km_s']:.2f}, "
          f"TOF={arr_opt['tof_days']:.0f}d")
    print(f"  C3 penalty:      +{c3_penalty:.2f} km^2/s^2")
    print(f"  v_inf savings:   {vinf_savings:.2f} km/s")

    # --- Recommendation ---
    recommendation = (
        f"The C3-optimal transfer (departure JD {best['departure_jd']:.1f}, "
        f"arrival JD {best['arrival_jd']:.1f}, "
        f"C3={best['c3_km2_s2']:.2f} km^2/s^2, "
        f"v_inf_arr={c3_opt_vinf_arr:.2f} km/s, "
        f"TOF={best['tof_seconds']/86400:.0f} days) minimizes departure energy, "
        f"maximizing injected mass for a given launch vehicle. "
        f"The arrival-optimal transfer (departure JD {arr_opt['departure_jd']:.1f}, "
        f"arrival JD {arr_opt['arrival_jd']:.1f}, "
        f"C3={arr_opt['c3_km2_s2']:.2f} km^2/s^2, "
        f"v_inf_arr={arr_opt['v_inf_arr_mag_km_s']:.2f} km/s, "
        f"TOF={arr_opt['tof_days']:.0f} days) reduces Mars arrival velocity by "
        f"{vinf_savings:.2f} km/s at a cost of {c3_penalty:.2f} km^2/s^2 "
        f"additional departure C3. For a mass-constrained mission where the "
        f"launch vehicle is the binding constraint, the C3-optimal solution is "
        f"preferable because each km^2/s^2 of C3 directly maps to delivered mass "
        f"via the rocket equation. If the spacecraft has adequate launch margin but "
        f"limited propulsion for Mars orbit insertion, the arrival-optimal solution "
        f"reduces capture delta-V, enabling a lighter propulsion stage or more "
        f"delivered payload at Mars. The C3-optimal launch window spans "
        f"{launch_window['window_width_days']:.0f} days with C3 below "
        f"{c3_threshold:.1f} km^2/s^2, providing adequate scheduling flexibility."
    )

    evaluation = {
        "launch_window": launch_window,
        "arrival_window": arrival_window,
        "arrival_optimal": arr_opt,
        "comparison": comparison,
        "recommendation": recommendation,
    }

    with open("/app/mission_evaluation.json", "w") as f:
        json.dump(evaluation, f, indent=2)
    print("\nMission evaluation written to /app/mission_evaluation.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
