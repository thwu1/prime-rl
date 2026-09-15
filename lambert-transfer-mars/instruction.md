A trajectory optimization script at `/app/trajectory_optimizer.py` finds minimum-C3 Type-I Earth-to-Mars transfers for the 2026-2027 launch window (Sep-Nov 2026 departures, Mar-Aug 2027 arrivals). It queries the JPL Horizons API for planetary ephemerides, implements a universal-variable Lambert solver, and grid-searches over departure/arrival dates.

The script runs without errors but produces incorrect results — multiple distinct bugs affect its API queries and solver logic. The grid resolution is also too coarse to locate a precise local C3 minimum.

Fix all bugs, design an optimization strategy that achieves a local C3 minimum (no single-day departure or arrival shift yields lower C3), and then evaluate the mission trade space. Determine launch and arrival flexibility windows, find the transfer that minimizes arrival v_infinity magnitude (which generally differs from the C3-optimal), and compare the two solutions to judge which is preferable for a mass-constrained mission. Use GM_Sun = 1.32712440018e11 km³/s².

Write `/app/results.json` — C3-optimal Type-I transfer:
```json
{
  "departure_jd": <float>,
  "arrival_jd": <float>,
  "c3_km2_s2": <float>,
  "v_inf_dep_km_s": [<vx>, <vy>, <vz>],
  "v_inf_arr_km_s": [<vx>, <vy>, <vz>],
  "transfer_v1_km_s": [<vx>, <vy>, <vz>],
  "transfer_v2_km_s": [<vx>, <vy>, <vz>],
  "tof_seconds": <float>,
  "earth_pos_km": [<x>, <y>, <z>],
  "earth_vel_km_s": [<vx>, <vy>, <vz>],
  "mars_pos_km": [<x>, <y>, <z>],
  "mars_vel_km_s": [<vx>, <vy>, <vz>]
}
```

Write `/app/diagnosis.json`:
```json
{
  "bugs_found": [
    {
      "location": "<function or line description>",
      "description": "<what is wrong>",
      "impact": "<how it affects the output>",
      "fix": "<what the correction is>"
    }
  ],
  "num_bugs_fixed": <int>
}
```

Write `/app/mission_evaluation.json` — trade study comparing C3-optimal and arrival-optimal transfers with launch/arrival window characterization:
```json
{
  "launch_window": {
    "optimal_arrival_jd": <float>,
    "earliest_departure_jd": <float>,
    "latest_departure_jd": <float>,
    "window_width_days": <float>,
    "c3_threshold_km2_s2": <float>
  },
  "arrival_window": {
    "optimal_departure_jd": <float>,
    "earliest_arrival_jd": <float>,
    "latest_arrival_jd": <float>,
    "window_width_days": <float>,
    "c3_threshold_km2_s2": <float>
  },
  "arrival_optimal": {
    "departure_jd": <float>,
    "arrival_jd": <float>,
    "c3_km2_s2": <float>,
    "v_inf_arr_mag_km_s": <float>,
    "tof_days": <float>
  },
  "comparison": {
    "c3_optimal_c3": <float>,
    "c3_optimal_vinf_arr": <float>,
    "c3_optimal_tof_days": <float>,
    "arr_optimal_c3": <float>,
    "arr_optimal_vinf_arr": <float>,
    "arr_optimal_tof_days": <float>,
    "c3_penalty_for_arr_optimal": <float>,
    "vinf_savings_for_arr_optimal": <float>
  },
  "recommendation": "<which transfer is preferable for a mass-constrained mission and why, with quantitative justification>"
}
```

Launch window: contiguous departure dates (arrival fixed at C3-optimal arrival) where C3 < C3_optimal + 2.0 km²/s². Arrival window: analogous with departure fixed. All vectors in heliocentric ecliptic J2000 geometric coordinates, Sun-centered, km and km/s.