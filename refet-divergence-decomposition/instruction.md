`/app/et_engine.py` implements the ASCE-EWRI 2005 standardized reference evapotranspiration engine. It delegates atmospheric pressure and clear-sky radiation to a C shared library (`/app/src/atmos.c`, `/app/src/atmos.h`) loaded via `ctypes`. Bugs exist across the C source, the Python `ctypes` bindings, and Python calculation functions. The `refet` method variant is partially unimplemented, and two of three API functions are stubs.

**Build and data pipeline:**
- `/app/Makefile` — `make lib` compiles `/app/src/atmos.c` into `/app/lib/libatmos.so`; `make preprocess` generates station data; `make validate` runs diagnostics
- `/app/scripts/preprocess.sh` — merges `/app/data/station_meta.json` and `/app/data/observations.json` into `/app/data/station.json` using `jq` (has errors in filter expressions)
- `/app/validate_runner.py` — incremental diagnostic tool (requires `station.json` to exist)
- `/app/data/golden_values.json` — reference intermediate and final values
- `/app/lib/refet_calcs_partial.py`, `/app/lib/pyeto_fao_partial.py` — partial source fragments from two reference ET libraries

**Required API** (all in `/app/et_engine.py`):

`compute_daily(tmin, tmax, ea, rs, uz, zw, elev, lat, doy, method='asce')` — daily reference ET. Units: temperatures °C, ea kPa, rs MJ m⁻² d⁻¹, uz m s⁻¹, zw/elev m, lat radians. Returns dict: `pair`, `tmean`, `es`, `ea`, `es_slope`, `vpd`, `psy`, `u2`, `delta`, `dr`, `omega_s`, `ra`, `rso`, `fcd`, `rnl`, `rn`, `eto`, `etr`.

`compute_hourly(tmean, ea, rs, uz, zw, elev, lat, lon, doy, time, method='asce')` — hourly reference ET. `time` is UTC hour at period start; lon in radians. Returns dict: `pair`, `es`, `ea`, `es_slope`, `vpd`, `psy`, `u2`, `delta`, `dr`, `sc`, `omega`, `omega_s`, `ra`, `rso`, `fcd`, `rnl`, `rn`, `eto`, `etr`. `omega` uses midpoint `time + 0.5`; `fcd` beta-clamping uses period start.

`decompose_daily_divergence(tmin, tmax, ea, rs, uz, zw, elev, lat, doy, surface='etr')` — decomposes ET difference between `asce` and `refet` into per-equation contributions. Returns dict: `total`, `air_pressure`, `es_slope`, `declination`, `solar_constant`, `clear_sky_radiation`, `residual`. `total = asce − refet`. Contributions plus residual must sum exactly to total.

**Acceptance criteria:**
- `make lib` produces working `/app/lib/libatmos.so`; `make preprocess` generates valid `/app/data/station.json`
- All intermediates match golden references to rel=1e-6
- ASCE daily ETo ∈ (7.94, 8.10) mm d⁻¹; ETo < ETr
- VPD ≥ 0 clipped; polar night (80°N, DOY 1) Ra=0, outputs finite; polar summer (70°N, DOY 182) omega_s=π
- ASCE and refet produce different ETr; default method is `asce`
- Decomposition: total > 0, residual < 15% of total, `clear_sky_radiation` is largest positive contributor, no contribution exceeds 3× total
