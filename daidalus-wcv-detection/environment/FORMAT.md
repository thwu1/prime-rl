# WCV Detector Input/Output Format

## Input: /app/encounters.json

Each encounter provides the **relative** state of an intruder aircraft (intruder minus ownship):

```json
{
  "encounters": [
    {
      "id": "string",
      "sx_nmi": 0.0,
      "sy_nmi": 5.0,
      "sz_ft": 0.0,
      "vx_kn": 0.0,
      "vy_kn": -300.0,
      "vz_fpm": 0.0
    }
  ]
}
```

- `sx_nmi`, `sy_nmi`: relative horizontal position [nautical miles]
- `sz_ft`: relative altitude [feet] (positive = intruder above ownship)
- `vx_kn`, `vy_kn`: relative horizontal velocity [knots]
- `vz_fpm`: relative vertical speed [feet per minute]

## Input: /app/config.json

Contains `corrective` WCV parameters (used for instantaneous checks and interval computation) and `alerts` (multi-level alerting thresholds).

Each alert level has its own WCV thresholds (`DTHR_nmi`, `ZTHR_ft`, `TTHR_s`, `TCOA_s`) and an `alerting_time_s` (lookahead window for that alert level).

## Output: /app/results.json

```json
{
  "results": [
    {
      "id": "head_on",
      "tau_mod_s": 58.95,
      "horizontal_wcv": false,
      "vertical_wcv": true,
      "wcv_3d": false,
      "time_to_wcv_entry_s": 23.29,
      "time_to_wcv_exit_s": 67.92,
      "alert_level": 3
    }
  ]
}
```

### Field definitions

- **tau_mod_s**: Modified tau time variable in seconds. Computed as `(DTHR^2 - |s|^2) / (s . v)` when `s . v < 0` (approaching). Return `-1.0` when aircraft are not approaching (`s . v >= 0`). Uses corrective `DTHR_nmi`. The horizontal position `s` and velocity `v` are 2D vectors.

- **horizontal_wcv**: Boolean. True if horizontal WCV is violated at t=0 using corrective parameters. Defined as: `|s|^2 <= DTHR^2` OR (`|s + tcpa*v|^2 <= DTHR^2` AND `0 <= tau_mod <= TTHR`), where `tcpa = max(0, -(s.v)/|v|^2)`.

- **vertical_wcv**: Boolean. True if vertical WCV is violated at t=0 using corrective parameters. Defined as: `|sz| <= ZTHR` OR (`0 <= tcoa(sz,vz) <= TCOA`), where `tcoa = -sz/vz` when approaching vertically.

- **wcv_3d**: Boolean. `horizontal_wcv AND vertical_wcv`.

- **time_to_wcv_entry_s**: Time in seconds to first 3D WCV violation within `lookahead_s` window, using corrective parameters. Return `-1.0` if no violation occurs. The 3D interval is the intersection of horizontal and vertical WCV intervals.

- **time_to_wcv_exit_s**: Time in seconds when 3D WCV violation ends. Return `-1.0` if no violation occurs.

- **alert_level**: Integer 0-3. Highest triggered alert level. An alert level is triggered if 3D WCV (using that level's thresholds) is violated at any time within [0, alerting_time_s].

### Unit conversions

- 1 knot = 1 nautical mile per hour
- 1 fpm = 1 foot per minute
- Horizontal computations use nmi for distance, knots for speed (time unit = hours)
- Vertical computations use ft for distance, fpm for speed (time unit = minutes)
- All output times are in seconds

### Key mathematical references

The horizontal WCV interval computation (from `horizontal_WCV_taumod.pvs`) uses a closed-form quadratic solution:
- `a = |v|^2`, `b = 2*(s.v) + TAUMOD*|v|^2`, `c = |s|^2 + TAUMOD*(s.v) - DTHR^2`
- Combined with `Delta[DTHR](s,v) = DTHR^2 * |v|^2 - (s.v)^2` for cylinder entry/exit
- `Theta_D[DTHR](s,v,eps) = (-(s.v) + eps*sqrt(Delta)) / |v|^2` for cylinder boundary times

The vertical WCV interval uses:
- Entry/exit times where `|sz + vz*t| <= ZTHR` (for TCOA=0)
- With TCOA>0: entry expanded using `act_H = max(ZTHR, |vz|*TCOA)`
