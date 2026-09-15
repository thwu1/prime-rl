#!/usr/bin/env python3

"""
Frozen sun-synchronous repeat ground track orbit design solver.

Queries the SQLite database for the active mission profile and gravity model,
solves the coupled J2/J3 perturbation constraints, writes results to JSON,
validates with jq, and stores computed orbit back in the database.
"""

import json
import math
import sqlite3
import sys
from datetime import datetime, timezone


def query_database(db_path):
    """Extract the active mission profile and its gravity model from the database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    c = conn.cursor()

    # Get the active mission profile with the highest priority
    c.execute("""
        SELECT mp.profile_id, mp.profile_name, mp.repeat_revolutions,
               mp.repeat_days, mp.target_raan_rate_deg_day,
               mp.altitude_min_km, mp.altitude_max_km,
               mp.frozen_arg_perigee_deg, mp.gravity_model_id,
               gm.model_name, gm.mu_km3_s2, gm.equatorial_radius_km,
               gm.flattening, gm.rotation_rate_rad_s
        FROM mission_profiles mp
        JOIN gravity_models gm ON mp.gravity_model_id = gm.model_id
        WHERE mp.status = 'active'
        ORDER BY mp.priority DESC
        LIMIT 1
    """)
    row = c.fetchone()
    if row is None:
        print("ERROR: No active mission profile found", file=sys.stderr)
        sys.exit(1)

    profile = dict(row)

    # Get the zonal harmonic coefficients for this gravity model
    c.execute("""
        SELECT degree, coefficient
        FROM zonal_harmonics
        WHERE model_id = ?
        ORDER BY degree
    """, (profile["gravity_model_id"],))
    harmonics = {r["degree"]: r["coefficient"] for r in c.fetchall()}

    conn.close()
    return profile, harmonics


def solve_orbit(profile, harmonics):
    """Solve the coupled nonlinear orbit design system."""
    mu = profile["mu_km3_s2"]
    R_E = profile["equatorial_radius_km"]
    omega_E = profile["rotation_rate_rad_s"]
    J2 = harmonics[2]
    J3 = harmonics[3]

    Q = profile["repeat_revolutions"]
    P = profile["repeat_days"]
    target_Omega_dot_deg_day = profile["target_raan_rate_deg_day"]
    omega_frozen_deg = profile["frozen_arg_perigee_deg"]
    omega_frozen = math.radians(omega_frozen_deg)

    target_Omega_dot = math.radians(target_Omega_dot_deg_day) / 86400.0

    # Required nodal period from repeat ground track condition
    T_nodal_req = 2.0 * math.pi * P / (Q * (omega_E - target_Omega_dot))

    def mean_motion(a):
        return math.sqrt(mu / a ** 3)

    def raan_rate(a, e, i):
        n = mean_motion(a)
        return -1.5 * n * J2 * (R_E / a) ** 2 * math.cos(i) / (1.0 - e ** 2) ** 2

    def arg_perigee_rate(a, e, i):
        n = mean_motion(a)
        return (1.5 * n * J2 * (R_E / a) ** 2
                * (2.0 - 2.5 * math.sin(i) ** 2) / (1.0 - e ** 2) ** 2)

    def mean_anomaly_rate(a, e, i):
        n = mean_motion(a)
        return n * (1.0 + 1.5 * J2 * (R_E / a) ** 2
                    * (1.0 - 1.5 * math.sin(i) ** 2) / (1.0 - e ** 2) ** 1.5)

    def nodal_period(a, e, i):
        return 2.0 * math.pi / (arg_perigee_rate(a, e, i) + mean_anomaly_rate(a, e, i))

    def frozen_eccentricity(a, i):
        return -J3 * R_E * math.sin(i) / (2.0 * J2 * a)

    def sun_sync_inclination(a, e):
        n = mean_motion(a)
        cos_i = (target_Omega_dot * (1.0 - e ** 2) ** 2
                 / (-1.5 * n * J2 * (R_E / a) ** 2))
        cos_i = max(-1.0, min(1.0, cos_i))
        return math.acos(cos_i)

    # Initial guesses
    a = R_E + 800.0
    e = 0.001
    i = math.radians(98.5)

    # Fixed-point iteration
    for iteration in range(500):
        a_prev, e_prev, i_prev = a, e, i

        # Update frozen eccentricity
        e = frozen_eccentricity(a, i)

        # Update sun-synchronous inclination
        i = sun_sync_inclination(a, e)

        # Update semi-major axis from nodal period requirement
        roa2 = (R_E / a) ** 2
        si2 = math.sin(i) ** 2
        ee = e ** 2
        C = (1.5 * J2 * roa2 * (2.0 - 2.5 * si2) / (1.0 - ee) ** 2
             + 1.5 * J2 * roa2 * (1.0 - 1.5 * si2) / (1.0 - ee) ** 1.5)
        u_dot_req = 2.0 * math.pi / T_nodal_req
        n_req = u_dot_req / (1.0 + C)
        a = (mu / n_req ** 2) ** (1.0 / 3.0)

        if (abs(a - a_prev) < 1e-12
                and abs(e - e_prev) < 1e-14
                and abs(i - i_prev) < 1e-14):
            break
    else:
        print("WARNING: iteration did not converge after 500 steps", file=sys.stderr)

    # Compute derived quantities
    T_nodal_final = nodal_period(a, e, i)
    Omega_dot_final = raan_rate(a, e, i)
    Omega_dot_deg_day = math.degrees(Omega_dot_final) * 86400.0
    ground_track_spacing_km = 2.0 * math.pi * R_E / Q
    max_alt_variation_m = 2.0 * a * e * 1000.0

    # Altitude at ascending equator crossing
    nu_asc = -omega_frozen
    r_asc = a * (1.0 - e ** 2) / (1.0 + e * math.cos(nu_asc))
    h_asc = r_asc - R_E

    return {
        "semi_major_axis_km": a,
        "eccentricity": e,
        "inclination_deg": math.degrees(i),
        "argument_of_perigee_deg": omega_frozen_deg,
        "nodal_period_s": T_nodal_final,
        "ground_track_spacing_km": ground_track_spacing_km,
        "max_altitude_variation_m": max_alt_variation_m,
        "altitude_at_equator_ascending_km": h_asc,
        "sun_synchronous_raan_rate_deg_day": Omega_dot_deg_day,
    }


def write_to_database(db_path, profile_id, results):
    """Create computed_orbits table and insert the result."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS computed_orbits (
            profile_id INTEGER,
            semi_major_axis_km REAL,
            eccentricity REAL,
            inclination_deg REAL,
            nodal_period_s REAL,
            computed_at TEXT
        )
    """)
    c.execute("""
        INSERT INTO computed_orbits
            (profile_id, semi_major_axis_km, eccentricity, inclination_deg,
             nodal_period_s, computed_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        profile_id,
        results["semi_major_axis_km"],
        results["eccentricity"],
        results["inclination_deg"],
        results["nodal_period_s"],
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    conn.close()


def main():
    db_path = "/app/orbit_data.db"

    # Step 1: Query the database
    profile, harmonics = query_database(db_path)

    # Step 2: Write query results for verification
    query_results = {
        "gravity_model": profile["model_name"],
        "mu_km3_s2": profile["mu_km3_s2"],
        "equatorial_radius_km": profile["equatorial_radius_km"],
        "rotation_rate_rad_s": profile["rotation_rate_rad_s"],
        "J2": harmonics[2],
        "J3": harmonics[3],
        "repeat_revolutions": profile["repeat_revolutions"],
        "repeat_days": profile["repeat_days"],
        "target_raan_rate_deg_day": profile["target_raan_rate_deg_day"],
        "altitude_min_km": profile["altitude_min_km"],
        "altitude_max_km": profile["altitude_max_km"],
        "frozen_arg_perigee_deg": profile["frozen_arg_perigee_deg"],
    }
    with open("/app/query_results.json", "w") as f:
        json.dump(query_results, f, indent=2)

    # Step 3: Solve the orbit design problem
    results = solve_orbit(profile, harmonics)

    # Step 4: Write results to JSON
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    # Step 5: Write computed orbit to the database
    write_to_database(db_path, profile["profile_id"], results)

    print("Orbit design pipeline completed successfully.")
    for k, v in results.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
