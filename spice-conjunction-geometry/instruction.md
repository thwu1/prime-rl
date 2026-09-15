`/app/` contains an ephemeris computation pipeline:

- `scenarios.json` — four SPICE computation requests specifying target bodies, observers, epochs, reference frames, aberration corrections, and required output fields
- `pipeline.py` — downloads SPICE kernels, computes ephemerides for each scenario, writes results
- `kernels.tm` — meta-kernel for kernel management

Running `python3 /app/pipeline.py` should produce `/app/results.json` with correct ephemeris data for every scenario. The pipeline currently fails or produces incorrect results due to multiple defects in the code and configuration.

Diagnose and fix all defects. Ensure the SPICE kernel set covers every target body and epoch. The corrected pipeline must run without errors and produce numerically accurate output for all four scenarios.

**Output** — `/app/results.json`: JSON object keyed by scenario ID, containing the fields listed in each scenario's `outputs` array.

| Field | Specification |
|---|---|
| `position_km` | `[x, y, z]` in scenario's reference frame (km) |
| `ra_deg` | Right ascension, J2000 equatorial, `[0, 360)` |
| `dec_deg` | Declination, J2000 equatorial, `[-90, 90]` |
| `range_km` | Observer-to-target distance (km) |
| `light_time_sec` | One-way light time (seconds) |
| `ecliptic_lon_deg` | Ecliptic longitude, ECLIPJ2000, `[0, 360)` |
| `ecliptic_lat_deg` | Ecliptic latitude, ECLIPJ2000, `[-90, 90]` |
| `phase_angle_deg` | Sun-Target-Observer angle at the target (degrees) |
| `velocity_km_s` | `[vx, vy, vz]` in scenario's frame and correction (km/s) |
| `speed_km_s` | Magnitude of velocity vector (km/s) |

**Constraints:**
- `range_km / light_time_sec` must equal the speed of light (299792.458 km/s) to within 0.01%
- `speed_km_s` must equal `|velocity_km_s|`
- All four scenarios must produce results without errors
