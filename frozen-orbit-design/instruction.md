All mission parameters and Earth gravitational constants are stored in a SQLite database at `/app/orbit_data.db`. The database contains multiple gravity models and mission profiles at various lifecycle stages. You must determine the active mission profile with the highest priority and retrieve its associated gravity model parameters, including the zonal harmonic coefficients J2 and J3.

Design a frozen sun-synchronous repeat ground track orbit satisfying three coupled constraints from J2/J3 secular perturbation theory:

- **Sun-synchronous**: J2 secular RAAN precession rate matches the profile's target value
- **Repeat ground track**: Exactly Q nodal revolutions in P solar days
- **Frozen orbit**: Eccentricity at the J2+J3 equilibrium for the specified argument of perigee

Write orbital elements to `/app/results.json` with fields: `semi_major_axis_km`, `eccentricity`, `inclination_deg`, `argument_of_perigee_deg`, `nodal_period_s`, `ground_track_spacing_km`, `max_altitude_variation_m`, `altitude_at_equator_ascending_km`, `sun_synchronous_raan_rate_deg_day`.

The output must pass the validation filter: `jq -e -f /app/validate_output.jq /app/results.json`

Write `/app/query_results.json` documenting the extracted database parameters: `gravity_model` (name), `mu_km3_s2`, `equatorial_radius_km`, `rotation_rate_rad_s`, `J2`, `J3`, `repeat_revolutions`, `repeat_days`, `target_raan_rate_deg_day`, `altitude_min_km`, `altitude_max_km`, `frozen_arg_perigee_deg`.

Insert the computed orbital elements into a new `computed_orbits` table in `/app/orbit_data.db` with schema: `(profile_id INTEGER, semi_major_axis_km REAL, eccentricity REAL, inclination_deg REAL, nodal_period_s REAL, computed_at TEXT)`.