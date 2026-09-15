Design the minimum-total-Δv **Type I** (prograde, transfer angle < π) two-impulse transfer trajectory from Earth to Mars for the **2033 launch window**.

Retrieve heliocentric ecliptic J2000 state vectors (positions in km, velocities in km/s) for Earth (body `399`) and Mars (body `499`) relative to the Sun center (`500@10`) from the JPL Horizons REST API at `https://ssd.jpl.nasa.gov/api/horizons.api`. Search over departure dates **2033-04-01 through 2033-09-30** and arrival dates **2033-08-01 through 2034-07-31**, both sampled at intervals of no more than 10 days. Constrain the time of flight to **120–400 days**.

For each feasible departure–arrival pair, solve **Lambert's boundary-value problem** under two-body solar gravity to find the transfer orbit connecting the two planetary positions in the given flight time. Compute the total mission Δv as the sum of:

- **Departure burn**: hyperbolic departure from a 200 km altitude circular LEO
- **Arrival capture**: into a 300 km altitude circular LMO

Use these constants exactly:

| Quantity | Value |
|---|---|
| μ☉ | 1.32712440041279419 × 10¹¹ km³/s² |
| μ⊕ | 3.986004418 × 10⁵ km³/s² |
| μ♂ | 4.282837 × 10⁴ km³/s² |
| R⊕ | 6371.0 km |
| R♂ | 3389.5 km |

Write results to `/app/trajectory.json` with this structure:

```json
{
  "optimal": {
    "departure_date_jd": 0.0,
    "arrival_date_jd": 0.0,
    "departure_date_cal": "YYYY-MM-DD",
    "arrival_date_cal": "YYYY-MM-DD",
    "tof_days": 0.0,
    "c3_km2s2": 0.0,
    "vinf_dep_kms": 0.0,
    "vinf_arr_kms": 0.0,
    "dv_dep_kms": 0.0,
    "dv_arr_kms": 0.0,
    "dv_total_kms": 0.0,
    "transfer_a_km": 0.0,
    "transfer_e": 0.0,
    "transfer_i_deg": 0.0,
    "transfer_raan_deg": 0.0,
    "transfer_argp_deg": 0.0,
    "r1_km": [0, 0, 0],
    "v1_kms": [0, 0, 0],
    "r2_km": [0, 0, 0],
    "v2_kms": [0, 0, 0],
    "v_earth_kms": [0, 0, 0],
    "v_mars_kms": [0, 0, 0]
  },
  "top5": [ "<same structure as optimal, sorted by dv_total ascending>" ],
  "search_grid": {
    "dep_start_jd": 0.0,
    "dep_end_jd": 0.0,
    "arr_start_jd": 0.0,
    "arr_end_jd": 0.0,
    "dep_step_days": 0,
    "arr_step_days": 0,
    "n_dep": 0,
    "n_arr": 0,
    "n_converged": 0
  },
  "constants": {
    "mu_sun_km3s2": 0.0,
    "mu_earth_km3s2": 0.0,
    "mu_mars_km3s2": 0.0,
    "r_park_earth_km": 0.0,
    "r_park_mars_km": 0.0
  }
}
```

`v1_kms` / `v2_kms` are the spacecraft's heliocentric velocity on the transfer orbit at departure / arrival (not the hyperbolic excess). `v_earth_kms` / `v_mars_kms` are the planets' heliocentric velocities at those epochs. All vectors are ecliptic J2000 heliocentric, km and km/s.